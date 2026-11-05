# Historia de Usuario: US-019 - Despeje de pantallas de RRHH y nómina; Inicio con indicadores

- **ID:** US-019
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-11-05
- **Sprint / Módulo:** `erp_theme`, `erp_hr_ec`, `erp_payroll_ec`, `erp_establishment`, `erp_hr_holidays_ec` (vistas)
- **Estado:** Pendiente
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-4 (DEV-2 si el tablero necesita datos de servidor)
- **Depende de:** US-018

---

### 1. Definición de la Historia
- **Como:** usuario de RRHH y nómina (poco técnico)
- **Quiero:** formularios y listas con solo lo necesario, agrupado con claridad, y una pantalla de inicio con lo que tengo pendiente
- **Para:** trabajar más rápido y con menos errores
- **Origen:** decisión del usuario 2026-11-05 («pantallas recargadas»); se separa de US-018 (tema y navegación).

### 2. Alcance a detallar al iniciar
- Ficha de empleado, contratos, rol de pagos, lotes, parámetros, establecimientos y vacaciones: reagrupar campos, menos pestañas, campos avanzados plegados, listas con columnas esenciales (resto opcionales).
- Kanban de empleados en tarjetas con foto, cargo, establecimiento y jefe inmediato.
- «Inicio» con indicadores por perfil (p. ej. solicitudes por aprobar, roles en borrador, parámetros a validar).
- Pendientes de US-018: `aria-label` de botones móviles del núcleo (atrás, rayo, engranaje) y de Guardar/Descartar en inglés; miga de pan truncada con muchos botones inteligentes; anchos de columnas de Empleados («Nombre» legible, «Actividades»/«Siguiente fecha límite» opcionales); menús redundantes «Empleados > Empleados» y «Configuración > Configuración»; tarjeta en calendario de Ausencias y Ajustes.
- Pendiente US-012: lista «Saldos de vacaciones» se desborda 11 px a 1536 px y corta «Empleado».
- Pendiente US-017: líneas del horario en inglés («Monday Morning…»), encabezado truncado y zona horaria UTC de la jornada por defecto; `help` propio de `payroll.hr_payslip_action_employee`; «nómina» → «rol de pagos» en Ajustes; texto del UserError del parámetro.

Criterios de aceptación detallados al iniciar la historia (con propuesta de QA-UX sobre las pantallas reales).
