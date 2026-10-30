# Historia de Usuario: US-008 - Nómina Ecuador: rol de pagos, IESS, décimos, fondos de reserva

- **ID:** US-008
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-30
- **Sprint / Módulo:** Nómina · `addons/erp_payroll_ec`
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (parámetros, catálogo, seguridad, datos de estructura) / DEV-2 (reglas, cálculo, estados, contabilización) / DEV-4 (vistas, menús)
- **Depende de:** US-006 (motor OCA `payroll`), US-007 (`erp_hr_ec`), US-001 (plan `l10n_ec`)

---

### 1. Definición de la Historia
- **Como:** responsable de nómina de LAARCOURIER EXPRESS S.A.
- **Quiero:** calcular, confirmar y contabilizar el rol de pagos mensual con sueldo, aportes IESS, fondos de reserva, décimo tercero y cuarto (pagados o provisionados según la elección de cada empleado) y los bonos y descuentos propios que la empresa defina
- **Para:** pagar y provisionar correctamente según la ley, con parámetros legales editables por vigencia

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Parámetros normativos**
- **CA-1 · Parámetros con vigencia:**
  - **Dado que:** el modelo `erp.payroll.parameter` (código, nombre, tipo importe/porcentaje, valor, vigente desde, norma/fuente, estado `a validar`/`validado`)
  - **Cuando:** se instala el módulo y se consulta un parámetro para una fecha
  - **Entonces:** existen como datos `noupdate` los parámetros del cálculo (SBU, % aporte personal IESS, % aporte patronal IESS, % fondos de reserva, divisor del décimo tercero, días base del mes, meses de servicio para fondos de reserva), cada uno con su norma citada y estado **"a validar"**; la consulta devuelve el valor vigente más reciente con `vigente desde` ≤ fecha; si no hay valor vigente, el cálculo del rol se detiene con un `UserError` en español que nombra el parámetro y la fecha; solo el responsable de nómina los edita y los cambios quedan auditados.

**Cálculo del rol mensual**
- **CA-2 · Sueldo y jornada:**
  - **Dado que:** un empleado con contrato en curso todo el mes, sueldo 1.000,00 y jornada completa
  - **Cuando:** se calcula su rol mensual con la estructura "Rol mensual Ecuador"
  - **Entonces:** el sueldo es 1.000,00; con jornada parcial de 20 h el sueldo del contrato se toma tal cual (el contrato ya refleja la parcialidad) y la tasa de tiempo de US-007 se usa solo para el décimo cuarto; con ingreso o salida a mitad de mes el sueldo se prorratea por días con el parámetro de días base; todas las líneas se redondean a centavos USD por regla y el neto es igual a la suma de líneas redondeadas (incluido el caso 1.000,05 heredado de US-006).
- **CA-3 · IESS:**
  - **Dado que:** la base de aportación = sueldo + conceptos propios marcados "suma a base IESS"
  - **Cuando:** se calcula el rol
  - **Entonces:** el aporte personal se descuenta al empleado y el patronal se registra como costo de la empresa (no afecta el neto), ambos con los porcentajes vigentes; los contratos de tipo sin relación laboral (`erp_labor_relationship = False`, p. ej. Bajo factura, Pasantía) no generan aportes, fondos de reserva ni décimos (la estructura se puede asignar, pero esas reglas no aplican).
- **CA-4 · Fondos de reserva:**
  - **Dado que:** un empleado con más meses de servicio que el parámetro (desde `first_contract_date`)
  - **Cuando:** se calcula el rol de un mes
  - **Entonces:** si su modalidad vigente (`_get_benefit_mode('reserve_fund', fecha)`) es `monthly`, se paga en el rol (ingreso, porcentaje vigente sobre la base IESS); si es `accumulated`, no se paga en el rol y se registra como aporte de la empresa a depositar en el IESS (provisión/obligación); con menos servicio, no aplica.
- **CA-5 · Décimo tercero:**
  - **Dado que:** la base de remuneraciones del mes
  - **Cuando:** se calcula el rol
  - **Entonces:** el monto es la base / divisor; si la modalidad vigente es `monthly`, se paga en el rol; si es `accumulated`, se provisiona (no afecta el neto) para su pago anual.
