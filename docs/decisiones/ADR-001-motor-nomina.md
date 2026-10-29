# ADR-001 · Motor de nómina: OCA `payroll` 18.0 frente a motor propio

- **Estado:** Aceptada (2026-10-29, Tech Lead con aprobación del usuario): Opción A; parámetros normativos en modelo propio `erp.payroll.parameter` (no `payroll_rule_time_parameter`)
- **Fecha:** 2026-10-29
- **Historia:** US-006 (CA-1)
- **Autor:** DEV-3 Datos e Integraciones
- **Afecta a:** `third_party/`, `addons/erp_payroll_ec`, US-007, US-008

---

## 1. Contexto

Odoo 18 Community no incluye nómina (`hr_payroll` es Enterprise). Necesitamos un motor de
estructuras salariales, reglas, categorías, roles de pago y contabilización sobre el que
construir la nómina de Ecuador (US-007, US-008) sin modificar el núcleo ni código de terceros.

Necesidades que el motor debe soportar, según US-006 §5:

1. Reglas por fórmula con **parámetros con vigencia** (SBU, % IESS, etc., con fuente normativa).
2. Opción **por empleado** de **mensualizar o acumular** décimos y fondos de reserva.
3. Bonos, anticipos y descuentos.
4. **Préstamos con cuotas**.
5. **Contabilización** con el plan `l10n_ec`.
6. **178 establecimientos** (asignación del empleado a un establecimiento).
7. Una sola empresa.

## 2. Método de evaluación

Todo lo siguiente se hizo el 2026-10-29. No se tocó el repositorio del proyecto.

- Se clonaron las ramas `18.0` (`git clone --depth 50 -b 18.0`) en un directorio temporal:

  | Repositorio | HEAD evaluado | Fecha HEAD |
  |---|---|---|
  | OCA/payroll | `4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e` | 2026-09-22 |
  | OCA/hr | `96c6ad78c7ff70b86e88e2ec3f5e58d4c1cda930` | 2026-10-01 |
  | OCA/l10n-ecuador | `3315e323661b101ea335d922fe5359a542f281cd` | 2025-10-24 |
  | OCA/server-tools (solo `base_time_parameter`, sparse) | `126afd2a62ec528386285aa753b24c15277d1f15` | 2026-10-11 |

- Manifiestos leídos con `ast.literal_eval`. El código clonado no se ejecutó en el host.
- Se consultaron en GitHub (`gh api`) los issues de migración, los PR abiertos y el estado de
  GitHub Actions.
- **Instalación de prueba real** en el entorno Docker del proyecto (imagen `odoo:18.0` fijada,
  PostgreSQL 16). Se usó un compose de sobrecarga temporal fuera del repositorio que monta la
  copia como `/mnt/third-party`, y dos BD efímeras, ya borradas junto con su filestore (§5).
- Revisión del código del modelo de reglas (`hr.salary.rule`, `hr.payslip`, `base_browsable`,
  `payroll_account`) frente a las necesidades (§6).

## 3. Inventario de módulos relevantes (rama 18.0)

### 3.1 OCA/payroll

| Módulo | Versión | installable | Licencia | Madurez | Depende de | Tests (archivos / métodos) | Notas |
|---|---|---|---|---|---|---|---|
| `payroll` | 18.0.1.4.0 | True | LGPL-3 | Beta | `hr_work_entry_holidays`, `mail` (Community) | 7 / 35 | Motor: estructuras, reglas, categorías, inputs, roles, lotes |
| `payroll_account` | 18.0.1.0.6 | True | LGPL-3 | Beta | `payroll`, `account` | 1 / 3 | Asiento contable por rol |
| `payroll_contract_advantages` | 18.0.1.0.0 | True | LGPL-3 | Beta | `hr_contract`, `payroll` | 1 / 5 | Importes recurrentes por contrato con plantillas y límites |
| `payroll_rule_time_parameter` | 18.0.1.0.0 | True | LGPL-3 (las cabeceras de los .py dicen AGPL) | Beta | `base_time_parameter` (OCA/server-tools), `payroll` | 1 / 1 | Parámetros con vigencia en las reglas |
| `payroll_hr_public_holidays` | 18.0.1.0.2 | True | AGPL-3 | Beta | `payroll`, `hr_holidays`, `calendar_public_holiday` (OCA/calendar) | 1 / 2 | Fuera de alcance por ahora |
| `hr_payroll_document` | 18.0.1.0.2 | True | AGPL-3 | Beta | `hr`, `base_vat`; Python `pypdf`, `fonttools` | 1 / 8 | Reparte PDFs de nómina; no aplica |

