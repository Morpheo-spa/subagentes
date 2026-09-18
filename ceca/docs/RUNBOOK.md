# Runbook de operación

Procedimientos para operar Estampa en producción. Todo comando asume que estás en la raíz de
`ceca/` y que el stack corre con Docker Compose.

**En producción se despliega con el fichero base y nada más.** `docker-compose.dev.yml` ya no se
llama `docker-compose.override.yml` justamente para que Compose no lo cargue solo: publicaba
Postgres, Redis y MinIO, abría el panel de Traefik y arrancaba las imágenes `dev` como root con
`DEBUG=true`. En el servidor:

```bash
docker compose up -d --build            # solo docker-compose.yml
```

Y en local, con las comodidades:

```bash
make up                                  # = docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Antes de cualquier despliegue:

```bash
python scripts/check_env.py .env.production   # falla y no despliegas
```

Ese script rechaza además un entorno de producción con Redis sin contraseña, MinIO con las
credenciales de fábrica, `DEBUG=true` o el proxy sin TLS (§7, §8).

---

## 1. Copia de seguridad

Hay **dos** cosas que respaldar, y perder cualquiera de ellas deja la otra inservible:

1. La base de datos (el registro legal).
2. El almacenamiento de PDF de cada tenant (los ficheros).

Y una tercera que no es una copia sino un secreto: `STORAGE_SECRET_KEY`. Sin ella, las
credenciales de los backends de almacenamiento del cliente no se pueden descifrar.

### Base de datos

```bash
docker compose exec -T postgres \
  pg_dump -U estampa -d estampa --format=custom --compress=9 \
  > backups/estampa-$(date +%F-%H%M).dump
```

Diario, con retención de 30 días, y una copia semanal fuera del servidor. El volcado no incluye
los PDF: son ficheros en el almacenamiento del tenant.

### Ficheros

Depende del backend de cada site (`storage_backends.kind`):

- `local`: respalda el volumen `api_local_storage`.
- `s3` / MinIO: versionado del bucket activado **y** replicación a otra región o proveedor.
- `ftp` / `sftp` / nubes del cliente: el respaldo es responsabilidad del cliente. Debe constar
  por escrito en el contrato; el plazo legal de conservación es suyo.

### Verificación (mensual, no opcional)

Una copia que no se ha restaurado nunca no es una copia. Restaura el último volcado en una base
de datos desechable y comprueba que `documents` tiene el número de filas esperado.

---

## 2. Restauración

```bash
# 1. Parar lo que escribe
docker compose stop api worker

# 2. Base de datos limpia
docker compose exec -T postgres psql -U estampa -d postgres \
  -c "DROP DATABASE IF EXISTS estampa;" -c "CREATE DATABASE estampa OWNER estampa;"

# 3. Restaurar
docker compose exec -T postgres pg_restore -U estampa -d estampa --no-owner \
  < backups/estampa-2026-09-18-0300.dump

# 4. Alinear el esquema (no debería aplicar nada si la copia estaba al día)
docker compose exec api alembic upgrade head

# 5. Arrancar y comprobar
docker compose start api worker
curl -fsS http://localhost/api/v1/../health
```

Después de restaurar, **comprueba la coherencia entre registro y ficheros**: un documento en
estado `ready` cuyo fichero no está en el almacenamiento es una incidencia legal, no un detalle.

```sql
SELECT id, storage_key, storage_backend_id
FROM documents
WHERE status = 'ready' AND withdrawn_at IS NULL
ORDER BY created_at DESC LIMIT 50;
```

Si la copia de la base de datos es más reciente que la del almacenamiento, esos documentos
existen como registro y no como fichero. Se marcan `withdrawn_at` con motivo explícito
(`restauración incompleta`), **no** se borran.

---

## 3. Rotar `STORAGE_SECRET_KEY`

`STORAGE_SECRET_KEY` es la clave Fernet que cifra `storage_backends.config_encrypted`. Rotarla
significa **descifrar con la vieja y volver a cifrar con la nueva**. No es un cambio de variable
de entorno.

Rótala si: alguien que ya no está la tuvo delante, se filtró un fichero de entorno, o han pasado
doce meses.

```bash
# 0. Copia de seguridad reciente y verificada. Sin esto no se empieza.

