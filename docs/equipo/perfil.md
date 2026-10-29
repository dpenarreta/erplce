# Perfil técnico del equipo — ERP (Odoo 18 Community · Ecuador)

Documento de referencia para el Tech Lead (`/equipo`) y todos los subagentes. Lo que se define aquí prevalece sobre las reglas genéricas de `~/.claude/agents/*.md`. Lo mantiene el Tech Lead.

## 1. Arquitectura

- **Base:** Odoo 18.0 Community (LGPL-3). **Prohibido modificar el núcleo** (código de la imagen oficial o del repositorio `odoo/odoo`). Toda personalización se hace por herencia (`_inherit`, herencia de vistas XML con `xpath`, `patch` de componentes OWL) en módulos propios.
- **Capas:**
  - Navegador (cliente web OWL de Odoo, portal) → servidor Odoo (ORM, controladores HTTP/JSON-RPC) → PostgreSQL.
  - Servidor Odoo → sistemas externos (SRI: recepción y autorización de comprobantes electrónicos; bancos; IESS si aplica) solo a través de conectores de DEV-3.
- **Módulos:**
  - `addons/`: módulos propios, prefijo `erp_` (p. ej. `erp_base`, `erp_branding`, `erp_account_ec`, `erp_hr_ec`, `erp_payroll_ec`). Un módulo por dominio funcional, con dependencias mínimas y explícitas.
  - `third_party/`: módulos de terceros (OCA u otros) incluidos como submódulos git o copias fijadas a un commit concreto, documentados en `third_party/README.md` (origen, rama, commit, licencia). No se editan; se extienden desde `addons/`.
- **Localización Ecuador:** base en `l10n_ec` (Community: plan de cuentas, impuestos, tipos de identificación, tipos de documento SRI). La facturación electrónica oficial de Odoo (`l10n_ec_edi`) es de Enterprise: en Community se cubre con módulos OCA (`OCA/l10n-ecuador`) si existen en 18.0, o con desarrollo propio. **Estado a confirmar en la historia técnica correspondiente** (no asumir).
- **Nómina:** Odoo Community no incluye nómina. Opciones: `OCA/payroll` (si está disponible y estable en 18.0) + reglas Ecuador propias, o módulo propio. Decisión a tomar en su historia técnica.

## 2. Roles activos y ámbitos

Convención dentro de cada módulo de `addons/<modulo>/`:

| Rol | Subagente | Rutas que puede modificar |
|---|---|---|
| DEV-5 DevOps | `dev-devops` | `docker-compose*.yml`, `docker/`, `config/` (`odoo.conf` plantillas), `scripts/`, `.github/` o CI, `.pre-commit-config.yaml`, `pyproject.toml`/configs de linters, `requirements*.txt` del entorno, `.env.example`, `.gitignore`, `third_party/` (alta de submódulos) y secciones de entorno del `README.md` |
| DEV-3 Datos e Integraciones | `dev-database` | En `addons/*/`: **declaración de modelos y campos** (`models/*.py`: clases, `_name`, `_inherit`, campos, `_sql_constraints`, `_order`, índices), `security/ir.model.access.csv`, `security/*_security.xml` (grupos y reglas de registro), `data/` (secuencias, parámetros, maestros), `migrations/<version>/`, conectores externos en `addons/*/services/` o módulos `erp_*_connector`, y sus tests |
| DEV-2 Backend | `dev-backend` | En `addons/*/`: **métodos de negocio** de los modelos (`@api.depends`/compute, `@api.constrains`, `@api.onchange`, acciones `action_*`, flujos de estado, overrides de `create`/`write`/`unlink`), `wizard/`, `controllers/`, `report/*.py`, crons (`ir.cron` + método), y sus tests |
| DEV-4 Web | `dev-web` | En `addons/*/`: `views/*.xml` (form, list, kanban, search, pivot, graph, menús, acciones de ventana), `report/*.xml` (QWeb PDF/HTML), `static/src/` (OWL, JS, SCSS, XML de plantillas), `static/description/`, traducciones `i18n/es.po` / `es_EC.po`, y el módulo de marca `erp_branding` |
| QA-FUNC / QA-TECH | `qa-functional` / `qa-technical` | Solo lectura + ejecutar verificación |
| DEV-1 Mobile | — | No aplica en esta fase |

