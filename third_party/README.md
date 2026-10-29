# Módulos de terceros (`third_party/`)

Módulos de terceros (OCA u otros) **fijados a un commit concreto**. No se editan:
cualquier cambio se hace por herencia desde un módulo propio en `addons/erp_*`.

## Inventario

| Directorio | Origen (URL) | Rama | Commit | Licencia | Módulos usados | Historia |
|---|---|---|---|---|---|---|
| *(vacío)* | | | | | | |

## Convención

- Cada repositorio es un **submódulo git** en `third_party/<repo>/`, con el mismo
  nombre que el repositorio de origen (p. ej. `third_party/l10n-ecuador/`).
- El contenedor monta `third_party/` en `/mnt/third-party` y
  `docker/odoo/entrypoint.sh` añade **automáticamente** al `addons_path` cada
  `third_party/<repo>/` que contenga al menos un módulo (`<repo>/<modulo>/__manifest__.py`).
  No hay que editar `config/odoo.conf` al añadir un repositorio.
- Que un repositorio esté en el `addons_path` no instala nada: solo se instalan
  los módulos declarados en `depends` de los módulos `erp_*`.
- Los módulos de `third_party/` no pasan por `scripts/check.sh` (no son código propio).

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

## Actualizar un repositorio

```bash
git -C third_party/<repo> fetch origin 18.0
git -C third_party/<repo> checkout <nuevo_sha>
git add third_party/<repo>   # y actualizar el commit en la tabla
```
