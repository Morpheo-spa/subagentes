# Plantilla: Etiqueta física (override de MASTER)

Objetivo: escaneable a la primera, legible sin escanear.

## Contenido (de arriba abajo, alineado a la izquierda)
1. QR: mínimo 20×20 mm, quiet zone 4 módulos, corrección de errores M (Q si la etiqueta < 30 mm).
2. Nombre original truncado a 2 líneas, 9-10pt, 600.
3. GUID corto (primeros 8 caracteres) en mono 8pt + fecha subida.
4. Nombre del tenant 7pt, `muted-foreground` (en impresión térmica: negro puro).

## Reglas
- Solo negro sobre blanco. Nada de grises finos en térmicas.
- Tamaños base: 50×30 mm (térmica), 63.5×38.1 mm (A4 3×7), 105×74 mm (A4 2×4). Escala proporcional.
- El QR codifica solo la URL pública corta (`https://<dominio>/v/<token>`), nunca datos del PDF.
- Mismo componente React para vista previa y `@media print`; sin fondos, sin bordes salvo guías opcionales de corte.
