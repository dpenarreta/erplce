# Historias de Usuario

Registro de trazabilidad del proyecto. Cada requerimiento ejecutado por el equipo (`/equipo`) genera un archivo `US-[NNN]-[nombre-corto].md` a partir de `_TEMPLATE.md`. El Tech Lead mantiene este índice. Las historias del backlog que aún no han empezado figuran como `Pendiente`.

| ID | Título | Tipo | Estado | Fecha |
|---|---|---|---|---|
| [US-001](US-001-base-plataforma.md) | Base de la plataforma ERP (Odoo 18 Community · Ecuador) | Historia Técnica | COMPLETADA CON PENDIENTES | 2026-10-29 |
| [US-002](US-002-localizacion-contable-ec.md) | Localización contable Ecuador (l10n_ec + OCA l10n-ecuador 18.0) | Historia Técnica | Pendiente | 2026-10-29 |
| [US-003](US-003-facturacion-electronica-sri.md) | Facturación electrónica SRI (factura) | Historia de Usuario | Pendiente | 2026-10-29 |
| [US-004](US-004-comprobantes-electronicos-sri.md) | Otros comprobantes electrónicos SRI | Historia de Usuario | Pendiente | 2026-10-29 |
| [US-005](US-005-anexos-reportes-sri.md) | Anexos y reportes tributarios (ATS, formularios 103/104) | Historia de Usuario | Pendiente | 2026-10-29 |
| [US-006](US-006-motor-nomina.md) | Evaluación e integración del motor de nómina (OCA payroll 18.0 vs propio) | Historia Técnica | COMPLETADA CON PENDIENTES | 2026-10-29 |
| [US-007](US-007-rrhh-ecuador.md) | RRHH Ecuador: empleados, contratos y establecimientos | Historia de Usuario | COMPLETADA CON PENDIENTES | 2026-10-29 |
| [US-008](US-008-nomina-ecuador.md) | Nómina Ecuador: rol de pagos, IESS, décimos, fondos de reserva | Historia de Usuario | Pendiente | 2026-10-29 |
| [US-009](US-009-respaldo-despliegue.md) | Respaldo, restauración y despliegue de producción | Historia Técnica | Pendiente | 2026-10-29 |

**Prioridad acordada (2026-10-29):** US-001 → US-006 → US-007 → US-008 (RRHH y nómina) → US-002 → US-003 → US-004 → US-005 (contabilidad y SRI) → US-009. La contabilización de la nómina usa el plan contable de `l10n_ec` instalado en US-001; la parametrización contable completa de US-002 puede ir en paralelo.
