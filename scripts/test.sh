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
#   ERROR/CRITICAL, y todos los módulos pedidos quedan en estado "installed".
#   (Odoo puede devolver 0 aunque un módulo no exista o falle su carga.)
# - Solo se ejecutan los tests de los módulos pedidos (--test-tags=/mod1,/mod2).
# - Instala SIN datos de demostración (--without-demo=all), como una BD real.
# - El contenedor efímero usa docker/compose.test.yml (sin healthcheck: sus
#   peticiones a /web/health interferían con el servidor HTTP de los HttpCase).
# - Variables opcionales:
#     TEST_TAGS=<spec>   sustituye al --test-tags por defecto
#     TEST_DEMO=1        instala con datos de demostración
#     TEST_KEEP_LOG=1    conserva el log al terminar
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

# Compose con la sobrecarga de tests (sin healthcheck en odoo).
DC=(docker compose -f docker-compose.yml -f docker/compose.test.yml)

DB="erp_test_$(date +%Y%m%d%H%M%S)_${RANDOM}"
LOG="$(mktemp "${TMPDIR:-/tmp}/erp_test_XXXXXX.log")"

psql_db() {
    # Ejecuta psql en el contenedor db con las credenciales de su propio entorno.
    docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -tAc "$2"' _ "$@"
}

# shellcheck disable=SC2329  # se invoca indirectamente vía trap EXIT
cleanup() {
    echo "--- Limpieza: eliminando BD efímera $DB y su filestore"
    docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$1"' _ "$DB" \
        || echo "AVISO: no se pudo eliminar la BD $DB; bórrala a mano." >&2
    "${DC[@]}" run --rm --no-deps -T --entrypoint rm odoo -rf "/var/lib/odoo/filestore/$DB" \
        > /dev/null 2>&1 || echo "AVISO: no se pudo eliminar el filestore de $DB." >&2
    if [ "${TEST_KEEP_LOG:-0}" = "1" ]; then
        echo "--- Log conservado en: $LOG"
    else
        rm -f "$LOG"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

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

echo "--- BD efímera: $DB · módulos: $MODULES · test-tags: $TAGS · $DEMO_TXT"

"${DC[@]}" run --rm --no-deps -T odoo \
    odoo -d "$DB" -i "$MODULES" \
    --test-enable --test-tags="$TAGS" --stop-after-init \
    --log-level=test --workers=0 --max-cron-threads=0 \
    "${DEMO_ARGS[@]}" \
    2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

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
grep -E 'odoo\.tests\.result: ' "$LOG" | tail -n 3 || true
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
