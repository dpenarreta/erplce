# Historia de Usuario: US-012 - Vacaciones y permisos

- **ID:** US-012
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-30
- **Sprint / Módulo:** Talento Humano · `addons/erp_hr_holidays_ec` (nuevo) sobre `hr_holidays` (Ausencias, Odoo 18 Community)
- **Estado:** BLOQUEADA (2 hallazgos tras 2 rondas; ver Registro de Cierre)
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (modelo, tipos, parámetros, seguridad) / DEV-2 (saldos por antigüedad, validaciones, aprobación) / DEV-4 (vistas, menús, UX)
- **Depende de:** US-007 (`erp_hr_ec`), US-008 (`erp.payroll.parameter`), US-010 (Jefe inmediato), US-017 (estándar UX)

---

### 1. Definición de la Historia
- **Como:** empleado, jefe inmediato y responsable de Talento Humano de LAARCOURIER EXPRESS S.A.
- **Quiero:** que cada empleado tenga su saldo anual de vacaciones según su antigüedad, pueda solicitar vacaciones y permisos/licencias de ley, y que su jefe inmediato los apruebe
- **Para:** cumplir el Código del Trabajo y llevar el control de ausencias sin hojas de cálculo

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Parámetros y tipos**
- **CA-1 · Parámetros de vacaciones "a validar":** al instalar existen en `erp.payroll.parameter` (estado «A validar», norma citada, vigencia) los parámetros de días base anuales de vacaciones, año de servicio desde el que se suman días adicionales, días adicionales por año y tope de adicionales, y las duraciones de las licencias de ley; ningún número legal en código; si falta un parámetro vigente, la asignación da un error en español claro que nombra el parámetro.
- **CA-2 · Tipos de ausencia de Ecuador:** existen como datos `noupdate` (editables por el responsable, «a validar»): Vacaciones anuales (con saldo), Enfermedad, Maternidad, Paternidad, Calamidad doméstica, Lactancia (por horas), Permiso sin sueldo y Permiso con sueldo; cada uno indica si requiere saldo, si es pagado, su unidad (días/horas), su duración máxima por solicitud (parámetro, cuando la ley la fija) y si exige adjunto (p. ej. certificado médico). Los tipos de ejemplo de Odoo no estorban (archivados o claramente separados; decisión documentada).

**Saldos**
- **CA-3 · Asignación anual por antigüedad:** *Dado* un empleado con fecha de ingreso (`first_contract_date`), *cuando* cumple cada año de servicio, *entonces* recibe automáticamente (tarea programada idempotente y botón manual para el responsable) una asignación de vacaciones = días base + días adicionales según años cumplidos (desde el año parametrizado, con tope), con vigencia del periodo de servicio; no se duplica si se ejecuta dos veces; los empleados sin relación laboral (tipo de contrato con `erp_labor_relationship = False`) no reciben vacaciones; jornada parcial: días proporcionales a la tasa de jornada de US-007 (regla «a validar»), redondeo documentado.
- **CA-4 · Saldo visible:** el empleado y su jefe ven el saldo disponible, lo usado y lo pendiente de aprobar, por periodo, en la ficha y al solicitar.

**Solicitudes y aprobación**
- **CA-5 · Aprobación por el jefe inmediato:** el aprobador de ausencias del empleado es, por defecto, el usuario de su Jefe inmediato (`parent_id`); al cambiar el jefe se actualiza (salvo que RRHH lo haya fijado a mano); los tipos de vacaciones y permisos se aprueban por el jefe (y RRHH cuando el tipo lo exija, p. ej. maternidad o sin sueldo); el empleado solo ve y pide lo suyo; el jefe ve las de su equipo.
- **CA-6 · Validaciones:** no se puede pedir más vacaciones que el saldo (mensaje en español con saldo disponible), ni una licencia por encima de su duración máxima, ni solapar ausencias; una solicitud aprobada solo la anula RRHH o el jefe (con traza); los días de vacaciones se cuentan según la convención parametrizada (días calendario o laborables, «a validar») y queda documentado.

