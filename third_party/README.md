# Módulos de terceros (`third_party/`)

Módulos de terceros (OCA u otros) **fijados a un commit concreto**. No se editan:
cualquier cambio se hace por herencia desde un módulo propio en `addons/erp_*`.

## Inventario

| Directorio | Origen (URL) | Rama | Commit | Licencia | Módulos usados | Historia |
|---|---|---|---|---|---|---|
| `payroll/` | <https://github.com/OCA/payroll> | `18.0` | `4c71cd42e46a09a7512d92f5c63c0a9f7c26ad3e` (2026-09-22) | LGPL-3 en los manifiestos (`payroll`, `payroll_account`); 4 archivos de `payroll` con cabecera AGPL-3, ver nota | `payroll`, `payroll_account` | US-006 · [ADR-001](../docs/decisiones/ADR-001-motor-nomina.md) |

### `payroll/` (OCA/payroll 18.0)

- **Se instalan solo** `payroll` y `payroll_account` (como dependencias de
  `addons/erp_payroll_ec`). **Licencia:** ambos manifiestos declaran LGPL-3 y
  `payroll_account` no tiene archivos con otra licencia, pero en `payroll` hay 4 archivos con
  cabecera **AGPL-3.0 or later** (comprobado con `grep -rn "AGPL"` el 2026-10-29, commit
  `4c71cd4`):
  - `payroll/wizard/hr_payslip_change_state.py` (línea 3)
  - `payroll/wizard/hr_payslip_change_state_view.xml` (línea 5)
  - `payroll/tests/test_hr_payslip_change_state.py` (línea 3)
  - `payroll/tests/test_hr_payroll_cancel.py` (línea 1)

  El uso es **interno, sin redistribución**: el software no se distribuye ni se ofrece como
  servicio a terceros. Si eso cambiara, revisar las obligaciones de la AGPL-3 para esos
  archivos. Al actualizar el commit, repetir
  `grep -rn "AGPL" third_party/payroll/payroll third_party/payroll/payroll_account`.
- **`requirements.txt` del repositorio OCA: NO se instala** ni se audita con
  `pip-audit`. Solo declara `pypdf` y `fonttools`, que son dependencias de
  `hr_payroll_document` (AGPL-3), un módulo que **no se usa**. Por eso no hace falta
  una imagen derivada de `odoo:18.0`.
- El resto de módulos del repositorio están en el `addons_path` pero **no se
  instalan**. Odoo los lista en Aplicaciones como "No instalado" sin afectar al
  arranque (comprobado con `update_list()` el 2026-10-29). Si se intentara instalarlos:

  | Módulo | Licencia | Estado en este entorno |
  |---|---|---|
  | `payroll_contract_advantages` | LGPL-3 | Instalable (opción a decidir en US-008) |
  | `payroll_rule_time_parameter` | LGPL-3 | No instalable: depende de `base_time_parameter` (OCA/server-tools, no incluido) |
  | `payroll_hr_public_holidays` | AGPL-3 | No instalable: depende de `calendar_public_holiday` (OCA/calendar, no incluido) |
  | `hr_payroll_document` | AGPL-3 | No instalable: Odoo lo bloquea con "External dependency pypdf not installed" (la imagen no trae `pypdf` ni `fonttools`) |

  Antes de instalar cualquiera de ellos, revisar la licencia (AGPL-3) y las dependencias,
  y actualizar esta tabla y el ADR.
- Los tests propios de OCA usan datos demo (`base.res_partner_12`): sin demo dan
  6 errores. Para validar el submódulo (p. ej. al actualizar el commit):
  `TEST_DEMO=1 bash scripts/test.sh payroll,payroll_account` (38 tests, 0 errores el
  2026-10-29). Solo instalación, sin sus tests:
  `TEST_TAGS=-standard bash scripts/test.sh payroll,payroll_account`.

## Convención

- Cada repositorio es un **submódulo git** en `third_party/<repo>/`, con el mismo
  nombre que el repositorio de origen (p. ej. `third_party/l10n-ecuador/`).
