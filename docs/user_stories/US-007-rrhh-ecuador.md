# Historia de Usuario: US-007 - RRHH Ecuador: empleados, contratos y establecimientos

- **ID:** US-007
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** RRHH · `erp_establishment` (nuevo), `erp_hr_ec` (nuevo)
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (modelos, seguridad, datos, plantilla) / DEV-2 (validaciones y lógica) / DEV-4 (vistas, menús, ajustes)
- **Depende de:** US-001 (US-006 no es requisito; `erp_payroll_ec` pasará a depender de `erp_hr_ec` en US-008)

---

### 1. Definición de la Historia
- **Como:** responsable de RRHH de LAARCOURIER EXPRESS S.A.
- **Quiero:** registrar los 178 establecimientos SRI con su región, y los empleados con los datos exigidos en Ecuador (cédula, establecimiento, discapacidad, cargas familiares, cuenta bancaria, opción de mensualizar o acumular décimos y fondos de reserva), datos adicionales configurables por la empresa, y contratos con tipo y jornada parametrizables
- **Para:** tener la base de datos completa y validada que la nómina (US-008) necesita, sin cifras legales fijas en el código

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Establecimientos (`erp_establishment`)**
- **CA-1 · Catálogo de establecimientos:**
  - **Dado que:** un usuario administrador (Ajustes)
  - **Cuando:** crea un establecimiento con código `1`, nombre, dirección, ciudad, provincia de Ecuador y región `Costa`
  - **Entonces:** se guarda con código normalizado a `001`, régimen de décimo cuarto `Costa / Galápagos` calculado de la región (Galápagos → `Costa / Galápagos`; Sierra y Amazonía → `Sierra / Amazonía`), activo por defecto y de la empresa actual. Un usuario interno sin ese grupo puede leer el catálogo pero no modificarlo.
- **CA-2 · Validaciones del código y la provincia:**
  - **Dado que:** existe el establecimiento `001` en la empresa
  - **Cuando:** se intenta crear otro `001` (o `1`), un código no numérico, `000` o de más de 3 dígitos, o una provincia que no es de Ecuador
  - **Entonces:** se rechaza con un mensaje en español que indica el código o la provincia inválidos; archivar (inactivar) un establecimiento es posible y conserva su historial.
- **CA-3 · Plantilla de carga masiva:**
  - **Dado que:** el usuario quiere cargar los 178 establecimientos
  - **Cuando:** abre *Importar registros* en la lista de establecimientos
  - **Entonces:** el importador nativo de Odoo ofrece descargar la plantilla `plantilla_establecimientos.csv` (columnas: Código, Nombre, Dirección, Ciudad, Provincia, Región, Activo; filas de ejemplo ficticias), las columnas se mapean solas en español, y al importar esa plantilla se crean los registros con sus regiones; `Activo = No` crea el establecimiento archivado; un código repetido en el archivo o ya existente hace fallar la importación con el error de la fila; una provincia ambigua por nombre (p. ej. `Bolívar`) se resuelve a la de Ecuador. Hay una guía en `docs/guias/carga-establecimientos.md` con el significado y valores admitidos de cada columna.

**Empleados (`erp_hr_ec`)**
- **CA-4 · Datos de Ecuador del empleado:**
  - **Dado que:** un usuario de RRHH (`hr.group_hr_user`)
  - **Cuando:** registra un empleado con nacionalidad Ecuador, cédula, establecimiento, cuenta bancaria (campo estándar `bank_account_id`, banco incluido), ciudad de residencia (campo estándar), discapacidad (sí/no, porcentaje, número de carné, sustituto) y cargas familiares (nombre, identificación, parentesco, fecha de nacimiento, discapacidad)
  - **Entonces:** se guardan; la región y el régimen de décimo cuarto del empleado se muestran heredados del establecimiento y cambian si se cambia de establecimiento; los datos personales sensibles (discapacidad, cargas) solo los ven usuarios de RRHH.
