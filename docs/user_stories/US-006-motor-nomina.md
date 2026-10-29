# Historia de Usuario: US-006 - Evaluación e integración del motor de nómina (OCA payroll 18.0 vs propio)

- **ID:** US-006
- **Tipo:** Historia Técnica
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Nómina · motor de nómina, `third_party/`, `erp_payroll_ec` (esqueleto)
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (evaluación y modelo) / DEV-5 (submódulo y entorno) / DEV-2 (prueba de humo del cálculo)
- **Depende de:** US-001

---

### 1. Definición de la Historia
- **Como:** equipo de desarrollo
- **Quiero:** elegir con criterios objetivos el motor de nómina (estructuras salariales, reglas, categorías, roles de pago y su contabilización) e integrarlo en el entorno
- **Para:** construir la nómina de Ecuador (US-007, US-008) sobre una base mantenible, actualizable y sin modificar código de terceros

---

### 2. Criterios de Aceptación (Gherkin / BDD)
- **CA-1 · Decisión documentada:**
  - **Dado que:** Odoo 18 Community no incluye nómina
  - **Cuando:** se evalúan al menos OCA/payroll 18.0 (y módulos relacionados de OCA/hr u OCA/l10n-ecuador si aportan) frente a un motor propio
  - **Entonces:** existe `docs/decisiones/ADR-001-motor-nomina.md` con criterios (madurez/estado de los módulos en 18.0, cobertura funcional frente a las necesidades de US-008, tests y CI del repositorio, licencia compatible con LGPL-3, actividad y mantenimiento, dependencias, riesgo de migración a 19.0), la opción elegida, las descartadas y por qué.
- **CA-2 · Terceros fijados y documentados:**
  - **Dado que:** la opción elegida usa código de terceros
  - **Cuando:** se revisa `third_party/`
  - **Entonces:** el repositorio está añadido como submódulo git en `third_party/<repo>/` fijado a un commit concreto de la rama 18.0, registrado en `third_party/README.md` (origen, rama, commit, licencia, módulos usados) y aparece en el `addons_path` tras reiniciar; clonar el repositorio con `--recurse-submodules` deja el entorno funcional (instrucciones en el README).
- **CA-3 · Módulo propio instalable:**
  - **Dado que:** una BD nueva sin demo
  - **Cuando:** se ejecuta `bash scripts/test.sh erp_payroll_ec`
  - **Entonces:** se instalan `erp_base`, el motor elegido, `hr` y los contratos de empleado sin errores y el script sale con 0.
- **CA-4 · Prueba de humo del cálculo:**
  - **Dado que:** un empleado con contrato vigente de salario mensual 1.000,00 USD y una estructura de prueba con una regla de sueldo básico y una deducción porcentual de prueba (valores ficticios de test, no normativos)
  - **Cuando:** se calcula un rol de pagos de un mes completo
  - **Entonces:** las líneas del rol tienen los importes esperados con redondeo de moneda USD, y el rol se puede confirmar; un rol sin contrato vigente en el periodo devuelve un error controlado en español.
- **CA-5 · Sin modificar terceros:**
  - **Dado que:** se revisa el repositorio
  - **Cuando:** se busca código modificado de `third_party/`
  - **Entonces:** el submódulo está limpio (`git -C third_party/<repo> status` sin cambios) y toda adaptación vive en `addons/erp_payroll_ec`.
- **CA-6 · Calidad:**
  - **Dado que:** el código entregado
  - **Cuando:** se ejecuta `bash scripts/check.sh --all`
  - **Entonces:** sale con 0; los linters no analizan `third_party/` (código ajeno) y los tests de los módulos propios pasan.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Evaluación / Datos | DEV-3 | ADR-001 con la evaluación real del código de OCA 18.0 (instalación de prueba, revisión de modelos y tests); tras la decisión: esqueleto `addons/erp_payroll_ec` (manifest, depends, ACL si hay modelos) |
| Infraestructura | DEV-5 | Submódulo en `third_party/`, `third_party/README.md`, exclusión de `third_party/` en linters, README (clonado con submódulos), ajustes de `test.sh`/`check.sh` si hace falta |
| Backend | DEV-2 | Tests de humo de CA-4 en `erp_payroll_ec` (estructura y reglas de prueba creadas en el test, no como datos del módulo) |

