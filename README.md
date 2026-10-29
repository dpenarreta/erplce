# ERP · Odoo 18 Community (Ecuador)

ERP personalizado sobre **Odoo 18.0 Community** para Ecuador. El núcleo de Odoo
no se modifica: toda la personalización vive en módulos propios (`addons/erp_*`)
y en módulos de terceros fijados (`third_party/`).

## Estructura

| Ruta | Contenido |
|---|---|
| `addons/` | Módulos propios (`erp_*`). Montado en `/mnt/extra-addons`. |
| `third_party/` | Submódulos git de terceros (OCA...). Ver `third_party/README.md`. |
| `config/` | Plantillas `odoo.conf` (`*.example`, versionadas) y `odoo.conf` local (no versionado). |
| `docker/odoo/entrypoint.sh` | Envoltorio del entrypoint oficial: calcula `addons_path` y valida `admin_passwd`. |
| `docker/lint/` | Imagen de herramientas de calidad (pre-commit, pip-audit). |
| `scripts/` | `check.sh` (calidad) y `test.sh` (tests en BD efímera). |
| `docs/` | Perfil del equipo e historias de usuario. |

## Entorno de desarrollo

### Requisitos

- Docker Engine con Docker Compose v2 (probado con Docker 29.6 / Compose v5, Docker Desktop en Windows 11).
- Bash: en Windows, **Git Bash** (los scripts usan `MSYS_NO_PATHCONV` para las rutas).
- Acceso a Internet la primera vez (imágenes Docker y hooks de pre-commit).
- Puerto `8069` libre en `127.0.0.1` (configurable con `ODOO_HTTP_PORT`).

No hace falta Python, pre-commit ni Node en la máquina: las herramientas de
calidad corren en contenedores.

### Primeros pasos

```bash
git clone --recurse-submodules <url> erp && cd erp

# 1. Variables de entorno (credenciales de PostgreSQL)
cp .env.example .env
#    editar .env: POSTGRES_PASSWORD=<contraseña>   (p. ej. openssl rand -hex 24)

# 2. Configuración de Odoo (contraseña maestra)
cp config/odoo.conf.example config/odoo.conf
#    editar config/odoo.conf: admin_passwd = <contraseña maestra>

# 3. Levantar
docker compose up -d
curl -s http://127.0.0.1:8069/web/health     # {"status": "pass"}
```

Abrir `http://127.0.0.1:8069` y crear una base de datos con la contraseña maestra.

### Comandos

| Acción | Comando |
|---|---|
| Levantar entorno | `docker compose up -d` |
| Estado / salud | `docker compose ps` · `curl -s http://127.0.0.1:8069/web/health` |
| Logs de Odoo | `docker compose logs -f odoo` |
| Reiniciar Odoo (tras cambiar Python o `third_party/`) | `docker compose restart odoo` |
| Actualizar un módulo en una BD | `docker compose run --rm odoo odoo -d <bd> -u <modulo> --stop-after-init` |
| Shell de Odoo | `docker compose run --rm odoo odoo shell -d <bd>` |
| psql | `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d <bd>'` |
| Calidad estática | `bash scripts/check.sh` |
| Tests de módulos | `bash scripts/test.sh <modulo>[,<modulo>]` |
| Verificación completa | `bash scripts/check.sh --all` |
| Apagar (conserva datos) | `docker compose down` |
| Borrar TODO (BD y filestore) | `docker compose down -v` (destructivo) |

Respaldo y restauración: se definen en US-009.

### Configuración y secretos

| Dato | Dónde | Versionado |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | `.env` (plantilla `.env.example`) | No |
| `ODOO_HTTP_PORT` (opcional, por defecto 8069) | `.env` | No |
| `ERP_EXTRA_CA_CERT` (opcional, CA de proxy/antivirus TLS) | `.env` o entorno | No |
| `admin_passwd` (contraseña maestra) y opciones de Odoo | `config/odoo.conf` (plantillas `config/odoo.conf.example` dev y `config/odoo.prod.conf.example` prod) | No |

