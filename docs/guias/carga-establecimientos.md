# Guía: carga masiva de establecimientos SRI

Esta guía explica cómo cargar (y actualizar) los establecimientos SRI de la empresa con el importador nativo de Odoo y la plantilla `plantilla_establecimientos.csv` (módulo `erp_establishment`, US-007).

Requisito: usuario con permisos de **Ajustes** (administrador). Los demás usuarios internos solo pueden consultar el catálogo.

## 1. Descargar la plantilla

1. Abra la lista de **Establecimientos** (Ajustes > Usuarios y empresas > Establecimientos, o Empleados > Configuración > Establecimientos).
2. En el menú de acciones (engranaje junto al título de la lista) elija **Importar registros**.
3. Pulse **Descargar plantilla** y elija *Plantilla de establecimientos*. Se descarga `plantilla_establecimientos.csv`.

La plantilla trae tres filas de **ejemplo ficticias**: bórrelas y escriba sus establecimientos (una fila por establecimiento).

## 2. Columnas

| Columna | Obligatoria | Valores admitidos | Notas |
|---|---|---|---|
| **Código** | Sí | Número de 1 a 3 dígitos, de `1` a `999` (`000` no es válido) | Se guarda siempre con 3 dígitos: `1` → `001`, `25` → `025`. Es único en la empresa, también frente a establecimientos archivados. |
| **Nombre** | Sí | Texto libre | Por ejemplo `Matriz Quito`, `Agencia Manta`. |
| **Dirección** | No | Texto libre | Calle principal, número y calle secundaria. |
| **Ciudad** | No | Texto libre | Por ejemplo `Quito`, `Guayaquil`. |
| **Provincia** | No | Nombre de una provincia de Ecuador | Escriba el nombre oficial (`Pichincha`, `Guayas`, `Bolívar`, `Cañar`, `Los Ríos`, `Manabí`, `Galápagos`, `Sucumbíos`, `Santo Domingo de los Tsáchilas`...). Se compara sin tildes ni mayúsculas (`Bolívar` = `bolivar`; `Cañar` = `Canar`) y siempre contra las provincias de Ecuador, por lo que los nombres que existen en otros países (p. ej. `Bolívar`) se resuelven a la de Ecuador. También admite el código de provincia de dos dígitos (`17` = Pichincha). Una provincia que no es de Ecuador se rechaza en su fila. |
| **Región** | Sí | `Costa`, `Sierra`, `Amazonía`, `Galápagos` | No distingue mayúsculas (`COSTA` = `costa`) y admite `Amazonia` y `Galapagos` sin tilde. Determina el régimen de décimo cuarto sueldo: Costa y Galápagos → *Costa / Galápagos*; Sierra y Amazonía → *Sierra / Amazonía*. El régimen no se importa: se calcula. |
| **Activo** | No | `Sí` o `Si` (sin tilde, en mayúsculas o minúsculas) o `1` = activo; `No` o `0` = archivado | **Vacío equivale a activo.** `No` o `0` crea el establecimiento archivado. Cualquier otro texto se rechaza en su fila. |

Las columnas se reconocen solas porque la cabecera coincide con los nombres de los campos en español. No cambie los nombres de las columnas.

## 3. Importar

1. Vuelva a **Importar registros** y suba el archivo (CSV o XLSX).
2. Revise que cada columna esté asociada a su campo (Código, Nombre, Dirección, Ciudad, Provincia, Región, Activo).
3. Pulse **Probar**. Si hay errores, Odoo indica la fila y el motivo; corrija el archivo y vuelva a probar.
4. Pulse **Importar**. La importación es todo o nada: si una fila falla, no se crea ningún registro.

## 4. Actualizar establecimientos ya cargados

Reimportar la misma plantilla **crea** registros nuevos (y falla por código duplicado). Para **modificar** establecimientos existentes:

1. En la lista, seleccione los establecimientos y use **Acción > Exportar**.
2. Marque *Quiero actualizar datos (exportación compatible con la importación)* e incluya los campos que quiera cambiar. La exportación añade la columna **ID** (ID externo), que identifica cada registro.
3. Modifique el archivo exportado **sin tocar la columna ID** e impórtelo. Las filas con ID actualizan el registro correspondiente; las filas con ID vacío crean registros nuevos.

Para archivar un establecimiento basta con poner `No` en *Activo* (o usar **Archivar** en la lista). Cuidado: en una actualización, una celda *Activo* vacía también cuenta como activo, por lo que **reactiva** un establecimiento archivado; si quiere que siga archivado, deje `No` (o quite la columna *Activo* del archivo). Archivar no borra su historial ni lo quita de los empleados que ya lo tienen asignado, pero ya no se podrá asignar a nuevos empleados.

## 5. Errores típicos

| Error | Causa | Solución |
|---|---|---|
| *Ya existe un establecimiento con el código 001 en la empresa (incluidos los archivados)* | Código repetido en el archivo (`1` y `001` cuentan como el mismo) o ya cargado, incluidos archivados. | Corrija el código o, si quiere modificar el existente, use la actualización con ID externo (apartado 4). |
| *El código de establecimiento «A1» no es válido: debe ser un número de 1 a 3 dígitos* (o *...el código 000 no existe en el SRI*, o *El código de establecimiento es obligatorio*) | Código con letras u otros signos, vacío, `000` o más de 3 dígitos. Los espacios se ignoran. | Use solo números de 1 a 999. |
| Códigos `1`, `2`... en lugar de `001`, `002` | Excel elimina los ceros a la izquierda al guardar. | No es un problema: el sistema los completa a 3 dígitos. Si prefiere conservarlos, dé formato *Texto* a la columna antes de escribir. |
| Tildes y eñes aparecen como `Ã±`, `Ã³` o la provincia `Bolívar` no se encuentra | El archivo no está en UTF-8 (Excel guarda por defecto en ANSI/Windows-1252). | En Excel use *Guardar como > CSV UTF-8 (delimitado por comas)*, o guarde como XLSX. En el importador puede elegir la codificación en *Opciones de formato*. |
| Todas las columnas en una sola | El separador del archivo es `;` (Excel con configuración regional en español). | En *Opciones de formato* del importador elija el separador `;`, o guarde como XLSX. |
| *Valor desconocido para el campo booleano Activo* | Se escribió un texto distinto de los admitidos (p. ej. `Activo`, `X`). | Use `Sí`, `Si`, `No`, `1` o `0`, o deje la celda vacía (activo). |
| *No se encontró ningún registro coincidente para el nombre '...' en el campo 'Provincia'* | Nombre de provincia mal escrito. | Use el nombre oficial de la provincia de Ecuador (las tildes y mayúsculas no importan). |
| *La provincia «...» (...) no es de Ecuador* | La provincia escrita solo existe en otro país (p. ej. `Antioquia`). | Use una provincia de Ecuador. |
| *Región* sin valor o desconocida | Valor distinto de los cuatro admitidos. | Use `Costa`, `Sierra`, `Amazonía` o `Galápagos` (mayúsculas indiferentes; `Amazonia` y `Galapagos` sin tilde también valen). |
