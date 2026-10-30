# Historia de Usuario: US-010 - Opción "Sin instructor" y campo "Jefe inmediato" en la ficha de empleado

- **ID:** US-010
- **Tipo:** Historia de Usuario
- **Fecha:** 2026-10-30
- **Sprint / Módulo:** RRHH · `erp_hr_ec`
- **Estado:** COMPLETADA CON PENDIENTES
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** DEV-3 (campo) / DEV-2 (lógica) / DEV-4 (widget y vistas)
- **Depende de:** US-007

---

### 1. Definición de la Historia
- **Como:** responsable de RRHH
- **Quiero:** elegir "Sin instructor" en el desplegable del campo Instructor del empleado
- **Para:** dejar constancia de que el empleado no necesita capacitación ni instructor asignado, distinguiéndolo de un instructor aún no asignado

---

### 2. Criterios de Aceptación (Gherkin / BDD)
- **CA-1 · Opción en el desplegable:**
  - **Dado que:** un usuario de RRHH edita un empleado
  - **Cuando:** abre el desplegable de Instructor
  - **Entonces:** además de los empleados aparece la entrada "Sin instructor" (al inicio de la lista); al elegirla, el campo muestra "Sin instructor", el empleado queda marcado como sin instructor y sin empleado instructor; se guarda y se mantiene al recargar.
- **CA-2 · Volver a asignar:**
  - **Dado que:** un empleado marcado "Sin instructor"
  - **Cuando:** se elige un empleado como instructor (o se borra el campo)
  - **Entonces:** la marca "Sin instructor" se quita automáticamente (al borrar el campo queda "sin asignar", no "Sin instructor").
- **CA-3 · Relleno automático de Odoo:**
  - **Dado que:** un empleado marcado "Sin instructor"
  - **Cuando:** se asigna o cambia su Gerente
  - **Entonces:** el Instructor no se rellena con el Gerente (sigue "Sin instructor"); para empleados sin la marca, el comportamiento estándar de Odoo no cambia.
- **CA-4 · Coherencia en servidor:**
  - **Dado que:** escrituras por API/importación
  - **Cuando:** se guarda un empleado con la marca "Sin instructor" y a la vez un instructor
  - **Entonces:** prevalece el instructor indicado explícitamente y la marca se quita (nunca quedan ambos); no existe ningún empleado ficticio "Sin instructor".
- **CA-5 · Búsqueda y lista:**
  - **Dado que:** la lista de empleados
  - **Cuando:** se filtra
  - **Entonces:** hay filtros "Sin instructor" (marcados) e "Instructor sin asignar" (ni instructor ni marca); en la lista con la columna Instructor visible se distingue "Sin instructor".
- **CA-7 · Renombrar Gerente a "Jefe inmediato":**
  - **Dado que:** el campo `parent_id` del empleado (relación de supervisión: organigrama, aprobaciones, relleno del Instructor), mostrado hoy como "Gerente"
  - **Cuando:** un usuario abre la ficha, la lista, los filtros/agrupaciones de empleados o el perfil público
  - **Entonces:** el campo se llama "Jefe inmediato" (con ayuda: "Persona a la que reporta directamente el empleado; define la línea de supervisión y el organigrama"); el campo "Gerente" del departamento (`hr.department.manager_id`) no cambia.
- **CA-6 · Calidad:** `bash scripts/test.sh erp_hr_ec` y `bash scripts/check.sh --all` salen con 0 (tests de servidor; el widget se prueba con carga de vistas y, si no hay navegador en la imagen, con revisión manual en Chrome).

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| Datos | DEV-3 / DEV-2 (autorizado) | Etiqueta `string="Jefe inmediato"` y `help` de `parent_id` en `hr.employee` y `hr.employee.public` (se decide si basta en el modelo o requiere vistas); `hr.employee.erp_no_coach` Boolean "Sin instructor" (`groups` como `coach_id`: sin grupo, porque `coach_id` es público; tracking), tests de campo |
| Backend | DEV-2 | Override de `_compute_coach` (respeta la marca), coherencia en create/write (instructor explícito quita la marca; marca vacía el instructor), tests |
| Web | DEV-4 | Widget OWL que extiende `many2one`/`many2one_avatar_user` con la entrada "Sin instructor" y la muestra cuando la marca está activa, aplicado por xpath al `coach_id` del formulario (y lista si aplica); filtros de búsqueda; tests de carga de vistas; revisión en Chrome |

**Fuera de alcance:** desactivar el relleno automático Gerente → Instructor para empleados sin la marca; reportes de capacitación.

---

