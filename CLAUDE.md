# erp

ERP personalizado sobre **Odoo 18 Community** para Ecuador. Toda la personalización vive en módulos propios (`addons/`) y módulos de terceros fijados (`third_party/`); el núcleo de Odoo no se modifica nunca. Entorno con Docker Compose (Odoo + PostgreSQL). Primera fase: Contabilidad y facturación (con SRI) y RRHH y nómina.

## Flujo de trabajo obligatorio: equipo de desarrollo

Todo requerimiento de desarrollo (funcionalidad nueva, historia de usuario, bug, refactorización, cambio de modelo de datos, vista, reporte o infraestructura) se ejecuta **siempre** invocando la skill `equipo` (Tech Lead) con el requerimiento completo como argumento, antes de leer o modificar código. El Tech Lead orquesta a los subagentes definidos en `docs/equipo/perfil.md` (`dev-devops`, `dev-database`, `dev-backend`, `dev-web`, `qa-functional`, `qa-technical`).

No implementes código directamente en la conversación principal.

Excepciones (se responden sin el equipo):
- Preguntas, explicaciones o consultas sobre el código que no piden cambios.
- Cambios en la configuración del propio equipo: `.claude/`, `CLAUDE.md`, `docs/equipo/` cuando solo se edita la convención.
- Cuando el usuario lo pida explícitamente ("sin equipo", "hazlo directo").

Si dudas de si un mensaje es un requerimiento de desarrollo, pregunta al usuario.

## Referencias

- Perfil técnico del equipo (stack, roles, rutas, convenciones Odoo, verificación): `docs/equipo/perfil.md`.
- Historias de usuario: `docs/user_stories/` (índice en `README.md`, plantilla en `_TEMPLATE.md`).
- Entorno local no versionado: `CLAUDE.local.md`.
