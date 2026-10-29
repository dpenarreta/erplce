# Imagen de herramientas de calidad (pre-commit + pip-audit) para scripts/check.sh.
# Contexto de build: raíz del repositorio (necesita requirements-dev.txt).
# python:3.12-slim (Debian 13), digest obtenido el 2026-10-29
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # El repositorio se monta desde el host con otro propietario.
    && git config --system --add safe.directory '*'

COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

RUN useradd --create-home --uid 1000 lint \
    && mkdir -p /home/lint/.cache/pre-commit \
    && chown -R lint:lint /home/lint/.cache
USER lint
ENV PRE_COMMIT_HOME=/home/lint/.cache/pre-commit
WORKDIR /src