Dependencia externa: `base_time_parameter` 18.0.1.0.0 (OCA/server-tools, LGPL-3, Beta). Se migró a
18.0 el 2026-08-12. CI de server-tools 18.0 en verde en `126afd2`.

Ninguno de estos módulos depende de módulos Enterprise. `hr_contract`, `hr_work_entry_holidays`,
`account` y `l10n_ec` están en la imagen `odoo:18.0` Community (comprobado en el contenedor).

### 3.2 OCA/hr (18.0)

Hay 36 módulos, todos `installable`. **Ninguno trata nómina, préstamos ni anticipos.** Los que
podrían servir a US-007, sin relación con el motor, son `hr_employee_firstname` y
`hr_employee_second_lastname` (dos apellidos), `hr_employee_ssn`, `hr_employee_relative` (cargas
familiares), `hr_contract_reference`, `hr_employee_id` y `hr_department_code`. Casi todos son
AGPL-3. Último commit: 2026-10-01, con actividad continua.

### 3.3 OCA/l10n-ecuador (18.0)

Solo contiene **`l10n_ec_base`** 18.0.1.0.0 (AGPL-3, depende de `l10n_ec` y `account`, 3 tests),
que amplía la contabilidad (partner, impuestos, diarios). **No tiene nómina.** El último commit en
18.0 es del 2025-10-24. Hay un PR abierto #96 "Draft_Human_Resources" (`l10n_ec_hr_contract`,
`l10n_ec_hr_employee`), pero **contra 19.0** y en borrador; no incluye nómina.

### 3.4 Actividad y mantenimiento de OCA/payroll

