# Página: Cola de impresión (override de MASTER)

Objetivo: acumular etiquetas y lanzarlas de golpe, 1 a 1 o en cuadrante.

## Layout (dos columnas ≥1024, apiladas en móvil)
- Izquierda: lista de items en cola (nombre · copias · quitar). Reordenar con botones ↑↓
  además de drag. Las copias se fijan **al añadir** a la cola: el API no admite cambiarlas
  después, así que la fila las muestra pero no las edita. Para cambiarlas, se quita y se
  vuelve a añadir.
- Derecha: panel “Configuración” + vista previa.
  - Impresora: campo de texto libre, recordado en el navegador. **No es un desplegable**:
    el navegador no puede enumerar impresoras. La impresora real la elige el diálogo de
    impresión del sistema; lo que se escribe aquí queda como etiqueta del trabajo
    (`print_jobs.printer_name`) para la trazabilidad.
  - Plantilla: `Select` **agrupado** por “Una etiqueta por página” y “Hoja cuadriculada”.
    No hay un control de “Modo” aparte: la plantilla ya dice cómo se imprime, y tenerlo
    separado permitía elegir un modo que contradecía la plantilla. Una decisión, no dos.
  - “Empezar en la posición N”, solo cuando la plantilla elegida tiene más de una etiqueta
    por hoja (para folios a medio usar).
  - Vista previa: render real de la hoja/etiqueta a escala, paginada.
- Barra inferior fija: “N etiquetas · M páginas” + botón primario “Imprimir”.

## Reglas
- Imprimir → confirma → registra `print_job` con cada item, copias, impresora, usuario → abre impresión.
- Tras imprimir: toast + pregunta “¿Se imprimió bien?” (Sí vacía cola / No mantiene y marca job como fallido).
- Cola persistente por usuario y tenant (sobrevive a recarga).
- Vista previa usa el mismo componente que la impresión (`@media print` sobre el mismo DOM).
