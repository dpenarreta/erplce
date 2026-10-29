# Historia de Usuario: US-009 - Respaldo, restauración y despliegue de producción

- **ID:** US-009
- **Tipo:** Historia Técnica
- **Fecha:** 2026-10-29
- **Sprint / Módulo:** Backlog fase 1
- **Estado:** Pendiente
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-5
- **Depende de:** US-001

---

### 1. Definición de la Historia
- **Como:** administrador del sistema
- **Quiero:** respaldar BD y filestore, restaurar con un script probado y desplegar en producción con proxy y TLS
- **Para:** proteger los datos y operar el ERP con seguridad

---

### 2. Criterios de Aceptación (Gherkin / BDD)
*(Se redactan al iniciar la historia, con las respuestas del usuario.)*

---

### 5. Decisiones Técnicas y Supuestos
- Heredado de QA US-001: rol de PostgreSQL sin superusuario (solo CREATEDB) para Odoo; `admin_passwd` como hash pbkdf2; credenciales de BD no visibles en `ps`; contraseña del admin distinta de `admin` en el alta; CA de inspección TLS solo si aplica en el servidor.
- Parámetros normativos: nunca fijos en código; fuente indicada por el usuario o 'a validar'.

### Preguntas abiertas para el usuario
- Servidor/proveedor de producción y dominio.
- Política de retención de respaldos.
