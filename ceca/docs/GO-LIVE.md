# Salida a producción — qué está verificado y qué no

Este documento existe para que nadie despliegue Estampa creyendo que algo se ha
probado cuando no se ha probado. Cada línea dice **cómo** se verificó. Lo que no
se pudo verificar en el entorno de desarrollo está en su propia sección, con lo
que hay que hacer antes del primer despliegue real.

Fecha de la última verificación: 2026-09-18. Rama: `claude/ceca-pdf-qr-manager-uf3ga3`.

## 1. Verificado ejecutándolo de verdad

| Qué | Cómo se verificó |
|-----|------------------|
| Migraciones 0001–0005 contra PostgreSQL 16 | `alembic upgrade head` en una base vacía; ida y vuelta completa (`downgrade base` deja 0 tablas, `upgrade head` vuelve a 5) en una base aparte |
| Sin deriva entre modelos y esquema | `alembic check` en la base migrada: "No new upgrade operations detected" |
| Guardián de correos duplicados (0004) | Sembrados dos usuarios con el mismo correo en dos empresas; la migración aborta con mensaje claro y la versión se queda en 0003 |
| Suite completa sobre PostgreSQL real | 209 tests, `TEST_DATABASE_URL` apuntando a Postgres 16. Misma cifra sobre SQLite con claves foráneas activas |
| Semilla de demo sobre Postgres | `scripts/seed_demo.py`: 1 empresa, 2 centros, 3 usuarios, 4 documentos; idempotente al repetirla |
| Ciclo de vida completo de un albarán | `scripts/smoke.py`: 55 pasos contra el API con Postgres y Redis reales, y los mismos 55 a través del proxy de Vite (el origen que ve el navegador) |
| Sesión: cookie HttpOnly, rotación, blacklist en Redis real, rechazo cross-origin, logout | Pasos de `smoke.py` y `tests/test_auth_cookie.py` |
| Visor público: cabeceras `noindex`, `no-store`, `nosniff`, CSP, `inline`, 404 uniforme, `HEAD` registrado | `smoke.py` y `tests/test_public_viewer.py` |
| Guardarraíl SSRF de storage a través del API real | `smoke.py` con `ALLOW_PRIVATE_STORAGE_ENDPOINTS=false`: el endpoint de metadatos de la nube se rechaza con `STORAGE_ENDPOINT_NOT_PUBLIC` |
| `/health/ready` | 200 con Postgres, Redis y storage arriba; 503 en 31 ms con Redis inalcanzable, sin filtrar el error |
| Barrido de retención, ruta completa | Worker de Dramatiq real contra Redis real; un documento caducado a mano; `python -m app.tasks.scheduler --once`; el worker lo retira, escribe `document.withdrawn_by_retention` con actor de sistema en `audit_logs`, y su QR pasa a 404 |
| Healthcheck de la imagen | Encontrado y corregido: usaba `curl`, que la imagen de runtime no instala, así que habría marcado el contenedor como no sano siempre. Ahora usa Python y pregunta a `/health/live` |
| Fusión de `docker-compose.yml` + `docker-compose.dev.yml` | `docker compose config` (CLI sin demonio): ocho servicios, readiness del API en `/health/ready`, planificador con las mismas restricciones que el resto, solo Traefik publica puertos |
| Frontend | `typecheck`, `lint`, 90 tests unitarios, `npm run build` (bundle de producción) |
| Contrato frontend ↔ backend | `src/lib/contract.test.ts` contra el OpenAPI real del backend: rutas, campos y enumeraciones |
| Gate completo con base real y API en marcha | `DATABASE_URL=… SMOKE_BASE_URL=… bash scripts/ci.sh`: todo en verde, incluidos `alembic check` y la prueba de humo |

## 2. Verificado solo por lectura o por configuración

| Qué | Estado |
|-----|--------|
| Levantar el stack con Docker | **No se ha hecho**: hay CLI de Docker pero no demonio. La configuración resuelve; las imágenes no se han construido ni arrancado |
| `backend/Dockerfile` y `frontend/Dockerfile` | Leídos, no construidos |
| Configuración de nginx del frontend (SPA fallback para `/v/{token}`) | Leída, no ejecutada: nginx no está instalado en el entorno |
| Traefik: TLS con Let's Encrypt, redirección, rate limits, cabeceras | Configuración estática y dinámica escritas y validadas como YAML. **Ningún certificado se ha emitido nunca** |
| Regla del visor `PathPrefix(/v/) && !HeaderRegexp(Accept, text/html)` | Razonada, no probada con Traefik en marcha. Es la que decide si un QR escaneado abre el visor o recibe JSON |
| Stripe | Código y dedup de eventos con tests; nunca contra la API de Stripe. Desactivado por `BILLING_ENABLED=false` |
| Backends de storage S3 y FTP | Adaptadores con tests unitarios; no probados contra un MinIO/S3/FTP real |

## 3. Antes del primer despliegue real

Por este orden. Cada punto tiene su procedimiento en `RUNBOOK.md`.

1. `cp .env.example .env && make secrets`. Poner `PUBLIC_BASE_URL` con `https://` y el
   dominio real, y el correo ACME en la copia de `infra/traefik/traefik.yml` que se
   monte vía `TRAEFIK_STATIC_CONFIG`.
2. `python scripts/check_env.py .env` tiene que decir `deployable`. Rechaza `DEBUG`,
   Redis sin contraseña, MinIO de fábrica, TLS apagado y el correo ACME de ejemplo.
3. `docker compose build` y **mirar que las dos imágenes construyen**. Es lo primero
   que no se ha podido hacer aquí.
4. `make up-prod`. Comprobar `docker compose ps`: `api` tiene que quedar `healthy`
   (su healthcheck pregunta a `/health/ready`) y `scheduler` en marcha.
5. `make migrate` y `make seed` **solo en staging**; en producción, `make migrate` a secas.
6. Escanear un QR con un móvil real contra el dominio real: debe abrir el visor de la
   SPA, no un JSON. Si abre JSON, la regla de Traefik del punto 2 de la tabla anterior
   es la sospechosa.
7. `python scripts/smoke.py https://<dominio> https://<dominio>` contra staging con la
   demo sembrada: 55 pasos en verde.
8. Comprobar el certificado: `openssl s_client -connect <dominio>:443 -servername <dominio>`.
9. Forzar un barrido de retención: `docker compose exec scheduler python -m app.tasks.scheduler --once`
   y ver el resultado en `audit_logs`.
10. Copia de seguridad de Postgres y de `acme.json` antes de dar acceso a nadie.

## 4. Deuda conocida que no bloquea

- No hay endpoint de auditoría (`audit:read` existe como permiso, sin ruta detrás).
- No hay cuota de usuarios ni de centros: los códigos de error existen y nadie los lanza.
- No hay UI de creación ni edición de usuarios: la administración de usuarios es solo
  lectura en el frontend; el API sí lo soporta con el ámbito de administración.
- El PDF subido por el cliente conserva sus metadatos (`/Author`, XMP): es decisión
  deliberada por su valor probatorio; la UI avisa.
- La estadística de accesos no distingue `HEAD` de `GET`.
- Los hallazgos de severidad baja E-16 a E-19 de `SECURITY-AUDIT.md`.