- **CA-6 · Décimo cuarto:**
  - **Dado que:** el SBU vigente y el régimen de décimo cuarto del establecimiento del empleado (`erp_decimo_cuarto_regime`)
  - **Cuando:** se calcula el rol
  - **Entonces:** el monto mensual es SBU / 12 × tasa de tiempo de trabajo (jornada parcial) y prorrateado por días trabajados; `monthly` → se paga; `accumulated` → se provisiona; cada línea de provisión indica el régimen (para el pago en la fecha de su región en una historia posterior); un empleado sin establecimiento no puede calcular su rol (error en español).

**Conceptos propios**
- **CA-7 · Catálogo de bonos y descuentos (vacío al instalar):**
  - **Dado que:** el catálogo `erp.payroll.concept` (nombre, código, tipo ingreso/descuento, fijo/variable, "suma a base IESS", "suma a base de décimo tercero", activo, cuenta contable opcional)
  - **Cuando:** el responsable de nómina crea un concepto fijo, lo asigna a un empleado con importe y vigencia, y registra un concepto variable como entrada en un rol
  - **Entonces:** el rol incluye ambos con su importe; los ingresos marcados suman a las bases correspondientes; los descuentos reducen el neto; un descuento que deje el neto negativo da error en español; el catálogo se entrega **vacío**.

**Estados, permisos y contabilización**
- **CA-8 · Integridad del rol (heredado de US-006):**
  - **Dado que:** roles de pago existentes
  - **Cuando:** se intenta crear un segundo rol no anulado del mismo empleado, estructura y periodo, recalcular o editar líneas de un rol confirmado, confirmar dos veces, o el lote toma un contrato que no cubre el periodo
  - **Entonces:** se rechaza con mensaje en español (duplicado, rol confirmado no recalculable, sin doble asiento); el lote usa el contrato que cubre el periodo; las líneas del rol no son editables por el usuario de nómina (solo lectura; el cálculo las genera).
- **CA-9 · Permisos:**
  - **Dado que:** los grupos de nómina (usuario y responsable)
  - **Cuando:** cada uno opera
  - **Entonces:** el usuario de nómina calcula y revisa roles; solo el responsable confirma (y genera el asiento sin requerir además ser contador, mediante `sudo` acotado y justificado o grupo implicado), edita parámetros y el catálogo; un usuario sin grupo de nómina no ve roles ni parámetros.
- **CA-10 · Contabilización:**
  - **Dado que:** el plan `l10n_ec` y un diario de nómina
  - **Cuando:** se confirma un rol
  - **Entonces:** se genera un único asiento cuadrado: gasto de sueldos y beneficios, aporte patronal y provisiones contra sueldos por pagar, IESS por pagar y provisiones por pagar; las cuentas vienen precargadas desde el plan `l10n_ec` cuando existe una cuenta equivalente y son editables por regla y por concepto (mapeo "a validar" por el contador); cancelar un rol confirmado revierte el asiento sin borrarlo.

**Calidad**
- **CA-11:** `bash scripts/test.sh erp_payroll_ec` y `bash scripts/check.sh --all` salen con 0; tests por regla con valores **ficticios de test** (no se testean cifras legales como verdad: los tests crean sus propios parámetros), incluidos los casos borde: mes parcial, jornada parcial, sin relación laboral, cambio de modalidad a mitad de año, menos/más de un año para fondos de reserva, falta de parámetro, neto negativo, duplicado, permisos.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Datos | DEV-3 | `erp.payroll.parameter` (+ datos `noupdate` "a validar" con norma), `erp.payroll.concept` y `erp.payroll.employee.concept` (asignación fija con vigencia), categorías, estructura "Rol mensual Ecuador" y reglas como datos `noupdate` (códigos y cuentas por defecto si existen en `l10n_ec`), grupos/ACL/reglas de registro, restricción de rol duplicado, dependencias del manifest (`erp_hr_ec`) |
| Backend | DEV-2 | Funciones de cálculo usadas por las reglas (Python en el modelo, no código largo en datos), consulta de parámetros, prorrateo, bases, modalidad de beneficios, conceptos, validaciones de estado, permisos de confirmación, asiento único y reversión, lote con contrato del periodo, tests |
| Web | DEV-4 | Vistas y menús de parámetros, catálogo de conceptos, asignación por empleado (pestaña en el contrato o en el empleado), entradas variables en el rol, campos de régimen/modalidad visibles en el rol |

