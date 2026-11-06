# Historia de Usuario: US-013 - Liquidación de haberes y finiquito; pago de décimos acumulados

- **ID:** US-013
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-30 (detallada el 2026-11-06)
- **Sprint / Módulo:** `erp_payroll_ec` (pago de décimos acumulados) y nuevo `erp_hr_settlement_ec` (liquidación)
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 / DEV-2 / DEV-4
- **Depende de:** US-008 (rol de pagos), US-007 (datos Ecuador del empleado), US-012 (vacaciones)

---

### 1. Definición de la Historia
- **Como:** responsable de Talento Humano y nómina
- **Quiero:** (A) pagar en su fecha los décimos tercero y cuarto acumulados de quienes no los cobran mensualmente, y (B) calcular la liquidación de haberes cuando termina la relación laboral, con su PDF de respaldo
- **Para:** cumplir la normativa laboral ecuatoriana sin cálculos manuales, sin pagar dos veces lo mismo y con el asiento contable correcto

**Decisiones del usuario (2026-11-06):**
1. Causas de salida: **todas las legales** (renuncia, despido intempestivo, visto bueno solicitado por el empleador, visto bueno solicitado por el trabajador, fin de contrato o de plazo, mutuo acuerdo, desahucio, fallecimiento, jubilación), cada una con sus rubros configurables.
2. Reingreso (pendiente O1 de US-012): **las vacaciones no gozadas se pagan al salir**; si la persona vuelve, empieza de cero con su nueva fecha de ingreso.
3. Documento: **liquidación en PDF** con el detalle de cada valor, para firma y respaldo; el acta oficial la registra RRHH en el SUT del Ministerio del Trabajo con esos valores.
4. **El pago anual de décimos acumulados entra en esta historia.**

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Parte A · Pago de décimos acumulados**

- **CA-1 · Generar el pago de décimo tercero acumulado:**
  - **Dado que:** hay empleados con modalidad «acumulado» de décimo tercero y roles mensuales confirmados con su provisión (`D13_PROV`) dentro del periodo de cálculo
  - **Cuando:** el responsable genera el «Pago de décimo tercero» de un año
  - **Entonces:** se crea un lote con un rol por empleado cuyo importe es la suma de sus provisiones del periodo aún no pagadas; quien no tenga provisiones pendientes no aparece, y se muestra un resumen (cuántos roles, cuántos omitidos y por qué).
- **CA-2 · Décimo cuarto por régimen:**
  - **Dado que:** el periodo de cálculo y la fecha de pago del décimo cuarto dependen del régimen (Costa/Galápagos o Sierra/Amazonía) del establecimiento
  - **Cuando:** se genera el «Pago de décimo cuarto» indicando el régimen y el año
  - **Entonces:** solo se incluyen empleados de ese régimen y solo sus provisiones `D14_PROV_*` del periodo de ese régimen. Los meses de inicio y fin de cada periodo son parámetros con vigencia, «a validar».
- **CA-3 · Sin pago doble:**
  - **Dado que:** una provisión ya se pagó (en un pago de décimos o en una liquidación confirmados)
  - **Cuando:** se vuelve a generar el pago del mismo periodo o se calcula una liquidación
  - **Entonces:** esa provisión no se vuelve a sumar; si no queda nada pendiente para nadie, el sistema lo dice en español y no crea un lote vacío. Si se anula el pago, las provisiones vuelven a quedar pendientes.
- **CA-4 · Contabilidad del pago de décimos:**
  - **Dado que:** se confirma un rol de pago de décimos
  - **Cuando:** se genera el asiento
  - **Entonces:** el asiento debita la cuenta de provisión del décimo (la misma que acreditó la provisión mensual) y acredita la cuenta por pagar al empleado; no se registra un gasto nuevo. Anular el rol revierte el asiento con las mismas reglas que el rol mensual.

**Parte B · Liquidación de haberes**

- **CA-5 · Crear la liquidación:**
  - **Dado que:** un empleado con contrato en curso o recién cerrado
  - **Cuando:** RRHH crea una liquidación eligiendo empleado, contrato, fecha de salida y causa
  - **Entonces:** queda en borrador; la fecha de salida no puede ser anterior al inicio del contrato ni posterior a su fin (si tiene); no puede haber dos liquidaciones no anuladas del mismo contrato (mensaje en español).