**Saldos históricos, acumulación y consumo (decisión del usuario 2026-10-30)**
- **CA-9 · Saldo desde la fecha de ingreso:** *Dado* que RRHH registra para todos los empleados su fecha de ingreso a la empresa, *cuando* se ejecuta el cálculo inicial (botón de RRHH, por empleado o en lote), *entonces* se generan los periodos de vacaciones de cada año de servicio desde el ingreso, con los días que correspondan a cada año (base + adicionales por antigüedad), excepto los periodos que ya habrían caducado por el **límite de acumulación** (parámetro «a validar» según el art. 75 del Código del Trabajo); cada periodo queda con su fecha de caducidad.
- **CA-10 · Límite de acumulación:** los días de un periodo no gozados dentro del plazo de acumulación caducan en su fecha (parámetro con vigencia y norma, «a validar»); el saldo disponible nunca incluye periodos caducados; queda visible qué días caducan y cuándo.
- **CA-11 · Consumo del más antiguo al más nuevo:** las vacaciones ya gozadas antes del sistema se registran por empleado (carga inicial: días gozados, total o con fechas) y, junto con las nuevas solicitudes, se descuentan **siempre del periodo más antiguo vigente al más nuevo** (FIFO); el detalle por periodo (asignado, gozado, disponible, caduca) es visible para RRHH, el jefe y el empleado.
- **CA-12 · Corte 2026 y tarea automática:** la tarea diaria se instala **inactiva** (RRHH la activa tras validar los parámetros); a partir de la fecha de corte explícita (parámetro propio, 2026-01-01, no ligado a la vigencia de otros parámetros) genera automáticamente cada nuevo aniversario; un error en un empleado no impide generar los demás (queda registrado).

**UX y calidad**
- **CA-7 · Interfaz para usuarios no técnicos:** menús en español («Mis ausencias», «Por aprobar», «Saldos»), estados vacíos útiles, mensajes claros, cumpliendo `docs/equipo/perfil.md` §5.1 (QA-UX sin Críticos ni Altos).
- **CA-8 · Calidad:** `bash scripts/test.sh erp_hr_holidays_ec` y `bash scripts/check.sh --all` salen con 0; tests con parámetros ficticios para: antigüedad < y > del año de días adicionales, tope, jornada parcial, sin relación laboral, idempotencia de la tarea, aprobación por jefe, saldo insuficiente, duración máxima, permisos por grupo.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables |
|---|---|---|
| Datos | DEV-3 | Módulo `erp_hr_holidays_ec` (depends `erp_hr_ec`, `erp_payroll_ec`, `hr_holidays`), campos de tipo de ausencia (pagado, duración máx. por código de parámetro, adjunto obligatorio, requiere RRHH), parámetros y tipos en datos `noupdate` con norma, ACL/reglas, tarea programada declarada |
| Backend | DEV-2 | Cálculo de días por antigüedad, generación idempotente de asignaciones, aprobador por jefe inmediato, validaciones de saldo/duración/solapamiento, tests |
| Web | DEV-4 | Vistas, menús, saldo visible, estados vacíos, i18n es_EC, cumplimiento UX |

**Fuera de alcance:** pago de vacaciones no gozadas y liquidación (US-013); impacto de licencias sin sueldo y subsidios del IESS en el rol (se registra en US-008 como pendiente para una historia posterior); marcaciones y horas (US-011); portal del empleado (decisión pendiente del usuario).

---

### 5. Decisiones Técnicas y Supuestos
- **Decisión del usuario (2026-10-30):** arrancar con los valores de ley como valores por defecto «a validar».
- Se reutiliza `hr_holidays` de Community (tipos, asignaciones, solicitudes, flujo de aprobación) y se extiende; no se crea un motor propio.
- Los valores legales (días base, adicionales, tope, duraciones de licencias, conteo calendario/laborable) son parámetros con vigencia en `erp.payroll.parameter` (US-008), citando la norma; el equipo no afirma cifras como vigentes: las confirma el contador/RRHH.
- La asignación se hace por aniversario del ingreso (periodo de servicio), no por año calendario.
- **Decisión del usuario (2026-10-30):** se mantiene el corte 2026 para la generación automática; RRHH ingresa la fecha de ingreso de todos los empleados y el sistema calcula sus periodos históricos desde esa fecha, limitados por el plazo de acumulación (art. 75, «a validar»); las vacaciones consumidas (históricas y nuevas) se descuentan del periodo más antiguo al más nuevo.
- Interpretación del Tech Lead a confirmar por el usuario: «corte 2026» = fecha desde la que la tarea automática genera aniversarios nuevos; los periodos anteriores los genera el cálculo inicial desde la fecha de ingreso (no carga manual de saldos), y las vacaciones gozadas antes del sistema se registran como consumo histórico.
- La aprobación usa el campo estándar de aprobador de ausencias del empleado, derivado del Jefe inmediato.

