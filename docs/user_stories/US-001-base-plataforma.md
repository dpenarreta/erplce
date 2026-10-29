# Historia de Usuario: US-001 - Base de la plataforma ERP (Odoo 18 Community · Ecuador)

- **ID:** US-001
- **Tipo:** Historia Técnica
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Plataforma · `erp_base`, `erp_branding`, entorno
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-5 / DEV-3 / DEV-2 / DEV-4

---

### 1. Definición de la Historia
- **Como:** equipo de desarrollo y administrador del ERP
- **Quiero:** un entorno Docker reproducible con Odoo 18 Community y PostgreSQL, scripts de calidad y de tests, un módulo base que deje la instancia configurada para Ecuador y un módulo de marca propia
- **Para:** construir los módulos de Contabilidad/SRI y RRHH/Nómina sobre una base estable, verificable y sin modificar el núcleo de Odoo

---

### 2. Criterios de Aceptación (Gherkin / BDD)
- **CA-1 · Entorno levanta (camino feliz):**
  - **Dado que:** el repositorio está clonado y se copió `.env.example` a `.env` (y la plantilla de configuración a `config/odoo.conf` si el diseño lo requiere)
  - **Cuando:** se ejecuta `docker compose up -d`
  - **Entonces:** el proyecto Compose se llama `erp`; Odoo 18.0 responde HTTP 200 en `http://127.0.0.1:8069/web/health` (o la ruta de salud equivalente de Odoo 18); PostgreSQL 16 no publica puerto (o solo en `127.0.0.1`); los volúmenes son `erp_db_data` y `erp_odoo_data`; `addons/` y cada `third_party/<repo>/` que contenga módulos están en el `addons_path`.
- **CA-2 · Secretos fuera del repositorio:**
  - **Dado que:** no existe `.env`
  - **Cuando:** se ejecuta `docker compose up -d`
  - **Entonces:** Compose falla con un mensaje claro que indica qué variable falta (sin valores por defecto inseguros). `.env`, `config/odoo.conf` y cualquier volcado/certificado están en `.gitignore`; el repositorio solo contiene `*.example` sin contraseñas reales. `list_db` desactivado en la plantilla de producción.
- **CA-3 · Script de tests:**
  - **Dado que:** el entorno está levantado
  - **Cuando:** se ejecuta `bash scripts/test.sh erp_base,erp_branding`
  - **Entonces:** se crea una BD efímera, se instalan los módulos con `--test-enable --stop-after-init`, se eliminan la BD al terminar y el código de salida es 0 si todos los tests pasan y ≠ 0 si alguno falla o la instalación falla (con el log del error visible).
- **CA-4 · Script de calidad:**
  - **Dado que:** existe `.pre-commit-config.yaml` tipo OCA
  - **Cuando:** se ejecuta `bash scripts/check.sh`
  - **Entonces:** corre ruff, pylint-odoo y validación de XML/manifest sobre `addons/` y sale con 0 en el código entregado; `bash scripts/check.sh --all` añade los tests de todos los módulos de `addons/`.
- **CA-5 · `erp_base` configura Ecuador:**
  - **Dado que:** una BD nueva
  - **Cuando:** se instala `erp_base`
  - **Entonces:** quedan instalados `l10n_ec` (y por tanto `account`); el idioma `es_EC` está activo y es el del usuario administrador; la empresa principal tiene país Ecuador y moneda USD; la zona horaria del administrador es `America/Guayaquil`; la empresa tiene cargado el plan contable de Ecuador de `l10n_ec` si no tenía uno.
- **CA-6 · `erp_base` idempotente y no destructivo:**
  - **Dado que:** `erp_base` ya está instalado y el usuario cambió manualmente su idioma o su zona horaria
  - **Cuando:** se actualiza el módulo (`-u erp_base`)
  - **Entonces:** la actualización termina sin errores y no sobrescribe esas preferencias ni duplica datos.
- **CA-7 · Marca propia (`erp_branding`):**
  - **Dado que:** `erp_branding` está instalado
  - **Cuando:** un usuario abre la pantalla de login y el cliente web
  - **Entonces:** el título de la pestaña del navegador y el login muestran el nombre de marca configurado, por defecto **ERP LCE** (no "Odoo"); el enlace "Powered by Odoo" no se muestra en login; el cliente web usa la paleta institucional (amarillo `#FCE200`, negro `#000000`, gris `#E1E1E1`) con contraste WCAG AA (texto negro sobre amarillo, nunca amarillo sobre blanco/gris claro para texto); hay favicon y logo propios (placeholder con las iniciales LCE hasta recibir el logo oficial; se reemplaza sustituyendo los archivos de `erp_branding/static/img/` con el mismo nombre, sin cambios de código); el nombre de marca se cambia desde un parámetro de sistema sin tocar código.