- **CA-5 · Validaciones del empleado:**
  - **Dado que:** el formulario de empleado
  - **Cuando:** se ingresa una cédula ecuatoriana inválida (dígito verificador) para nacionalidad Ecuador, una cédula ya usada por otro empleado activo de la empresa, un porcentaje de discapacidad fuera de 0–100 o con discapacidad marcada y porcentaje 0, o un establecimiento archivado
  - **Entonces:** se rechaza con un mensaje en español específico. Un empleado extranjero sin cédula ecuatoriana (pasaporte) se guarda.
- **CA-6 · Décimos y fondos de reserva por empleado, con vigencia:**
  - **Dado que:** los valores por defecto de la empresa en Ajustes de Empleados (décimo tercero, décimo cuarto y fondos de reserva: `Mensualizado` / `Acumulado`, valores iniciales "a validar")
  - **Cuando:** se registra para un empleado una elección por beneficio con fecha de vigencia (p. ej. fondos de reserva `Acumulado` desde 2026-01-01 y `Mensualizado` desde 2026-07-01)
  - **Entonces:** el método de consulta para nómina devuelve la modalidad vigente para cada beneficio y fecha (`Acumulado` en marzo, `Mensualizado` en agosto, el valor por defecto de la empresa antes de la primera elección); dos elecciones del mismo beneficio y misma fecha se rechazan.
- **CA-7 · Datos adicionales configurables:**
  - **Dado que:** un responsable de RRHH (`hr.group_hr_manager`) define en Configuración un dato adicional (nombre, tipo: texto, entero, decimal, fecha, sí/no o lista de opciones, con sus opciones), y puede archivarlo
  - **Cuando:** un usuario de RRHH abre un empleado
  - **Entonces:** en la pestaña *Datos adicionales* registra un valor por cada dato activo según su tipo; no puede repetir el mismo dato en un empleado; un valor de tipo lista solo admite opciones de ese dato; archivar un dato lo oculta sin borrar los valores ya registrados. Un usuario de RRHH sin rol de responsable no puede crear ni modificar las definiciones.

**Contratos y jornadas (`erp_hr_ec`)**
- **CA-8 · Tipos de contrato parametrizables:**
  - **Dado que:** el módulo recién instalado
  - **Cuando:** se consultan los tipos de contrato (modelo estándar `hr.contract.type`)
  - **Entonces:** existen Indefinido, Eventual, Bajo factura, Pasantía y Tiempo parcial (país Ecuador), editables y ampliables, cada uno con el indicador *Relación laboral (IESS y beneficios de ley)* (valores iniciales "a validar"); una actualización del módulo no sobrescribe los cambios del usuario; un contrato en curso exige tipo de contrato.
- **CA-9 · Jornadas parametrizables con máximo legal:**
  - **Dado que:** el máximo de horas semanales de la empresa en Ajustes de Empleados (valor inicial 40, "a validar") y las jornadas estándar de Odoo (`resource.calendar`)
  - **Cuando:** se guarda un contrato con una jornada de 40 h semanales, una parcial de 20 h, o una de más horas que el máximo
  - **Entonces:** las dos primeras se aceptan (la parcial queda con su tasa de tiempo de trabajo para la nómina), la tercera se rechaza con un mensaje que indica las horas de la jornada y el máximo configurado.