**Fuera de alcance (backlog):** préstamos y anticipos con cuotas (US-016), horas extra (US-011), quincena, vacaciones (US-012), pago anual de décimos acumulados y liquidación (US-013), utilidades (US-014), planillas IESS/MDT y rol individual PDF (US-015), impuesto a la renta en relación de dependencia (a evaluar con el usuario).

---

### 4. Contrato
| Operación | Modelo / Método | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Valor de parámetro | `erp.payroll.parameter._get_value(code, date, company)` | servidor | código, fecha | `float` | sin vigencia → `UserError` |
| Concepto propio | `erp.payroll.concept` | lectura usuario nómina; CRUD responsable | | | |
| Asignación fija | `erp.payroll.employee.concept` | responsable | empleado, concepto, importe, desde/hasta | | solapamiento → `ValidationError` |
| Rol | `hr.payslip` (OCA) estructura "Rol mensual Ecuador" | usuario calcula; responsable confirma | empleado, periodo | líneas por regla (Monetary USD) | duplicado, confirmado, sin establecimiento/parámetro, neto negativo → `UserError`/`ValidationError` |

**Definitivo (DEV-3/DEV-2, 2026-10-30):**
- `erp.payroll.parameter._get_value(code, date, company=None) -> float` (empresa > global; porcentajes como 9.45; `UserError` si no hay vigente). Tipos de valor: importe, porcentaje, número.
- Reglas `EC_MONTHLY`: BASIC, INC_OTHER, FR_PAID, D13_PAID, D14_PAID, GROSS, IESS_PERSONAL, DED_OTHER, NET, IESS_PATRONAL, FR_ACCRUED, D13_PROV, D14_PROV_COSTA, D14_PROV_SIERRA; condición `payslip._erp_rule_applies(code, contract)`, importe `payslip._erp_rule_amount(code, contract, categories, result_rules)`.
- Confirmar: solo `payroll.group_payroll_manager` (usuario → `AccessError`); asiento propio único con `sudo` acotado, sin línea de ajuste (descuadre → `UserError`); anular confirmado solo responsable y con `payroll.allow_cancel_payslips`, revierte y concilia el asiento.
- `UserError`: parámetro sin vigencia, neto negativo, sin establecimiento (si aplica décimo cuarto), entrada variable inválida, sin diario, rol duplicado, rol confirmado/anulado recalculado, doble confirmación.
- Lotes: contrato que cubre el periodo; empleados sin contrato o con rol existente se omiten e informan.
- **Ronda 1 de QA (DEV-2, 2026-10-30):**
  - Contratos del rol: el asignado más todos los del empleado `open`/`close` que se solapan con el periodo (rol manual y lote). Cada contrato se evalúa en una pasada propia del motor (lista negra y sumas por categoría por contrato); las líneas son por contrato (`<código>-<contrato>`: p. ej. dos BASIC/GROSS/NET) y el neto del rol es la suma de las líneas NET. Los conceptos fijos y las entradas sin contrato van al contrato de inicio más reciente (una sola vez por rol). Rol sin contrato asignado: diario del contrato más reciente.
  - Estructura `EC_MONTHLY`: el periodo debe estar dentro de un único mes natural (`UserError`).
  - Campos protegidos `state`, `move_id`, `credit_note`, `refunded_id`: solo los escriben las acciones (calcular, confirmar, anular, volver a borrador, reembolso); un rol `done` solo admite `note`, `paid` y las preferencias de visualización. Un rol nuevo nace en borrador sin asiento ni reembolsado. Fuera de las acciones → `UserError` (también al responsable). `env.su` no se restringe (procesos internos).
  - Reembolso (`refund_sheet`): solo responsable (`AccessError`). Confirmar en lote: un asiento por rol.
  - Anular un rol con apuntes conciliados (p. ej. pago del sueldo) → `UserError` pidiendo a contabilidad romper la conciliación.
  - Entradas (`hr.payslip.input`) de un rol confirmado: no se crean, modifican ni borran (`UserError`).
  - Duplicar un rol (fuera del reembolso): no copia las líneas calculadas (nace en borrador y se calcula); sí entradas y días trabajados; nunca `refunded_id`.
  - Errores de negocio (`UserError`/`ValidationError`/`AccessError`) lanzados dentro de las reglas llegan al usuario con su mensaje original, sin el envoltorio «Wrong python code…» de OCA.
  - Décimo cuarto: contrato sin jornada, o jornada sin horas de tiempo completo y empresa sin máximo semanal → `UserError`.
