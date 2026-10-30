# Historia de Usuario: US-002 - Localización contable Ecuador (l10n_ec + OCA l10n-ecuador 18.0)

- **ID:** US-002
- **Tipo:** Historia Técnica
- **Fecha:** 2026-10-30
- **Sprint / Módulo:** Contabilidad · `third_party/` (si aplica), `addons/erp_account_ec` (nuevo)
- **Estado:** Pendiente (pausada 2026-10-30 por prioridad de Talento Humano; ADR-002 aceptada)
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (evaluación, datos) / DEV-5 (submódulo si aplica) / DEV-2 (lógica, tests) / DEV-4 (vistas si aplica)
- **Depende de:** US-001 (plan `ec` instalado por `erp_base`); base de US-003/US-004/US-005

---

### 1. Definición de la Historia
- **Como:** administrador contable de LAARCOURIER EXPRESS S.A.
- **Quiero:** la empresa configurada con su RUC, el plan de cuentas, los impuestos (IVA, retenciones de renta e IVA) y los tipos de documento SRI vigentes, con cada valor legal identificado por su norma
- **Para:** operar la contabilidad conforme a la normativa ecuatoriana y tener la base de la facturación electrónica

---

### 2. Criterios de Aceptación (Gherkin / BDD)
- **CA-1 · Decisión documentada (ADR-002):**
  - **Dado que:** Odoo 18 Community trae `l10n_ec` (plan, impuestos, tipos de identificación y de documento) pero no la facturación electrónica (`l10n_ec_edi` es Enterprise)
  - **Cuando:** se evalúan los módulos de OCA/l10n-ecuador rama 18.0 (y otras fuentes comunitarias si existen) frente a `l10n_ec` + desarrollo propio, instalándolos en una BD de prueba
  - **Entonces:** existe `docs/decisiones/ADR-002-localizacion-contable.md` con módulos disponibles e `installable` en 18.0, cobertura (retenciones, ATS, documentos electrónicos, firma XAdES, conector SRI), tests y CI, licencia (compatibilidad con LGPL-3), actividad, dependencias Python, riesgo de migración, la opción elegida y las descartadas. **La opción la aprueba el usuario** antes de implementar.
- **CA-2 · Datos de la empresa:**
  - **Dado que:** una BD nueva sin demo con `erp_base` y el módulo de esta historia
  - **Cuando:** se instala
  - **Entonces:** la empresa es "LAARCOURIER EXPRESS S.A." con RUC `1791705726001` (tipo de identificación RUC, válido para `l10n_ec`), país Ecuador y moneda USD; en una BD existente con la empresa por defecto ("My Company") se corrige igual; si la empresa ya fue personalizada por el usuario, no se sobrescribe.
- **CA-3 · Impuestos vigentes con fuente:**
  - **Dado que:** el plan `ec` instalado
  - **Cuando:** se revisan los impuestos de venta y compra
  - **Entonces:** existen y están activos los impuestos IVA y las retenciones de renta e IVA vigentes; `docs/normativa/impuestos-ec.md` lista cada impuesto (código, tasa, uso, norma y fecha de vigencia o "a validar"); los impuestos no vigentes (p. ej. tasas de IVA anteriores) quedan archivados o documentados como históricos sin borrarse; todo valor es editable por el contador (sin tasas fijas en código).
- **CA-4 · Tipos de documento e identificación SRI:**
  - **Dado que:** la localización instalada
  - **Cuando:** se consultan los tipos de documento (factura, nota de crédito, nota de débito, liquidación de compra, comprobante de retención, guía de remisión) y de identificación (RUC, cédula, pasaporte, consumidor final, exterior)
  - **Entonces:** existen con sus códigos SRI, y un cliente con RUC/cédula inválido se rechaza al validarlo (validación de `l10n_ec` o propia), con mensaje en español.
- **CA-5 · Sin modificar terceros ni núcleo:** si se adopta OCA, queda como submódulo fijado en `third_party/` documentado en `third_party/README.md` y limpio; adaptaciones en `addons/erp_account_ec`.
- **CA-6 · Calidad:** `bash scripts/test.sh erp_account_ec` y `bash scripts/check.sh --all` salen con 0, con tests de CA-2..CA-4.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Evaluación / Datos | DEV-3 | ADR-002 con instalación de prueba real; tras la decisión: `addons/erp_account_ec` (manifest, datos de empresa/impuestos si hacen falta), `docs/normativa/impuestos-ec.md` |
| Infraestructura | DEV-5 | Submódulo en `third_party/` y requisitos Python, solo si se adopta OCA |
| Backend | DEV-2 | Hook/idempotencia de datos de empresa, validaciones, tests |
| Web | DEV-4 | Solo si hace falta ajustar vistas |

**Fuera de alcance:** firma electrónica, envío al SRI y RIDE (US-003/US-004), ATS y formularios (US-005), establecimientos y puntos de emisión en diarios (US-003), contabilización de nómina (US-008).

---

### 4. Contrato
*(Se fija tras ADR-002.)*

---

### 5. Decisiones Técnicas y Supuestos
- Preferencia por defecto: reutilizar OCA si cumple criterios (mismo criterio que ADR-001); el usuario aprueba la opción.
- Las tasas y códigos se toman de los datos de `l10n_ec`/OCA y se contrastan con la norma vigente; lo que el equipo no pueda contrastar con una fuente oficial queda "a validar" en `docs/normativa/impuestos-ec.md` (el usuario o su contador confirman).
- La empresa se configura desde datos/hook idempotente (corrige el "My Company" observado en `erp_dev` el 2026-10-30).
- Se ejecuta en paralelo con US-010 (solo `erp_hr_ec`); esta historia no toca `erp_hr_ec`.

### Respuestas del usuario (2026-10-29)
- Empresa: LAARCOURIER EXPRESS S.A., RUC 1791705726001. **Una sola empresa** (confirmado 2026-10-29); se mantiene `company_id` por convención.
- Fuente normativa: la legislación ecuatoriana vigente; cargar los valores legales vigentes como valores por defecto, parametrizables con vigencia, citando la norma de cada uno.
- 2026-10-30: el usuario aprueba empezar esta historia en paralelo con US-010.

- 2026-10-30: el usuario aprueba seguir en Odoo 18 y la Opción C1 de ADR-002, y pide terminar primero todo Talento Humano; esta historia se pausa con la evaluación hecha.

### Preguntas abiertas para el usuario
- ¿Rechazar RUC/cédula con dígito verificador inválido, con excepción marcable solo por un administrador? (recomendación del equipo: sí)
- Confirmación del contador de las tasas "a validar" (IVA 5 % y 8 %, retenciones de renta activas).
