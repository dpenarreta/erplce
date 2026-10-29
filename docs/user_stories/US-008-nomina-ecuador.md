# Historia de Usuario: US-008 - Nómina Ecuador: rol de pagos, IESS, décimos, fondos de reserva

- **ID:** US-008
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Backlog fase 1
- **Estado:** Pendiente
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 / DEV-2 / DEV-4
- **Depende de:** US-006, US-007 (contabilización con el plan `l10n_ec` de US-001; US-002 deseable)

---

### 1. Definición de la Historia
- **Como:** responsable de nómina
- **Quiero:** calcular y contabilizar el rol de pagos mensual con aportes IESS, décimo tercero y cuarto, fondos de reserva, horas extra y provisiones
- **Para:** pagar y provisionar correctamente según la ley

---

### 2. Criterios de Aceptación (Gherkin / BDD)
*(Se redactan al iniciar la historia, con las respuestas del usuario.)*

---

### 5. Decisiones Técnicas y Supuestos
- Todos los porcentajes y valores (SBU, aportes, recargos) parametrizados con vigencia y fuente.
- Parámetros normativos: nunca fijos en código; fuente indicada por el usuario o 'a validar'.

### Heredado de QA de US-006 (2026-10-29)
- Redondeo en cascada: con 1.000,05 el neto (900,05) no cuadra con la suma de líneas (900,04) y `payroll_account` añade un ajuste de 0,01 → convención de redondeo USD por regla y test con 1.000,05.
- Permisos: confirmar un rol exige además el grupo contable `account.group_account_invoice`; diseñar los grupos de nómina y su test.
- Lotes en renovación/terminación: el asistente OCA asigna `employee.contract_id` (contrato actual) sin mirar el periodo; preferir el contrato que cubre el periodo y decidir si un lote es "todo o nada" (178 establecimientos).
- Estados heredados de OCA: doble asiento al confirmar dos veces (PR #308), `compute_sheet` sobre un rol `done` lo devuelve a `verify` con asiento publicado, roles duplicados del mismo empleado y periodo.
- `group_payroll_user` tiene CRUD completo sobre `hr.payslip.line` (puede alterar importes).

### Respuestas del usuario (2026-10-29)
- **Prioridad:** la nómina va antes que la facturación electrónica.
- Fondos de reserva: mensualizados o acumulados **según lo que solicite cada empleado** (opción por empleado con vigencia).
- Décimo tercero y décimo cuarto: también mensualizados o acumulados **por empleado** (confirmado 2026-10-29).
- Reglas propias: bonos, anticipos, descuentos y **préstamos a empleados descontados como anticipos** (cuotas en el rol).
- Fuente normativa: legislación ecuatoriana vigente (Código del Trabajo, Ley de Seguridad Social/IESS, acuerdos del Ministerio del Trabajo para el SBU); valores legales vigentes como valores por defecto, parametrizables con vigencia.

### Preguntas abiertas para el usuario
- Región del décimo cuarto (Sierra/Amazonía vs Costa/Galápagos) por empleado o por establecimiento.
- Catálogo de bonos y descuentos propios y política de préstamos (montos máximos, plazo, interés).