- **CA-8 · Núcleo intacto y terceros documentados:**
  - **Dado que:** se revisa el repositorio
  - **Cuando:** se busca código de Odoo modificado
  - **Entonces:** no existe copia ni parche del núcleo; toda personalización está en `addons/erp_*`; `third_party/README.md` existe con la tabla (origen, rama, commit, licencia) aunque esté vacía.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Infraestructura | DEV-5 | `docker-compose.yml` (`name: erp`, imágenes `odoo:18.0` y `postgres:16` fijadas por digest), `.env.example`, `config/odoo.conf.example` (dev) y plantilla de producción, `.gitignore`, `scripts/check.sh`, `scripts/test.sh`, `.pre-commit-config.yaml` + configs de linters, `addons/.gitkeep`, `third_party/README.md`, `README.md` (sección de entorno) |
| Datos | DEV-3 | `addons/erp_base/`: `__init__.py`, `__manifest__.py` (`18.0.1.0.0`, LGPL-3, depends `base`, `l10n_ec`), datos declarativos que aplique (`data/`) y ACL si hubiera modelos (no se esperan) |
| Backend | DEV-2 | `erp_base`: `post_init_hook` (idioma `es_EC`, país/moneda de la empresa, tz admin, carga del plan `l10n_ec` si falta) idempotente; tests `TransactionCase` de CA-5/CA-6 |
| Web | DEV-4 | Módulo `addons/erp_branding/` completo: parámetro de sistema del nombre de marca, título del cliente web (patch OWL), login sin "Powered by Odoo" (herencia QWeb), favicon/logo placeholder, `static/description/`, `i18n/es.po`; tests del parámetro y de la plantilla |

**Fuera de alcance:** carga de datos reales de la empresa (razón social, RUC; ver US-002), logo definitivo, facturación electrónica SRI, nómina, módulos OCA (solo se prepara `third_party/`), CI remoto, respaldo/restauración y despliegue de producción (US-009).

---

### 4. Contrato
| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Salud | `GET /web/health` | Público | — | 200 `{"status":"pass"}` | — |
| Nombre de marca | `ir.config_parameter` `erp_branding.name` | Administración (Ajustes técnicos) | texto | usado en título y login; por defecto `ERP LCE` | vacío → se usa `ERP LCE` |
| Tests | `scripts/test.sh <modulos>` | Desarrollador | lista separada por comas | código de salida 0/≠0 | módulo inexistente → ≠0 con mensaje |
| Calidad | `scripts/check.sh [--all]` | Desarrollador | — | código de salida 0/≠0 | — |

---