# 1. Clave nueva
docker compose exec api python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Parar lo que escribe credenciales
docker compose stop api worker

# 3. Recifrar: lee con la clave vieja, escribe con la nueva
OLD_KEY=... NEW_KEY=... docker compose run --rm api python - <<'PY'
import asyncio, os
from cryptography.fernet import Fernet
from sqlalchemy import select
from app.db import SessionLocal
from app.models import StorageBackend

old, new = Fernet(os.environ["OLD_KEY"].encode()), Fernet(os.environ["NEW_KEY"].encode())

async def rotate() -> None:
    async with SessionLocal() as session:
        rows = (await session.execute(select(StorageBackend))).scalars().all()
        for row in rows:
            if row.config_encrypted:
                row.config_encrypted = new.encrypt(old.decrypt(row.config_encrypted))
        await session.commit()
        print(f"recifrados {len(rows)} backends")

asyncio.run(rotate())
PY

# 4. Poner la clave nueva en .env.production y validar
python scripts/check_env.py .env.production

# 5. Arrancar y probar la salud de un backend por tenant desde la API
docker compose up -d api worker
```

Si el paso 3 falla a mitad, **no arranques con la clave nueva**: restaura y repite. Una mezcla de
filas cifradas con dos claves distintas deja backends inaccesibles y el síntoma es
`STORAGE_SECRET_UNREADABLE` en producción.

`JWT_SECRET_KEY` se rota distinto: cambiarla invalida todas las sesiones vivas. Es aceptable, se
avisa, y no hay que recifrar nada.

---

## 4. Barrido de retención manual

El barrido normal lo lanza el worker a la hora `RETENTION_SWEEP_HOUR_UTC`. Para ejecutarlo a
mano — tras una caída del worker, o para un site concreto:

```bash
# Qué caducaría, sin tocar nada
docker compose exec -T postgres psql -U estampa -d estampa -c "
SELECT site_id, count(*) AS vencidos
FROM documents
WHERE expires_at <= now() AND withdrawn_at IS NULL AND status = 'ready'
GROUP BY site_id ORDER BY vencidos DESC;"
```

```bash
# Ejecutar el barrido
docker compose exec api python -c \
  "from app.tasks.retention import sweep_expired; sweep_expired.send()"
```

Reglas que el barrido no rompe, y que hay que respetar también a mano:

- **Nunca se borra un `Document` de la base de datos.** Se retira el fichero del almacenamiento y
  la fila queda con `withdrawn_at` y `withdrawn_reason`. El registro legal sobrevive al PDF.
- El plazo mínimo legal es **un año**; el valor por defecto de Estampa es 365 días. Bajarlo de ahí
  no es una configuración, es un incumplimiento.
- El actor es idempotente: repetirlo no retira dos veces ni pierde trazas.
- Toda retirada deja `AuditLog`. Si un cliente pregunta por un documento que ya no está, la
  respuesta sale de ahí.

Para pausar el barrido de un site, pon su política en `action = 'flag_only'`. No desactives el
worker: también procesa subidas y QR.

---

## 5. Stripe se ha desincronizado

Síntomas: un cliente paga y sigue con el plan viejo, una suscripción cancelada en Stripe sigue
activa en Estampa, o `subscriptions.provider_subscription_id` apunta a algo que Stripe no conoce.

**Stripe es la fuente de verdad del cobro. Estampa es la fuente de verdad de los límites.**
Cuando discrepan, se reconcilia desde Stripe.

```bash
# 1. ¿Está la facturación siquiera encendida?
docker compose exec api python -c \
  "from app.config import get_settings; s=get_settings(); print(s.billing_enabled)"