- **CA-6 · Calcular según la causa:**
  - **Dado que:** la liquidación en borrador
  - **Cuando:** se pulsa «Calcular»
  - **Entonces:** se generan las líneas que correspondan a la causa, cada una con base, cantidad, importe y una explicación legible de cómo se obtuvo:
    1. Décimo tercero pendiente: provisiones no pagadas hasta la fecha de salida (solo modalidad acumulada; la proporción del último mes se calcula si no hay rol de ese mes).
    2. Décimo cuarto pendiente: ídem por régimen.
    3. Vacaciones no gozadas: saldo en días de los periodos de vacaciones vigentes (US-012) × valor del día.
    4. Vacaciones proporcionales del año de servicio en curso.
    5. Bonificación por desahucio (si la causa la contempla).
    6. Indemnización por despido intempestivo (si la causa la contempla), por tramos de años de servicio.
    7. Otras causas con rubros propios (p. ej. visto bueno solicitado por el trabajador) según la configuración de la causa.
    Todas las fórmulas toman parámetros con vigencia a la fecha de salida, marcados «a validar»; ningún valor normativo fijo en código.
- **CA-7 · Rubros manuales:**
  - **Dado que:** existen otros valores (p. ej. anticipos, préstamos pendientes hasta US-016, bonos acordados)
  - **Cuando:** RRHH añade líneas manuales de ingreso o descuento con descripción
  - **Entonces:** se suman o restan al total y se conservan al recalcular; el neto negativo se bloquea con mensaje claro.
- **CA-8 · Último rol del mes:**
  - **Dado que:** el sueldo de los días trabajados del último mes se paga en el rol mensual (no en la liquidación)
  - **Cuando:** se confirma la liquidación y no existe un rol confirmado que cubra hasta la fecha de salida
  - **Entonces:** el sistema lo bloquea indicando el periodo que falta pagar.
- **CA-9 · Confirmar:**
  - **Dado que:** la liquidación calculada
  - **Cuando:** el responsable de nómina (grupo gestor) la confirma
  - **Entonces:** (a) se genera el asiento contable (provisiones de décimos contra su pasivo; vacaciones, desahucio e indemnización contra gasto; neto a la cuenta por pagar del empleado); (b) el contrato queda cerrado con esa fecha de fin y el empleado queda archivado con la causa y fecha de salida; (c) los periodos de vacaciones liquidados quedan sin saldo y marcados como liquidados, de modo que un reingreso empieza de cero (decisión 2); (d) las provisiones pagadas quedan marcadas para no volver a pagarse (CA-3). Un usuario sin el grupo gestor no puede confirmar.
- **CA-10 · Anular:**
  - **Dado que:** una liquidación confirmada cuyo asiento no está conciliado
  - **Cuando:** el gestor la anula
  - **Entonces:** se revierte el asiento, las provisiones y los saldos de vacaciones vuelven a estar pendientes; el contrato y el empleado no se reabren solos (se indica en el mensaje que RRHH debe reabrirlos si procede). Con asiento conciliado se bloquea con mensaje claro.
- **CA-11 · PDF de liquidación:**
  - **Dado que:** una liquidación calculada o confirmada
  - **Cuando:** se imprime
  - **Entonces:** el PDF con la marca ERP LCE muestra empresa (razón social y RUC), empleado (nombre, cédula, cargo), fechas de ingreso y salida, tiempo de servicio, causa, última remuneración, cada rubro con su explicación, total de ingresos, descuentos y neto, y espacios de firma del empleador y del trabajador. Un borrador lleva la marca «BORRADOR».
- **CA-12 · Parámetros y causas configurables:**
  - **Dado que:** los valores legales pueden cambiar
  - **Cuando:** el gestor revisa Nómina › Configuración
  - **Entonces:** encuentra las causas de salida con los rubros que aplican a cada una, y los parámetros nuevos (desahucio, tramos de indemnización, valor del día de vacaciones, periodos de décimos) con vigencia y la marca «a validar» visible, igual que los parámetros de US-008.
