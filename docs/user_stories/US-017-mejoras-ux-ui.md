# Historia de Usuario: US-017 - Mejoras de UX/UI y accesibilidad (auditoría 2026-10-30)

- **ID:** US-017
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-30
- **Sprint / Módulo:** Transversal · `erp_branding`, `erp_base`, `erp_establishment`, `erp_hr_ec`, `erp_payroll_ec` (vistas), `scripts/`
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-5 (serializar tests) / DEV-2 (método de validación, campo de visualización, signup) / DEV-4 (marca, vistas, terminología)
- **Depende de:** US-001, US-007, US-008 (en ronda de correcciones en paralelo), US-010

---

### 1. Definición de la Historia
- **Como:** usuario final del ERP LCE (muchos usuarios, poco técnicos)
- **Quiero:** pantallas claras, accesibles y coherentes con la marca, con la terminología de Ecuador ("Rol de pagos") y sin pasos confusos
- **Para:** usar el sistema sin capacitación extensa ni errores por descuido
- **Origen:** reporte del auditor UX/UI del 2026-10-30 (1 crítico, 3 altos, 9 medios, 6 bajos). Decisión del usuario: se trabaja **ahora**, antes de continuar el backlog, y el auditor UX/UI pasa a ser fijo en el ciclo (`docs/equipo/perfil.md` §5.1).

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Marca y accesibilidad global (`erp_branding`)**
- **CA-1 · Login sin restos de Odoo:** *Dado que* la página de login, *cuando* el botón «Iniciar sesión» está en carga (deshabilitado), con foco o hover, y en los enlaces (`.btn-link`) y botones secundarios, *entonces* usan la paleta ERP LCE (amarillo `#FCE200`/negro/gris `#E1E1E1`; texto sobre amarillo negro), sin `#714B67` ni azul `#2D3142`; la auditoría de CSS (`tests/css_audit.py`) cubre estos estados.
- **CA-2 · Registro de cuentas desactivado:** *Dado que* el sistema es interno, *cuando* se abre el login, *entonces* no aparece «¿No tienes una cuenta?» ni se puede registrar una cuenta por `/web/signup` (`auth_signup.invitation_scope = b2b` o equivalente, aplicado por módulo y con test); restablecer contraseña se mantiene.
- **CA-3 · Contraste de controles y textos:** casillas y radios sin marcar con borde ≥ 3:1 (WCAG 1.4.11); `text-muted` y textos de ayuda ≥ 4.5:1 (WCAG 1.4.3) en todo el cliente interno; los campos obligatorios se distinguen sin necesidad de foco; ilustraciones de estados vacíos sin malva de Odoo; la auditoría de CSS lo verifica.
- **CA-4 · Idioma del documento:** `<html lang="es-EC">` (o el idioma del usuario) en login y cliente interno.

**Pantallas de RRHH y establecimientos**
- **CA-5 · Ficha de empleado más simple:** como máximo 6 pestañas visibles para el perfil RRHH + nómina sin barra de desplazamiento a 1366 px; «Datos adicionales» y «Bonos y descuentos fijos» se integran como secciones (p. ej. «Datos adicionales» dentro de «Ecuador» y «Bonos y descuentos fijos» dentro de «Nómina»); ayudas en una línea (detalle en `help` de campos).
- **CA-6 · Datos adicionales con un solo «Valor»:** la lista muestra una columna «Valor» (texto calculado) y se edita en un formulario emergente con un único campo según el tipo y la ayuda del dato visible.
- **CA-7 · «Sin instructor» al final:** en el desplegable de Instructor la opción «Sin instructor» aparece **siempre al final** de la lista (después de los empleados y antes/después de «Buscar más» según el patrón de Odoo), nunca como primera opción activa; Tab/Intro tras abrir el campo no la selecciona (cambia CA-1 de US-010; decisión del usuario 2026-10-30).
- **CA-8 · Establecimientos y Datos adicionales:** formularios con título (`oe_title`/`h1`), estado vacío con la indicación correcta (engranaje ⚙ > Importar registros), filtros con etiquetas no truncadas, Ajustes con «40 horas» (unidad después y sin decimales).

**Nómina**
- **CA-9 · Rol de pagos claro:** el campo de título del rol tiene etiqueta y ejemplo; terminología unificada en español de Ecuador en menús, botones, campos y estado vacío del motor OCA: «Roles de pagos», «Lotes de roles», «Calcular rol», «Anular rol», «Rol rectificativo» (no «Factura rectificativa»), «Líneas del rol», «Cálculo del rol»; avisos fijos con `role="note"` y como máximo dos frases.
- **CA-10 · Validar parámetros de forma deliberada:** la barra de estado del parámetro no es clicable; hay un botón primario «Marcar como validado» con confirmación (método de servidor solo para el responsable); la lista abre sin agrupar por código técnico, con el filtro «A validar» activo por defecto y encabezados no truncados.
- **CA-11 · Listas legibles:** encabezados no truncados en listas propias (etiquetas cortas «Base IESS», «Base 13.º», «Desde», «Hasta»; columna «Activo» opcional/oculta); pestaña de bonos fijos sin interruptor «Activo» visible y orden por fecha.

