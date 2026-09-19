# Página: Administración (override de MASTER)

Objetivo: ver de un vistazo los centros, quién entra y con qué rol, dónde se archiva y cuánto se
conserva. Lectura sobre todo; la única escritura es el plazo de retención.

## Layout
- `PageHeader` + `Tabs` (Centros · Usuarios y roles · Almacenamiento · Retención), icono 16 + texto.
  La lista de pestañas **envuelve** en < 480px (`flex-wrap`, `max-w-full`); nunca desborda el
  viewport ni se corta.
- Cada pestaña es una `Table` sin tarjeta alrededor: la tabla ya ordena, la caja sobraría.
- Retención: un bloque por política, `Label` + `Input` numérico (`w-32`) + botón "Guardar" en la
  misma línea; el botón solo se activa cuando el valor cambia.

## Reglas
- Los códigos de rol (`mm_admin`, `site_admin`…) son identificadores: en `Badge outline`, mono,
  sin traducir. Un rol que la API no conoce se marca `warning`, no se oculta.
- Almacenamiento: **nunca** una credencial, ni enmascarada. La tabla muestra solo la configuración
  no secreta; el aviso de arriba lo dice en una línea con `ShieldWarning` 16, sin caja.
- Salud del backend: `Badge` con icono + texto (ok / caído / sin comprobar); nunca solo color.
- Retención en el mínimo legal (365 d): aviso en línea `WarningCircle` 16 `text-warning-text`.
  No es un error: se puede guardar.
- Sin edición de usuarios ni de centros en esta versión (deuda conocida, `GO-LIVE.md` §4): la vista
  no enseña botones que no hacen nada.
- 375: tablas con `overflow-x-auto` (mínimo de MASTER §5). Son tablas de lectura de pocas filas;
  no se convierten en cards.