- Compose exige las variables con `${VAR:?mensaje}`: sin `.env` (o con la contraseña vacía) falla indicando qué variable falta.
- Las credenciales de BD llegan a Odoo como variables `HOST/USER/PASSWORD`, que el entrypoint oficial de la imagen pasa como `--db_host/--db_user/--db_password` (no se escriben en `odoo.conf`; si se escriben allí, prevalecen).
- `docker/odoo/entrypoint.sh` impide arrancar si `admin_passwd` falta o conserva el valor de ejemplo `__CAMBIAR__`.
- Si falta `config/odoo.conf`, Odoo no arranca: Compose falla al montar (`bind source path does not exist`, Linux) o, en Docker Desktop (que crea un **directorio** vacío `config/odoo.conf/` en el host), el envoltorio aborta con `No se puede leer /etc/odoo/odoo.conf`.
- La plantilla de producción fija `list_db = False`, `proxy_mode = True`, `dbfilter`, `workers` y límites.

### `addons_path`

Lo calcula `docker/odoo/entrypoint.sh` en cada arranque y lo pasa por línea de comandos:

1. núcleo de Odoo (`/usr/lib/python3/dist-packages/odoo/addons`);
2. `/mnt/extra-addons` (= `addons/`), si contiene algún módulo;
3. cada `/mnt/third-party/<repo>` (= `third_party/<repo>/`) que contenga algún módulo.

Se comprueba con `docker compose logs odoo | grep "addons paths"`.

### Servicios, red y volúmenes

| Servicio | Imagen (fijada por digest) | Puertos | Volúmenes |
|---|---|---|---|
| `db` | `postgres:16` (16.15) | ninguno publicado | `erp_db_data` |
| `odoo` | `odoo:18.0` (build 2026-10-26) | `127.0.0.1:8069` | `erp_odoo_data` (filestore, sesiones) |

- Proyecto Compose `erp`; contenedores `erp-db-1`, `erp-odoo-1`; redes `erp_backend` (interna, sin salida a Internet: db↔odoo) y `erp_egress` (solo odoo).
- Healthchecks: `pg_isready` (db) y `GET /web/health` (odoo); `odoo` espera a `db` sano. Política `restart: unless-stopped`.
- Ambos contenedores corren con el usuario no root de su imagen (`odoo`; PostgreSQL baja a `postgres`).
- `addons/`, `third_party/` y `config/odoo.conf` se montan en solo lectura.

### Tests (`scripts/test.sh`)

```bash
bash scripts/test.sh erp_base,erp_branding
TEST_TAGS=/erp_base:TestX bash scripts/test.sh erp_base   # filtrar tests
TEST_DEMO=1 bash scripts/test.sh erp_base                 # instalar con datos de demo
TEST_KEEP_LOG=1 bash scripts/test.sh erp_base             # conservar el log
```

- Requiere el entorno levantado. Crea una BD `erp_test_<fecha>_<n>`, instala los
  módulos en un contenedor temporal con `--test-enable --stop-after-init` y elimina
  siempre la BD y su filestore (también con Ctrl+C o fallo).
- Instala **sin datos de demostración** (`--without-demo=all`), como una BD real;
  `TEST_DEMO=1` los carga.
- El contenedor de tests usa `docker/compose.test.yml`, que desactiva el healthcheck
  (sus `GET /web/health` interferían con el servidor HTTP de los `HttpCase`).
- Por defecto solo ejecuta los tests **de los módulos pedidos** (`--test-tags=/mod1,/mod2`);
  sus dependencias se instalan sin ejecutar sus tests.
- Falla (código 1) si Odoo devuelve ≠ 0, si el log tiene líneas `ERROR`/`CRITICAL`,
  o si algún módulo pedido no queda `installed` (incluido módulo inexistente).
  Odoo puede devolver 0 con un módulo inexistente; por eso se hacen las tres comprobaciones.
- La imagen oficial no incluye Chrome/Chromium: los tests `HttpCase` que abren navegador
  (`browser_js`, tours) no pueden ejecutarse en este entorno (Odoo los marca como omitidos;
  pendiente de confirmar con el primer tour real). Los `HttpCase` sin navegador (`url_open`) sí funcionan.

### Calidad (`scripts/check.sh`)

