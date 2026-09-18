---
paths: ["backend/app/services/deca.py", "backend/app/models/deca.py", "docs/DECA.md"]
---

# DECA - registro de albaranes

## Principio

Los campos obligatorios del albarán **no se hardcodean**. Viven en la tabla
`deca_field_definitions`, se siembran desde `backend/app/i18n/deca_fields.json` y se sirven por
`GET /api/v1/deca/fields`. El frontend construye el formulario a partir de esa respuesta.

Motivo: la norma cambia y el conjunto de campos verificado está en `docs/DECA.md` con su
artículo de origen. Cuando cambie la norma, se cambia el JSON y se añade una migración de
datos. Ni un `if` en el código.

## Validación

- `DecaValidator` valida el `dict` contra las definiciones activas del site: tipo, regex,
  obligatoriedad, rango de fechas.
- Un documento con metadatos incompletos se acepta y se marca `deca_status = "incompleto"`.
  No se bloquea la subida: primero se archiva el PDF, luego se completan los datos.
- `deca_status = "completo"` solo cuando todos los campos `required` del catálogo vigente en la
  fecha de subida están presentes y son válidos.
- Los errores de validación se devuelven por campo: `{field, code, message}`.

## Retención

- El plazo legal por defecto está en `docs/DECA.md` y se siembra como política por defecto.
- Retención cumplida = se retira el **fichero** del storage, el registro permanece con
  `withdrawn_at` y motivo. Un albarán nunca se borra de la base de datos por caducidad.
- Toda retirada queda en `audit_logs`.
