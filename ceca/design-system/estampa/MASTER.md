# Estampa — Design System MASTER

> Fuente de verdad global de UI. Generado con la skill `ui-ux-pro-max` (search.py `--design-system`,
> dials variance 4 · motion 3 · density 7) y afinado a mano donde la base de datos no encajaba.
> Las páginas en `pages/*.md` sobreescriben lo que digan aquí.

## 1. Producto

- Tipo: B2B SaaS de cumplimiento **DeCA** (Documento electrónico de Control Administrativo,
  transporte de mercancías por carretera). Datos → PDF nativo con QR → GUID → archivo → etiqueta.
- Usuarios: personal de planta/oficina con guantes o prisa, sesiones cortas, muchas subidas seguidas.
- Público externo: quien escanea el QR. Sin login, móvil, ruido ambiente, luz mala.
- Idioma: ES por defecto, EN. Todos los textos vía i18n (`errors.json → byCode`, misma norma que Meerkat).
- Stack UI: React 19 + Vite + Tailwind 4 + shadcn/ui (base radix) + TanStack Table/Form + Phosphor Icons.
  Vetos heredados: sin axios, lodash, moment, Redux, class components.

## 2. Estilo

- Elegido: **Minimalism & Swiss Style** (`styles.csv: minimalism-and-swiss-style`).
  Riesgo a11y: bajo. Coste: bajo. Best for: enterprise apps, dashboards, professional tools.
- Descartado: Glassmorphism (primera propuesta del script). Motivo: a11y condicional, blur sobre
  tablas densas y previsualizaciones de PDF, mala impresión. No encaja con un producto de registro.
- Reglas: grid 12 col, bordes 1px, sin sombras salvo overlays, una sola acción primaria por vista,
  radio 6px (no 0px: shadcn por defecto, botones táctiles), nada decorativo.

## 3. Color (tokens semánticos, nunca hex en componentes)

Base: `colors.csv → E-signature / Document Workflow` ("trust navy + signature green + audit trail").

| Rol | Light | Dark | CSS var |
|-----|-------|------|---------|
| Primary | `#1E3A5F` | `#93B4E8` | `--color-primary` |
| On Primary | `#FFFFFF` | `#0B1220` | `--color-on-primary` |
| Secondary | `#2563EB` | `#60A5FA` | `--color-secondary` |
| Accent (éxito / listo) | `#16A34A` | `#4ADE80` | `--color-accent` |
| On Accent | `#052E16` | `#052E16` | `--color-on-accent` |
| Background | `#F8FAFC` | `#0B1220` | `--color-background` |
| Foreground | `#0F172A` | `#E2E8F0` | `--color-foreground` |
| Card | `#FFFFFF` | `#111A2E` | `--color-card` |
| Muted | `#E9EEF5` | `#1E293B` | `--color-muted` |
| Muted Foreground | `#475569` | `#94A3B8` | `--color-muted-foreground` |
| Border | `#CBD5E1` | `#334155` | `--color-border` |
| Destructive | `#DC2626` | `#F87171` | `--color-destructive` |
| Warning (caduca pronto) | `#D97706` | `#FBBF24` | `--color-warning` |
| Ring (focus) | `#1E3A5F` | `#93B4E8` | `--color-ring` |

Estados de documento (color + icono + texto, nunca solo color):

| Estado | Token | Icono Phosphor |
|--------|-------|----------------|
| Subiendo / procesando | `muted-foreground` | `Spinner` |
| Listo | `accent` | `CheckCircle` |
| En cola de impresión | `secondary` | `Printer` |
| Impreso | `primary` | `Tag` |
| Caduca en < 30 d | `warning` | `Clock` |
| Retirado (retención) | `destructive` | `Prohibit` |
| Error | `destructive` | `WarningCircle` |
| Sustituido por revisión | `muted-foreground` | `ArrowUUpLeft` |

Estado de conformidad DeCA, separado del estado del documento porque responde a otra pregunta
("¿está archivado?" frente a "¿sirve como documento de control?"):

| Conformidad | Token | Icono | Texto |
|-------------|-------|-------|-------|
| Conforme | `accent` | `SealCheck` | "Válido como DeCA" |
| Incompleto | `warning` | `PencilSimple` | "Faltan datos" |
| No es un DeCA | `destructive` | `ImageBroken` | "Escaneo: no válido" |
| Sustituido | `muted-foreground` | `ArrowUUpLeft` | "Revisión N" |

Contraste: texto normal ≥ 4.5:1, iconos con significado y bordes de controles ≥ 3:1. Dark mode
opcional, nunca por defecto (anti-patrón detectado por el script). Mismo contraste en ambos modos.

## 4. Tipografía

`typography.csv → Friendly SaaS`. Una sola familia.

- Heading y body: **Plus Jakarta Sans** 400/500/600/700. Fallback `system-ui, sans-serif`.
- Mono (GUID, hash, token): `JetBrains Mono` o `ui-monospace`. GUID siempre en mono, con botón copiar.
- Escala: 12 (solo metadatos, nunca body) · 14 body tablas · 16 body · 18 · 24 h2 · 30 h1. Line-height 1.5.
- Etiqueta física: ver `pages/label-template.md`.

