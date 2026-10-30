#!/usr/bin/env bash
# Ejecuta los tests de Odoo de uno o varios módulos en una BD efímera.
#
#   bash scripts/test.sh <modulo>[,<modulo>...]
#
# - Requiere el entorno levantado (docker compose up -d).
# - Crea una BD con nombre único, instala los módulos con
#   --test-enable --stop-after-init en un contenedor temporal (docker compose run)
#   y elimina SIEMPRE la BD y su filestore al terminar (trap).
# - Sale con 0 solo si: Odoo termina con código 0, el log no contiene líneas
#   ERROR/CRITICAL, todos los módulos pedidos quedan en estado "installed" y el
#   log solo contiene salida de su propia BD efímera.
#   (Odoo puede devolver 0 aunque un módulo no exista o falle su carga.)
# - Solo se ejecutan los tests de los módulos pedidos (--test-tags=/mod1,/mod2).
# - Instala SIN datos de demostración (--without-demo=all), como una BD real.
# - El contenedor efímero usa docker/compose.test.yml (sin healthcheck: sus
#   peticiones a /web/health interferían con el servidor HTTP de los HttpCase).
# - Ejecuciones concurrentes (varios agentes/terminales): se SERIALIZAN con un
#   candado del host (directorio creado con mkdir atómico, portable a Git Bash de
#   Windows, que no trae flock). Mientras otra ejecución lo tiene, esta espera
#   ("Esperando a otra ejecución de tests...") hasta ERP_TEST_LOCK_TIMEOUT
#   segundos. El candado se libera al salir (normal, error o Ctrl+C) y se
#   considera huérfano si el proceso que lo creó ya no existe.
# - Cada ejecución usa un contenedor con nombre propio (erp-test-<BD>), espera a
#   que termine y valida que el log solo contiene salida de SU BD efímera.
# - Variables opcionales:
#     TEST_TAGS=<spec>             sustituye al --test-tags por defecto
#     TEST_DEMO=1                  instala con datos de demostración
#     TEST_KEEP_LOG=1              conserva el log al terminar
#     ERP_TEST_LOCK_DIR=<dir>      candado (defecto: $HOME/.cache/erp-lce/test.lock)
#     ERP_TEST_LOCK_TIMEOUT=<seg>  espera máxima por el candado (defecto: 3600)
set -uo pipefail

export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

usage() {
    echo "Uso: bash scripts/test.sh <modulo>[,<modulo>...]" >&2
    echo "Ej.: bash scripts/test.sh erp_base,erp_branding" >&2
}

