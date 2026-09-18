# Estampa — frontend

React 19 + Vite + Tailwind 4 + shadcn/ui + TanStack Query/Table/Form + Phosphor.
Sin axios, lodash, moment, Redux ni componentes de clase (`eslint.config.js` lo veta).

```bash
npm install
npm run dev          # Vite en :5173, con proxy a la API
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npx vitest run       # unit + contrato
npm run contract:snapshot   # vuelca el OpenAPI del backend (ver abajo)
```

## Desarrollo: el proxy de Vite no es opcional

El backend deja el refresh token en una cookie **HttpOnly** `estampa_refresh`
(`Path=/api/v1/auth`, `SameSite=strict`) y `POST /auth/refresh` la lee de ahi: no
hay refresh token en el cuerpo de ninguna peticion ni en ninguna respuesta, y el
cliente no lo guarda en ningun sitio. Ademas `POST /auth/refresh` rechaza con
403 `CROSS_ORIGIN_REJECTED` cualquier `Origin` que no sea el `PUBLIC_BASE_URL`
del backend.

Para que eso funcione en desarrollo, la SPA y la API tienen que verse desde el
**mismo origen**: `vite.config.ts` reenvia `/api` y `/v` al backend
(`VITE_DEV_API_PROXY`, por defecto `http://localhost:8000`). El `Origin` que
recibe el backend es entonces el de Vite, asi que en `backend/.env`:

```bash
PUBLIC_BASE_URL=http://localhost:5173   # exactamente la URL con la que abres Vite
ENVIRONMENT=local                       # cookie sin `Secure`: en dev no hay TLS
```

`localhost:5173` y `127.0.0.1:5173` son origenes distintos: abre Vite con la
misma URL que pongas en `PUBLIC_BASE_URL`, o el refresh dara 403.

`/v/:token` es a la vez la pagina del visor publico (SPA) y la ruta JSON del
backend. El proxy lo resuelve por `Accept`: una navegacion (`text/html`) la sirve
Vite; el JSON y el PDF que pide esa pagina van al backend.

## Sesion

- Access token **solo en memoria** (`src/lib/auth.tsx`). Nada en `localStorage`.
- Refresh token: **en ninguna parte del cliente**. Viaja en la cookie HttpOnly y
  por eso `src/lib/api.ts` manda `credentials: 'include'` en todas las peticiones.
- **La sesion sobrevive a recargar**: al arrancar, `AuthProvider` hace
  `POST /auth/refresh` (sin cuerpo). 200 → hay sesion y se cargan los sites; 401
  (o cualquier otro fallo) → `anonymous` y a `/login`. Mientras tanto el estado
  es `loading` y las rutas protegidas pintan un skeleton.
- Cualquier 401 en una peticion (`TOKEN_EXPIRED`, `TOKEN_REVOKED`,
  `SESSION_STALE`...) dispara **un** refresh compartido (`refreshOnce`) y **un**
  reintento. Si el refresh tambien falla, se cierra la sesion local.
  `SESSION_STALE` (cambiaron rol, membresia o activacion) no tiene trato
  especial: el refresh devuelve los permisos nuevos.
- `POST /auth/logout` va sin cuerpo: el backend revoca bearer y cookie.

## Contrato con el backend

`src/lib/openapi.snapshot.json` es el OpenAPI que sirve el backend **hoy**, y
`src/lib/contract.test.ts` lo contrasta con el cliente:

- cada ruta de `src/lib/routes.ts` existe en el snapshot con ese metodo;
- cada campo que el frontend tipa en `src/lib/types.ts` existe en el schema del
  backend con ese nombre (`fieldsOf<T>` obliga, en tiempo de compilacion, a que
  la lista sea exactamente la de la interfaz);
- los enumerados que la UI pinta (estados, origenes, tipos de storage...) son
  los mismos;
- `TokenPair` no lleva `refresh_token` y el cliente no declara ningun `HEAD`.

**Cuando cambie el backend, regenera el snapshot** y vuelve a pasar los tests:

```bash
npm run contract:snapshot   # equivale a:
# cd ../backend && .venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > ../frontend/src/lib/openapi.snapshot.json
npx vitest run src/lib/contract.test.ts
```

Importar `app.main` necesita configuracion: `pydantic-settings` lee
`backend/.env`; si no existe, exporta `DATABASE_URL`, `REDIS_URL`,
`JWT_SECRET_KEY`, `STORAGE_SECRET_KEY` y `ACCESS_LOG_IP_SALT` con valores de
relleno de la longitud minima.

Los codigos de error **no se traducen en el cliente**: se muestra
`detail.message` (ya viene en el idioma de `Accept-Language`) y se registra
`detail.code`. Las unicas comparaciones por codigo son los avisos de subida
(`DUPLICATE_DOCUMENT`, `DOCUMENT_IS_A_SCAN`, `DOCUMENT_METADATA_VISIBLE`) y
`DECA_FIELD_REQUIRED` en la validacion.

## Reglas de siempre

`.claude/rules/frontend.md`, `.claude/rules/i18n.md` y
`design-system/estampa/MASTER.md`. En corto: cero literales en JSX (ES y EN con
las mismas claves), ningun hex fuera de `src/styles/tokens.css`, Phosphor, visor
publico identico para inexistente/revocado/retirado, y un escaneo nunca se
presenta como DeCA valido.