### 4. Contrato
| Operación | Modelo | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|
| Marcar sin instructor | `hr.employee.erp_no_coach` | quien puede editar el empleado | `True` | `coach_id = False` | — |
| Asignar instructor | `hr.employee.coach_id` | idem | id empleado | `erp_no_coach = False` | — |

---

### 5. Decisiones Técnicas y Supuestos
- Se usa un campo booleano real y no un empleado ficticio "Sin instructor" (contaminaría organigrama, nómina, permisos y reportes).
- `erp_no_coach` se declara en `hr.employee` (y en `hr.employee.public` si hace falta para que la vista pública no falle), sin grupo restringido, como `coach_id`.
- Solicitado por el usuario el 2026-10-30 tras revisar la ficha en Chrome.
- 2026-10-30: el usuario pide renombrar "Gerente" (`parent_id`) a **"Jefe inmediato"** dentro de esta historia (CA-7).
- Traducción de "Jefe inmediato" (`addons/erp_hr_ec/i18n/es.po`): se aplica a `es`, `es_EC` y demás variantes de español al instalar/actualizar `erp_hr_ec`. Al **activar otra variante de español** después de instalar el módulo, la traducción "Gerente" de `hr` puede prevalecer: hay que cargar el idioma desde *Ajustes > Traducciones > Cargar una traducción* marcando **"Sobrescribir términos existentes"** (o actualizar `erp_hr_ec` después de activarlo).
- Posición de la entrada "Sin instructor" en el desplegable: primera solo con la búsqueda vacía y el campo sin instructor (CA-1); con instructor ya asignado y búsqueda vacía, al final; con texto escrito solo aparece si coincide por inicio de palabra ("sin", "instr") y va después de los empleados, para que Tab/Intro sobre la primera opción no marque "Sin instructor" por error.
- Edición múltiple en la lista: vaciar el Instructor envía también `erp_no_coach = false`, de modo que todas las filas seleccionadas quedan "sin asignar".
- Versión de `erp_hr_ec`: `18.0.1.1.0` (columna booleana nueva; sin script de migración).

---

### 6. Registro de Cierre

- **Estado final:** COMPLETADA CON PENDIENTES
- **Fecha de cierre:** 2026-10-30
- **QA-FUNC:** 🟡 APROBADO CON OBSERVACIONES (7/7 CA; brecha 1 —orden de la entrada con texto— y brecha 2 —comentario/documentación de traducciones— corregidas) · **QA-TECH:** 🟡 APROBADO CON OBSERVACIONES 8.5/10 (sin P1/P2; P3 de normalización, edición múltiple y versión corregidos)
- **Criterios de aceptación:** CA-1 ✅ CA-2 ✅ CA-3 ✅ CA-4 ✅ CA-5 ✅ CA-6 ✅ CA-7 ✅
- **Archivos principales:** `addons/erp_hr_ec/models/hr_employee.py` (`erp_no_coach`, `_compute_coach`, coherencia create/write, onchanges, `parent_id` "Jefe inmediato"), `models/res_users.py`, `i18n/es.po`, `views/hr_employee_coach_views.xml`, `static/src/fields/coach_many2one/` (widget `erp_coach_many2one` y `coach_no_coach_options.js`), `static/tests/coach_no_coach_options.test.js`, tests `test_hr_ec_no_coach.py` y `test_hr_ec_coach_views.py`; versión `18.0.1.1.0`.
- **Verificación ejecutada:** `bash scripts/check.sh --all` por el Tech Lead → exit 0 (`0 failed, 0 error(s) of 215 tests`, una sola BD efímera en el log; pip-audit sin vulnerabilidades). Prueba manual en Chrome sobre `erp_dev` (registro nuevo sin guardar, descartado): "Jefe inmediato" visible; "Sin instructor" primera con búsqueda vacía; al seleccionarla el campo muestra "Sin instructor"; con "in" aparece tras "Administrator"; consola sin errores.
- **Pendientes:**
  1. "Mis preferencias" (`res.users.coach_id`) usa el widget estándar: un empleado marcado se ve con Instructor vacío y vaciarlo ahí no quita la marca.
  2. Vaciar `coach_id` por API/importación conserva la marca (regla documentada; CA-2 se cumple desde el formulario).
  3. Tests hoot del widget no ejecutados en `/web/tests` (sin navegador en la imagen; ejecutados aparte con Node).
  4. DEV-5: ejecuciones simultáneas de `scripts/test.sh` mezclan logs (serializar con `flock` o nombre de contenedor por BD).
  5. Aviso docutils `(ERROR/3) Unexpected indentation` al cargar `mail` (heredado).
