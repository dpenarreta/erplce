# Historia de Usuario: US-[ID] - [Título Descriptivo]

- **ID:** US-[ID]
- **Tipo:** [Historia de Usuario / Bug / Historia Técnica]
- **Fecha:** [AAAA-MM-DD]
- **Sprint / Módulo:** [Nombre del Módulo o Feature]
- **Estado:** En Progreso
- **Tech Lead Asignado:** Tech-Lead Orchestrator
- **Desarrolladores Requeridos:** [DEV-1 / DEV-2 / DEV-3 / DEV-4 / DEV-5]

---

### 1. Definición de la Historia
- **Como:** [Rol de usuario o sistema]
- **Quiero:** [Acción concreta]
- **Para:** [Beneficio de negocio]

*(En un Bug: **Comportamiento actual**, **Comportamiento esperado** y **Pasos para reproducir** en lugar de Como/Quiero/Para).*

---

### 2. Criterios de Aceptación (Gherkin / BDD)
- **CA-1 · Escenario (Camino Feliz):**
  - **Dado que:** [Precondición]
  - **Cuando:** [Acción]
  - **Entonces:** [Resultado esperado exacto]
- **CA-2 · Escenario (Falla o Validación):**
  - **Dado que:** [Precondición de error o límite]
  - **Cuando:** [Acción incorrecta o falla]
  - **Entonces:** [Respuesta controlada, con el código/mensaje de error del contrato]

---

### 3. Alcance Técnico por Capa
| Capa | Sub-Agente | Entregables Requeridos |
|---|---|---|
| [Capa] | [DEV-X] | [Entregables] |

**Fuera de alcance:** [Lo que explícitamente no incluye esta historia]

---

### 4. Contrato
*(Endpoints, modelos/campos, acciones o eventos que cruzan capas.)*

| Operación | Ruta / Modelo / Acción | Acceso | Entrada | Salida | Errores |
|---|---|---|---|---|---|

---

### 5. Decisiones Técnicas y Supuestos
- [Decisión o supuesto, y por qué. Parámetros normativos: fuente o "a validar".]

---

### 6. Registro de Cierre
*(Lo completa el Tech Lead al finalizar).*

- **Estado final:** [COMPLETADA / COMPLETADA CON PENDIENTES / BLOQUEADA]
- **Fecha de cierre:** [AAAA-MM-DD]
- **QA-FUNC:** [Veredicto] · **QA-TECH:** [Veredicto]
- **Criterios de aceptación:** [CA-1 ✅, CA-2 ✅, ...]
- **Archivos principales:** [Rutas]
- **Verificación ejecutada:** [Comandos y resultado]
- **Pendientes:** [Lista o "Ninguno"]