- Ramas: 13.0 a 20.0. Issue de migración 18.0 (#169) cerrado: `payroll` y `hr_payroll_document`
  migrados. **`payroll` ya está migrado a 19.0** (el módulo existe en la rama 19.0 y depende de
  `hr.version`); `payroll_account` 19.0 está en PR (#294, abierto).
- Último commit en 18.0: 2026-09-22 (#311). Últimos cambios funcionales en `payroll`: 2026-08-25
  (#264) y 2026-05 (estructura por defecto y vacaciones globales).
- PR abiertos contra 18.0 que nos afectan:
  - **#308** `payroll_account`: cuentas resueltas en la empresa del rol, **reversión real al
    cancelar** (hoy se borra el asiento si el diario no tiene hash) y **sin asiento duplicado al
    confirmar dos veces**.
  - **#320** `payroll`: la estructura de un rol en borrador vuelve a ser editable.
  - #316 (pago quincenal), #317 (`Payslips.max_monthly()`), #318, #290 (etiquetas de reglas).
- Hay 6 issues abiertos (todos de migración) y 29 PR abiertos en el repositorio.
- GitHub Actions en `4c71cd4`: `tests` success y `pre-commit` success (2026-09-22). Una corrida
  previa (`f210ac8`, 2026-09-16) falló, y la siguiente quedó en verde.
- Mantenedores declarados: `appstogrow`, `nimarosa`.

> **Nota de licencia (QA US-006):** el manifiesto de `payroll` declara LGPL-3, pero `wizard/hr_payslip_change_state.py`, `hr_payslip_change_state_view.xml` y 2 tests llevan cabecera AGPL-3. Uso interno sin redistribución ni prestación como servicio a terceros: aceptado; revisar si el ERP se ofrece a terceros.

## 4. Opciones

### Opción A: OCA `payroll` + `payroll_account` (18.0) extendidos desde `erp_payroll_ec` (recomendada)
Es el motor clásico de Odoo (heredero de `hr_payroll` de Odoo ≤ 10), mantenido por OCA y con
reglas Python en `safe_eval`. Todo lo propio de Ecuador vive en `addons/erp_payroll_ec` por
herencia.

### Opción B: motor propio (`erp_payroll_ec` desde cero)
Modelos propios de rol, líneas, reglas y contabilización. Control total, pero hay que construir
y mantener lo que OCA ya resuelve: estructuras jerárquicas, categorías, días trabajados desde
ausencias, lotes, reembolsos, informes y asiento.

### Opción C: Odoo Mates `om_hr_payroll` (github.com/odoomates/hr, rama 18.0, LGPL-3)
Es un fork del mismo motor clásico. Se trasladó el 2026-10-19 de `odoomates/odooapps` a
`odoomates/hr`, lo que indica un repositorio inestable. Tiene un solo mantenedor (empresa), sin
CI ni revisión comunitaria visibles y con una numeración de versión no OCA (`1.2.1`). No se
instaló.

### Opción D: Odoo Enterprise `hr_payroll` + `l10n_ec` de nómina
Queda descartada: el proyecto está fijado en Community (perfil §1).

## 5. Instalación de prueba (evidencia)

Compose de sobrecarga temporal fuera del repositorio (monta la copia de `payroll` y
`base_time_parameter` como `/mnt/third-party`). Usa el mismo `entrypoint.sh`, que añadió ambos
directorios al `addons_path`. El comando reproduce el de `scripts/test.sh`:

```
docker compose -f docker-compose.yml -f docker/compose.test.yml -f <scratchpad>/compose.eval.yml \
  run --rm --no-deps -T odoo odoo -d <BD> \
  -i erp_base,payroll,payroll_account,payroll_contract_advantages,payroll_rule_time_parameter \
  --test-enable --test-tags=/payroll,/payroll_account,/payroll_contract_advantages,/payroll_rule_time_parameter \
  --stop-after-init --log-level=test --workers=0 --max-cron-threads=0 [--without-demo=all]
```

### 5.1 Corrida 1: BD `eval_payroll`, **sin demo** (como `scripts/test.sh`)

- 72 módulos cargados en 53,88 s. Quedaron `installed`: `erp_base`, `l10n_ec` (18.0.3.9),
  `hr_contract`, `hr_work_entry_holidays`, `payroll` 18.0.1.4.0, `payroll_account` 18.0.1.0.6,
  `payroll_contract_advantages`, `payroll_rule_time_parameter` y `base_time_parameter`.
  **La instalación no tuvo errores.**
- Tests: `0 failed, 6 error(s) of 44 tests` (salida de Odoo con RC=1).
  - `payroll`: 0 failures, 3 errors of 35 (`TestHrPayrollCancel.test_action_payslip_cancel`,
    `TestHrPayrollCancel.test_refund_sheet`, `TestHrPayslipChangeState.test_change_state`).
  - `payroll_account`: 0 failures, 3 errors of 3.
  - `payroll_contract_advantages` y `payroll_rule_time_parameter`: sin errores.
  - **Causa única de los 6 errores:** `ValueError: External ID not found in the system:
    base.res_partner_12`. Es un **dato de demo** que usa el `setUp` de esos tests. No se trata de
    un fallo funcional: el CI de OCA instala con demo.

### 5.2 Corrida 2: BD `eval_payroll_demo`, **con demo** (como el CI de OCA)

- 74 módulos cargados en 68,06 s. Todos los pedidos quedaron `installed`, igual que en la
  corrida 1. RC de Odoo = 0, sin líneas `ERROR` ni `CRITICAL`.
- **`odoo.tests.result: 0 failed, 0 error(s) of 44 tests`.**
  - `odoo.tests.stats`: `payroll` 49 tests (8,36 s), `payroll_account` 5 tests,
    `payroll_contract_advantages` 7 tests y `payroll_rule_time_parameter` 3 tests. El recuento de
    `stats` incluye los `setUp`/clases.
- Esto confirma que los 6 errores de la corrida 1 se deben solo a la ausencia de datos de demo.

Ambas BD y sus filestores se borraron tras la prueba (`dropdb --force` + `rm -rf
/var/lib/odoo/filestore/<BD>`). Se verificó que solo queda `erp_dev`.

**Consecuencia para CA-3/CA-6:** `scripts/test.sh` ejecuta solo los tests de los módulos pedidos
(`/erp_payroll_ec`), así que los tests de OCA dependientes de demo no se ejecutan ni rompen la
verificación. No hay que tocar `test.sh`.

## 6. Modelo de reglas de `payroll` frente a las necesidades de US-008

**Cómo funciona el motor (código revisado):**

- `hr.payroll.structure`: jerarquía padre/hija (`parent_id`). Las reglas de la estructura y de
  sus padres se ordenan por `sequence` (`get_structure_with_parents`, `get_all_rules`).
- `hr.salary.rule`: `condition_select` ∈ {siempre, rango, Python} y `amount_select` ∈ {fijo, %,
  código Python}. La fórmula se evalúa con **`odoo.tools.safe_eval`** y el resultado se devuelve
  en `result`, `result_qty`, `result_rate` y `result_name`. Hay reglas hijas (`parent_rule_id`):
  si la madre no cumple su condición, sus hijas se descartan.
- Variables disponibles en la fórmula: `payslip`, `employee`, `contract`, `categories` (sumas por
  categoría jerárquica), `rules` y `result_rules` (resultados previos por código), `worked_days`,
  `inputs`, `payslips` (con `sum(code, desde, hasta)` sobre roles confirmados), `payroll`,
  `current_contract` y `tools` (`math`).
- **Puntos de extensión** previstos para heredar: `get_payroll_dict()`,
  `get_current_contract_dict()`, `_get_tools_dict()`, `get_inputs()`, `localdict_hook()` y
  `_get_lines_dict()`.
- `hr.salary.rule.category` es jerárquica (`parent_id`). `hr.contribution.register` define el
  tercero (partner) beneficiario, por ejemplo IESS.
- `hr.rule.input` declara en la regla las entradas que necesita. `hr.payslip.input` guarda el
  importe por rol y se usa en la fórmula como `inputs.CODE.amount`.
- `hr.payslip.line` hereda de `hr.salary.rule`: cada línea copia la regla aplicada (trazabilidad).
  `amount` y `total` son `Monetary` con la moneda del contrato; `quantity` y `rate` son `Float`.
- Estados del rol: `draft → verify → done | cancel`, con reembolso (`refund_sheet`) y lotes
  (`hr.payslip.run`). Las reglas de registro son multiempresa en todos los modelos.

| # | Necesidad (US-006 §5 / US-008) | Cobertura | Cómo |
|---|---|---|---|
| 1 | Reglas por fórmula | **Nativa** | `amount_select = code` con `safe_eval`, condiciones Python o de rango, categorías y estructuras padre/hija |
| 1b | Parámetros con vigencia (SBU, % IESS…) con fuente normativa | **Extendiendo** | Opción 1: `payroll_rule_time_parameter` + `base_time_parameter` (OCA, `payslip.rule_parameter("SBU")`). Probado: se instala y su test pasa. El valor se guarda como `Char` tipado y no tiene campo de fuente normativa. Opción 2, **recomendada**: modelo propio `erp.payroll.parameter` (código, `date_from`, valor numérico exacto, fuente normativa), expuesto a las reglas con `get_payroll_dict()`/`_get_tools_dict()`. Así no hay que añadir OCA/server-tools entero como submódulo |
| 2 | Mensualizar / acumular décimos y fondos de reserva por empleado | **Extendiendo** | Campos por contrato o empleado en `erp_payroll_ec` (DEV-3) y reglas con condición Python (`contract.x… == 'monthly'`). Para el acumulado, regla de provisión, `payslips.sum(code, desde, hasta)` sobre roles `done` y pago en el periodo legal. Nada nativo lo modela |
| 3 | Bonos, anticipos y descuentos | **Nativa (puntuales) / Extendiendo (masivos o recurrentes)** | Puntuales: `hr.payslip.input` por rol. Recurrentes por contrato: `payroll_contract_advantages` (OCA, probado) o campos propios. Carga masiva por lote (178 establecimientos): asistente propio (DEV-2) |
| 4 | Préstamos con cuotas | **No cubierto** | No existe en OCA/payroll, OCA/hr ni OCA/l10n-ecuador 18.0. Desarrollo propio en `erp_payroll_ec`: `erp.hr.loan` + `erp.hr.loan.line` (cuotas con fecha, importe `Monetary`, estado y FK al rol que la descontó), inyectadas como input en `get_inputs()`/`get_current_contract_dict()`. La cuota se marca pagada al confirmar el rol y se libera al cancelarlo |
| 5 | Contabilización con `l10n_ec` | **Nativa con limitaciones** | `payroll_account`: cuenta debe/haber por regla, impuesto opcional, partner según tipo de cuenta (empleado o tercero de `register_id`), analítica del contrato o de la regla y diario por contrato o lote. Genera **un asiento por rol**, no por lote. Limitaciones: cancelar borra el asiento si el diario no tiene hash (PR #308 lo corrige, aún abierto) y la analítica es 100 % a una sola cuenta. Las cuentas concretas `l10n_ec` se configuran como datos en US-008 |
| 6 | 178 establecimientos | **Extendiendo** | Nada nativo. Propuesta: modelo de establecimiento (o reutilizar `hr.work.location` del núcleo) con su cuenta analítica; empleado o contrato → establecimiento; `contract.analytic_account_id` = analítica del establecimiento, que `payroll_account` ya propaga al asiento. Lotes por establecimiento con un asistente propio. Lo modela DEV-3 en US-007 |
| 7 | Una sola empresa | **Nativa** | Todos los modelos tienen `company_id` y reglas multiempresa |
| 8 | CA-4: rol sin contrato vigente → error en español | **Extendiendo** | Comprobado en el código: `compute_sheet()` sin contrato **no falla**, genera un rol vacío. Hay que heredar `compute_sheet()` en `erp_payroll_ec` (DEV-2) para lanzar `UserError` |
| 9 | Redondeo USD | **Parcial** | `total` es `Monetary` (se redondea al guardar), pero los valores intermedios de la fórmula son `float` sin redondear. Convención para US-008: cada regla redondea su `result` (por ejemplo, una función `round_usd` publicada en `tools`) |

## 7. Tabla de criterios

| Criterio | A · OCA payroll 18.0 | B · Motor propio | C · Odoo Mates |
|---|---|---|---|
| Madurez en 18.0 | Migrado (issue #169 cerrado). `installable`, **Beta**. Se instaló sin errores en nuestro entorno (§5) | Inexistente: todo por construir | 18.0 publicado, sin evaluar a fondo; acaba de cambiar de repositorio |
| Cobertura frente a US-008 | Nativa: reglas, categorías, estructuras, inputs, lotes, reembolso y asiento. Hay que extender: parámetros, mensualizar/acumular, establecimientos y error sin contrato. Falta: préstamos (§6) | Toda a medida | Similar a A (mismo origen) |
| Tests y CI | 35 tests en `payroll` y 3 en `payroll_account`; GitHub Actions tests y pre-commit en verde en `4c71cd4`; codecov | Los nuestros | Sin CI visible |
| Licencia | LGPL-3 (`payroll`, `payroll_account`, `payroll_contract_advantages`, `base_time_parameter`): compatible con LGPL-3 | Propia (LGPL-3) | LGPL-3 |
| Actividad y mantenimiento | OCA, 2 mantenedores, commits mensuales y PR de corrección activos (#308, #320) | Solo nuestro equipo | Una empresa, un mantenedor |
| Dependencias | Solo Community (`hr_work_entry_holidays`, `mail`, `account`, `hr_contract`). Ninguna dependencia Python | Ninguna | Community |
| Riesgo de migración a 19.0 | **Medio**: `payroll` ya está en 19.0 (sobre `hr.version`) y `payroll_account` está en PR. Nuestras extensiones sobre `hr.contract` habrá que llevarlas a `hr.version` | **Alto**: el mismo cambio `hr.contract → hr.version` lo asumimos solos, más todo el motor | Desconocido |
| Coste inicial | Bajo: submódulo + extensiones | Alto: varias historias más solo para igualar el motor | Bajo, pero con riesgo de abandono |

## 8. Decisión propuesta

**Opción A:** adoptar **OCA/payroll 18.0** fijado en
**`4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e`** (2026-09-22, CI tests y pre-commit en verde) e
instalar **`payroll` + `payroll_account`**. Toda la adaptación a Ecuador va en
`addons/erp_payroll_ec`.

- `payroll_contract_advantages`: no instalar de momento. Se decide en US-008 si los ingresos y
  descuentos recurrentes por contrato se modelan con él o con campos propios. Está probado e
  instalable si se necesita (mismo submódulo, sin coste extra).
- `payroll_rule_time_parameter`: **no instalar**. Los parámetros normativos irán en un modelo
  propio con vigencia y fuente normativa, lo que evita añadir OCA/server-tools como submódulo.
  Alternativa válida si el Tech Lead prefiere reutilizar OCA: submódulo `OCA/server-tools` en
  `126afd2a62ec528386285aa753b24c15277d1f15` + `payroll_rule_time_parameter`.
- Se descartan B (coste y riesgo 19.0 mayores sin ventaja funcional: los huecos de A se cubren
  extendiendo), C (repositorio inestable, sin CI ni gobierno comunitario) y D (Enterprise).
- OCA/hr y OCA/l10n-ecuador **no** aportan al motor. Se reconsideran en US-007 para la ficha del
  empleado (dos apellidos, cargas familiares).

## 9. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Módulos en **Beta**: cambios de comportamiento entre commits | Medio | Submódulo fijado a un commit; actualización explícita con `scripts/test.sh erp_payroll_ec` en verde |
| `payroll_account` borra el asiento al cancelar un rol confirmado si el diario no tiene hash; confirmar dos veces podría duplicarlo (PR #308 abierto) | Alto (contabilidad) | Diario de nómina con `restrict_mode_hash_table` activado, o hasta que #308 se fusione, heredar `action_payslip_cancel`/`action_payslip_done` en `erp_payroll_ec` (DEV-2) con test. Revisar #308 al actualizar el commit |
| Un asiento por rol: con cientos de empleados y 178 establecimientos, muchos asientos | Medio (rendimiento y legibilidad) | Aceptable al inicio. Si contabilidad lo exige, agrupar por lote o establecimiento heredando `action_payslip_done` en US-008 |
| Rol sin contrato no da error (devuelve un rol vacío) | Medio | Override de `compute_sheet()` con `UserError` (CA-4) |
| Intermedios `float` en las fórmulas | Medio (céntimos) | Convención de redondeo por regla + tests con importes límite |
| Fórmulas `safe_eval` editables desde la interfaz | Medio (seguridad e integridad) | Edición de reglas solo para `payroll.group_payroll_manager`; las reglas de Ecuador como datos `noupdate` del módulo, con tests |
| 6 tests de OCA dependen de datos demo | Bajo | `test.sh` solo ejecuta `/erp_payroll_ec`. Para validar el submódulo al actualizarlo, usar `TEST_DEMO=1 TEST_TAGS=/payroll,/payroll_account` |
| Migración a 19.0 (`hr.contract` → `hr.version`; `payroll_account` 19.0 sin fusionar) | Medio | Extender lo mínimo `hr.contract`; agrupar los campos propios para migrarlos juntos; seguir #216 y #294 |
| Dependencia de 2 mantenedores OCA | Bajo/medio | Licencia LGPL: si el proyecto se detiene, se puede mantener un fork fijado |
| `_get_parent` de la estructura referencia `hr_payroll.structure_base` (nombre antiguo): sin estructura padre por defecto | Bajo | Definir la estructura base de Ecuador como datos propios en US-008 |

## 10. Plan de integración (tras aprobar el ADR)

1. **DEV-5:** submódulo
   `git submodule add -b 18.0 https://github.com/OCA/payroll.git third_party/payroll` y
   `git -C third_party/payroll checkout 4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e`. Registrar en
   `third_party/README.md`: origen `https://github.com/OCA/payroll`, rama 18.0, commit
   `4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e`, licencia LGPL-3 (`payroll`, `payroll_account`) y
   módulos usados `payroll`, `payroll_account`. Confirmar que `check.sh` excluye `third_party/`
   y reiniciar Odoo para verificar el `addons_path`.
   - El repositorio incluye `hr_payroll_document`, que declara `pypdf` y `fonttools`. **No se
     instala**, así que no hace falta imagen derivada. `requirements.txt` del repositorio no debe
     incorporarse a `pip-audit` como dependencia del entorno.
2. **DEV-3:** esqueleto `addons/erp_payroll_ec` (18.0.1.0.0, LGPL-3) con
   `depends = ["erp_base", "hr_contract", "payroll", "payroll_account"]`. Sin modelos en US-006
   (sin ACL nueva). Los modelos de parámetros, préstamos y establecimiento van en US-007/US-008.
3. **DEV-2:** tests de humo de CA-4 en `erp_payroll_ec` (estructura y reglas creadas en el test)
   y override de `compute_sheet()` para el error sin contrato vigente.
4. Verificación: `bash scripts/test.sh erp_payroll_ec` y `bash scripts/check.sh --all`.