- Ejecuta `pre-commit` (config `.pre-commit-config.yaml`, estilo OCA 18.0) sobre `addons/`,
  `scripts/` y `docker/` dentro de la imagen `docker/lint` (se construye sola la primera
  vez; caché de hooks en el volumen `erp_precommit_cache`): ruff (+format), pylint-odoo
  (`.pylintrc`, `valid-odoo-versions=18.0`), `oca-checks-odoo-module` (manifiestos/XML/CSV),
  `check-xml`, prettier (XML/JS/SCSS), ESLint 9 sobre `addons/*/static/src/**/*.js`
  (`eslint.config.cjs`: módulos ES, globals de navegador y de Odoo; los imports
  `@web/...`/`@odoo/owl` no se resuelven; sin `--fix`), shellcheck sobre
  `scripts/*.sh` y `docker/**/*.sh`, y hooks generales.
- Los hooks con corrección automática pueden modificar archivos: el check falla, se
  revisan los cambios y se vuelve a ejecutar.
- `--all` añade `scripts/test.sh` con todos los módulos de `addons/` y `pip-audit`
  de `requirements-dev.txt` (herramientas de calidad), del `requirements.txt` raíz y de
  los `requirements*.txt` de módulos, si existen.
- Hook de git opcional en local: `python -m pip install -r requirements-dev.txt && pre-commit install`.

### Proxy o antivirus que inspecciona TLS

Si `scripts/check.sh` no puede descargar los hooks por un certificado no confiable,
exportar la CA raíz que usa el proxy/antivirus y declararla (se **añade** al bundle
del sistema dentro del contenedor de herramientas; la verificación TLS sigue activa):

```powershell
# PowerShell (Windows): localizar la CA y exportarla a PEM (no versionado: config/*, *.pem)
Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -like '*Kaspersky*' | Format-List Subject,Thumbprint,NotAfter
$c = Get-Item Cert:\LocalMachine\Root\<THUMBPRINT>
"-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($c.RawData,'InsertLineBreaks') + "`n-----END CERTIFICATE-----" | Set-Content -Encoding ascii config\extra-ca.pem
```

y en `.env`: `ERP_EXTRA_CA_CERT=config/extra-ca.pem` (ruta relativa a la raíz del repo o absoluta).
El antivirus puede regenerar su CA: si vuelve el error, repetir la exportación.

### Actualizar imágenes

```bash
docker pull odoo:18.0 && docker image inspect odoo:18.0 --format '{{index .RepoDigests 0}}'
```

Sustituir el digest en `docker-compose.yml`, `docker compose up -d` y ejecutar
`bash scripts/check.sh --all`. Igual para `postgres:16` y `python:3.12-slim` (`docker/lint/Dockerfile`).

### Solución de problemas

| Síntoma | Causa / solución |
|---|---|
| `required variable POSTGRES_... is missing a value` | Falta `.env` o el valor está vacío: `cp .env.example .env` y completar. |
| `bind source path does not exist: .../config/odoo.conf`, `No se puede leer /etc/odoo/odoo.conf` o `not a directory: Are you trying to mount a directory onto a file` | Falta `config/odoo.conf` (Docker Desktop crea en su lugar un directorio vacío). Borrar ese directorio (`rmdir config/odoo.conf`), `cp config/odoo.conf.example config/odoo.conf`, definir `admin_passwd` y `docker compose up -d`. |
| Odoo se reinicia con `admin_passwd no está definido` | Definir `admin_passwd` en `config/odoo.conf`. |
| `port is already allocated` en 8069 | Cambiar `ODOO_HTTP_PORT` en `.env`. |
| `$'\r': command not found` en scripts | Fines de línea CRLF: el repo fuerza LF (`.gitattributes`); `git add --renormalize . && git checkout -- .` |
| `check.sh`: `server verification failed: certificate signer not trusted` | Un proxy/antivirus (p. ej. Kaspersky) inspecciona TLS. Exportar su CA raíz vigente a PEM y definir `ERP_EXTRA_CA_CERT` en `.env` (ver abajo). Nunca desactivar la verificación TLS. |
| Rutas `C:/Program Files/Git/...` en comandos docker | Conversión de rutas de Git Bash: ejecutar con `MSYS_NO_PATHCONV=1`. |
| Un módulo nuevo no aparece | `docker compose restart odoo` (el `addons_path` se calcula al arrancar) y actualizar la lista de apps. |
| Cambié la contraseña de `.env` y Odoo no conecta | PostgreSQL fija la contraseña al crear `erp_db_data`; cambiarla con `ALTER USER` o recrear el volumen (destructivo). |
