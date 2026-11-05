# Historia de Usuario: US-018 - Tema visual ERP LCE: menú lateral, aspecto moderno y uso en celular

- **ID:** US-018
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-11-05
- **Sprint / Módulo:** Transversal · módulo nuevo `erp_theme` (+ `erp_branding` para la auditoría de contraste)
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-4
- **Depende de:** US-001, US-017

---

### 1. Definición de la Historia
- **Como:** usuario del ERP LCE (muchos usuarios, poco técnicos; parte de ellos desde el celular)
- **Quiero:** una interfaz moderna con un menú lateral claro, pantallas en tarjetas con aire y que funcione bien en el celular
- **Para:** encontrar las opciones sin capacitación y trabajar cómodo, con una imagen propia de LAARCOURIER y no la de Odoo
- **Origen:** decisión del usuario 2026-11-05 («la UI está horrible de Odoo, por eso quiero personalizarla»). Le molestan: aspecto anticuado, navegación confusa (cuadrícula de aplicaciones y menús superiores), pantallas recargadas y uso en celular. Estilo elegido: **menú lateral moderno** (barra lateral negra con módulos e íconos, contenido en tarjetas blancas, acentos amarillos; estilo SaaS actual tipo Notion/Linear).

---

### 2. Criterios de Aceptación (Gherkin / BDD)

**Navegación**
- **CA-1 · Menú lateral:**
  - **Dado que** un usuario interno inicia sesión en una pantalla de ≥ 992 px,
  - **cuando** se carga el cliente web,
  - **entonces** a la izquierda hay una barra lateral fija negra (`#000000`, ~240 px) con el logo ERP LCE arriba y la lista de aplicaciones visibles para ese usuario (respeta los grupos, igual que el menú de Odoo), cada una con su ícono y su nombre; al elegir una aplicación se despliegan sus submenús (secciones y opciones) dentro de la barra, y la opción activa se marca con indicador amarillo `#FCE200` y texto legible (contraste ≥ 4.5:1).
- **CA-2 · Barra superior simplificada:**
  - **Entonces** la barra superior ya no muestra el botón de cuadrícula de aplicaciones ni los menús de sección de la aplicación (están en la barra lateral); conserva el nombre de la aplicación/pantalla actual y el área de sistema (actividades, mensajes, empresa, usuario, modo depuración cuando aplique), con fondo claro y altura contenida.
- **CA-3 · Contraer barra:**
  - **Dado que** el usuario necesita más espacio, **cuando** pulsa el botón «Contraer menú», **entonces** la barra queda solo con íconos (~64 px) con nombre en `title`/tooltip; la preferencia se recuerda en el navegador (`localStorage` envuelto en try/catch; si falla, se muestra expandida).
- **CA-4 · Celular y tableta (< 992 px):**
  - **Dado que** la pantalla mide < 992 px (incluido 375 px),
  - **cuando** se abre el ERP,
  - **entonces** la barra lateral no ocupa espacio; un botón hamburguesa (≥ 44×44 px, `aria-label="Abrir menú"`) en la barra superior la abre como panel superpuesto con fondo oscurecido; se cierra con Escape, con la X, al tocar fuera o al elegir una opción; mientras está abierta el foco queda dentro y al cerrar vuelve al botón.
- **CA-5 · Accesibilidad de la navegación:** la barra es `<nav aria-label="Menú principal">`; las aplicaciones desplegables usan `aria-expanded`; la opción activa `aria-current="page"`; se navega completa con Tab/Intro/Espacio; foco visible con la marca; áreas táctiles ≥ 44 px de alto en celular.