- El contenedor monta `third_party/` en `/mnt/third-party` y
  `docker/odoo/entrypoint.sh` añade **automáticamente** al `addons_path` cada
  `third_party/<repo>/` que contenga al menos un módulo (`<repo>/<modulo>/__manifest__.py`).
  No hay que editar `config/odoo.conf` al añadir un repositorio.
- Que un repositorio esté en el `addons_path` no instala nada: solo se instalan
  los módulos declarados en `depends` de los módulos `erp_*`.
- Los módulos de `third_party/` no pasan por `scripts/check.sh` ni por los hooks de
  pre-commit (no son código propio). `pip-audit` (`check.sh --all`) tampoco audita los
  `requirements.txt` de `third_party/`: solo los de los módulos propios. Si un módulo de
  terceros instalado necesita dependencias Python, se declaran en el `requirements.txt` raíz
  (que sí se audita) y se construye una imagen derivada.

## Añadir un repositorio (DEV-5)

```bash
# 1. Añadir el submódulo en la rama 18.0
git submodule add -b 18.0 https://github.com/OCA/<repo>.git third_party/<repo>

# 2. Fijar el commit concreto (el submódulo ya queda fijado al commit actual;
#    para otro commit: cd third_party/<repo> && git checkout <sha>)
git -C third_party/<repo> rev-parse HEAD

# 3. Registrar origen, rama, commit y licencia en la tabla de arriba
#    (licencia: campo "license" de los __manifest__.py, normalmente AGPL-3 o LGPL-3)

# 4. Reiniciar Odoo para recalcular el addons_path y verificar
docker compose restart odoo
docker compose logs odoo | grep "addons paths"
```

Si un repositorio requiere dependencias Python (`requirements.txt` del repo o
`external_dependencies` de sus manifiestos) no incluidas en la imagen `odoo:18.0`,
hace falta una imagen derivada en `docker/`: solicitarlo a DEV-5.

Al clonar el proyecto: `git clone --recurse-submodules <url>` o, en un clon ya
existente, `git submodule update --init --recursive`.

## Actualizar el commit fijado de un repositorio

Ejemplo con `payroll` (igual para cualquier `<repo>`):

```bash
# 1. Traer la rama y elegir el commit (revisar el changelog/PR y que el CI de OCA esté en verde)
git -C third_party/payroll fetch origin 18.0
git -C third_party/payroll log --oneline HEAD..origin/18.0
git -C third_party/payroll checkout <nuevo_sha>

# 2. Reiniciar Odoo y validar: módulos de OCA con sus tests (con demo) y módulos propios
docker compose restart odoo
TEST_DEMO=1 bash scripts/test.sh payroll,payroll_account
bash scripts/test.sh erp_payroll_ec
bash scripts/check.sh --all

# 3. Registrar el nuevo commit en el índice del repo y en la tabla de arriba (y en el ADR si aplica)
git add third_party/payroll third_party/README.md
git submodule status          # debe mostrar <nuevo_sha> sin prefijo "+"
```

Para el `payroll`, revisar también en cada actualización el PR OCA #308 (cancelación de
roles y asientos), ver riesgos en ADR-001.

Si `git` falla por TLS detrás de un proxy/antivirus que inspecciona tráfico, pasar su
CA solo en ese comando (`git -c http.sslCAInfo=<ruta a la CA en PEM> ...`). No guardarla en la
configuración del repositorio ni desactivar la verificación TLS.

## Notas

- `git submodule status` con prefijo `-`: submódulo sin inicializar
  (`git submodule update --init --recursive`). Con prefijo `+`: el checkout no coincide con
  el commit fijado (`git submodule update` lo devuelve al fijado).
- En Windows con `core.autocrlf=true` los archivos del submódulo se extraen con CRLF (el
  `.gitattributes` raíz no se aplica dentro de submódulos). No afecta: Odoo los carga
  igual y `git -C third_party/<repo> status` sigue limpio.
