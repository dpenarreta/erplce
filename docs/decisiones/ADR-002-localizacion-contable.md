# ADR-002 · Localización contable Ecuador: `l10n_ec` + OCA/l10n-ecuador frente a desarrollo propio

- **Estado:** Aceptada (2026-10-30, aprobada por el usuario): se mantiene Odoo 18; Opción C, variante C1 (fork propio con rama 18.0 retroportando EDI de OCA 19.0, fijado como submódulo, con PR a OCA). La creación del fork se hará al iniciar US-003, con confirmación del usuario. Pendiente: política de RUC/cédula con dígito verificador inválido.
- **Fecha:** 2026-10-30
- **Historia:** US-002 (CA-1)
- **Autor:** DEV-3 Datos e Integraciones
- **Afecta a:** `third_party/`, `addons/erp_account_ec` (nuevo), imagen Docker (dependencias Python, solo
  si se adopta la facturación electrónica), US-003, US-004, US-005

---

## 1. Contexto

Odoo 18 Community trae `l10n_ec`, con el plan de cuentas, los impuestos, los tipos de identificación y
los tipos de documento. La facturación electrónica oficial de Odoo (`l10n_ec_edi`, con firma, envío
al SRI y retenciones) es de **Enterprise**, y el proyecto está fijado en Community (perfil §1).

Necesidades:

| Historia | Necesidad |
|---|---|
| US-002 | Empresa con RUC, plan de cuentas, IVA y retenciones de renta e IVA vigentes, tipos de documento e identificación SRI, validación de RUC/cédula con rechazo y mensaje en español |
| US-003 | Factura electrónica: XML SRI, firma XAdES-BES con .p12, envío a recepción y autorización en el ambiente de **pruebas**, RIDE, establecimiento y punto de emisión (178 establecimientos ya modelados en `addons/erp_establishment`) |
| US-004 | Nota de crédito, nota de débito, comprobante de retención, liquidación de compra y guía de remisión electrónicos |
| US-005 | ATS y formularios 103/104 |

## 2. Método de evaluación

Todo se hizo el 2026-10-30, sin modificar el repositorio del proyecto, salvo este documento.

- **`l10n_ec` de la imagen** (`odoo:18.0@sha256:9668abac…`): se copiaron `l10n_ec*` desde
  `/usr/lib/python3/dist-packages/odoo/addons` y se leyeron sus datos CSV/XML y sus modelos.
- **OCA/l10n-ecuador**: se clonaron las ramas 18.0, 17.0 y 19.0 (`git clone --depth 200 -b <rama>`)
  en un directorio temporal. Los manifiestos se leyeron con `ast.literal_eval` y el código clonado no
  se ejecutó en el host:

  | Rama | HEAD evaluado | Fecha HEAD | CI en el HEAD (GitHub checks) |
  |---|---|---|---|
  | 18.0 | `3315e323661b101ea335d922fe5359a542f281cd` | 2025-10-24 | test with Odoo, test with OCB y pre-commit: success |
  | 17.0 | `4a297c3be8c3ef9e874d6d9575c3e27bd77a18f5` | 2026-08-25 | test with Odoo, test with OCB y pre-commit: success |
  | 19.0 | `7e33dc5a8cb36f88f894ae942efe70aaa27c2122` | 2026-10-24 | test with Odoo, test with OCB y pre-commit: success |

