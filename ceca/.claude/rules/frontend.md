---
paths: ["frontend/**"]
---

# Frontend

## Comandos

```bash
cd frontend
npm run dev         # Vite en :5173
npm run lint        # eslint
npm run typecheck   # tsc --noEmit
npx vitest run      # unit
```

## Reglas

- **Lee `design-system/estampa/MASTER.md` antes de tocar UI.** Si la página tiene fichero en
  `design-system/estampa/pages/`, ese manda sobre MASTER.
- Tokens de color en `src/styles/tokens.css`. **Nunca un hex en un componente.**
- El access token vive **en memoria** (contexto de React). El refresh, en cookie httpOnly.
  Nada de `localStorage`.
- Cliente HTTP: `fetch` envuelto en `src/lib/api.ts`. Sin axios.
- Estado de servidor: TanStack Query. Estado local: `useState`/`useReducer`. Sin Redux.
- Textos por i18n (`src/lib/i18n.ts`), ES por defecto. Ningún literal en JSX.
- Los errores de la API llegan como `{code, message}`: se muestra `message` y se registra `code`.
- Todo control interactivo: `cursor-pointer`, foco visible, target >= 44px, transición 150-300ms.
- Iconos Phosphor. Decorativo junto a texto -> `aria-hidden`. Solo icono -> `aria-label`.
- Tabla que no cabe: `overflow-x-auto` como mínimo; en `<768px`, cards.
- Toda acción destructiva pasa por `AlertDialog` con el nombre del objeto en el texto.
- `prefers-reduced-motion` respetado en toda animación.