- **CA-13 · Interfaz en español y usable:**
  - **Dado que:** usuarios poco técnicos
  - **Cuando:** usan Nómina › Liquidaciones y Nómina › Pago de décimos
  - **Entonces:** textos en español («rol de pagos», nunca «nómina» en etiquetas cuando el término propio es «rol»), estados visibles con barra de estado, ayudas en los campos clave, lista y formulario coherentes con el tema ERP LCE y sin hallazgos Críticos/Altos de QA-UX.

- **CA-14 · Ingresos que no son remuneración:**
  - **Dado que:** un empleado cobra viáticos o reembolsos de gastos mediante conceptos de ingreso con «Cuenta como remuneración» desmarcado
  - **Cuando:** se calcula su liquidación
  - **Entonces:** esos importes no entran en la última remuneración, el valor del día de vacaciones ni las vacaciones proporcionales; sueldo, alimentación, comisiones y demás conceptos marcados sí entran. La explicación del rubro lo indica.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Datos | DEV-3 | Parámetros nuevos (datos XML, «a validar») en `erp.payroll.parameter`; trazabilidad de provisiones pagadas (líneas de provisión ↔ pago); estructura «Pago de décimos acumulados» con sus reglas; módulo `erp_hr_settlement_ec`: modelos de liquidación, líneas, causa de salida (catálogo con datos de las causas legales y sus rubros), tramos de indemnización con vigencia; marca «liquidado» en periodos de vacaciones; seguridad (ACL y reglas multiempresa) con los grupos de `erp_payroll_ec`; restricciones SQL; migración si cambia `erp_payroll_ec`. |
| Lógica | DEV-2 | Asistente de pago de décimos (CA-1..4); cálculo de liquidación (CA-6..8), confirmar/anular (CA-9..10) con asiento contable y cierre de contrato/empleado; consumo y restitución de saldo de vacaciones; validaciones y mensajes en español; tests `TransactionCase`. |
| Web | DEV-4 | Vistas (lista, formulario con barra de estado, búsqueda), menús Nómina › Liquidaciones / Pago de décimos / Configuración › Causas de salida y tramos, asistente de pago de décimos, informe QWeb PDF de liquidación con marca, traducciones `es`. |

**Fuera de alcance:** registro automático en el SUT o envío al IESS (US-015); préstamos y anticipos automáticos (US-016; por ahora líneas manuales); jubilación patronal (cálculo actuarial: línea manual); utilidades (US-014); fondos de reserva acumulados (los administra el IESS: no se liquidan por la empresa); impuesto a la renta sobre la liquidación (si aplica, línea manual hasta que exista el módulo de impuesto a la renta).

---

### 4. Contrato
| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Generar pago de décimos | asistente `erp.payroll.benefit.payment.wizard` (nombre final según DEV-3) | gestor nómina | beneficio (D13 / D14), año, régimen (D14), fecha de pago | lote `hr.payslip.run` con roles de estructura «Pago de décimos acumulados» + resumen | sin pendientes; parámetros faltantes |
| Saldo de provisiones pendientes | método en `hr.employee` / servicio de `erp_payroll_ec` | interno | empleado, beneficio, fecha hasta | importe y líneas de provisión pendientes | — |
| Liquidación | `erp.hr.settlement` (estados `draft` → `computed` → `done` / `cancel`) | usuario nómina (crear/calcular), gestor (confirmar/anular) | empleado, contrato, fecha de salida, causa | líneas `erp.hr.settlement.line` (código de rubro, base, cantidad, importe, explicación, manual sí/no) | duplicado por contrato, fechas, neto negativo, último rol faltante, asiento conciliado |
| Causa de salida | `erp.hr.termination.cause` | gestor | nombre, código, rubros que aplican | — | — |
| Saldo de vacaciones a liquidar | método de `erp_hr_holidays_ec` sobre `hr.employee` | interno | empleado, fecha de salida | días por periodo + días proporcionales | — |
| PDF | informe QWeb `erp_hr_settlement_ec.report_settlement` | usuario nómina | liquidación | PDF | — |

---

