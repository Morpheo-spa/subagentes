# Página: Facturación (override de MASTER)

Objetivo: saber cuánto se ha consumido este mes, en qué plan se está y, si procede, cambiarlo.

## Layout
- Dos **secciones** (Consumo, Suscripción), no tarjetas: son texto y una barra. La caja se reserva
  a los planes, que sí se comparan entre sí (`grid` 1 · 2 · 3 columnas en 375 · 768 · 1024).
- Consumo: `h2`, periodo en `muted-foreground`, `Progress` con `aria-label`, y tres líneas de texto
  (documentos, etiquetas, almacenamiento). Sin gráfico: son tres números.
- Cada plan: nombre, precio grande con el intervalo en pequeño, `dl` de límites, un botón.

## Reglas
- `BILLING_ENABLED=false` → la página no revienta ni enseña planes: `EmptyState` con `Info` y una
  explicación. Sin CTA, porque no hay nada que hacer.
- El botón de plan solo existe con `billing:manage`; el plan actual se muestra como "Plan actual",
  deshabilitado. Una sola acción primaria por tarjeta; ninguna compite con otra sección.
- Los límites vienen de la API (`plan.limits`): un límite nuevo que el catálogo estrene se enseña
  con su clave en mono, nunca se oculta.
- Estado de la suscripción: `Badge` `success`/`warning` con `CreditCard` 14 + texto.
- Stripe redirige fuera: antes de `window.location.assign` no hay diálogo; el propio Stripe pide
  confirmación. Un error de checkout es un toast con el mensaje del servidor.
