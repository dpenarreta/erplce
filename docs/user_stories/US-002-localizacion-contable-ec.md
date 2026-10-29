# Historia de Usuario: US-002 - Localización contable Ecuador (l10n_ec + OCA l10n-ecuador 18.0)

- **ID:** US-002
- **Tipo:** Historia Técnica
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Backlog fase 1
- **Estado:** Pendiente
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-5 / DEV-3 / DEV-2
- **Depende de:** US-001

---

### 1. Definición de la Historia
- **Como:** administrador contable
- **Quiero:** configurar la(s) empresa(s) con RUC, plan de cuentas, impuestos (IVA, retenciones) y tipos de documento SRI parametrizados por vigencia
- **Para:** operar la contabilidad conforme a la normativa ecuatoriana

---

### 2. Criterios de Aceptación (Gherkin / BDD)
*(Se redactan al iniciar la historia, con las respuestas del usuario.)*

---

### 5. Decisiones Técnicas y Supuestos
- Evaluar módulos de OCA/l10n-ecuador rama 18.0 (madurez, licencia, cobertura, tests) y decidir cuáles fijar en `third_party/`.
- Parámetros tributarios con vigencia por fecha y fuente normativa citada (o 'a validar').
- Parámetros normativos: nunca fijos en código; fuente indicada por el usuario o 'a validar'.

### Respuestas del usuario (2026-10-29)
- Empresa: LAARCOURIER EXPRESS S.A., RUC 1791705726001. **Una sola empresa** (confirmado 2026-10-29); se mantiene `company_id` por convención.
- Fuente normativa: la legislación ecuatoriana vigente; cargar los valores legales vigentes como valores por defecto, parametrizables con vigencia, citando la norma de cada uno.

### Preguntas abiertas para el usuario
- Ninguna.