- Con `gh api` se consultaron los PR abiertos y cerrados, el issue de migración a 18.0 (#78) y los
  checks de CI.
- **Otras fuentes comunitarias** (búsqueda en GitHub). Se revisaron sin instalarlas:
  `JhonRomero26/l10n-ecuador` rama 18.0 (clonada, solo lectura estática) y
  `joguenco/odoo-l10n-ecuador` 18.0 (inventario por API).
- **Instalación de prueba real** en el entorno Docker del proyecto (§5), con un compose de sobrecarga
  temporal fuera del repositorio. Las BD efímeras y su filestore ya se borraron.
- **`pip-audit`** (imagen `erp-lint` del proyecto) sobre los conjuntos de dependencias candidatos
  (§7).

## 3. Qué trae `l10n_ec` (Odoo 18 Community, en la imagen)

### 3.1 Módulos `l10n_ec*` de la imagen

| Módulo | Versión | Licencia | Depende de | Contenido |
|---|---|---|---|---|
| `l10n_ec` | 18.0.3.9 | LGPL-3 | `base`, `base_iban`, `account_debit_note`, `l10n_latam_invoice_document`, `l10n_latam_base`, `account` | Plan de cuentas, impuestos, grupos de impuesto, tipos de documento e identificación, formas de pago SRI, bancos, informes 103/104 (definición) y campos de establecimiento y punto de emisión en el diario |
| `l10n_ec_stock` | 1.0 | LGPL-3 | `l10n_ec`, `stock` (`auto_install`) | Solo asigna cuentas de valoración de inventario. **No** incluye la guía de remisión |
| `l10n_ec_website_sale` | 1.0 | LGPL-3 | `website_sale`, `l10n_ec` (`auto_install`) | Comercio electrónico; no aplica |

**No existen en Community** `l10n_ec_edi` ni `l10n_ec_edi_stock` (firma, envío al SRI, retenciones
electrónicas y guía de remisión), ni `account_reports`, que es el motor que muestra los informes
103/104. Se comprobó que no están en la imagen.

### 3.2 Impuestos (según datos de `l10n_ec`, `data/template/account.tax-ec.csv`)

Hay 173 impuestos en la plantilla. Al instalar con `l10n_ec_base` (OCA) quedaron **174, de ellos 129
activos** (consultado en la BD de prueba):

| Grupo (`l10n_ec_type`) | Uso | Activos | Inactivos | Observación (según datos de `l10n_ec`) |
|---|---|---|---|---|
| IVA 15 % (`vat15`) | venta / compra | 4 / 13 | 0 | Impuestos por defecto de la empresa: `IVA 15% (411, B)` en venta y `IVA 15% (510, 01 Créd)` en compra |
| IVA 12 % (`vat12`) | venta / compra | 0 | 4 / 13 | Archivados (histórico) |
| IVA 5 % (`vat05`) | venta / compra | 0 / 13 | 4 / 0 | 5 % activo **solo en compras** |
| IVA 8 % (`vat08`) | compra | 1 | 0 | `IVA 8% (510, 01 Créd)` |
| IVA 0 %, no objeto y exento | venta / compra | 11 / 12 | 0 | Bienes, servicios, exportación y reembolsos |
| IVA 13 % y 14 % | — | 0 | 0 | Hay grupos, pero no impuestos |
| Retención renta compras | — (`type_tax_use = none`) | 51 | 24 | Códigos 303…3482 y pagos al exterior 5xx; las tasas sustituidas quedan inactivas (p. ej. 304 8 % inactivo y 304 10 % activo) |
| Retención renta ventas | none | 10 | 0 | 1 %…22 %, sin código de formulario |
| Retención IVA compras | none | 7 (+1 de `l10n_ec_base`: "No procede retención") | 0 | 0/10/20/30/50/70/100 %, códigos 721…731 |
| Retención IVA ventas | none | 6 | 0 | 10…100 %, código 609 |

- **Campos SRI en el impuesto** (`l10n_ec`): `l10n_ec_code_base` y `l10n_ec_code_applied` (casilleros
  del formulario 103/104) y `l10n_ec_code_ats` (código ATS, solo informado en retenciones de renta).
  `l10n_ec_base` (OCA) añade `l10n_ec_xml_fe_code` (código de impuesto del XML electrónico): se
  verificó que **todos los IVA activos lo tienen**.
- **Las retenciones tienen `type_tax_use = none`**: no se pueden elegir en las líneas de factura. En
  Enterprise las usa el asistente de retención de `l10n_ec_edi`. En Community **son datos sin flujo**:
  sin `l10n_ec_withhold` (OCA) o un desarrollo propio no hay forma de emitir ni registrar retenciones.
- Las tasas son datos editables: no hay tasas fijas en código. **Todas deben contrastarse con la norma
  vigente** (LRTI, su reglamento y las resoluciones NAC del SRI sobre porcentajes de retención). En
  particular hay que validar:
  - IVA 15 % como tarifa general y la vigencia de 5 % y 8 %.
  - Por qué el IVA 5 % de venta viene inactivo.
  - Las tasas de retención de renta activas frente a la última resolución.

  Esto se documentará en `docs/normativa/impuestos-ec.md` (CA-3) como "a validar" hasta tener la
  fuente.

### 3.3 Tipos de documento (`l10n_latam.document.type`)

Hay 37 tipos con país EC, de ellos 15 activos. Activos: 01 factura, 02 nota de venta, 03 liquidación
de compra (`purchase_liquidation`), 04 nota de crédito, 05 nota de débito, 07 comprobante de
retención (`withhold`), 08, 09, 11, 12, 15, 16, 19, 20 y 21.

- **No existe el código 06 (guía de remisión).** En Odoo la guía es un documento de inventario
  (`l10n_ec_edi_stock`, Enterprise).
- Formato del número `001-001-000000001`, validado en `_format_document_number` (`l10n_ec`).
- Los tipos de documento permitidos se filtran por tipo de identificación del contacto (tabla ATS,
  `_DOCUMENTS_MAPPING`).
- La secuencia se construye con `l10n_ec_entity` y `l10n_ec_emission` **del diario**: un diario por
  combinación de establecimiento y punto de emisión.

### 3.4 Tipos de identificación y validación

- Activos: **RUC** (`l10n_ec.ec_ruc`, `is_vat`) y **Cédula** (`l10n_ec.ec_dni`) de `l10n_ec`, y
  **Pasaporte**, **ID extranjero** y **VAT** de `l10n_latam_base`. Inactivos ("Deprecated"): pasaporte
  EC y "Unknown".
- **Consumidor final:** no tiene tipo propio. Es RUC `9999999999999`, que el código reconoce
  (`verify_final_consumer`). Los códigos ATS 01–08 se derivan en el código (`PartnerIdTypeEc`).
- **Validación (verificada en la BD de prueba):**

  | Caso | Resultado |
  |---|---|
  | RUC con 12 dígitos | **Rechazado** (`ValidationError`, mensaje en inglés): `l10n_ec` solo exige 13 dígitos para RUC y 10 para cédula |
  | RUC `1791705726001` (empresa) | Válido (también con `python-stdnum` 1.19 de la imagen) |
  | RUC o cédula con dígito verificador incorrecto (`1791705727001`, `1710034066`) | **Se crea**. Solo aparece un **aviso** calculado (`l10n_ec_vat_validation`), porque "SRI has stated that this validation is not required anymore for some VAT numbers" |

  **Consecuencia para CA-4:** "un RUC/cédula inválido se rechaza" **no lo cumple `l10n_ec`**. Hay que
  añadir una restricción en `erp_account_ec` (DEV-2) con `stdnum.ec.ruc` y `stdnum.ec.ci`, salvo la
  decisión del usuario sobre las excepciones (pregunta 3).

### 3.5 Otros datos

- Formas de pago SRI (`l10n_ec.sri.payment`): 8, de ellas 5 activas (01, 15, 16, 19, 20).
- Informes `account.report` **103** y **104** (383 líneas) con etiquetas de casillero en los impuestos.
  En Community **no hay motor para mostrarlos** (`account_reports` es Enterprise): sirven como
  etiquetas, pero no como informe.
- Tras instalar, la empresa sigue siendo "My Company", sin RUC (CA-2 pendiente, como se esperaba).

## 4. OCA/l10n-ecuador y otras fuentes

### 4.1 Inventario por rama

| Módulo | 17.0 | **18.0** | 19.0 | Licencia | Depende de | Python externo | Tests (archivos / métodos, en la rama más reciente) |
|---|---|---|---|---|---|---|---|
| `l10n_ec_base` | 17.0.1.0.2 | **18.0.1.0.0** (`installable`) | 19.0.1.0.0 | AGPL-3 | `l10n_ec`, `account` | — | 3 / 4 |
| `l10n_ec_account_edi` (XML, firma XAdES, SRI, RIDE) | 17.0.1.2.0 | **no existe** | 19.0.1.0.0 (fusionado el 2026-10-24, PR #102) | AGPL-3 | `account`, `account_edi`, `l10n_ec`, `l10n_ec_base` | 17: `cryptography==36.0.0`, `xmlsig==0.1.9`, `xades==0.2.4`, `zeep`. 19: `cryptography>=42`, `pyopenssl>=24.1.0`, `urllib3>=2.0.7`, `xmlsig>=0.1.9`, `xades==0.2.4`, `zeep` | 16 / 60 (19.0) |
| `l10n_ec_withhold` (retenciones de compra y venta + XML) | 17.0.1.0.1 | **no existe** | PR #104 abierto (CI verde, *changes requested*) | AGPL-3 | `l10n_ec_base`, `l10n_ec_account_edi` | — | 4 / 20 (17.0) |
| `l10n_ec_credit_note` (cuentas de NC) | 17.0.1.0.0 | **no existe** | PR #103 abierto (CI verde, *changes requested*) | AGPL-3 | `l10n_ec_account_edi`, `stock_account`… | — | 1 / 9 (17.0) |
| `l10n_ec_delivery_note` (guía de remisión) | PR #79 abierto (*changes requested*) | **no existe** | PR #107 abierto (CI verde) | AGPL-3 | — | — | — |
| `l10n_ec_ats` | — | — | PR #105 abierto (CI tests verde, "unreleased dependencies" en rojo, depende de withhold) | AGPL-3 | `l10n_ec_base`, `l10n_ec_account_edi`, `l10n_ec_withhold` | — | — |
| `l10n_ec_104` / `l10n_ec_103` (prellenado de formularios) | — | — | PR #108 / #109 abiertos (CI verde) | AGPL-3 | `l10n_ec_base`, `account` | — | — |

- **La rama 18.0 solo tiene `l10n_ec_base`.** El issue de migración a 18.0 (#78, abierto desde
  2024-10-06) solo marca `l10n_ec_base`. No hay ningún PR abierto contra 18.0. El de
  `l10n_ec_account_edi` (#84, @JhonRomero26, 62 commits, +20 953 líneas) **se cerró sin fusionar** el
  2026-03-23. En la revisión se reportaron fallos de firma con certificados del BCE.
- **La actividad de la comunidad pasó a 19.0.** En octubre de 2026 se migró `l10n_ec_account_edi`
  (fusionado) y se abrieron PR de withhold, credit_note, delivery_note, ATS, 103 y 104. La rama 18.0
  **se saltó**: su último commit es del 2025-10-24.
- 17.0 está mantenida (último commit 2026-08-25, "Support RUC Provider") y con CI verde.
- Mantenedores efectivos: `celm1990` (revisor), `cormaza`, `jorge-luis-dev`/`joguenco`, `JhonRomero26`
  y Carlos López. Hay pocos revisores y las revisiones son lentas (comentarios en #84).
- **Licencia:** todos los módulos son **AGPL-3**. Se pueden combinar con nuestros módulos LGPL-3, pero
  el conjunto queda sujeto a la AGPL-3 si se ofrece como servicio a terceros. Para uso interno de
  LAARCOURIER, sin redistribución, se aplica el mismo criterio que en ADR-001.

### 4.2 Calidad del código de facturación electrónica de OCA (revisión estática)

| Aspecto | 17.0 / fork 18.0 | 19.0 | Frente al perfil §6 (DEV-3) |
|---|---|---|---|
| Firma XAdES-BES | `xades`/`xmlsig` (etobella, OCA) + `cryptography`. **Convierte el .p12 con `subprocess` + `openssl pkcs12 … -passin pass:<contraseña>`**: la contraseña queda visible en la lista de procesos | Sin `subprocess`: solo `cryptography` | 19.0 es aceptable. 17.0 y el fork no |
| Almacenamiento del .p12 y la contraseña | `sri.key.type.file_content` (Binary) y `password` (**Char en claro**). ACL de **lectura para `base.group_user`**, sin `groups=` en el campo: cualquier usuario interno puede leer la contraseña y el certificado | Igual | **No cumple**: hay que reforzarlo desde nuestro módulo (campo con `groups="base.group_system"` y cifrado) |
| Cliente SRI | `zeep` con `Transport(timeout=30)`, sin reintentos y con `except Exception` genérico. El reintento depende del cron de `account_edi` | Igual; el WSDL se carga en local | Parcial: falta el timeout de conexión y lectura por separado, el registro de cada envío y respuesta (lo tiene en parte `account.edi.document`) y la clasificación de errores |
| Ambientes | `l10n_ec_type_environment` (pruebas / producción) con URL `celcer` / `cel` | Igual | OK |
| Comprobantes | Factura, NC, ND y liquidación (XSD incluidos; también hay XSD de retención y guía) + RIDE QWeb. Retención en `l10n_ec_withhold` | Igual | Guía de remisión: no hay módulo fusionado en ninguna rama |
| Establecimiento y punto de emisión | Del **diario** (`l10n_ec_entity`/`l10n_ec_emission`) | Igual | Con 178 establecimientos hay que crear un diario de venta por establecimiento y punto de emisión (más los de liquidación y retención), o un desarrollo propio (§8) |

### 4.3 Otras fuentes comunitarias (no instaladas)

| Fuente | Qué ofrece en 18.0 | Valoración |
|---|---|---|
| `JhonRomero26/l10n-ecuador` rama 18.0 (fork personal, HEAD `80f32f65` 2026-04-30, AGPL-3/LGPL-3) | `l10n_ec_account_edi` 18.0.1.0.1, `l10n_ec_withhold`, `l10n_ec_credit_note`, `l10n_ec_base`, y además `l10n_ec_ote`, `l10n_ec_partner`, `l10n_ec_bank`, módulos POS y geolocalización | Es la base del PR #84 cerrado. Sin revisión OCA ni checks de CI visibles en el HEAD. Mantiene la conversión con `subprocess` y la contraseña en línea de comandos. El diff de `l10n_ec_account_edi` respecto a 17.0 es de unas 2 200 líneas. Un usuario reporta en #78 que funciona en 18, pero **sin probar conexión real con el SRI**. **No es confiable como dependencia** |
| `joguenco/odoo-l10n-ecuador` 18.0 (repositorio personal de un contribuidor OCA, AGPL-3, último commit 18.0 2026-10-05) | `l10n_ec_account_edi`, `l10n_ec_withhold`, `l10n_ec_base`, `l10n_ec_pos`, `l10n_ec_online_services` | Repositorio personal sin gobierno comunitario. Sirve de referencia, no como dependencia |
| Otros (`huntergps/*` 17, `fcosilva/l10n_ec_ats` sin licencia declarada, `webfixec/l10n_ec_einvoice`, `leninviv/ceos_fix_l10n_ec` sobre Enterprise…) | Módulos sueltos | Se descartan por origen, licencia o versión |

## 5. Instalación de prueba (evidencia)

Se usó un compose de sobrecarga temporal fuera del repositorio que monta solo la copia de
OCA/l10n-ecuador 18.0 (`3315e32`) como `/mnt/third-party`. El `entrypoint.sh` del proyecto la añadió
al `addons_path` (`/mnt/third-party/l10n-ecuador`). El comando reproduce el de `scripts/test.sh`:

```
docker compose -f docker-compose.yml -f docker/compose.test.yml -f <scratchpad>/compose.eval.yml \
  run --rm --no-deps -T odoo odoo -d <BD> -i erp_base,l10n_ec,l10n_ec_base \
  --test-enable --test-tags=/l10n_ec,/l10n_ec_base --stop-after-init \
  --log-level=test --workers=0 --max-cron-threads=0 [--without-demo=all]
```

### 5.1 Corrida 1: BD `eval_us002_l10n`, **sin demo** (como `scripts/test.sh`)

- 54 módulos cargados en 35,34 s. Quedaron `installed`: `erp_base` 18.0.1.0.0, `l10n_ec` 18.0.3.9,
  `l10n_ec_base` 18.0.1.0.0, `l10n_latam_base` y `l10n_latam_invoice_document`. **La instalación no
  tuvo errores.**
- Tests: `odoo.tests.result: 0 failed, 2 error(s) of 6 tests` (RC=1). `l10n_ec` no tuvo errores. Los
  2 errores son de `l10n_ec_base`:
  - `TestModelA.test_l10n_ec_purchase_liquidation`
  - `TestModelA.test_valid_l10n_ec_entity`

  **Causa única:** `self.env.ref("base.demo_company_ec")`, un **dato de demo**. No es un fallo
  funcional: el CI de OCA instala con demo. Es el mismo patrón que en ADR-001.
- En esa BD se comprobaron con `odoo shell` los datos de §3.2–§3.5: recuentos de impuestos, códigos
  XML, tipos de documento e identificación, diarios (`INV` 001-001, `FACTU`, y `LDP` "Liquidación de
  compras" 001-001 que añade `l10n_ec_base`) y la validación de RUC/cédula.
  `l10n_ec_base` deja `tax_calculation_rounding_method = round_globally`.

### 5.2 Corrida 2: BD `eval_us002_l10n_demo`, **con demo** (como el CI de OCA)

- 56 módulos cargados en 43,10 s. RC de Odoo = 0, sin líneas `ERROR` ni `CRITICAL`.
- **`odoo.tests.result: 0 failed, 0 error(s) of 6 tests`**. `odoo.tests.stats`: `l10n_ec` 6 y
  `l10n_ec_base` 10 (incluyen `setUp`/clases).

Ambas BD y su filestore se borraron (`dropdb --force` + `rm -rf /var/lib/odoo/filestore/<BD>`). Se
verificó que solo quedan `erp_dev` y `postgres`, y que no quedan contenedores `run` extra.

**No se instalaron** `l10n_ec_account_edi`, `l10n_ec_withhold` ni `l10n_ec_credit_note`:

- No existen en OCA 18.0.
- Las versiones 17.0 y 19.0 no son instalables en Odoo 18 (versión de manifiesto y API).
- El fork 18.0 es de origen no revisado.
- Ninguna podría cargar en la imagen actual porque **faltan `xmlsig` y `xades`** (comprobado:
  `ModuleNotFoundError`).

## 6. Cobertura frente a las necesidades

| Necesidad | `l10n_ec` (Community) | + OCA `l10n_ec_base` 18.0 | OCA 17.0 / 19.0 (no instalables en 18 sin migrar) | Hueco que queda |
|---|---|---|---|---|
| US-002 plan de cuentas | **Sí** | — | — | — |
| US-002 IVA vigente / histórico | **Sí** (15 % activo, 12 % archivado; datos a contrastar) | Código XML por impuesto | — | Documentar la fuente normativa (CA-3) |
| US-002 retenciones renta e IVA | **Datos sí, flujo no** (`type_tax_use = none`) | "No procede retención" | `l10n_ec_withhold` | Asistente de retención (US-004) |
| US-002 tipos de documento | **Sí** (01, 03, 04, 05, 07…) | Diario de liquidación de compras | — | **Guía de remisión (06)** |
| US-002 tipos de identificación | **Sí** (RUC, cédula, pasaporte, ID extranjero; consumidor final = RUC 9999999999999) | Protege al consumidor final | — | — |
| US-002 RUC/cédula inválido se rechaza | **No** (solo longitud; el dígito verificador es un aviso) | No (omite la validación para RUC con tercer dígito 9) | 19.0 valida el contacto antes de emitir | Restricción propia (`stdnum`) en `erp_account_ec` |
| US-002 datos de empresa (RIMPE, agente de retención, nombre comercial) | No | **Sí** (campos) | — | Valores de LAARCOURIER (CA-2) |
| US-003 XML SRI + firma XAdES-BES .p12 | No | No | **Sí** | Migrar a 18.0 + reforzar la custodia del .p12 |
| US-003 envío a recepción y autorización (pruebas) | No | No | **Sí** (zeep, `celcer`) | Resiliencia y log según el perfil §6 |
| US-003 RIDE | No | No | **Sí** (QWeb) | Marca propia (DEV-4) |
| US-003 establecimiento y punto de emisión | Campos en el diario | Valida 3 dígitos | Del diario | Vincular `erp.establishment` ↔ diarios (178) |
| US-004 NC / ND / liquidación | Tipos de documento | Diario LDP | **Sí** (`l10n_ec_account_edi`) | Migrar |
| US-004 comprobante de retención | Datos | — | **Sí** (`l10n_ec_withhold`, 19.0 en PR) | Migrar |
| US-004 guía de remisión | No | No | Solo en PR (#79 17.0, #107 19.0) | Migrar el PR o desarrollo propio |
| US-005 ATS | Códigos ATS en impuestos y contactos | — | Solo PR 19.0 (#105) | Migrar el PR o desarrollo propio |
| US-005 103 / 104 | Definición `account.report` + etiquetas (sin motor en Community) | — | Solo PR 19.0 (#108, #109) | Migrar los PR o desarrollo propio |

## 7. Dependencias Python y `pip-audit`

Solo hacen falta si se adopta la facturación electrónica de OCA (opciones A y C para US-003 y
siguientes). `l10n_ec` y `l10n_ec_base` **no** tienen dependencias Python externas.

| Paquete | En la imagen `odoo:18.0` | Requisito OCA 19.0 | Última versión en PyPI | Licencia |
|---|---|---|---|---|
| `xmlsig` | **no** | `>=0.1.9` | 1.0.1 (2023-05-10) | LGPL-3 (1.0.x); 0.1.9 era AGPL-3 |
| `xades` | **no** | `==0.2.4` | 1.0.0 (2023-02-08) | LGPL-3 (1.0.0); 0.2.4 es AGPL-3 |
| `zeep` | 4.2.1 (paquete del sistema) | sin versión | 4.3.3 | MIT |
| `cryptography` | 41.0.7 (sistema) | `>=42` | — | Apache/BSD |
| `pyOpenSSL` | 23.2.0 (sistema) | `>=24.1.0` | — | Apache |

`pip-audit` ejecutado el 2026-10-30 con la imagen `erp-lint:0145643a12ca`:

- `cryptography==36.0.0, xmlsig==0.1.9, xades==0.2.4, zeep==4.2.1` (pines de OCA 17.0): **23
  vulnerabilidades en 2 paquetes** (`cryptography` 36.0.0 y `zeep` 4.2.1, PYSEC-2026-2323, que se
  corrige en 4.3.3). **Los pines de 17.0 no deben usarse.**
- `xmlsig==1.0.1, xades==1.0.0, zeep==4.3.3` (con sus dependencias resueltas a la última versión):
  **"No known vulnerabilities found"**.
- Versiones del sistema de la imagen (`cryptography` 41.0.7, `pyOpenSSL` 23.2.0, `urllib3` 2.0.7,
  `zeep` 4.2.1, `lxml` 5.2.1, `requests` 2.31.0): `pip-audit` reporta avisos PyPI en todas. Son
  paquetes de la distribución, que pueden traer parches retroportados que `pip-audit` no detecta.
  **No verificado** contra los avisos de seguridad de la distribución. Afectan ya al entorno actual,
  no solo a esta decisión.

**Consecuencia:** la facturación electrónica exige una **imagen derivada** (DEV-5) con `xmlsig==1.0.1`
y `xades==1.0.0` fijados, y probablemente `zeep==4.3.3`, además de decidir si se actualizan
`cryptography` y `pyOpenSSL` sobre los del sistema (riesgo de conflicto con paquetes de la distro).
Hay que comprobar que la firma funciona con `xades` 1.0.0, porque OCA fija 0.2.4.

## 8. Opciones

### Opción A: `l10n_ec` + módulos OCA 18.0
Hoy solo existe `l10n_ec_base`. Cubre US-002, salvo la validación estricta del RUC y la
documentación normativa. **No cubre nada de US-003/004/005**, y no hay ningún PR 18.0 en curso que lo
vaya a cubrir: la comunidad se saltó 18.0. Como solución completa, A no es viable. Como base de
US-002, sí.

### Opción B: `l10n_ec` + desarrollo propio completo
Módulos `erp_*` propios para XML, firma, cliente SRI, RIDE, retenciones, guía, ATS y 103/104. Control
total, código LGPL-3 y diseño a la medida de 178 establecimientos y del perfil (cifrado, log,
reintentos). Pero hay que rehacer lo que OCA ya resolvió y probó con certificados reales: XSD,
claves de acceso, firma con BCE, Security Data y Uanataca y casuística de NC/ND, reembolsos,
retenciones y RIMPE. Son unas 7 000 líneas de Python solo en EDI y retenciones de OCA, con 80 tests.

### Opción C: híbrida (recomendada)
1. **US-002:** `l10n_ec` + **OCA `l10n_ec_base` 18.0** como submódulo fijado en `third_party/` (no se
   edita) + `addons/erp_account_ec` (datos de empresa, restricción de RUC/cédula, documentación
   normativa).
2. **US-003/US-004:** **retroportar a 18.0 los módulos de OCA 19.0** (`l10n_ec_account_edi`
   fusionado; `l10n_ec_withhold`, `l10n_ec_credit_note` y `l10n_ec_delivery_note` cuando se fusionen
   o desde su PR) y **no** los de 17.0 ni el fork:
   - 19.0 es lo más reciente y revisado (CI verde) y ya eliminó `subprocess` y la contraseña en línea
     de comandos.
   - Su diff con 17.0 es de unas 745 líneas, frente a unas 2 200 del fork 18.0.
   - No usa API exclusiva de 19 en el módulo EDI: `self.env._` ya existe en 18.

   El código retroportado **se modifica**, así que no puede vivir en `third_party/` como copia
   intacta. Dos variantes:
   - **C1 (preferida):** un fork propio de `OCA/l10n-ecuador` con la rama `18.0` + commits de
     migración, como submódulo fijado, y un **PR a OCA 18.0** (contribución y revisión comunitaria).
   - **C2:** copiar los módulos a `addons/` conservando su nombre y licencia AGPL-3 (excepción
     documentada a la convención `erp_`).

   En ambas variantes, el refuerzo propio (custodia del .p12, log de envíos, reintentos y
   clasificación de errores, vínculo con `erp.establishment`) va en un módulo `erp_*` por herencia.
3. **US-005:** retroportar los PR #105/#108/#109 si se fusionan en 19.0 antes de empezar la historia.
   Si no, desarrollo propio usando los códigos ATS y de casillero que ya traen `l10n_ec` y
   `l10n_ec_base`.

### Opción D: subir el proyecto a Odoo 19 Community
Es donde está la actividad de OCA/l10n-ecuador: EDI fusionado y el resto en PR. Queda **fuera de
alcance**: el perfil fija Odoo 18.0 y US-001/006/007 ya están construidas sobre 18. Se menciona porque
cambia el coste de C a medio plazo (pregunta 1).

### Opción E: Odoo Enterprise (`l10n_ec_edi`)
Descartada: el proyecto está fijado en Community.

## 9. Matriz de criterios

| Criterio | A · OCA 18.0 | B · Propio | **C · Híbrida (19.0 → 18.0)** |
|---|---|---|---|
| Disponible e `installable` en 18.0 | Solo `l10n_ec_base` (instalado sin errores, §5) | No aplica | `l10n_ec_base` sí; EDI y retenciones requieren retroportar |
| Cobertura US-002 | Alta (falta la validación estricta del RUC) | Alta (todo propio) | Alta (= A) |
| Cobertura US-003/004 | **Ninguna** | Total, a construir | Alta: factura, NC, ND, liquidación, retención y RIDE ya resueltos en OCA. Guía solo en PR |
| Cobertura US-005 | Ninguna | A construir | PR 19.0 en curso; si no, propio |
| Tests y CI | `l10n_ec_base` 3/4, CI verde | Los nuestros | 60 tests EDI + 20 retención (OCA). CI verde en 19.0; en 18.0 hay que hacerlos pasar nosotros |
| Licencia | AGPL-3 | LGPL-3 | AGPL-3 (OCA) + LGPL-3 (nuestro); uso interno sin problema |
| Actividad y mantenimiento | Rama 18.0 parada desde 2025-10 | Solo nuestro equipo | Comunidad activa en 19.0. La rama 18.0 la mantendríamos nosotros (o vía PR a OCA) |
| Dependencias Python | Ninguna | Las que elijamos (probablemente las mismas `xmlsig`/`xades`) | `xmlsig`, `xades`, `zeep` en imagen derivada (§7) |
| Seguridad (.p12) | — | Diseño propio conforme al perfil | Hay que reforzarla: contraseña en claro y legible por usuarios internos en OCA |
| Riesgo de migración a 19.0 | Bajo | Alto (todo a mano) | **Bajo**: al pasar a 19 se vuelve a los módulos OCA 19.0 originales |
| Coste inicial | Bajo (solo US-002) | **Alto** | Medio: retroportar unas 7 000 líneas con tests + refuerzo |

## 10. Decisión propuesta

**Opción C, variante C1**, en dos fases:

1. **Ahora (US-002):**
   - Adoptar **OCA/l10n-ecuador 18.0 fijado en `3315e323661b101ea335d922fe5359a542f281cd`**
     (2025-10-24, CI verde) e instalar solo **`l10n_ec_base`** como dependencia de
     `addons/erp_account_ec`.
   - En `erp_account_ec`:
     - Datos e *hook* idempotente de la empresa (CA-2).
     - Restricción de RUC/cédula con `stdnum` y mensaje en español (CA-4, según la pregunta 3).
     - `docs/normativa/impuestos-ec.md` con cada impuesto "según datos de l10n_ec" y su estado
       (vigente / histórico / a validar) (CA-3).
   - Los impuestos se mantienen como datos de `l10n_ec`: no se recrean ni se fijan en código.
2. **Al iniciar US-003:**
   - Retroportar `l10n_ec_account_edi` desde **OCA 19.0 (`7e33dc5`)** a una rama 18.0 de un fork
     propio, con el CI de OCA en verde en 18.0, y abrir un PR a OCA 18.0.
   - Imagen derivada con `xmlsig==1.0.1`, `xades==1.0.0` y `zeep==4.3.3`.
   - Refuerzo en un módulo `erp_*`: contraseña y .p12 solo para `base.group_system` y cifrados con
     una clave fuera de la BD, log de envíos, y timeouts y reintentos según el perfil §6.
   - Retención, NC, ND, liquidación y guía en US-004, con el mismo procedimiento sobre los PR de 19.0.

Se descartan:

- A como solución completa (no cubre facturación electrónica y 18.0 no avanza).
- B como punto de partida (duplica trabajo probado con certificados reales).
- El **fork `JhonRomero26` 18.0** (sin revisión, PR cerrado, contraseña en línea de comandos).
- Los **pines de 17.0** (`cryptography==36.0.0` y `zeep` 4.2.1: 23 avisos de `pip-audit`).
- D y E por el stack fijado.

## 11. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| OCA no revisa ni fusiona el retroporte a 18.0: mantenemos la rama solos | Medio | El fork queda fijado. El diff con 19.0 se mantiene mínimo para poder hacer *cherry-pick* de las correcciones de 19.0. Revisión trimestral de 19.0 |
| La firma falla con algunos certificados (BCE, renovados): problema reportado en #84 | Alto (US-003) | Probar en el ambiente de **pruebas** con el .p12 real de LAARCOURIER antes de cerrar US-003. Los tests de OCA incluyen certificados de prueba |
| Contraseña del .p12 en claro y legible por `base.group_user` (OCA) | **Alto** (seguridad) | Herencia en `erp_*`: `groups="base.group_system"` en `password` y `file_content`, cifrado con una clave en variable de entorno (DEV-5). Ni la contraseña ni el contenido se registran en logs |
| Cliente SRI sin reintentos ni clasificación de errores; SRI inestable | Medio | Envoltorio propio: timeouts de conexión y lectura, reintentos con *backoff* solo en la consulta de autorización (idempotente por clave de acceso), log de cada envío y respuesta, y el cron de `account_edi` como reintento de fondo |
| 178 establecimientos → cientos de diarios (venta, liquidación y retención por establecimiento y punto de emisión) | Medio (operación) | Diseño en US-003: generar los diarios desde `erp.establishment` con un asistente (DEV-2), o como alternativa sobrescribir la obtención de `estab`/`ptoEmi`. Requiere la lista de puntos de emisión (pregunta abierta de US-003) |
| `l10n_ec` acepta RUC/cédula con dígito verificador inválido | Medio (CA-4) | Restricción propia con `stdnum`; las excepciones (RUC antiguos, sociedades) según la respuesta del usuario |
| Tasas de `l10n_ec` desactualizadas frente a la norma (p. ej. IVA 5 % de venta inactivo, retenciones) | Medio (fiscal) | Contraste con la norma por el contador. Los cambios se hacen como datos (activar/archivar o editar), con documentación en `docs/normativa/impuestos-ec.md` |
| Guía de remisión, ATS y 103/104 sin módulo fusionado en ninguna rama | Medio | Decidir en US-004/US-005 entre retroportar los PR o desarrollo propio. `account_reports` (Enterprise) no está disponible: los 103/104 se generan con un asistente propio u OCA |
| Dependencias del sistema de la imagen con avisos `pip-audit` (`cryptography` 41, `urllib3` 2.0.7, `zeep` 4.2.1…) | Medio | DEV-5: evaluar los avisos de la distribución y fijar versiones en la imagen derivada. `zeep` ≥ 4.3.3 (PYSEC-2026-2323) |
| Licencia AGPL-3 de OCA | Bajo (uso interno) | Mismo criterio que ADR-001: revisar si el ERP se ofrece a terceros |
| Tests de `l10n_ec_base` dependen de demo | Bajo | `test.sh` solo ejecuta `/erp_account_ec`. Para validar el submódulo: `TEST_DEMO=1 TEST_TAGS=/l10n_ec_base` |

## 12. Plan de integración (tras aprobar el ADR)

1. **DEV-5:**
   - `git submodule add -b 18.0 https://github.com/OCA/l10n-ecuador.git third_party/l10n-ecuador` y
     `git -C third_party/l10n-ecuador checkout 3315e323661b101ea335d922fe5359a542f281cd`.
   - Registrar en `third_party/README.md`: origen, rama 18.0, commit, licencia AGPL-3 y módulo usado
     `l10n_ec_base`.
   - Reiniciar Odoo y comprobar el `addons_path`. El `requirements.txt` de la rama 18.0 está vacío
     de dependencias: no hay imagen derivada en esta historia.
2. **DEV-3:** esqueleto de `addons/erp_account_ec` (18.0.1.0.0, LGPL-3):
   - `depends = ["erp_base", "l10n_ec", "l10n_ec_base"]`.
   - Datos de empresa (con DEV-2 para el *hook* idempotente).
   - `docs/normativa/impuestos-ec.md`.
3. **DEV-2:**
   - *Hook* idempotente de empresa (CA-2).
   - Restricción de RUC/cédula (CA-4).
   - Tests de CA-2 a CA-4 con datos reales (RUC `1791705726001`, nombres con tildes y ñ).
4. Verificación: `bash scripts/test.sh erp_account_ec` y `bash scripts/check.sh --all`.
5. **US-003** (no ahora): rama de retroporte desde 19.0, imagen derivada, refuerzo de seguridad y
   conector, según §10.

## 13. Preguntas para el usuario

1. **Versión de Odoo:** la comunidad ecuatoriana de OCA saltó de 17.0 a 19.0. ¿Se mantiene Odoo 18
   (opción C, retroportando la facturación electrónica) o se valora pasar a 19 antes de US-003? Eso
   implicaría rehacer US-001/006/007 sobre 19 (`hr.contract` → `hr.version` en nómina).
2. **Variante C1 o C2:** ¿se puede crear un fork de `OCA/l10n-ecuador` en la cuenta de GitHub del
   proyecto y proponer el retroporte a OCA (C1)? ¿O se prefiere copiarlo en `addons/` (C2)?
3. **Validación de RUC/cédula:** ¿se rechaza todo RUC/cédula con dígito verificador inválido, o se
   admiten excepciones? `l10n_ec` indica que el SRI ya no exige la validación para algunos RUC.
4. **Fuente normativa de impuestos:** ¿el contador puede confirmar la vigencia de las tasas que trae
   `l10n_ec`, en especial el IVA 5 % y 8 % y las retenciones de renta activas, y facilitar las
   resoluciones a citar?