**Calidad**
- **CA-12:** `bash scripts/test.sh` serializa ejecuciones concurrentes (un solo log por BD efímera); `bash scripts/check.sh --all` sale con 0; QA-UX re-audita en vivo y no quedan hallazgos Críticos ni Altos.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Infraestructura | DEV-5 | Candado en `scripts/test.sh` (p. ej. `flock`) o nombre de contenedor por BD, para que ejecuciones simultáneas no mezclen logs; documentado en README/perfil |
| Backend / Datos | DEV-2 (autorizado también en campos) | `erp.payroll.parameter.action_validate` (solo responsable), `erp.hr.extra.value.value_display` (calculado), desactivación del signup por datos/hook idempotente en `erp_base` o `erp_branding`, tests |
| Web | DEV-4 | SCSS de marca (login, casillas, `text-muted`, obligatorios, ilustración), `lang`, vistas de RRHH/establecimientos/nómina, widget del Instructor, traducción `es_EC` de terminología OCA (`i18n/es.po` del módulo propio o `string` en herencias), tests de vistas y de la auditoría CSS |
| QA | QA-FUNC, QA-TECH, QA-UX | Auditoría en paralelo |

**Fuera de alcance:** cambios del núcleo de Odoo (contador de mensajes de la barra superior, altura de opciones de autocompletado, `aria-selected` en pestañas: observaciones del núcleo, se documentan).

---

### 5. Decisiones Técnicas y Supuestos
- US-008 continúa en paralelo (DEV-2 en `erp_payroll_ec/models`, `wizard`, tests de lógica). DEV-4 toca solo `views/`, `static/`, `i18n/` y tests de vistas; los cambios de modelo de esta historia se hacen después de que DEV-2 cierre su ronda de US-008 para no editar los mismos archivos a la vez.
- La terminología se cambia por traducción/`string` en herencias, sin tocar `third_party/`.
- "Sin instructor" al final reemplaza el CA-1 de US-010 ("al inicio de la lista").
- El signup se desactiva porque el sistema es interno (decisión del usuario 2026-10-30).

### Hallazgos de la auditoría (2026-10-30, resumen)
- Crítica: título del rol sin nombre accesible.
- Altas: malva de Odoo en estados del login y `.btn-link`; casillas sin marcar 1.30:1; `text-muted` ~4.1–4.3:1.
- Medias: 8 pestañas en el empleado; 6 columnas «Valor» en Datos adicionales; validar parámetro con un clic; parámetros agrupados por código; terminología OCA; obligatorios invisibles; encabezados truncados; pestaña de bonos fijos con «Activo» y ayuda larga; estado vacío de establecimientos con indicación errónea e ilustración malva; «Sin instructor» como primera opción activa.
- Bajas: falta `lang`; tú/usted en login; filtros truncados; formularios sin título; `role="status"` en avisos fijos; unidad de horas en Ajustes.
- No verificado: ancho 375 px (ventana maximizada).

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-30
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (ronda 2; CA-6 bloqueante en ronda 1 —ayuda del dato— corregido) · **QA-TECH:** 🟡 APROBADO CON OBSERVACIONES 8/10 · **QA-UX:** ronda 1 2 Altos (regresión de `o-color-2` 1,13:1 y placeholders 1,74:1) corregidos; verificación final: todos los hallazgos de la auditoría corregidos; queda **1 Alta marginal de origen en el núcleo** (texto «Seguir» del chatter #6c757d sobre #f8f9fa, 4,45:1) no introducida por esta historia → pendiente (límite de 2 rondas).
- **Criterios:** CA-1 ✅ CA-2 ✅ CA-3 ✅ (salvo chatter del núcleo) CA-4 ✅ CA-5 ✅ CA-6 ✅ CA-7 ✅ CA-8 ✅ (horas mostradas con 2 decimales, «40,00 horas», para no redondear 37,5; decisión del Tech Lead) CA-9 ✅ CA-10 ✅ CA-11 ✅ CA-12 ✅ (salvo pendiente 1)
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (`0 failed, 0 error(s) of 411 tests`; pip-audit limpio). `erp_dev` actualizado; verificación en vivo por QA-UX en Chrome.
- **Pendientes (próxima ronda de UX):**
  1. [Alta, núcleo] Seguidores del chatter a 4,45:1 → color de marca `$erp-brand-muted` o redefinir gris 600 del backend.
  2. [Media] `payroll.hr_payslip_action_employee` sin `help` propio.
  3. [Baja] UserError del parámetro aún cita «Volver a A validar» (botón: «Devolver a revisión»).
  4. [Baja] Líneas del horario «Monday Morning…» en inglés, encabezado truncado y zona horaria UTC en la jornada por defecto.
  5. [Baja] Ajustes de Nómina con «nómina» en lugar de «rol de pagos».
  6. Ancho 375 px no verificado (ventana de Chrome maximizada); tests hoot no ejecutables (sin navegador en la imagen).
  7. Núcleo (fuera de alcance): contador de mensajes 3,13:1, desbordamiento de la barra del chatter, OdooBot en inglés.
