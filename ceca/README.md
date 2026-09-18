# Estampa

SaaS multi-tenant para el **registro de albaranes como DeCA** (Documento electrónico de Control
Administrativo). El usuario sube o genera PDF de albarán, la aplicación los archiva con nombre
GUID en el almacenamiento del cliente, incrusta un QR por documento e imprime etiquetas. Quien
escanea el QR ve el documento sin identificarse. Todo queda registrado y sujeto a una política
de retención.

---

## Aviso DeCA: el PDF tiene que ser nativo

> **Un escaneo o una foto de un albarán no es un DeCA válido.**
>
> La Resolución de 5 de junio de 2026 exige que el fichero se genere **digitalmente a partir de
> datos estructurados**. Un flujo de "escanea el albarán de papel y ponle un QR" **no produce un
> documento conforme**, por muy bien que se vea el QR.
>
> Estampa lo resuelve por dos vías (ADR-002 en `docs/DECISIONES.md`):
>
> 1. **Generar** el PDF desde los datos del albarán, con el QR incrustado. Vía conforme.
> 2. **Subir** un PDF nativo ya emitido por el ERP del cliente. Vía conforme si trae todos los
>    campos del art. 6.
>
> Un PDF sin capa de texto se archiva marcado como `not_a_deca`: se conserva, pero la aplicación
> nunca dice que cumple. El detalle normativo está en `docs/DECA.md`.

Fechas que importan: el formato electrónico es **obligatorio desde el 5 de octubre de 2026** en
transporte interior, y los ficheros se conservan **un año como mínimo**.

---

## Arranque en 5 comandos

```bash
cp .env.example .env     # 1. plantilla de entorno
make secrets             # 2. genera JWT_SECRET_KEY, STORAGE_SECRET_KEY (Fernet) y el salt
make up                        # 3. traefik, postgres, redis, minio, api, worker, frontend
make migrate             # 4. alembic upgrade head (crea el esquema y siembra planes y campos DECA)
make seed                # 5. tenant de demostración con usuarios, documentos y política
```

Luego: <http://localhost> (aplicación), <http://localhost:8080> (panel de Traefik),
<http://localhost:9001> (consola de MinIO).

Antes de desplegar a producción, **obligatorio**:

```bash
python scripts/check_env.py .env.production
```

El gate de calidad local, el mismo que ejecuta CI:

```bash
bash scripts/ci.sh
```

---

## Mapa del repositorio

```text
ceca/
  backend/
    app/
      main.py              composición de la app, middlewares, manejadores de error
      config.py            settings; única fuente de entorno
      db.py  deps.py       sesión, contexto de tenant, permisos, scoped_select
      errors.py            DomainError + catálogo de códigos
      security.py          JWT, argon2, tokens de share, cifrado Fernet
      models/              SQLAlchemy 2.x, un fichero por agregado
      schemas/ routers/    Pydantic y HTTP (sin lógica de negocio)
      services/            lógica de negocio, incluido services/storage/
      tasks/               actores Dramatiq
      i18n/                errors.json y deca_fields.json (catálogos en datos)
    alembic/versions/      0001 esquema, 0002 planes, 0003 campos DECA
    tests/                 i18n, aislamiento de tenant, visor público, DECA, config
  frontend/src/            React 19 + Vite + TanStack + Tailwind
  infra/traefik/           configuración estática y dinámica del proxy
  scripts/                 ci.sh, check_env.py, seed_demo.py
  docs/                    DECA.md, DECISIONES.md, PLAN.md, RUNBOOK.md
  design-system/estampa/   fuente de verdad de la UI
```

Puertos locales: aplicación en `80`, panel de Traefik en `8080`, Postgres en `5433`,
Redis en `6380`, MinIO en `9000` / `9001`.

---

## Lo que nunca hace esta aplicación

- Devolver al público una URL del almacenamiento. El PDF se sirve por streaming desde la API.
- Usar el GUID del documento como token del QR. Son secretos distintos y el token es revocable.
- Distinguir un token inexistente de uno revocado: `/v/{token}` responde lo mismo a los dos.
- Borrar un `Document` por retención. Se retira el fichero; el registro legal sobrevive.
- Imprimir sin dejar antes un `PrintJob`. Toda copia queda trazada.
- Consultar una tabla con ámbito de tenant sin filtrar por `mm_id` **y** `site_id`.

---

## Documentación

| Documento | Para qué |
|-----------|----------|
| `CLAUDE.md` | Reglas transversales del repositorio |
| `docs/DECA.md` | Qué exige la norma y de dónde sale cada campo |
| `docs/DECISIONES.md` | ADR numerados. No se revierte uno aceptado sin otro ADR |
| `docs/PLAN.md` | Fases de construcción y estado real |
| `docs/RUNBOOK.md` | Copias, restauración, rotación de claves, retención, Stripe |
| `.claude/rules/*.md` | Reglas por área (arquitectura, backend, BD, frontend, DECA) |
| `design-system/estampa/MASTER.md` | Fuente de verdad de la interfaz |