- **Ronda 2 de QA (DEV-2, 2026-10-30):**
  - Neto negativo: se valida sobre el rol completo (suma de las líneas NET de todas las pasadas de contrato, `_erp_check_lines_net`), no por contrato: una renovación el día 30/31 con un descuento fijo puede dar NET negativo en el contrato nuevo de 1 día sin bloquear el rol si el total es ≥ 0. Total negativo → `UserError` antes de escribir líneas.
  - Asiento: la analítica de cada apunte sale del contrato de la línea (`line.contract_id`), con la del contrato del rol como respaldo y la de la regla en último lugar.
  - Parámetros: cambiar `value`, `value_type`, `date_from`, `norm` o `company_id` de un parámetro «Validado» (fuera de las acciones de estado) lo devuelve a «A validar» con nota en el chatter. `env.su` está exento de la protección de `state` (si fija `state` en la misma escritura, se respeta).
  - El marcador de transición del rol vive en `cr.cache` (por cursor) y se retira aunque la acción falle.

---

### 5. Decisiones Técnicas y Supuestos
- **Decisión del usuario (2026-10-30):** arrancar con reglas de ley y catálogo de conceptos vacío; préstamos/anticipos, horas extra y quincena quedan fuera hasta tener política (US-016, US-011).
- Todos los valores legales se cargan como **valores por defecto "a validar"** con la norma citada (Código del Trabajo, Ley de Seguridad Social y resoluciones del IESS, acuerdo ministerial del SBU del año); el responsable/contador los marca "validado". Ningún porcentaje ni monto en código Python.
- Reglas de OCA en datos con código Python mínimo que llama a métodos del modelo (`payslip._erp_...`), para testear la lógica en Python y no en `safe_eval`.
- Provisiones (décimos acumulados, fondos de reserva acumulados, aporte patronal) no afectan el neto; su categoría las excluye del neto y van al asiento.
- Prorrateo por días con el parámetro "días base del mes" (convención laboral de 30 días, a validar).
- Base del décimo tercero: remuneraciones del mes (sueldo + conceptos marcados); fondos de reserva y décimos no forman base.
- Pago del décimo cuarto acumulado según región (Costa/Sierra) y del décimo tercero acumulado: historia posterior (US-013/US-015); aquí solo se provisiona con el régimen anotado.

- Decisiones de cálculo (DEV-2, a validar por usuario/contador): convención de 30 días (mes completo = 30; ingreso día 16 de un mes de 31 = 15 días); fondos de reserva proporcionales desde el día en que se cumplen los 12 meses; conceptos fijos sin prorrateo si la asignación está vigente algún día del periodo; contrato sin tipo = con relación laboral; cuenta por defecto de descuentos 21070402.