### 5. Decisiones Técnicas y Supuestos
- Imagen oficial `odoo:18.0` y `postgres:16` fijadas por digest para reproducibilidad; actualizar el digest es un cambio explícito.
- `es_EC` como idioma: Odoo trae `es_EC`; si su traducción es incompleta, Odoo usa la de `es` como base. Los textos propios se traducen en `i18n/es.po`.
- La configuración regional se aplica en `post_init_hook` (no en XML de datos) para poder hacerla idempotente y no destructiva.
- **Plan contable (decisión Tech Lead, 2026-10-29):** Odoo 18 carga la plantilla pendiente (`generic_coa` si la empresa no es EC) en `IrModule._register_hook`, *después* de los `post_init_hook` (hallazgo DEV-3). Como el ERP es de una sola empresa ecuatoriana, el hook fuerza país Ecuador y plan `ec` en la empresa principal **solo si no tiene contabilidad existente** (`_existing_accounting()`), sustituyendo la carga pendiente del registro (API privada, acceso defensivo) o llamando a `try_loading('ec')`. Con apuntes contables no se toca nada.
- **Logo (decisión Tech Lead, ronda QA 1):** el logo del login es un recurso de marca versionado en `erp_branding` (no el logo de `res.company`); "reemplazable sin código" = sustituir el archivo. Los textos "Odoo" restantes del núcleo (diálogos, selector de BD, menú de usuario, portal) quedan fuera de alcance (historia de marca futura si se pide).
- **Tests sin demo (ronda QA 1):** `scripts/test.sh` instala sin datos de demostración por defecto (como producción) para cubrir CA-5 de verdad; `TEST_DEMO=1` los activa.
- `erp_base` usa categoría `Technical` (no `Accounting/Localizations/Account Charts`) para que Odoo no lo trate como plantilla de plan contable.
- No existe `es_EC.po` en Odoo; las traducciones se toman de `es_419`/`es` (comportamiento estándar de `get_po_paths`).
- Marca indicada por el usuario (2026-10-29): nombre **ERP LCE**; paleta institucional LAARCOURIER EXPRESS S.A.: amarillo `#FCE200` (Pantone P 4-8 C), negro `#000000` (Process Black C), gris `#E1E1E1` (P 179-3 C). Logo oficial pendiente de entrega: placeholder reemplazable sin código.
- Empresa principal: LAARCOURIER EXPRESS S.A., RUC 1791705726001. La carga de estos datos en la empresa es de US-002 (no de esta historia).
- Retirar "Powered by Odoo" está permitido por la licencia LGPL-3 de Odoo Community; se mantiene la atribución de licencia en los manifiestos.
- OCA tiene ramas `18.0` en `l10n-ecuador`, `payroll` y `hr` (verificado con `git ls-remote` el 2026-10-29); su idoneidad se decide en US-002 y US-006.
- Esta máquina ejecuta contenedores SQL Server de otros proyectos: no se tocan; se evita cualquier colisión de puertos/nombres.

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-29
- **QA-FUNC:** 🟢 APROBADO CON OBSERVACIONES (ronda 2; ronda 1 BLOQUEADO por B-1 contraste, B-2 tests inestables, B-3 CA-5 sin test) · **QA-TECH:** 🟢 APROBADO CON OBSERVACIONES 9/10 (ronda 3 de P3: sin hallazgos abiertos; ronda 2 8,5/10; ronda 1 RECHAZADO por 2 P1 + 1 P2)
- **Criterios de aceptación:** CA-1 ✅, CA-2 ✅, CA-3 ✅, CA-4 ✅, CA-5 ✅, CA-6 ✅, CA-7 ✅ (título de pestaña OWL solo revisado en código), CA-8 ✅
- **Archivos principales:** `docker-compose.yml`, `docker/odoo/entrypoint.sh`, `docker/compose.test.yml`, `docker/lint/`, `config/*.example`, `.env.example`, `scripts/test.sh`, `scripts/check.sh`, `.pre-commit-config.yaml`, `third_party/README.md`, `README.md`, `addons/erp_base/` (hook `_setup_ecuador`, 14 tests), `addons/erp_branding/` (marca ERP LCE, SCSS, patch OWL del título, auditor de contraste CSS, 13 tests)
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead tras la ronda P3 → exit 0 (pre-commit con ruff, pylint-odoo, prettier, **eslint 9.39.5** y **shellcheck** sobre `addons/`, `scripts/`, `docker/`; `0 failed, 0 error(s) of 28 tests`, sin demo, BD efímera eliminada; pip-audit de `requirements-dev.txt`: sin vulnerabilidades conocidas). QA-FUNC: `check.sh --all` ×3 exit 0 (una con carga paralela); `TEST_DEMO=1` exit 0; instalación limpia → empresa EC/USD/plan `ec` (505 cuentas, 7 diarios, 173 impuestos), admin `es_EC`/`America/Guayaquil`; `-u` respeta preferencias. Login `erp_dev`: `<title>ERP LCE</title>`, sin "Powered by".
- **Pendientes:**
  1. Revisión visual en navegador (sin Chrome en la imagen): título de pestaña "<acción> - ERP LCE", botón "Nuevo", avatar, campo copiar, ChatHub; auditoría axe/Lighthouse incl. zoom 200 %.
  2. Logo oficial de LAARCOURIER (sustituir archivos de `erp_branding/static/img/`).
  3. ~~P3 DEV-5: shellcheck/ESLint; pip-audit de `requirements-dev.txt`~~ → resuelto (ronda P3, 2026-10-29).
  4. ~~P3 DEV-4: comentario de contrastes; auditoría CSS del login~~ → resuelto (ronda P3). Sigue abierto: correcciones de `mail`/`web_editor` sin test automático hasta que un módulo propio dependa de ellos; el auditor CSS es heurístico (revisar al actualizar la imagen de Odoo).
  5. ~~P3 DEV-2: `test_core_pending_template_api` ejecuta toda la cadena `_register_hook`~~ → resuelto (ronda P3).
  6. Marca fuera de alcance: textos "Odoo" del núcleo (diálogos, menú de usuario, portal, selector de BD), amarillos no corporativos del núcleo (O-7).
  7. A US-009: rol de BD sin superusuario, hash de `admin_passwd`, credenciales visibles en `ps`, contraseña `admin` por defecto en BD sin demo.