#### Decisiones de implementación (DEV-2, ronda 1, 2026-10-30)
- **Fecha de ingreso (CA-9):** campo propio `hr.employee.erp_company_entry_date` «Fecha de ingreso a la empresa» (editable por RRHH, con historial); si está vacío se usa `first_contract_date`. Motivo: los empleados antiguos pueden no tener todos sus contratos cargados y `first_contract_date` lo recalcula el núcleo desde los contratos (se reinicia tras un hueco ≥ 4 días).
- **Reingreso:** la fecha de ingreso forma parte de la clave de cada periodo (`erp_entry_date` en la asignación y en la restricción `erp_auto_service_year_uniq`): tras un reingreso los años de servicio vuelven a empezar en 1 y son periodos nuevos. Si RRHH corrige la fecha de ingreso y ya hay periodos nacidos desde la nueva fecha, el sistema exige rechazarlos y eliminarlos antes (mensaje en español); una fecha posterior a todos los periodos (reingreso) se admite. Los periodos del empleo anterior quedan como estaban (su liquidación es de US-013).
- **Límite de acumulación (CA-10):** parámetro `VACATION_VALIDITY_YEARS` = 4 («a validar»). Código del Trabajo, art. 75 (inciso único): «El trabajador podrá no hacer uso de las vacaciones hasta por tres años consecutivos, a fin de acumularlas en el cuarto año». Traducción a fechas: el periodo del año de servicio N nace en el aniversario A = ingreso + N años (`date_from`) y caduca el día anterior a A + 4 años (`date_to`, «Caduca el»); p. ej. ingreso 2020-03-15 → año 1 nace 2021-03-15 y caduca 2025-03-14. Admite fracciones (se pasan a meses); debe ser > 0. Si RRHH interpreta «máximo tres periodos», pone 3.
- **Cálculo inicial y corte (CA-9, CA-12):** el botón de RRHH genera todos los periodos desde la fecha de ingreso **excepto los ya caducados** a la fecha de cálculo, con los parámetros vigentes en cada aniversario. La tarea diaria se instala **inactiva** y solo genera aniversarios iguales o posteriores al «Vigente desde» más antiguo de `VACATION_GENERATION_START` (2026-01-01; su valor no se usa; no depende de `VACATION_BASE_DAYS`). Cada empleado se procesa en su propio *savepoint* (un error se registra y se sigue; en el botón con varios empleados se listan en la notificación); candado `pg_advisory_xact_lock` contra la ejecución simultánea de tarea, botón y carga histórica; doble validación (`both`) llevada hasta «Aprobada».
- **Consumo FIFO (CA-11):** lo hace el núcleo: `hr.employee._get_consumed_leaves` (Odoo 18) ordena las asignaciones con fecha de fin por `date_to` ascendente y descuenta cada ausencia de la primera vigente en sus fechas; como todo periodo tiene fecha de caducidad creciente, el orden es del más antiguo al más nuevo (test que lo demuestra). Limitación conocida: si una solicitud cruza la caducidad de un periodo o el nacimiento del siguiente, el núcleo reparte la parte cortada en días laborables (no calendario); el mensaje de saldo lo explica y pide dividir la solicitud.
- **Vacaciones gozadas antes del sistema (CA-11):** modelo `erp.hr.vacation.history` (empleado o identificación, fecha, días gozados, año de servicio opcional, observación), solo encargados de ausencias, importable con la plantilla `static/csv/plantilla_vacaciones_gozadas.csv` (Importar > Plantilla). Cada cambio reparte todas las líneas del empleado en FIFO entre sus periodos vigentes en la fecha de la línea (o el año indicado): lo descontado se guarda en `erp_history_days` y se resta de `number_of_days` (el saldo que usa el núcleo); `erp_entitled_days` conserva los días del periodo. Se eligió frente a crear ausencias (`hr.leave`) históricas porque no exige fechas exactas (basta el total), no choca con solapamientos ni calendario laboral y no ensucia calendario ni nómina pasada. Se redefine la restricción nativa `duration_check` para permitir un periodo en 0 solo si lo consumió la carga histórica. Requiere calcular antes los periodos; si la carga supera los días o deja sin saldo ausencias ya aprobadas, error en español.
- **Redondeo:** días proporcionales a la jornada parcial redondeados al medio día más cercano; «Vacaciones anuales» se pide en medios días (`half_day`).
- **Adjunto obligatorio:** se exige al aprobar (primera aprobación en doble validación y validación final), una sola búsqueda por paso; un tipo sin aprobación (`no_validation`) no puede exigir adjunto (restricción del tipo).
- **Rechazadas no se regeneran:** un periodo rechazado no se vuelve a crear solo; RRHH lo elimina y recalcula (la carga histórica se reparte otra vez).
- **Primera aprobación:** el empleado (o el jefe sin grupo de ausencias) no puede eliminar una solicitud en «Segunda aprobación»; la anulan el jefe o RRHH con el asistente.
- **Pendiente:** `LEAVE_NURSING_MONTHS` (12 meses de lactancia) está cargado pero ninguna validación lo usa (requiere registrar la fecha de parto); queda para una historia posterior.