if [ $# -ne 1 ] || [ -z "$1" ]; then
    usage
    exit 2
fi
MODULES="$1"
if ! [[ "$MODULES" =~ ^[a-z0-9_]+(,[a-z0-9_]+)*$ ]]; then
    echo "ERROR: lista de módulos inválida: '$MODULES' (nombres técnicos separados por comas, sin espacios)." >&2
    usage
    exit 2
fi

if [ ! -f config/odoo.conf ]; then
    echo "ERROR: config/odoo.conf no existe o no es un archivo. Copia config/odoo.conf.example a config/odoo.conf (si Docker creó un directorio con ese nombre, bórralo antes)." >&2
    exit 2
fi
if [ -z "$(docker compose ps --status running -q db 2>/dev/null)" ]; then
    echo "ERROR: el servicio 'db' no está en ejecución. Levanta el entorno con: docker compose up -d" >&2
    exit 2
fi

LOCK_TIMEOUT="${ERP_TEST_LOCK_TIMEOUT:-3600}"
if ! [[ "$LOCK_TIMEOUT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: ERP_TEST_LOCK_TIMEOUT debe ser un número de segundos." >&2
    exit 2
fi
LOCK_DIR="${ERP_TEST_LOCK_DIR:-$HOME/.cache/erp-lce/test.lock}"

# Compose con la sobrecarga de tests (sin healthcheck en odoo).
DC=(docker compose -f docker-compose.yml -f docker/compose.test.yml)

DB="erp_test_$(date +%Y%m%d%H%M%S)_${RANDOM}${RANDOM}"
CNAME="erp-test-${DB}"
LOG="$(mktemp "${TMPDIR:-/tmp}/erp_test_XXXXXX.log")"
LOCK_HELD=0
STARTED=0

psql_db() {
    # Ejecuta psql en el contenedor db con las credenciales de su propio entorno.
    docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -tAc "$2"' _ "$@"
}

# --- Candado del host ---------------------------------------------------------
# mkdir es atómico en todos los sistemas (Git Bash de Windows no trae flock).
# El archivo owner guarda "<pid> <inicio> <módulos>" para diagnóstico y
# para detectar candados huérfanos (proceso inexistente).
lock_owner() {
    local pid since mods
    if read -r pid since mods < "${1:-$LOCK_DIR}/owner" 2> /dev/null; then
        echo "PID $pid desde $since, módulos $mods"
    else
        echo "sin registrar"
    fi
}

lock_is_stale() {
    local owner pid mtime
    owner="$(cat "$LOCK_DIR/owner" 2> /dev/null || true)"
    if [ -z "$owner" ]; then
        # Candado sin dueño registrado: huérfano si tiene más de 60 s.
        mtime="$(stat -c %Y "$LOCK_DIR" 2> /dev/null || date +%s)"
        [ $(($(date +%s) - mtime)) -gt 60 ]
        return
    fi
    pid="${owner%% *}"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    ! kill -0 "$pid" 2> /dev/null
}

acquire_lock() {
    local start waited last_msg=-1 stale
    if ! mkdir -p "$(dirname "$LOCK_DIR")"; then
        echo "ERROR: no se puede crear el directorio del candado: $(dirname "$LOCK_DIR")" >&2
        exit 2
    fi
    start="$(date +%s)"
    while ! mkdir "$LOCK_DIR" 2> /dev/null; do
        if lock_is_stale; then
            # Renombrado atómico: si dos esperas detectan el huérfano a la vez,
            # solo una lo retira.
            stale="${LOCK_DIR}.stale.$$"
            if mv "$LOCK_DIR" "$stale" 2> /dev/null; then
                echo "--- Candado huérfano retirado (dueño: $(lock_owner "$stale"))"
                rm -rf "$stale"
            fi
            continue
        fi
        waited=$(($(date +%s) - start))
        if [ "$waited" -ge "$LOCK_TIMEOUT" ]; then
            echo "ERROR: tiempo de espera agotado (${LOCK_TIMEOUT}s) por el candado $LOCK_DIR" >&2
            echo "       Dueño: $(lock_owner)" >&2
            echo "       Si no hay ninguna ejecución de tests en curso, borra ese directorio." >&2
            exit 2
        fi
        if [ $((waited / 60)) -ne "$last_msg" ]; then
            last_msg=$((waited / 60))
            echo "--- Esperando a otra ejecución de tests... (${waited}s; dueño: $(lock_owner))"
        fi
        sleep 5
    done
    LOCK_HELD=1
    printf '%s %s %s\n' "$$" "$(date '+%Y-%m-%dT%H:%M:%S')" "$MODULES" > "$LOCK_DIR/owner"
}

# shellcheck disable=SC2329  # se invoca desde cleanup (trap EXIT)
release_lock() {
    if [ "$LOCK_HELD" -eq 1 ]; then
        rm -rf "$LOCK_DIR"
        LOCK_HELD=0
    fi
}

# shellcheck disable=SC2329  # se invoca indirectamente vía trap EXIT
cleanup() {
    trap '' INT TERM
    if [ "$STARTED" -eq 1 ]; then
        # Contenedor propio (p. ej. tras Ctrl+C): se retira antes de borrar la BD.
        docker rm -f "$CNAME" > /dev/null 2>&1 || true
        echo "--- Limpieza: eliminando BD efímera $DB y su filestore"
        docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$1"' _ "$DB" \
            || echo "AVISO: no se pudo eliminar la BD $DB; bórrala a mano." >&2
        "${DC[@]}" run --rm --no-deps -T --name "${CNAME}-rm" --entrypoint rm odoo \
            -rf "/var/lib/odoo/filestore/$DB" \
            > /dev/null 2>&1 || echo "AVISO: no se pudo eliminar el filestore de $DB." >&2
    fi
    release_lock
    if [ "${TEST_KEEP_LOG:-0}" = "1" ]; then
        echo "--- Log conservado en: $LOG"
    else
        rm -f "$LOG"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

acquire_lock

# Por defecto solo se ejecutan los tests de los módulos pedidos (/mod1,/mod2):
# sus dependencias (base, mail, account...) se instalan pero sin ejecutar sus
# tests, que son lentos y algunos dependen del entorno de CI de Odoo.
DEFAULT_TAGS="/$(printf '%s' "$MODULES" | sed 's#,#,/#g')"
TAGS="${TEST_TAGS:-$DEFAULT_TAGS}"

DEMO_ARGS=(--without-demo=all)
DEMO_TXT="sin demo"
if [ "${TEST_DEMO:-0}" = "1" ]; then
    DEMO_ARGS=()
    DEMO_TXT="con demo"
fi

echo "--- BD efímera: $DB · contenedor: $CNAME · módulos: $MODULES · test-tags: $TAGS · $DEMO_TXT"

STARTED=1
"${DC[@]}" run --rm --no-deps -T --name "$CNAME" odoo \
    odoo -d "$DB" -i "$MODULES" \
    --test-enable --test-tags="$TAGS" --stop-after-init \
    --log-level=test --workers=0 --max-cron-threads=0 \
    "${DEMO_ARGS[@]}" \
    2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

# Espera a que SU contenedor termine de verdad (por si "compose run" vuelve antes
# de que el motor lo retire) y lo elimina si quedara.
if docker container inspect "$CNAME" > /dev/null 2>&1; then
    docker wait "$CNAME" > /dev/null 2>&1 || true
    docker rm -f "$CNAME" > /dev/null 2>&1 || true
fi

FAILED=0
REASONS=()
if [ "$RC" -ne 0 ]; then
    FAILED=1
    REASONS+=("Odoo terminó con código $RC")
fi

if grep -qE 'invalid module names, ignored' "$LOG"; then
    FAILED=1
    REASONS+=("$(grep -oE 'invalid module names, ignored: .*' "$LOG" | head -n1) (módulo inexistente o fuera del addons_path)")
fi

# El log debe contener solo salida de SU BD efímera.
FOREIGN_DBS="$(grep -oE 'erp_test_[0-9]+_[0-9]+' "$LOG" | sort -u | grep -vxF "$DB" || true)"
if [ -n "$FOREIGN_DBS" ]; then
    FAILED=1
    REASONS+=("log contaminado con salida de otra(s) BD efímera(s): $(printf '%s\n' "$FOREIGN_DBS" | paste -sd' ' -)")
fi

# Líneas de log de Odoo con nivel ERROR o CRITICAL (fallos de test, errores de carga).
ERRLINES="$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:,]+ [0-9]+ (ERROR|CRITICAL) ' "$LOG" || true)"
if [ -n "$ERRLINES" ]; then
    FAILED=1
    REASONS+=("el log contiene $(printf '%s\n' "$ERRLINES" | wc -l | tr -d ' ') línea(s) ERROR/CRITICAL")
fi

# Estado final de cada módulo pedido.
IN_LIST="'$(printf '%s' "$MODULES" | sed "s/,/','/g")'"
STATES="$(psql_db "$DB" "SELECT name || '=' || state FROM ir_module_module WHERE name IN ($IN_LIST) ORDER BY name" 2>/dev/null || true)"
IFS=',' read -r -a MODS <<< "$MODULES"
for m in "${MODS[@]}"; do
    state="$(printf '%s\n' "$STATES" | sed -n "s/^${m}=//p" | head -n1)"
    if [ "$state" != "installed" ]; then
        FAILED=1
        if [ -z "$state" ]; then
            REASONS+=("módulo '$m' no existe en el addons_path (no está en la BD)")
        else
            REASONS+=("módulo '$m' quedó en estado '$state'")
        fi
    fi
done

echo
echo "=================== RESUMEN scripts/test.sh ==================="
echo "BD: $DB"
# Solo las líneas de resultado de SU BD (formato: fecha hora pid NIVEL <bd> logger: ...).
grep -E "^[0-9-]+ [0-9:,]+ [0-9]+ [A-Z]+ ${DB} odoo\.tests\.result: " "$LOG" | tail -n 3 || true
if [ "$FAILED" -ne 0 ]; then
    if [ -n "$ERRLINES" ]; then
        echo "--- Líneas ERROR/CRITICAL:"
        printf '%s\n' "$ERRLINES" | head -n 40
    fi
    echo "--- FALLO:"
    for r in "${REASONS[@]}"; do echo "  * $r"; done
    echo "==============================================================="
    exit 1
fi
echo "OK: módulos instalados y tests sin fallos ($MODULES)"
echo "==============================================================="
exit 0