**Archivos compartidos** (`__manifest__.py`, `__init__.py`, `models/*.py`): DEV-3 crea el archivo y declara campos; DEV-2 añade métodos en el mismo archivo después; cada uno añade en `__manifest__.py` solo sus entradas (`data`, `depends`, `assets`). El Tech Lead los lanza en secuencia (DEV-3 → DEV-2 → DEV-4), nunca en paralelo sobre el mismo módulo.

## 3. Stack fijo

| Capa | Tecnología |
|---|---|
| ERP | Odoo 18.0 Community, imagen Docker oficial `odoo:18.0` fijada por digest o fecha de build |
| Base de datos | PostgreSQL 16 (imagen oficial fijada) |
| Lenguaje servidor | Python 3 (el de la imagen de Odoo 18) |
| Interfaz | Vistas XML de Odoo, OWL 2 (framework JS de Odoo 18), QWeb, SCSS de assets |
| Reportes | QWeb PDF (wkhtmltopdf de la imagen oficial) |
| Calidad | `pre-commit` con configuración tipo OCA: `ruff`, `pylint-odoo`, `prettier`/`eslint` para JS/XML cuando aplique |
| Tests | Framework de tests de Odoo (`odoo.tests.TransactionCase`, `tagged`, `Form`, `HttpCase` para tours) |
| Contenedores | Docker Compose v2 |

## 4. Convenciones (Odoo)

- Nombres técnicos en inglés siguiendo las guías de Odoo (`erp.payslip.line`, `l10n_ec_*` solo para extensiones de localización); etiquetas (`string`) y mensajes en **español**, traducibles (`_()` / `_lt()`, `i18n/es.po`).
- Moneda USD. Zona horaria `America/Guayaquil`. Idioma por defecto `es_EC`. Fechas en la BD en UTC (lo gestiona el ORM).
- Importes con `fields.Monetary` + `currency_id`; nunca `Float` para dinero. Redondeos con `float_round`/`currency.round`.
- Multiempresa: todo modelo de negocio lleva `company_id` y reglas de registro por empresa cuando aplique (`check_company=True`).
- Errores de negocio con `UserError` / `ValidationError` y mensaje en español accionable; nunca excepciones genéricas hacia el usuario.
- Seguridad: cada modelo nuevo tiene ACL en `ir.model.access.csv`; `sudo()` solo con comentario que lo justifique y acotado.
- Sin SQL crudo salvo necesidad justificada; si se usa, `self.env.cr.execute(query, params)` parametrizado (o `SQL()` de Odoo 18), nunca con formateo de strings, e invalidando la caché del ORM tras escribir.
- Rendimiento: operaciones en lote (`create` con lista de valores, `read_group`/`_read_group`, `search_fetch`), sin `search` dentro de bucles, `prefetch` respetado.
- **Parámetros normativos de Ecuador** (porcentajes IVA, retenciones, aportes IESS, décimos, fondos de reserva, SBU, utilidades, plazos SRI): nunca hardcodeados en código; se modelan como datos/parámetros configurables con vigencia por fecha, y cada valor cargado cita su fuente normativa en la Historia de Usuario. Si no hay fuente proporcionada por el usuario, queda marcado "a validar".
- Versión de cada módulo: `18.0.X.Y.Z`. Al cambiar estructuras con datos existentes, subir versión y añadir script en `migrations/`.

## 5. Comandos de verificación

*(Creados en US-001. Todo corre en contenedores; en el host solo hacen falta Docker y Git Bash.)*

| Capa | Comando | Qué ejecuta |
|---|---|---|
| Entorno | `docker compose up -d` | Levanta Odoo + PostgreSQL |
| Calidad estática | `bash scripts/check.sh` | pre-commit en contenedor (`docker/lint`) sobre `addons/`, `scripts/` y `docker/`: ruff, pylint-odoo 18.0, odoo-pre-commit-hooks, prettier XML/JS, ESLint 9 (`addons/*/static/src/**/*.js`, `eslint.config.cjs`) y shellcheck (`scripts/*.sh`, `docker/**/*.sh`). Si un hook corrige archivos, sale ≠ 0: volver a ejecutar |
| Tests | `bash scripts/test.sh <modulo>[,<modulo>]` | Crea BD efímera, instala los módulos **sin demo** (`--without-demo=all`; `TEST_DEMO=1` para cargarla) con `--test-enable --stop-after-init`, ejecuta solo los tests de esos módulos (`TEST_TAGS` para cambiarlo), borra la BD y devuelve ≠ 0 si falla un test, hay `ERROR`/`CRITICAL` en el log o un módulo no queda instalado |
| Completa | `bash scripts/check.sh --all` | Calidad estática + tests de todos los módulos de `addons/` + `pip-audit` de `requirements-dev.txt` y de los requirements de addons |