#### Fuentes por cifra (parámetros «a validar», Código del Trabajo, texto Lexis publicado por el CES en LOTAIP 2020)
| Código | Valor de partida | Vigente desde | Fuente |
|---|---|---|---|
| `VACATION_BASE_DAYS` | 15 | 2005-12-16 (Codificación 17, R.O. Supl. 167) | art. 69, inciso 1 |
| `VACATION_EXTRA_FROM_YEAR` | 6 | 2005-12-16 | art. 69 («más de cinco años») |
| `VACATION_EXTRA_DAYS_PER_YEAR` | 1 | 2005-12-16 | art. 69 |
| `VACATION_EXTRA_MAX_DAYS` | 15 | 2005-12-16 | art. 69, último inciso |
| `VACATION_VALIDITY_YEARS` | 4 | 2005-12-16 | art. 75 (3 años de acumulación + el cuarto) |
| `VACATION_GENERATION_START` | — (fecha) | 2026-01-01 | decisión del usuario 2026-10-30 (no es norma) |
| `VACATION_COUNT_CALENDAR_DAYS` | 1 | 2005-12-16 | art. 69 («incluidos los días no laborables») |
| `LEAVE_COUNT_CALENDAR_DAYS` | 1 | 2005-12-16 | arts. 152 y 42 num. 30 (interpretación) |
| `LEAVE_MATERNITY_MAX_DAYS` | 94 | 2009-02-13 (R.O. Supl. 528) | art. 152, inciso 1 (84 + 10 por nacimiento múltiple) |
| `LEAVE_PATERNITY_MAX_DAYS` | 25 | 2009-02-13 (R.O. Supl. 528) | art. 152, incisos 2 y 3 |
| `LEAVE_CALAMITY_MAX_DAYS` | 3 | 2005-12-16 | art. 42, num. 30 (fecha de inclusión a confirmar) |
| `LEAVE_NURSING_HOURS_PER_DAY` | 2 | 2012-09-26 (R.O. Supl. 797) | art. 155, inciso 3 + art. 47 |
| `LEAVE_NURSING_MONTHS` | 12 | 2012-09-26 (R.O. Supl. 797) | art. 155, inciso 3 |

Las fechas «Vigente desde» anteriores a 2026 permiten calcular periodos y registrar ausencias históricas (carga inicial); son la fecha de la norma que introdujo el texto citado y están a confirmar por la asesoría laboral.