**Fuera de alcance:** reglas salariales de Ecuador, IESS, décimos, fondos de reserva, préstamos (US-008); datos de empleados y contratos de Ecuador (US-007); contabilización real de la nómina; vistas propias.

---

### 4. Contrato
| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Rol de pagos | Modelo del motor elegido (p. ej. `hr.payslip`) — se fija en el ADR | Grupo de nómina del motor | empleado, contrato, periodo, estructura | líneas por regla con importes `Monetary` USD | sin contrato vigente → `UserError` en español |

---

### 5. Decisiones Técnicas y Supuestos
- OCA tiene ramas `18.0` en `payroll`, `hr` y `l10n-ecuador` (verificado con `git ls-remote` el 2026-10-29); su estado real (módulos migrados, `installable`) se comprueba en el ADR, no se asume.
- Preferencia por defecto: reutilizar OCA si cumple los criterios, por mantenimiento comunitario; motor propio solo si OCA no está migrado o no es extensible para las reglas de Ecuador.
- Necesidades que el motor debe poder soportar (para US-008): reglas por fórmula con vigencia de parámetros, opción por empleado de mensualizar/acumular décimos y fondos de reserva, bonos, anticipos, descuentos y préstamos con cuotas, contabilización con el plan `l10n_ec`, 178 establecimientos (asignación del empleado a un establecimiento), una sola empresa.
- Valores de los tests de humo: ficticios, no normativos.
- **Decisión (2026-10-29, aprobada por el usuario):** ADR-001 Opción A: OCA/payroll 18.0 fijado en `4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e` como submódulo `third_party/payroll`; se instalan solo `payroll` y `payroll_account`. No se incorpora el `requirements.txt` del repositorio OCA (dependencias de `hr_payroll_document`, no usado). Parámetros normativos en modelo propio `erp.payroll.parameter` (US-008).
- Contrato concreto: rol de pagos = `hr.payslip` (OCA `payroll`); `compute_sheet()` de OCA genera un rol vacío sin contrato → `erp_payroll_ec` lo hereda para lanzar `UserError` (CA-4).
- Riesgos aceptados a tratar en US-008: cancelación de rol borra el asiento si el diario no tiene hash (PR OCA #308) y posible doble asiento; un asiento por rol; redondeo por regla; edición de fórmulas restringida a gestores.
- Los tests propios de OCA dependen de datos demo (`base.res_partner_12`); `test.sh` solo ejecuta `/erp_payroll_ec`, por lo que no se ejecutan en el gate.

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-29
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (6/6 CA; G1/G2 corregidos en ronda 1; O1–O5 trasladadas a US-008) · **QA-TECH:** 🟢 APROBADO 9/10 (ronda 2; ronda 1 RECHAZADO por P2: confirmar sin recálculo saltaba la validación de contrato)
- **Criterios de aceptación:** CA-1 ✅, CA-2 ✅ (clon real verificado tras el push), CA-3 ✅, CA-4 ✅, CA-5 ✅, CA-6 ✅
- **Archivos principales:** `docs/decisiones/ADR-001-motor-nomina.md` (Aceptada, Opción A), `.gitmodules`, `third_party/payroll` (OCA, `4c71cd4`), `third_party/README.md`, `README.md`, `scripts/check.sh`, `addons/erp_payroll_ec/` (`compute_sheet` y `action_payslip_done` con validación de contrato vigente y propio del empleado; 26 tests)
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (pre-commit completo; `0 failed, 0 error(s) of 54 tests` de erp_base, erp_branding y erp_payroll_ec, sin demo; pip-audit sin vulnerabilidades). `git -C third_party/payroll status` limpio; `git submodule status` → `4c71cd4`.
- **Pendientes:**
  1. Observaciones de nómina trasladadas a US-008 (redondeo en cascada, grupos para confirmar, lotes en renovación, doble asiento, roles `done` recalculables, duplicados, CRUD de `hr.payslip.line`).
  2. P3 opcional DEV-2: unificar en un solo mensaje los errores de contrato ajeno y sin contrato vigente cuando coinciden en un lote.
  3. Aviso de docutils `(ERROR/3) Unexpected indentation` en el log de tests (RST de algún módulo; no es de Odoo ni falla el gate): localizar.
  4. Licencia: 4 archivos de `payroll` con cabecera AGPL-3 (uso interno aceptado; revisar si el ERP se ofrece a terceros).