## 6. Reglas específicas por rol

### DEV-3
- Campos con `string`, `help` cuando no sea obvio, `index=True` en campos de búsqueda frecuente, `ondelete` explícito en `Many2one`, `tracking=True` en campos auditables de documentos.
- Restricciones de BD con `_sql_constraints` (unicidad/CHECK); validaciones complejas las implementa DEV-2 con `@api.constrains`.
- Conectores SRI: cliente SOAP/HTTP con timeouts, reintentos solo idempotentes, registro de cada envío y respuesta en un modelo de log, certificados de firma electrónica (.p12) y contraseñas cifrados o en almacenamiento seguro, nunca en el repositorio ni en logs.

### DEV-2
- Lógica en métodos del modelo o servicios; acciones de botón finas.
- Documentos con estados (`state` Selection) y transiciones validadas en servidor; documentos confirmados/autorizados no editables.
- Tests con `TransactionCase` por regla de negocio: camino feliz, validaciones, permisos (usuario sin grupo, otra empresa) y transiciones inválidas.

### DEV-4
- Herencia de vistas con `xpath` precisos; nunca reemplazar vistas completas del núcleo.
- Componentes OWL con `patch` o registros (`registry`) del framework; assets declarados en `__manifest__.py` (`web.assets_backend`, `web.report_assets_common`).
- Accesibilidad y estados vacíos (`<field name="help">` en acciones de ventana).
- Marca (logo, colores, nombre, favicon, pantalla de login) concentrada en `erp_branding`.

### DEV-5
- Contenedores con nombre de proyecto `erp` (Compose `name: erp`), volúmenes propios (`erp_db_data`, `erp_odoo_data`).
- PostgreSQL sin puerto publicado o ligado a `127.0.0.1`; Odoo en `127.0.0.1:8069` en desarrollo.
- `admin_passwd` (master password) y credenciales de BD solo en `.env` / `config/odoo.conf` no versionados, con `.example`.
- `list_db = False` y `proxy_mode` en la configuración de producción.
- Respaldo: volcado PostgreSQL + filestore, con script de restauración probado.
- Esta máquina ya ejecuta contenedores SQL Server de otros proyectos (puertos 1433, 14330-14332): no tocarlos.

## 7. Estado actual

- 2026-10-29: entorno Docker y scripts de verificación creados (US-001 completada con pendientes). Empresa: LAARCOURIER EXPRESS S.A. (RUC 1791705726001), una sola empresa. Marca: ERP LCE. Prioridad: RRHH/Nómina antes que facturación SRI (ver índice de historias).
- Primera historia obligatoria: **Historia Técnica de base de la plataforma** (entorno Docker reproducible, estructura `addons/` y `third_party/`, `scripts/check.sh` y `scripts/test.sh`, módulo `erp_base` con dependencias de `l10n_ec`, idioma `es_EC`, zona horaria y moneda, y módulo `erp_branding`).
- Pendiente de confirmar con el usuario: razón social/RUC de la(s) empresa(s), multiempresa, ambiente SRI (pruebas/producción), tipos de comprobantes electrónicos requeridos, reglas de nómina (contratos, horas extra, beneficios propios) y fuente normativa de los parámetros.

### Notas de entorno (US-001)
- Imágenes fijadas: `odoo:18.0@sha256:9668abac…` (build 2026-10-26) y `postgres:16@sha256:1beaa308…` (16.15). Ver `docker-compose.yml`.
- `addons_path` lo calcula `docker/odoo/entrypoint.sh`: núcleo + `addons/` + cada `third_party/<repo>/` con módulos (se detecta al reiniciar).
- La imagen oficial de Odoo **no trae Chrome**: los tours (`HttpCase.start_tour`/`browser_js`) no son ejecutables; usar `TransactionCase` y `HttpCase.url_open` para probar HTML.
- Antivirus con inspección TLS en esta máquina: `ERP_EXTRA_CA_CERT` en `.env` apunta a la CA a añadir en los contenedores (ver `CLAUDE.local.md`).