### 5. Decisiones Técnicas y Supuestos
- **Módulos:** el pago de décimos acumulados vive en `erp_payroll_ec` (es rol de pagos y no necesita vacaciones). La liquidación vive en un módulo nuevo `erp_hr_settlement_ec` que depende de `erp_payroll_ec` y `erp_hr_holidays_ec`, para no acoplar el rol de pagos con ausencias.
- **El sueldo del último mes se paga en el rol mensual**, que ya prorratea por fecha de fin de contrato (US-008); la liquidación solo exige que ese rol esté confirmado (CA-8). Evita duplicar el motor del rol.
- **Provisiones como fuente de los décimos pendientes:** lo pendiente = provisiones de roles confirmados no marcadas como pagadas. La marca se guarda en la base (no se recalcula) para garantizar CA-3 aun si cambian los parámetros.
- **Parámetros normativos nuevos, todos «a validar»** por el contador o asesor laboral: periodo de cálculo y mes de pago de cada décimo por régimen; porcentaje de la bonificación por desahucio por año de servicio; tramos de indemnización por despido intempestivo (años de servicio → meses de remuneración, con mínimo); base y divisor del valor del día de vacaciones; rubros por causa. Los valores iniciales se cargan como referencia marcados «a validar»; no se toman como verdad legal.
- **Reingreso (O1 de US-012):** las vacaciones no gozadas se pagan en la liquidación y los periodos quedan liquidados; el reingreso empieza de cero (comportamiento de reingreso ya implementado en US-012).
- **Contrato y empleado al confirmar:** se reutilizan los campos del núcleo (`hr.contract.date_end`/`state`, `hr.employee.departure_reason_id`/`departure_date`/`active`); las causas de salida se asocian a un `hr.departure.reason` del núcleo cuando exista equivalencia.
- **Contabilidad:** mismas convenciones que el rol mensual (diario del contrato/estructura, socio del empleado, reversión al anular, bloqueo si está conciliado).
- **Remuneración (decisión del usuario 2026-11-06):** incluye el sueldo y todos los beneficios o bonos que recibe el empleado, como alimentación o comisiones. Implementación: líneas `BASIC` + `INC_OTHER` del rol mensual (todos los conceptos propios de tipo ingreso), sin décimos ni fondos de reserva. Las horas extra de US-011 deberán sumarse a esta base cuando existan.
- **Viáticos y reembolsos (decisión del usuario 2026-11-06):** la empresa los paga y **no** cuentan como remuneración. Cada concepto de ingreso tendrá la casilla «Cuenta como remuneración» (por defecto marcada); RRHH la desmarca en viáticos y reembolsos. La base de remuneración suma `BASIC` + solo los conceptos de ingreso marcados (CA-14). Se implementa en la ronda de correcciones.
- **erp_dev tiene datos reales:** no se crean liquidaciones ni pagos de décimos ahí; las pruebas van en la base de tests.

### Preguntas abiertas para el usuario
- Ninguna bloqueante. Valores legales a validar con el contador antes del uso real.

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-11-06
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (13/13 CA; O-1, O-5 y O-6 corregidos en ronda 1) · **QA-TECH:** ronda inicial 🔴 (P2 ACL de marcas de provisión pagada) → ronda 1 🔴 (P2 N+1 en remuneración CA-14) → ronda 2 🟡 APROBADO CON OBSERVACIONES · **QA-UX:** inicial 2 Altos (año «2.026», lista de tramos) → resueltos y verificados en vivo; sin Críticos ni Altos propios de la historia.
- **Criterios de aceptación:** CA-1 ✅ CA-2 ✅ CA-3 ✅ CA-4 ✅ CA-5 ✅ CA-6 ✅ (CA-6.1: la proporción del último mes la cubre el rol mensual exigido por CA-8) CA-7 ✅ CA-8 ✅ CA-9 ✅ CA-10 ✅ CA-11 ✅ CA-12 ✅ CA-13 ✅ (móvil verificado a 502 px, no a 375 px) CA-14 ✅
- **Decisiones durante la ejecución:**
  - Un rol de «Pago de décimos acumulados» paga un solo décimo (`hr.payslip.erp_benefit_pay_code`), fijado por el asistente; el régimen del D14 se toma del código de cada provisión (quien cambió de régimen aparece en ambos pagos con lo suyo).
  - Periodo de décimos: parámetros vigentes al 1 de enero del año de pago; «año» = año de pago (D13 2026 = 01/12/2025–30/11/2026).
  - Número LIQ/AAAA/NNNN asignado al confirmar. Marcas de provisión pagada solo creadas/borradas por las acciones (ACL de solo lectura + guarda `env.su`).
  - Última remuneración: último rol mensual completo confirmado (BASIC + conceptos de ingreso «Cuenta como remuneración»); si no hay, sueldo del contrato. Valor del día de vacaciones: año móvil anterior a la salida con prorrateo de 30 días (criterio a validar).
  - Desinstalar `erp_hr_settlement_ec` se bloquea si hay liquidaciones confirmadas; el `uninstall_hook` restaura `hr_leave_allocation_duration_check` (corregida con COALESCE en `erp_hr_holidays_ec` 18.0.1.0.2).
  - O1 de US-012 resuelto: las vacaciones no gozadas se pagan en la liquidación, los periodos quedan liquidados y el reingreso empieza de cero (test integrado).
