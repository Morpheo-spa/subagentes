# Página: Documentos (override de MASTER)

Objetivo: encontrar un PDF, reimprimir su etiqueta, ver su historial, revocar o retirar.

## Layout
- Filtros arriba: búsqueda (nombre original / GUID), estado, fecha subida, caduca antes de, usuario.
- `DataTable` server-side: [ ] · Nombre original · GUID (mono, copiar) · Estado (Badge) · Subido · Caduca ·
  Impresiones (contador) · Acciones (menú `DotsThree`).
- Selección múltiple → action bar flotante: “Añadir a cola de impresión”, “Exportar CSV”, “Retirar”.
- Click en fila → Sheet lateral (no navegación): QR grande 200px, URL pública, metadatos, historial
  (subida, impresiones con impresora/copias/usuario, accesos por QR, retención).

## Reglas
- Reimprimir desde Sheet: elige copias → añade a cola → toast “Añadido a cola (2 copias)”. Nunca imprime directo.
- “Retirar” y “Revocar QR” → AlertDialog con nombre del documento. Retirado sigue listado, en gris, con motivo.
- Caduca < 30 d → Badge warning + fila con borde izquierdo `--color-warning`.
- < 768px: tabla → cards con nombre, estado, caduca y un botón “Imprimir”.