```css
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
```

## 5. Espaciado y layout

Density 7 → escala 8-48: `--space-1..6` = 4 · 8 · 12 · 16 · 24 · 32 · 48.

- App shell: sidebar 240px colapsable a iconos (≥1024) · topbar 56px con selector de tenant + usuario.
- Contenido `max-width: 1280px`, gutters 16 (móvil) · 24 (tablet) · 32 (desktop).
- Breakpoints: 375 · 768 · 1024 · 1440. Tablas → cards en < 768 (`overflow-x-auto` como mínimo).
- Targets táctiles ≥ 44×44. Separación entre acciones ≥ 8px.

## 6. Componentes (shadcn)

| Necesidad | Componente | Regla |
|-----------|-----------|-------|
| Listados | `DataTable` (Table + TanStack) | Checkbox column + action bar flotante para bulk. Sort, filter, paginación server-side. |
| Formularios | `Form` + TanStack Form | Label visible siempre, error junto al campo, helper text. Placeholder ≠ label. |
| Confirmación destructiva | `AlertDialog` | Borrar, retirar, revocar token. Botón destructivo a la derecha, texto con el nombre del objeto. |
| Feedback | `Sonner` toast | Éxito breve (3 s). Error persistente con código y acción. Nunca silencio. |
| Carga | `Skeleton` | Reservar espacio (CLS < 0.1). Sin spinner para < 300 ms. `aria-busy`. |
| Vacío | Empty state propio | Icono + una frase + CTA (“Sube tu primer PDF”). |
| Estado | `Badge` | Siempre icono + texto. |
| Ayuda | `Tooltip` | Nunca única vía de información. |

## 7. Iconos

Phosphor, `weight="regular"`, 20px en UI, 16px en tablas, 24px en nav. Tokens `icon-sm/md/lg`.
Un solo estilo por nivel. Decorativo junto a texto → `aria-hidden`. Botón solo icono → `aria-label`.
Sin emojis. Iconos clave: `UploadSimple`, `File`, `QrCode`, `Printer`, `Tag`, `Copy`, `Clock`, `Prohibit`.

## 8. Motion

Subtle (3/10). 150-250 ms hover/estado, `ease-out`. Entrada de filas: fade 12px, 300 ms.
`prefers-reduced-motion` → estado final inmediato. Nada de animar width/height. Sin parallax.

## 9. Formularios y feedback (ux-guidelines)

- Validación inline al blur, resumen arriba solo si hay > 1 error, foco al primer error.
- Progreso multipaso visible (“2 de 3”) en subida y en asistente de impresión.
- Toda acción exitosa confirma (toast o cambio visual). Toda acción irreversible confirma antes.
- Drag & drop nunca es la única vía (WCAG 2.2): siempre botón “Seleccionar archivos”.

## 10. Accesibilidad

Contraste 4.5:1 · teclado completo · focus visible (ring 2px `--color-ring` offset 2px) · orden de
foco = orden visual · `aria-live="polite"` en cola de subida · zoom no bloqueado · alt en QR
(“Código QR del documento {nombre}”).

## 10 bis. Reglas que impone la norma

Estas no son preferencias de diseño. Salen de la Resolución de 5/06/2026 y no se negocian.

- **Un escaneo nunca se presenta como válido.** Si el PDF no tiene capa de texto, la UI lo dice
  con todas las letras y no ofrece "imprimir etiqueta" como si tal cosa. Se archiva, se marca
  y se ofrece la vía correcta: generar el DeCA desde los datos.
- **El QR va dentro del PDF**, no solo en la etiqueta de papel. La etiqueta es una comodidad
  añadida; el documento tiene que llevarlo embebido.
- **Cargador contractual y transportista efectivo son dos bloques separados y etiquetados.**
  Nunca un genérico "cliente" / "proveedor", ni un solo bloque de "partes".
- **Modificar es crear una revisión.** No hay "editar y guardar". El formulario de cambio pide
  el motivo, y la vista del documento muestra la cadena de revisiones con la vigente arriba.
- **El visor público es la prueba en carretera.** Se diseña para un móvil con mala cobertura y
  prisa: sin app shell, sin login, un toque hasta el PDF.

## 11. Anti-patrones (no hacer)

Glass/blur sobre contenido · dark por defecto · hex en componentes · color como único indicador ·
icon-only sin label · spinner que parpadea · tablas que desbordan · borrar sin confirmar ·
exceso de animación · catálogos (campos DECA, estados, tipos) hardcodeados en el front:
vienen de la API · presentar un escaneo como DeCA válido · editar un DeCA en vez de
revisarlo · enseñar un secreto de storage, ni enmascarado.

## 12. Checklist pre-entrega

- [ ] Sin emojis como iconos; una familia (Phosphor)
- [ ] `cursor-pointer` y hover 150-300 ms en clicables
- [ ] Contraste light 4.5:1 y dark 4.5:1 medidos
- [ ] Focus visible, navegación por teclado completa
- [ ] `prefers-reduced-motion` respetado
- [ ] 375 · 768 · 1024 · 1440 probados, sin scroll horizontal
- [ ] Skeleton reserva espacio; CLS < 0.1
- [ ] Textos por i18n; ningún literal en JSX
