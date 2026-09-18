# Página: Formulario DeCA (override de MASTER)

Objetivo: capturar los datos del artículo 6 para generar un PDF nativo válido, o para
completar los de un PDF ya subido.

## Origen de los campos

**El formulario se construye desde `GET /api/v1/deca/fields`.** Ni un campo hardcodeado en el
front. La respuesta trae `code`, `label_es`, `label_en`, `data_type`, `is_required`, `pattern`,
`choices`, `help_*` y `sort_order`. Si la norma cambia, cambia el catálogo y el formulario se
redibuja solo.

## Layout

Dos columnas en ≥1024, apiladas por debajo. Bloques en este orden, con título visible:

1. **Cargador contractual** — nombre, NIF, domicilio.
2. **Transportista efectivo** — nombre, NIF.
3. **Envío** — origen, destino, fecha del transporte, matrícula.
4. **Mercancía** — naturaleza, peso + unidad.
5. **Observaciones** — opcional, ancho completo.

Los bloques 1 y 2 van visualmente separados (tarjetas distintas, no un `fieldset` compartido):
la norma exige identificación expresa y diferenciada de ambas partes.

Barra fija inferior: resumen de validación ("Faltan 3 campos obligatorios") + botón primario
"Generar DeCA" o "Guardar datos" según el contexto.

## Reglas

- Validación inline al blur. Error junto al campo. Resumen arriba solo con más de un error,
  con enlaces que llevan el foco al campo.
- NIF/CIF se valida con dígito de control real, no con una regex de longitud.
- Campos incompletos **no bloquean**: se guarda como `incompleto` y se avisa. Primero se
  archiva, luego se completa.
- Cada campo muestra su `legal_reference` en un `Tooltip` discreto (el usuario quiere saber por
  qué se lo piden). El tooltip nunca es la única vía: el `help` va debajo del campo.
- En modo revisión el formulario precarga los valores vigentes, exige **motivo del cambio** en
  un `Textarea` al principio, y marca en el diff qué campos cambian.
