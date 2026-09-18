# Página: Visor público por QR (override de MASTER)

Objetivo: quien escanea ve el PDF en 1 toque, en móvil, sin login. Nada más.

## Layout
- Sin app shell. Cabecera 48px: logo del tenant (si lo tiene) + nombre original del documento.
- Cuerpo: visor PDF a pantalla completa (pdf.js o `<iframe>` con fallback a “Descargar”).
- Pie: “Abrir / Descargar” (botón primario, 48px alto), fecha de subida, GUID corto.
- Estados: `Cargando` (skeleton página) · `Retirado` (icono `Prohibit`, texto claro, sin detalles internos) ·
  `No encontrado` (mismo diseño que retirado; no revelar si existió).

## Reglas
- Todo tap target ≥ 48px. Fuente base 16px. Sin zoom bloqueado.
- Sin analítica de terceros. Solo registro de acceso propio (fecha, user-agent, IP truncada) para auditoría.
- Cabeceras: `X-Robots-Tag: noindex`, `Content-Disposition: inline`, sin caché en CDN.
