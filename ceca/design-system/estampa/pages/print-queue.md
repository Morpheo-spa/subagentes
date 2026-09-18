# Página: Cola de impresión (override de MASTER)

Objetivo: acumular etiquetas y lanzarlas de golpe, 1 a 1 o en cuadrante.

## Layout (dos columnas ≥1024, apiladas en móvil)
- Izquierda: lista de items en cola (nombre · copias editables · quitar). Reordenar con botones ↑↓ además de drag.
- Derecha: panel “Configuración” + vista previa.
  - Impresora: `Select` (lista del navegador/servidor según decisión pendiente). Recordar última.
  - Modo: `RadioGroup` “Una etiqueta por página” / “Hoja cuadriculada”.
  - Cuadrante: plantilla (`Select`: A4 2×4, A4 3×8, personalizada) + “Empezar en la posición N” (para hojas a medio usar).
  - Vista previa: render real de la hoja/etiqueta a escala, paginada.
- Barra inferior fija: “N etiquetas · M páginas” + botón primario “Imprimir”.

## Reglas
- Imprimir → confirma → registra `print_job` con cada item, copias, impresora, usuario → abre impresión.
- Tras imprimir: toast + pregunta “¿Se imprimió bien?” (Sí vacía cola / No mantiene y marca job como fallido).
- Cola persistente por usuario y tenant (sobrevive a recarga).
- Vista previa usa el mismo componente que la impresión (`@media print` sobre el mismo DOM).
