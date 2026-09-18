# Página: Subida de PDFs (override de MASTER)

Objetivo: subir 1..N PDFs, ver cada uno pasar a “Listo” con su QR, sin esperar al último.

## Layout
- Zona única de drop a ancho completo (min-height 200px, borde discontinuo 2px `--color-border`,
  hover/dragover → borde `--color-secondary` + bg `--color-muted`). Botón “Seleccionar archivos” dentro.
- Debajo: lista de archivos en cola como tabla ligera (nombre original · tamaño · estado · QR · acciones).
- Barra fija inferior con: total, subidos, errores, botón primario “Enviar a impresión (N)”.

## Estados por fila
`En cola` → `Subiendo 42 %` (progress bar por fila) → `Procesando` (hash, GUID, QR, storage) → `Listo`
(QR miniatura 48px + GUID mono + botones Copiar URL / Imprimir / Ver) → `Error` (código + “Reintentar”).

## Reglas
- `aria-live="polite"` anuncia “3 de 8 listos”. No un toast por archivo.
- Solo `.pdf`, tamaño máx. y cuota del plan validados en cliente antes de subir; mensaje junto al archivo.
- Duplicado por hash: aviso amarillo “Ya existe (subido el …)”, opción “Subir igualmente” o “Usar existente”.
- Metadatos CECA (pendientes de definir) en un panel lateral aplicable a todos los seleccionados.
- Salir con subidas en curso → AlertDialog.