**Aspecto**
- **CA-6 · Contenido en tarjetas:** el fondo del área de trabajo es gris claro neutro; formularios (`o_form_sheet`), listas, kanban y paneles de búsqueda se muestran como tarjetas blancas con bordes redondeados (≈ 8–12 px) y sombra suave; botones e inputs con esquinas redondeadas coherentes; jerarquía tipográfica clara (título de pantalla y de formulario más grandes); espaciado más generoso en listas sin perder legibilidad.
- **CA-7 · Tipografía:** fuente sans-serif moderna. Preferida **Inter** alojada dentro del módulo (licencia OFL, archivo de licencia incluido, sin cargar de CDN externos: el sistema es intranet); si no se puede incluir, pila de fuentes del sistema (`system-ui, "Segoe UI", Roboto, …`). Decisión registrada en §5.
- **CA-8 · Marca y contraste:** solo colores de la marca y neutros (amarillo `#FCE200` como fondo de botones primarios/indicadores con texto negro, nunca texto amarillo sobre blanco); la auditoría `addons/erp_branding/tests/css_audit.py` (o una equivalente en `erp_theme`) cubre la barra lateral (texto normal, activo, hover, foco), la barra superior, el fondo y las tarjetas, con texto ≥ 4.5:1 y bordes/íconos ≥ 3:1.
- **CA-9 · Pendiente US-017 · «Seguir» del chatter:** el texto del botón «Seguir»/seguidores del chatter alcanza ≥ 4.5:1.

**Responsive de pantallas**
- **CA-10 · Sin desplazamiento horizontal a 375 px:** a 375 px de ancho, la lista y la ficha de Empleados, la lista de Establecimientos y la lista/ficha de Rol de pagos no tienen desplazamiento horizontal de la página (las listas pueden desplazarse dentro de su propio contenedor), con márgenes laterales ≈ 16 px y botones de acción usables con el dedo.

**Calidad**
- **CA-11 · Sin regresiones:** los módulos existentes funcionan igual (abrir, crear, guardar, búsquedas, diálogos, asistentes, impresión); el login y el portal no cambian (salvo lo que herede de la tipografía); no hay errores de JS en consola al navegar; `bash scripts/check.sh --all` sale con 0; QA-UX audita en vivo en `erp_dev` (≥ 1366 px y 375 px) sin hallazgos Críticos ni Altos.

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Web | DEV-4 | Módulo `addons/erp_theme` (depende de `web`, `mail`, `erp_branding`): componente OWL de barra lateral (lee `menu` service: aplicaciones y árbol de submenús), patch/t-inherit del `WebClient`/`NavBar` para insertarlo y ocultar cuadrícula y menús de sección, drawer móvil, SCSS del tema (tarjetas, tipografía, densidad, botones, inputs, chatter), fuente, tests Python (instalación, assets, plantillas) y ampliación de la auditoría de contraste; `i18n/es.po` |
| QA | QA-FUNC, QA-TECH, QA-UX | Auditoría en paralelo; QA-UX en vivo a 1366 px y 375 px |

**Fuera de alcance (backlog):**
- Despeje de pantallas concretas de RRHH/nómina (reagrupar campos, menos pestañas, kanban de empleados), tablero «Inicio» con indicadores y horario en inglés de US-017 → **US-019**.
- Login y sitio web/portal (ya con la marca en US-017).
- Modo oscuro.

---

### 4. Contrato
Sin cambios de servidor ni de datos.

| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Árbol de menús | servicio `menu` del cliente (`getApps`, `getMenuAsTree`, `selectMenu`) | Usuario interno (menús filtrados por grupos por el servidor, como hoy) | — | Aplicaciones y submenús | — |
| Preferencia contraído | `localStorage["erp_theme.sidebar_collapsed"]` | Navegador | `"1"`/`"0"` | — | Acceso fallido → expandido |

---

### 5. Decisiones Técnicas y Supuestos
- **Módulo propio `erp_theme`** separado de `erp_branding`: la marca (colores, logo, login) sigue en `erp_branding`; la disposición del cliente web (barra lateral, tarjetas, responsive) va en `erp_theme`, que puede desinstalarse para volver al aspecto estándar sin perder la marca.
- **OCA `web_responsive` no se adopta (decisión del Tech Lead):** su menú de aplicaciones a pantalla completa y sus ajustes móviles no dan una barra lateral, y parchea los mismos componentes (`NavBar`, menú de aplicaciones) que esta historia, con riesgo de conflictos; añade un submódulo más a mantener. Se reevaluará si aparecen necesidades móviles que no cubra `erp_theme`.
- Sin tocar el núcleo de Odoo ni `third_party/`: solo `patch()`, `t-inherit` y SCSS en assets del backend.
- El menú lateral reutiliza el servicio de menús de Odoo: los permisos por grupo se mantienen exactamente.
- Breakpoint de escritorio 992 px (`lg` de Bootstrap, el mismo que usa Odoo para su modo «small»).
- Fuente sin CDN externo (intranet, privacidad); Inter (SIL OFL 1.1) incluida en el módulo si se puede obtener la distribución oficial; si no, pila del sistema.