- **Archivos principales:** `addons/erp_payroll_ec` (18.0.1.2.1: `models/const.py`, `models/erp_payroll_provision_payment.py`, `models/hr_payslip.py`, `models/erp_payroll_concept.py`, `wizard/erp_payroll_benefit_payment_wizard.py`, `data/hr_payroll_structure_benefit_pay_data.xml`, parámetros, migraciones 18.0.1.2.0 y 18.0.1.2.1, vistas del asistente y conceptos); `addons/erp_hr_settlement_ec` (nuevo, 18.0.1.0.1: modelos, datos de 9 causas, 2 tramos y 6 parámetros «a validar», seguridad, vistas, informe PDF, widget «Sin tope», `hooks.py`, migración 18.0.1.0.1); `addons/erp_hr_holidays_ec` (18.0.1.0.2: `duration_check`).
- **Verificación ejecutada:** `bash scripts/check.sh --all` → pip-audit «No known vulnerabilities found», `check.sh: OK`, «0 failed, 0 error(s) of 692 tests». erp_dev actualizado (erp_payroll_ec 18.0.1.2.1, erp_hr_holidays_ec 18.0.1.0.2, erp_hr_settlement_ec 18.0.1.0.1 instalado; solo catálogo, 0 liquidaciones/pagos).
- **Pendientes:**
  1. [Contador / asesor laboral] Validar todo lo «a validar»: parámetros de periodo y pago de décimos por régimen, desahucio (25 % y proporcional), tramos de indemnización y fracción de año, divisores 360 y 24, rubros por causa (p. ej. renuncia, visto bueno del trabajador), qué cuenta como remuneración, valor del día con año móvil, cuentas contables por defecto (incluida la de descuentos manuales: conviene cuenta por cobrar al empleado).
  2. [QA-FUNC O-2] Marcar provisiones de décimos «pagadas externamente» antes de cargar roles históricos (si no, se pagarían de nuevo).
  3. [QA-FUNC O-9] Al confirmar, el pago de décimos se recalcula si no está activo `prevent_compute_on_confirm`.
  4. [QA-TECH P3] `_check_no_overlap` de tramos hace un `search` por registro (catálogo pequeño); confirmar la regla de versión de tramos propios frente a comunes más recientes.
  5. [Datos] El desglose por concepto de un rol confirmado se reconstruye al calcular la liquidación (no se guarda): si se edita una asignación fija tras confirmar el rol, la exclusión de no remunerativos puede diferir.
  6. [QA-UX → US-019] Foco de teclado casi invisible en radios/casillas (del tema), áreas táctiles < 44 px, columnas booleanas ilegibles a ~500 px, bloque «Contracts» en inglés en Ajustes, prueba a 375 px exactos.
  7. [Empresa] Comprobar razón social y RUC de la empresa en erp_dev antes de imprimir liquidaciones reales (CA-11).
  8. Horas extra de US-011: sumarlas a la base de remuneración cuando existan.