### Heredado de QA de US-006 (2026-10-29)
- Redondeo en cascada: con 1.000,05 el neto (900,05) no cuadra con la suma de líneas (900,04) y `payroll_account` añade un ajuste de 0,01 → convención de redondeo USD por regla y test con 1.000,05.
- Permisos: confirmar un rol exige además el grupo contable `account.group_account_invoice`; diseñar los grupos de nómina y su test.
- Lotes en renovación/terminación: el asistente OCA asigna `employee.contract_id` (contrato actual) sin mirar el periodo; preferir el contrato que cubre el periodo y decidir si un lote es "todo o nada" (178 establecimientos).
- Estados heredados de OCA: doble asiento al confirmar dos veces (PR #308), `compute_sheet` sobre un rol `done` lo devuelve a `verify` con asiento publicado, roles duplicados del mismo empleado y periodo.
- `group_payroll_user` tiene CRUD completo sobre `hr.payslip.line` (puede alterar importes).

### Respuestas del usuario (2026-10-29)
- **Prioridad:** la nómina va antes que la facturación electrónica.
- Fondos de reserva: mensualizados o acumulados **según lo que solicite cada empleado** (opción por empleado con vigencia) — implementado en US-007 (`_get_benefit_mode`).
- Décimo tercero y décimo cuarto: también mensualizados o acumulados **por empleado** (confirmado 2026-10-29).
- Región del décimo cuarto: la del establecimiento del empleado (US-007).
- Reglas propias: bonos, anticipos, descuentos y **préstamos a empleados descontados como anticipos** (cuotas en el rol) → US-016.
- Fuente normativa: legislación ecuatoriana vigente; valores legales vigentes como valores por defecto, parametrizables con vigencia.

### Preguntas abiertas para el usuario
- Catálogo de bonos y descuentos (lo llena la empresa en el sistema).
- Política de préstamos/anticipos, horas extra y quincena (US-016, US-011).
- ¿Se calcula la retención de impuesto a la renta en relación de dependencia en el rol?

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-30
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (ronda 2; 11/11 CA; ronda 1 BLOQUEADO por errores envueltos, escritura directa de estado y renovación a mitad de mes) · **QA-TECH:** 🟡 APROBADO CON OBSERVACIONES 8,5/10 (ronda 2; ronda 1 RECHAZADO 6/10 por P1 de varios contratos y escritura de estado, P2 de conciliación y N+1). Observaciones de ronda 2 (neto sobre el rol completo, revalidación de parámetros modificados, analítica por contrato, guardas) corregidas.
- **Criterios:** CA-1 ✅ … CA-11 ✅
- **Archivos principales:** `addons/erp_payroll_ec/` (parámetros con vigencia y validación, catálogo de conceptos, asignaciones, estructura `EC_MONTHLY` de 14 reglas, cálculo por contrato, guardas de estado, asiento propio único, lotes, vistas y terminología «Rol de pagos»), migraciones 18.0.1.1.0 y 18.0.1.1.1.
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (`0 failed, 0 error(s) of 411 tests`, una sola BD efímera; pip-audit sin vulnerabilidades). `erp_dev` actualizado sin ERROR; `/web/health` 200.
- **Pendientes:**
  1. Contador/usuario: validar los 8 parámetros «A validar» (SBU 482 y su acuerdo ministerial; IESS patronal 11,15 % vs 12,15 % con IECE/SECAP; fondos de reserva proporcionales desde el aniversario; convención de 30 días), el mapeo de cuentas l10n_ec (gasto en 5202 vs 5201/5102; descuentos 21070402; tercero de IESS por pagar) y decisiones: modalidad tomada a la fecha fin del periodo, conceptos fijos sin prorrateo, lote que se detiene ante errores de configuración.
  2. Cambiar el código de un concepto usado en roles abiertos rompe el cálculo de esas entradas (bloquear o propagar).
  3. Asignaciones archivadas no visibles en la pestaña del empleado (sí en el menú con filtro).
  4. Terminología: los textos es_EC escritos sobre menús/acciones de OCA no se restauran al desinstalar; ajustes de Nómina aún dicen «nómina» en algunos textos.
  5. Informes futuros (US-015) deben sumar todas las líneas NET (una por contrato).
  6. Préstamos/anticipos (US-016), horas extra (US-011), quincena, pago de décimos acumulados (US-013) e impuesto a la renta: fuera de alcance.