**Calidad**
- **CA-10 · Instalación, permisos y calidad:**
  - **Dado que:** una BD nueva sin demo
  - **Cuando:** se ejecutan `bash scripts/test.sh erp_establishment,erp_hr_ec` y `bash scripts/check.sh --all`
  - **Entonces:** ambos salen con 0; cada modelo nuevo tiene ACL; hay tests de camino feliz, validaciones, importación de la plantilla y permisos (usuario sin grupo).

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Datos | DEV-3 | Módulos `erp_establishment` y `erp_hr_ec` (manifest, modelos y campos, `_sql_constraints`, ACL, grupos/reglas por empresa), `erp.establishment`; extensiones de `hr.employee`, `hr.contract.type`, `res.company`/`res.config.settings`; `erp.hr.dependent`, `erp.hr.benefit.election`, `erp.hr.extra.field`(+`.option`), `erp.hr.extra.value`; datos de tipos de contrato (`noupdate`); plantilla `static/` CSV; guía `docs/guias/carga-establecimientos.md`; tests de modelo y BD |
| Backend | DEV-2 | Normalización y validación de código, provincia EC en importación, cómputo de régimen, `get_import_templates`, validación de cédula (`stdnum.ec.ci`) y unicidad, discapacidad, establecimiento activo, `_get_benefit_mode(benefit, date)`, validación de valores adicionales, tipo de contrato obligatorio en curso, máximo de horas semanales; tests |
| Web | DEV-4 | Vistas lista/form/búsqueda de establecimientos (menú en Ajustes > Usuarios y empresas y en Empleados > Configuración), pestañas de empleado (Ecuador, cargas, beneficios, datos adicionales), configuración de datos adicionales, campo en tipos de contrato, ajustes de empleados (modalidades por defecto, máximo semanal), `i18n/es.po` si hace falta |

**Fuera de alcance:** cálculo de nómina, IESS, décimos, fondos de reserva, bonos, préstamos (US-008); uso de establecimientos en facturación SRI (US-003); carga de los 178 establecimientos reales (la hace el usuario con la plantilla); validación de cuentas bancarias contra el banco.

---

### 4. Contrato
| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Establecimiento | `erp.establishment` | lectura `base.group_user`; CRUD `base.group_system` | `code`, `name`, `street`, `city`, `state_id` (EC), `region` (`costa`/`sierra`/`amazonia`/`galapagos`), `active`, `company_id` | `decimo_cuarto_regime` (`costa_galapagos`/`sierra_amazonia`, almacenado) | código duplicado/inválido, provincia no EC → `ValidationError` |
| Importación | `get_import_templates()` en `erp.establishment` | CRUD | CSV de la plantilla | registros | errores por fila del importador |
| Empleado EC | `hr.employee` | `hr.group_hr_user` en campos sensibles | `erp_establishment_id`, `erp_disability`, `erp_disability_percentage`, `erp_disability_card`, `erp_disability_substitute`, `erp_dependent_ids`, `erp_benefit_election_ids`, `erp_extra_value_ids` | `erp_region`, `erp_decimo_cuarto_regime` (related almacenados) | cédula, discapacidad, establecimiento archivado → `ValidationError` |
| Modalidad de beneficio | `hr.employee._get_benefit_mode(benefit, date)` | servidor (US-008) | `benefit` ∈ `reserve_fund`/`thirteenth`/`fourteenth`, fecha | `monthly` / `accumulated` | beneficio desconocido → `ValueError` |
| Datos adicionales | `erp.hr.extra.field` (CRUD `hr.group_hr_manager`, lectura `hr.group_hr_user`); `erp.hr.extra.value` (CRUD `hr.group_hr_user`) | | tipo, opciones / valor tipado | | dato repetido, opción ajena → `ValidationError` |
| Tipo de contrato | `hr.contract.type` + `erp_labor_relationship` | estándar hr | | | |
| Contrato | `hr.contract` | estándar hr_contract | `contract_type_id`, `resource_calendar_id` | | sin tipo en curso, horas > máximo → `ValidationError` |
| Ajustes | `res.company` / `res.config.settings` | `base.group_system` | `erp_default_reserve_fund_mode`, `erp_default_thirteenth_mode`, `erp_default_fourteenth_mode`, `erp_max_weekly_hours` | | |

*(Nombres técnicos orientativos; DEV-3 fija los definitivos y el Tech Lead actualiza esta tabla.)*

