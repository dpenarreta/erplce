#!/bin/bash
# Envoltorio del entrypoint oficial de la imagen odoo:18.0.
#
# 1. Comprueba que /etc/odoo/odoo.conf define admin_passwd y que no es el
#    valor de ejemplo (sin contraseña maestra por defecto).
# 2. Calcula addons_path:
#      núcleo de Odoo
#      + /mnt/extra-addons            (addons/ del repo, módulos propios erp_*)
#      + /mnt/third-party/<repo>      (cada submódulo de third_party/ que contenga módulos)
#    Solo se añaden directorios que contienen al menos un módulo (<dir>/*/__manifest__.py),
#    porque Odoo rechaza por CLI rutas que no son directorios de addons válidos.
# 3. Delega en /entrypoint.sh (que añade los parámetros de conexión a la BD).
set -euo pipefail

ODOO_RC="${ODOO_RC:-/etc/odoo/odoo.conf}"
CORE_ADDONS=/usr/lib/python3/dist-packages/odoo/addons

die() { echo "[erp-entrypoint] ERROR: $*" >&2; exit 1; }

# Se lee el archivo de verdad: en Docker Desktop, si config/odoo.conf no existe
# en el host, Docker crea un DIRECTORIO vacío con ese nombre y lo monta, en lugar
# de fallar (ignora create_host_path: false).
if ! conf_content="$(cat "$ODOO_RC" 2> /dev/null)" || [ -z "$conf_content" ]; then
    die "No se puede leer $ODOO_RC: config/odoo.conf no existe, está vacío o es un directorio (Docker Desktop lo crea si falta el archivo). Borra el directorio config/odoo.conf si existe, copia config/odoo.conf.example a config/odoo.conf y define admin_passwd."
fi

admin_line="$(printf '%s\n' "$conf_content" | grep -E '^[[:space:]]*admin_passwd[[:space:]]*=' | tail -n1 || true)"
admin_value="$(printf '%s' "${admin_line#*=}" | tr -d '[:space:]')"
if [ -z "$admin_value" ] || [ "$admin_value" = "__CAMBIAR__" ]; then
    die "admin_passwd no está definido en config/odoo.conf (o conserva el valor de ejemplo __CAMBIAR__). Define una contraseña maestra."
fi

has_modules() {
    compgen -G "$1/*/__manifest__.py" > /dev/null
}

addons_path="$CORE_ADDONS"
if has_modules /mnt/extra-addons; then
    addons_path+=",/mnt/extra-addons"
fi
shopt -s nullglob
for repo in /mnt/third-party/*/; do
    repo="${repo%/}"
    if has_modules "$repo"; then
        addons_path+=",$repo"
    fi
done
shopt -u nullglob
export ERP_ADDONS_PATH="$addons_path"

# Subcomandos de odoo que aceptan opciones de configuración (--addons-path).
case "${1:-}" in
    odoo | --)
        shift
        case "${1:-}" in
            "" | -* | server | shell | populate | neutralize | start)
                if [ -n "${1:-}" ] && [ "${1#-}" = "$1" ]; then
                    sub="$1"
                    shift
                    exec /entrypoint.sh odoo "$sub" --addons-path="$addons_path" "$@"
                fi
                exec /entrypoint.sh odoo --addons-path="$addons_path" "$@"
                ;;
            *)
                exec /entrypoint.sh odoo "$@"
                ;;
        esac
        ;;
    -*)
        exec /entrypoint.sh odoo --addons-path="$addons_path" "$@"
        ;;
    *)
        exec /entrypoint.sh "$@"
        ;;
esac