```

Si devuelve `False`, no hay desincronización: los límites no se aplican y nadie cobra
(ADR-005). Ese es el estado esperado en instalaciones sin facturación.

```bash
# 2. Webhooks fallidos: Stripe Dashboard > Developers > Webhooks > el endpoint > Failed.
#    Reenvíalos desde ahí. Ojo: el manejador NO deduplica por event.id todavia
#    (auditoria E-20). Hoy es inofensivo porque los handlers solo asignan estado,
#    pero reenviar el mismo evento lo reprocesa entero.

# 3. Reconciliar un MM concreto contra Stripe
docker compose exec api python -c \
  "from app.tasks.billing import reconcile_subscription; reconcile_subscription.send('<mm_id>')"
```

Comprobaciones manuales útiles:

```sql
-- Suscripciones activas sin identificador de Stripe: nunca llegaron a crearse allí
SELECT mm_id, plan_code, status FROM subscriptions
WHERE status IN ('active','trialing') AND provider = 'stripe'
  AND provider_subscription_id IS NULL;

-- Periodos caducados hace más de un día: el webhook de renovación no llegó
SELECT mm_id, plan_code, current_period_end FROM subscriptions
WHERE current_period_end < now() - interval '1 day' AND status = 'active';
```

Mientras dure la incidencia, **no bloquees la subida de documentos**. Un albarán que no se puede
archivar por un problema de cobro es un problema legal del cliente causado por nosotros. Si hay
que elegir, se sube el documento y se reclama el cobro después: sube el límite con
`subscriptions.limit_overrides` y deja constancia.

Si la desincronización es masiva (cambio de cuenta de Stripe, migración de precios), apaga
`BILLING_ENABLED`, reconcilia con calma y vuelve a encenderlo. Recuerda que encenderlo sin las
dos claves de Stripe impide arrancar, a propósito.

---

## 6. Comprobaciones rápidas

```bash
docker compose ps                         # ¿qué está vivo?
curl -fsS http://localhost/health         # API
docker compose logs -f --tail=100 api     # errores recientes, con X-Request-ID
docker compose exec redis redis-cli ping  # broker y lista negra de JWT (usa REDISCLI_AUTH)
docker compose exec postgres pg_isready -U estampa
```

Un error que ve un usuario lleva `X-Request-ID`. Pídeselo: con él la traza aparece en los logs.

---

## 7. Certificados TLS: emisión y renovación

Traefik los pide y los renueva solo. Lo que hay que hacer es configurarlo bien una vez y saber
mirar cuando algo no sale.

**Cómo está montado.** `infra/traefik/traefik.yml` (configuración estática del fichero base)
redirige `:80` a `:443` de forma permanente, sirve `websecure` con el resolver `letsencrypt` y
guarda los certificados en el volumen `traefik_acme` (`/letsencrypt/acme.json`). El desafío es
HTTP-01 sobre el entrypoint `web`: Traefik lo atiende antes de aplicar la redirección.

**Requisitos antes de arrancar:**

1. El DNS de `PUBLIC_BASE_URL` apunta al servidor. Sin eso el desafío HTTP-01 no valida.
2. Los puertos 80 **y** 443 llegan al contenedor desde Internet. El 80 no es opcional: es por
   donde se valida el desafío.
3. La dirección de contacto ACME es real. La que viene en el repositorio es `ops@example.com` y
   `check_env.py` la rechaza.

**Poner la dirección de contacto sin tocar un fichero versionado:**

```bash
cp infra/traefik/traefik.yml /etc/estampa/traefik.prod.yml
sed -i 's/ops@example.com/ops@tu-dominio.es/' /etc/estampa/traefik.prod.yml

# en .env.production
TRAEFIK_STATIC_CONFIG=/etc/estampa/traefik.prod.yml

python scripts/check_env.py .env.production   # lee ese mismo fichero y lo valida
docker compose up -d traefik
```

**Primera emisión:** arranca y mira el log. Tarda segundos, no minutos.

```bash
docker compose logs -f traefik | grep -i acme
curl -sSI https://tu-dominio.es/health | head -1      # 200 y sin aviso de certificado
curl -sSI http://tu-dominio.es/health | head -1       # 301 hacia https
```

**Comprobar la caducidad** (Let's Encrypt renueva a los 60 días de los 90; no hay que hacer nada,
pero sí hay que vigilarlo):

```bash
echo | openssl s_client -servername tu-dominio.es -connect tu-dominio.es:443 2>/dev/null \
  | openssl x509 -noout -dates -issuer
