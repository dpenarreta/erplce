# Historia de Usuario: US-003 - Facturación electrónica SRI (factura)

- **ID:** US-003
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Backlog fase 1
- **Estado:** Pendiente
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 / DEV-2 / DEV-4
- **Depende de:** US-002

---

### 1. Definición de la Historia
- **Como:** usuario de facturación
- **Quiero:** emitir facturas electrónicas firmadas (XAdES-BES), enviarlas a recepción y autorización del SRI y entregar el RIDE al cliente
- **Para:** cumplir la obligación de facturación electrónica

---

### 2. Criterios de Aceptación (Gherkin / BDD)
*(Se redactan al iniciar la historia, con las respuestas del usuario.)*

---

### 5. Decisiones Técnicas y Supuestos
- Reutilizar OCA si US-002 lo valida; si no, conector propio con timeouts, reintentos idempotentes y log de envíos.
- Certificado .p12 y su contraseña cifrados, nunca en el repositorio.
- Parámetros normativos: nunca fijos en código; fuente indicada por el usuario o 'a validar'.

### Respuestas del usuario (2026-10-29)
- Ambiente inicial: **pruebas** del SRI.
- 178 establecimientos registrados en el SRI.
- Requisitos externos: firma electrónica .p12 vigente y RUC habilitado en ambiente de pruebas (SRI en Línea).

### Preguntas abiertas para el usuario
- Listado de los 178 establecimientos y sus puntos de emisión (código, dirección), p. ej. exportación del RUC en SRI en Línea.
- ¿Envío automático del RIDE por correo?