---

### 6. Registro de Cierre (parcial, 2026-10-30)

- **Estado:** BLOQUEADA — se alcanzó el máximo de 2 rondas de QA con 2 hallazgos bloqueantes abiertos (correcciones pequeñas, con propuesta de código de los auditores). El código se respalda en `main` a pedido del usuario antes de su feriado; **retomar aquí**.
- **QA-FUNC (ronda 2):** 🔴 BLOQUEADO por B8; 10/12 CA (CA-7 depende de QA-UX, aprobado en ronda 2). Ronda 1 (B1 reingreso, B2 tests) corregida.
- **QA-TECH (ronda 2):** 🔴 RECHAZADO 8/10 por un P2 nuevo; los 3 P2 de la ronda 1 (cron activo, corte acoplado, sin aislamiento de errores) resueltos.
- **QA-UX (ronda 2):** 🟡 sin Críticos ni Altos (los 2 Altos de ronda 1 corregidos); quedan Medios/Bajos.
- **Verificación del Tech Lead:** `bash scripts/check.sh --all` → `0 failed, 0 error(s) of 520 tests`, pip-audit limpio (dos hooks marcaron archivos modificados por ediciones de documentación simultáneas); `bash scripts/check.sh` repetido con el árbol estable → OK.
- **Bloqueantes abiertos (siguiente sesión, primero):**
  1. **QA-TECH P2 – periodos duplicados al cambiar `first_contract_date`:** si `erp_company_entry_date` está vacío y RRHH carga/corrige un contrato anterior tras el cálculo, se generan periodos solapados (saldo duplicado). Corrección propuesta: en `_erp_generate_employee_vacations`, si existen periodos no rechazados con otra `erp_entry_date` que nacen en o después de la nueva fecha → `UserError` (en el cron, registrar y seguir). Test incluido en la propuesta (`hr_employee.py:416`, `:500-550`).
  2. **QA-FUNC B8 – FIFO al cruzar una caducidad:** cuando una solicitud de vacaciones en días calendario cruza la caducidad de un periodo con saldo y el siguiente periodo cubre la diferencia, el núcleo reparte el tramo en días laborables y el empleado pierde días sin aviso. Corrección mínima: rechazar solicitudes de vacaciones que crucen la fecha de caducidad de un periodo con saldo («Divida la solicitud: el periodo del año N caduca el …»), con test (año 4 caduca 2026-11-09, solicitud 05–14/11).
- **Pendientes no bloqueantes:**
  - QA-FUNC: O1 saldo del empleo anterior tras reingreso (decisión del usuario, liga con US-013); O2 el nombre del periodo se pierde tras la carga histórica («Vacaciones anuales (0.0 día(s))»); O3 reimportar la plantilla duplica la carga histórica sin aviso.
  - QA-TECH P3: rendimiento de la carga histórica (`_get_consumed_leaves` 2× por empleado); periodo rechazado no reparte el histórico al instante; `duration_check` redefinida y registro del núcleo reapuntado (`hr_leave_allocation_action_my_view_form`) no se restauran al desinstalar; falta test de anclajes de los patches OWL; corte de empresa vs global en `start_date`; orden FIFO si `VACATION_VALIDITY_YEARS` baja; textos OWL no traducibles.
  - QA-UX Medios/Bajos: plural «1 días» y «Solicitud de asignación»/«(1.0 día(s))» en textos del servidor; «Calcular vacaciones» desde la lista sin confirmación; mensajes de error con «asignación»; columna «Aprobación de asignación»; «Año de servicio» = 0 sin explicación; áreas táctiles < 44 px; tablero vacío sin mensaje; formato numérico de stat buttons; ubicación del menú de carga histórica; ayuda del botón de saldo sin saldo; 375 px no verificado.
  - Validar con RRHH/asesoría laboral los parámetros «a validar» (incl. `VACATION_VALIDITY_YEARS`=4 y fechas de vigencia 2005/2009/2012).
- **erp_dev:** módulo reinstalado; tarea programada **inactiva**; 0 saldos y 0 ausencias. No pulsar «Calcular vacaciones» hasta corregir el bloqueante 1.