```

**Forzar una renovación** (cambio de dominio, certificado corrupto, o el aviso de caducidad llegó
y no se renovó solo):

```bash
# 1. Copia del almacén, por si hay que volver atrás.
docker compose cp traefik:/letsencrypt/acme.json backups/acme-$(date +%F).json

# 2. Borrar el certificado del dominio afectado obliga a pedirlo de nuevo al arrancar.
docker compose stop traefik
docker compose run --rm --entrypoint sh traefik -c 'rm -f /letsencrypt/acme.json'
docker compose up -d traefik
docker compose logs -f traefik | grep -i acme
```

Ojo con el límite de Let's Encrypt: 5 emisiones por dominio y semana. Si estás depurando, apunta
primero al entorno de pruebas añadiendo `caServer:
https://acme-staging-v02.api.letsencrypt.org/directory` bajo `acme:` en tu fichero estático, y
quítalo cuando funcione (los certificados de staging no los valida ningún navegador).

**Si el certificado no sale:** casi siempre es (a) DNS que aún no propaga, (b) el puerto 80
cerrado en el cortafuegos, o (c) `acme.json` con permisos distintos de 600 dentro del volumen.
Mientras tanto Traefik sirve su certificado autofirmado: el sitio responde, el navegador avisa.

---

## 8. Rotar la contraseña de Redis

Redis guarda la lista negra de JWT y es el broker de Dramatiq. Quien lo alcance puede revivir
tokens revocados y encolar `withdraw_document` con cualquier `mm_id`/`site_id`, que el worker
acepta como contexto de superusuario. Por eso lleva `requirepass` obligatorio y no se publica
ningún puerto.

Rótala si: alguien que ya no está la tuvo delante, se filtró un fichero de entorno, o han pasado
doce meses.

La contraseña vive en **dos** sitios que tienen que coincidir: `REDIS_PASSWORD` (la que arranca el
servidor) y la que va dentro de `REDIS_URL` (la que usan API y worker). `check_env.py` compara
las dos y falla si divergen.

```bash
# 0. Contraseña nueva.
NEW=$(python -c "import secrets; print(secrets.token_urlsafe(24))")

# 1. Aceptar las dos a la vez, en caliente, sin reiniciar Redis.
#    requirepass en caliente no expulsa a las conexiones ya autenticadas.
docker compose exec redis redis-cli CONFIG SET requirepass "$NEW"

# 2. Actualizar el entorno: las dos apariciones.
sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$NEW|" .env.production
sed -i "s|^REDIS_URL=redis://:[^@]*@|REDIS_URL=redis://:$NEW@|" .env.production
python scripts/check_env.py .env.production

# 3. Reiniciar quien se conecta. Redis no hace falta: ya tiene la nueva.
docker compose up -d --force-recreate api worker

# 4. Comprobar.
docker compose exec redis redis-cli ping            # PONG (REDISCLI_AUTH lleva la nueva)
docker compose logs --tail=50 worker | grep -i noauth   # vacío
curl -fsS https://tu-dominio.es/health

# 5. Fijar la nueva también en el arranque de Redis, para el próximo reinicio.
docker compose up -d --force-recreate redis
```

El paso 1 antes que el 3 es lo que evita el corte: si reinicias Redis primero, API y worker se
quedan con la contraseña vieja y cada petición que toca la lista negra devuelve 500 — la lista
negra **falla cerrada** a propósito.

**Si te quedas fuera** (`NOAUTH Authentication required` en los logs de la API), la contraseña
efectiva es la que tenga el proceso vivo de Redis; si no la sabes, para el servicio, arráncalo
con la del `.env` y vuelve a empezar por el paso 1:

```bash
docker compose stop redis && docker compose up -d redis
```

Rotar la contraseña **no** invalida nada de lo guardado: la lista negra de JWT y la cola de
Dramatiq sobreviven en el volumen `redis_data`.

