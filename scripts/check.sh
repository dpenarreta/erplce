#!/usr/bin/env bash
# Verificación de calidad del proyecto.
#
#   bash scripts/check.sh          Calidad estática (pre-commit sobre addons/, scripts/, docker/)
#   bash scripts/check.sh --all    + tests de todos los módulos de addons/
#                                  + pip-audit (requirements-dev.txt y requirements de addons)
#
# pre-commit (ruff, pylint-odoo, oca-checks-odoo-module, check-xml, prettier...)
# se ejecuta dentro de la imagen docker/lint para que el resultado no dependa de
# lo instalado en cada máquina. Caché de hooks en el volumen erp_precommit_cache.
# Nota: los hooks con --fix (ruff, prettier, end-of-file...) pueden modificar
# archivos; en ese caso el check falla y basta con revisar y volver a ejecutar.
set -uo pipefail

export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

ALL=0
case "${1:-}" in
    "") ;;
    --all) ALL=1 ;;
    -h | --help)
        sed -n '2,12p' "$0"
        exit 0
        ;;
    *)
        echo "Uso: bash scripts/check.sh [--all]" >&2
        exit 2
        ;;
esac

LINT_IMAGE="erp-lint:$(cat docker/lint/Dockerfile requirements-dev.txt | git hash-object --stdin | cut -c1-12)"
# Ruta del repo en formato que entienda Docker (C:/... en Git Bash de Windows).
if pwd -W > /dev/null 2>&1; then
    HOST_ROOT="$(pwd -W)"
else
    HOST_ROOT="$ROOT"
fi

FAIL=0
step() { echo; echo "=== $*"; }

step "Imagen de herramientas ($LINT_IMAGE)"
if ! docker image inspect "$LINT_IMAGE" > /dev/null 2>&1; then
    docker build -q -t "$LINT_IMAGE" -f docker/lint/Dockerfile . || {
        echo "ERROR: no se pudo construir la imagen de herramientas." >&2
        exit 2
    }
fi
echo "OK"

# CA adicional opcional (proxy/antivirus que inspecciona TLS, p. ej. Kaspersky):
# ERP_EXTRA_CA_CERT=<ruta a .pem> en el entorno o en .env. Se monta en solo
# lectura y se AÑADE al bundle del sistema; la verificación TLS nunca se desactiva.
if [ -z "${ERP_EXTRA_CA_CERT:-}" ] && [ -f .env ]; then
    ERP_EXTRA_CA_CERT="$(sed -n 's/^ERP_EXTRA_CA_CERT=//p' .env | tail -n1 | tr -d '\r"')"
fi
CA_ARGS=()
if [ -n "${ERP_EXTRA_CA_CERT:-}" ]; then
    ca_local="$ERP_EXTRA_CA_CERT"
    command -v cygpath > /dev/null 2>&1 && ca_local="$(cygpath -u "$ERP_EXTRA_CA_CERT")"
    # Rutas relativas: respecto a la raíz del repositorio.
    case "$ca_local" in /*) ;; *) ca_local="$ROOT/$ca_local" ;; esac
    if [ ! -f "$ca_local" ]; then
        echo "ERROR: ERP_EXTRA_CA_CERT apunta a un archivo inexistente: $ERP_EXTRA_CA_CERT" >&2
        exit 2
    fi
    ca_host="$ca_local"
    command -v cygpath > /dev/null 2>&1 && ca_host="$(cygpath -m "$ca_local")"
    CA_ARGS=(-v "$ca_host:/run/erp-extra-ca.pem:ro")
fi

lint_run() {
    docker run --rm -i \
        -v "$HOST_ROOT:/src" \
        -v erp_precommit_cache:/home/lint/.cache/pre-commit \
        "${CA_ARGS[@]}" \
        -w /src "$LINT_IMAGE" sh -c '
            if [ -f /run/erp-extra-ca.pem ]; then
                cat /etc/ssl/certs/ca-certificates.crt /run/erp-extra-ca.pem > /tmp/ca-bundle.pem
                export GIT_SSL_CAINFO=/tmp/ca-bundle.pem SSL_CERT_FILE=/tmp/ca-bundle.pem \
                    REQUESTS_CA_BUNDLE=/tmp/ca-bundle.pem PIP_CERT=/tmp/ca-bundle.pem \
                    NODE_EXTRA_CA_CERTS=/run/erp-extra-ca.pem
            fi
            exec "$@"' sh "$@"
}

step "pre-commit sobre addons/, scripts/ y docker/"
lint_run sh -c '
    set -e
    pre-commit validate-config .pre-commit-config.yaml
    # Lista separada por NUL: admite espacios y caracteres especiales en los nombres.
    find addons scripts docker -type f ! -name .gitkeep ! -path "*/__pycache__/*" -print0 | sort -z \
        | xargs -0 pre-commit run --show-diff-on-failure --color=always --files
' || FAIL=1

if [ "$ALL" -eq 1 ]; then
    step "Tests de los módulos de addons/"
    MODS="$(find addons -mindepth 2 -maxdepth 2 -name __manifest__.py -print \
        | awk -F/ '{print $2}' | sort | paste -sd, -)"
    if [ -z "$MODS" ]; then
        echo "addons/ no contiene módulos: no hay tests que ejecutar."
    else
        bash scripts/test.sh "$MODS" || FAIL=1
    fi

    step "Auditoría de dependencias Python (pip-audit)"
    # requirements-dev.txt (herramientas de calidad), requirements.txt raíz
    # (dependencias de los addons) y los de cada módulo propio. Los requirements de
    # third_party/ NO se auditan: declaran dependencias de módulos de terceros que no
    # se instalan (p. ej. hr_payroll_document de OCA/payroll). Si un módulo de terceros
    # instalado necesita paquetes, se declaran en el requirements.txt raíz.
    REQS=()
    for r in requirements-dev.txt requirements.txt; do
        [ -f "$r" ] && REQS+=("$r")
    done
    while IFS= read -r -d '' r; do
        REQS+=("$r")
    done < <(find addons -maxdepth 2 -name 'requirements*.txt' -print0 2>/dev/null | sort -z)
    if [ "${#REQS[@]}" -eq 0 ]; then
        echo "Sin archivos requirements: auditoría omitida."
    else
        for r in "${REQS[@]}"; do
            echo "--- $r"
            lint_run pip-audit --progress-spinner off -r "$r" || FAIL=1
        done
    fi
fi

echo
if [ "$FAIL" -ne 0 ]; then
    echo "check.sh: FALLO"
    exit 1
fi
echo "check.sh: OK"
exit 0