---

### 6. Registro de Cierre
- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-11-05
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (8/11 CA verificados por código y tests; CA-10/11 delegados a QA-UX y al Tech Lead; regresión de 374 tests con el tema OK) · **QA-TECH:** 🟡 APROBADO CON OBSERVACIONES 8.5/10 (sin P1/P2; P3 corregidos en ronda 1) · **QA-UX:** ronda 1: 2 Altas (contraste de botones inteligentes 4,16:1 y «Siguiendo» 4,39:1 sobre el fondo gris) + 6 Medias → corregidas; ronda 2: 1 Alta nueva (Guardar/Descartar 26×18 px en móvil) + 6 Medias/Bajas → corregidas; revalidación en vivo: **no quedan Críticos ni Altos**.
- **Criterios:** CA-1 ✅ CA-2 ✅ CA-3 ✅ (con menú emergente de submenús en modo contraído) CA-4 ✅ CA-5 ✅ CA-6 ✅ CA-7 ✅ (Inter 4.1 variable, OFL, alojada en el módulo) CA-8 ✅ (incluye placas de íconos, colores de estado y chatter) CA-9 ✅ CA-10 ✅ (375 px medido por DEV-4 en Chrome sin interfaz; en vivo a 502 px, mínimo de la ventana del usuario) CA-11 ✅
- **Decisiones añadidas en la ejecución:** el chatter pasa debajo del formulario cuando el área útil (ventana − barra lateral) es < 1534 px (parche de `FormRenderer`/`mailLayout`); acordeón de una sola aplicación abierta; enlace «Saltar al contenido»; colores de estado propios (success `#006b13`, warning `#7a5500`, danger `#b3261e`) en botones inteligentes y chatter; selección del panel de búsqueda en `#e1e1e1`.
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (`0 failed, 0 error(s) of 538 tests`; pip-audit limpio). `erp_theme` 18.0.1.0.2 instalado en `erp_dev` (Odoo reiniciado para servir los assets nuevos).
- **Pendientes:**
  1. [→ US-019] `aria-label` de botones móviles del núcleo (atrás, rayo de botones inteligentes, engranaje «Acciones») y etiquetas accesibles de Guardar/Descartar en inglés («Save manually», «Discard all changes»).
  2. [→ US-019] Miga de pan truncada cuando hay muchos botones inteligentes; anchos de columnas de la lista de Empleados; menús redundantes «Empleados > Empleados», «Configuración > Configuración»; tarjeta para calendario de Ausencias y Ajustes.
  3. [P3] Las extensiones de `web.NavBar` dependen de los nodos `t-call` del núcleo (`AppsMenu`, `SectionsMenu`): si una actualización o un módulo futuro (p. ej. `web_responsive`) los reemplaza, el cliente no carga; `test_templates_and_patches` lo detecta al actualizar la imagen. Riesgo aceptado.
  4. [P3] Se pierden los atajos de teclado «h» (menú de aplicaciones) y Alt+1…9 (secciones); la paleta Ctrl+K sigue disponible.
  5. `erp_branding/tests/css_audit.py` aún trata `o_main_navbar` como fondo oscuro (lo cubre `erp_theme/tests/theme_audit.py`); alinear en la próxima ronda de `erp_branding`.
  6. Sin tests JS (hoot): la imagen no trae Chrome; el comportamiento se verificó con Chrome sin interfaz (BD temporal borrada) y en vivo.
  7. 375 px exactos no medidos en vivo (ventana mínima ~500 px); medido por DEV-4 sin interfaz.