---

### 5. Decisiones Técnicas y Supuestos
- **Establecimientos en módulo propio `erp_establishment`** (sin dependencia de `hr`), para reutilizarlo en facturación SRI (US-003). `erp_hr_ec` depende de él.
- **Región** como atributo del establecimiento (4 valores geográficos); el régimen de décimo cuarto (2 valores) se calcula. El empleado hereda ambos de su establecimiento (respuesta del usuario 2026-10-29).
- **Código SRI** normalizado a 3 dígitos con ceros a la izquierda (Excel elimina los ceros al guardar CSV); único por empresa incluyendo archivados.
- **Importación:** importador nativo de Odoo (CSV o XLSX) con plantilla descargable, sin asistente propio. Reimportar actualizando registros requiere la columna de ID externo que Odoo exporta; se explica en la guía.
- **Tipos de contrato:** se reutiliza el modelo estándar `hr.contract.type` (ya parametrizable) con datos `noupdate`. El indicador *Relación laboral* (Bajo factura y Pasantía = No; resto = Sí) es un valor inicial **a validar por el usuario**; US-008 lo usará para excluir del rol o de aportes.
- **Jornadas:** se reutiliza `resource.calendar` (catálogo nativo, tasa de tiempo de trabajo para jornadas parciales). El máximo semanal (40 h, Código del Trabajo; confirmado por el usuario como jornada actual) es un ajuste editable, **a validar**.
- **Modalidad de décimos y fondos de reserva:** historial de elecciones por empleado con fecha de vigencia + valor por defecto de la empresa. Valores por defecto iniciales **a validar**: fondos de reserva `Mensualizado`, décimo tercero y cuarto `Acumulado` (regla general de la legislación vigente según el equipo; no hay fuente entregada por el usuario).
- **Datos adicionales:** catálogo de definiciones + valores tipados por empleado (no se crean columnas dinámicas `x_`, que requieren Studio/Enterprise para la vista). Los datos con efecto legal o de nómina (discapacidad, cargas, banco, ciudad, cédula) son campos reales; banco/cuenta y ciudad son los estándar de Odoo. El catálogo se entrega vacío; la empresa define los suyos. Sin datos adicionales obligatorios en esta versión.
- **Permisos:** establecimientos los administra `base.group_system`; empleados y contratos con los grupos estándar de `hr`.
- **Archivar** un establecimiento con empleados se permite (no se reasignan solos); no se puede asignar uno archivado.
- **Cédula:** validada con `python-stdnum` (`stdnum.ec.ci`, ya incluido en Odoo) cuando la nacionalidad es Ecuador; única entre empleados activos de la empresa.
- Una sola empresa, pero los modelos llevan `company_id` y reglas multiempresa por convención.

### Respuestas del usuario (2026-10-29)
- Tipos de contrato parametrizables; iniciales: indefinido, eventual, bajo factura, pasantía, tiempo parcial.
- Jornada de 40 h, parametrizable según la normativa de Ecuador.
- Décimo cuarto según la región del establecimiento donde trabaja el empleado (agencia de la Costa → región Costa).
- Campos adicionales parametrizables (discapacidad, cuenta bancaria, banco, ciudad de origen/residencia, etc.).
- Los 178 establecimientos los carga el usuario más tarde con una plantilla (incluye activo/inactivo).

### Decisiones de la ronda de QA (2026-10-29)
- Importación: celda *Activo* vacía o `Si`/`si` sin tilde → activo (conversión acotada a `erp.establishment`; en una actualización, vacío reactiva). Región admite mayúsculas/minúsculas y nombres sin tilde. Provincia resuelta siempre a Ecuador sin tildes ni mayúsculas (override acotado de `ir.fields.converter.db_id_for`).
- Cédula: validada también sin nacionalidad cuando tiene 10 dígitos; única por empresa entre activos con índice único parcial en `init()` (se omite con aviso si hay duplicados) y comprobación previa con mensaje en español.
- Contrato en borrador marcado como listo (`kanban_state = done`) también exige tipo (el cron `update_state` no lo abriría sin avisar).
- Máximo semanal validado también en jornadas flexibles (`full_time_required_hours`) y al cambiar el empleado del contrato (jornada calculada).
- `check_company` del establecimiento aplicado en servidor (`hr.employee` no activa `_check_company_auto`).
- "Sustituto de persona con discapacidad" siempre visible (puede ser un empleado sin discapacidad).
- Menú de Empleados > Configuración > Establecimientos con acción propia de solo consulta; la administración del catálogo está en Ajustes.
- Contrato concreto: `hr.employee._get_benefit_mode(benefit, date) -> "monthly" | "accumulated"`; `resource.calendar._erp_get_weekly_hours()` y `_erp_get_work_time_rate()` (Odoo 18 Community no tiene `work_time_rate`); cambiar el tipo de un dato adicional con valores → `UserError`; establecimiento de otra empresa → `UserError` del núcleo.
- Ajuste en `erp_payroll_ec/tests/test_compute_sheet.py`: los contratos en curso del test llevan tipo de contrato (regla nueva de US-007).

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-29
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (10/10 CA; observaciones resueltas en ronda 1: Activo vacío, cédula sin nacionalidad, cron, multiempresa) · **QA-TECH:** 🟢 APROBADO CON OBSERVACIONES 9.3/10 (ronda 2; ronda 1 RECHAZADO 8.5 por P2: jornadas flexibles saltaban el máximo semanal)
- **Criterios de aceptación:** CA-1 ✅ CA-2 ✅ CA-3 ✅ CA-4 ✅ CA-5 ✅ CA-6 ✅ CA-7 ✅ CA-8 ✅ CA-9 ✅ CA-10 ✅
- **Archivos principales:** `addons/erp_establishment/` (modelo, conversor de importación acotado, plantilla `static/csv/plantilla_establecimientos.csv`, vistas, tests), `addons/erp_hr_ec/` (empleado, contrato, jornada, cargas, elecciones de beneficio, datos adicionales, tipos de contrato, ajustes, vistas, tests), `docs/guias/carga-establecimientos.md`, `addons/erp_payroll_ec/tests/test_compute_sheet.py`.
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (pre-commit completo; `0 failed, 0 error(s) of 180 tests` en erp_base, erp_branding, erp_establishment, erp_hr_ec y erp_payroll_ec, sin demo; pip-audit sin vulnerabilidades). Módulos instalados y actualizados en `erp_dev`.
- **Pendientes:**
  1. Validar con el usuario los valores "a validar": modalidades por defecto (fondos de reserva Mensualizado; décimos Acumulado), máximo 40 h, indicador *Relación laboral* de Bajo factura y Pasantía.
  2. Confirmar con el usuario la UX de *Datos adicionales* (líneas añadidas por el usuario vs. todos los datos listados de entrada).
  3. Prueba manual en navegador (sin Chrome en la imagen): importar la plantilla guardada desde Excel (CSV `;`/ANSI y XLSX), pestañas *Ecuador* y *Datos adicionales*, acción de solo consulta de RRHH.
  4. P3 QA-TECH: `uninstall_hook` que borre el índice de cédula; revalidar empresa al cambiar `company_id` de un establecimiento con empleados; unicidad de identificación sin distinguir mayúsculas (pasaportes); consulta duplicada en la restricción de cédula.
  5. Tipos de contrato estándar de Odoo siguen visibles junto a los de Ecuador (decisión del usuario si se ocultan).
  6. Antes de producción: revisar contratos en curso sin tipo cargados antes de instalar (`state = open` y `contract_type_id` vacío).
  7. WARNING de traducción en `erp_payroll_ec/models/hr_payslip.py:74` (US-006): `_()` sin idioma detectado.
