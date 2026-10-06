# Deploy de WIDO (Hermes + Telegram)

Mismo esquema que Mercedino (Pelusa): **una imagen = Hermes Agent oficial + el server MCP `guido`**.
Pensado para correr en el **mismo VPS que Pelusa** (Hostinger KVM 1), en un contenedor aparte, con
su propio bot y su propio volumen. Consume poco (sin LibreOffice): límite 768 MB / 0.5 vCPU.

```
Telegram ──► bot de GÜIDO ◄──────────── sendMessage (avisos de compra)
                │                                 ▲
                ▼ (getUpdates)                    │
        Hermes (contenedor `guido`)        Vercel: webhook NAVE / GET ordenes / cron
                │ stdio                           │
                ▼                                 │
        server MCP `guido` ──── PostgREST ───► Supabase ◄┘
```

Los **avisos de compra no pasan por Hermes**: la web los manda directo con el mismo token, así
llegan aunque el agente esté caído. Hermes sólo atiende lo que le escriben.

## 0. Antes (una sola vez, desde el teléfono / dashboards)

1. **Crear el bot** con @BotFather → `/newbot` → guardar el token (en el vault, `Contraseñas.md`).
2. **Tu id de usuario**: escribile a **@userinfobot** y te devuelve tu `Id`.
   ⚠️ **No** es el número que está antes de los `:` en el token — ese es el id **del bot**, y
   Telegram rechaza el aviso con *"the bot can't send messages to the bot"* (pasó en el primer
   deploy, 2026-10-05). Si van a ser varios, conviene un **grupo** con el bot adentro: su id es negativo.
3. **Supabase**: correr la migración `24_movimientos_stock_y_aviso_telegram.sql` (vive en el repo de
   la tienda, [`naza89/gu.idocapuzzi.com`](https://github.com/naza89/gu.idocapuzzi.com), `backend/sql/`).
4. **Vercel** (Production): `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_IDS` (ids separados por coma) →
   redeploy. Desde ahí, cada compra pagada llega al chat.

## 1. En el VPS

```bash
git clone https://github.com/naza89/wido-agent.git /srv/guido/wido-agent && cd /srv/guido/wido-agent

# Secretos (dos archivos, los dos chmod 600)
cp deploy/env.example          deploy/.env          && chmod 600 deploy/.env
cp deploy/supabase.env.example deploy/supabase.env  && chmod 600 deploy/supabase.env
# supabase.env se monta en el contenedor y lo lee el server MCP, que corre como el usuario
# `hermes` (uid 10000): sin este chown, un 600 de root no se puede leer adentro.
chown 10000:10000 deploy/supabase.env
#   .env          → OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USERS (gateway)
#   supabase.env  → SUPABASE_SERVICE_ROLE_KEY (sólo el server MCP; montado read-only)

# Build + arranque
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

## 2. Configurar Hermes (queda en el volumen `guido_hermes_data`)

```bash
# Provider + canal (interactivo)
docker exec -it guido hermes setup
#   → Full setup (NO el Quick: es Nous Portal) · provider: OpenRouter · modelo: un Claude Sonnet · canal Telegram con el token
#   → restringir allowed users a los chat_id del equipo (paso 0.2). Sin esto, cualquiera que
#     encuentre el bot puede mover stock.

# Identidad (fuera del repo, en /opt/data)
docker cp deploy/identidad/SOUL.md   guido:/opt/data/SOUL.md
docker cp deploy/identidad/AGENTS.md guido:/opt/data/AGENTS.md

# Server MCP. Sin --env: las credenciales las toma el launcher de /run/guido/supabase.env.
# (el `echo Y` contesta el "Enable all 7 tools?"; sin stdin lo cancela)
echo Y | docker exec -i guido /opt/hermes/bin/hermes mcp add guido \
  --command /srv/guido/deploy/mcp_launch.sh \
  --connect-timeout 60
#   → debe decir "7/7 tools enabled". Si falla: docker exec guido cat /tmp/guido_mcp_stderr.log

# Recortar toolsets de Telegram: el agente no necesita terminal, archivos ni ejecutar código.
# Además de ahorrar tokens, es seguridad: la service_role está en /run/guido/supabase.env y
# un agente con lectura de archivos o terminal podría leerla.
#   Quedan sólo clarify, todo, session_search + el MCP guido (deploy del 2026-10-05).
for t in web browser terminal file code_execution vision image_gen tts skills memory \
         connections delegation cronjob computer_use; do
  docker exec guido hermes tools disable --platform telegram $t
done

# Memoria inyectada OFF (lección de Pelusa): apagar el toolset `memory` no alcanza, Hermes
# igual mete MEMORY.md/USER.md en cada prompt. En un bot de stock, un número "recordado"
# es un número viejo.
docker exec guido hermes config set memory.memory_enabled false
docker exec guido hermes config set memory.user_profile_enabled false

docker restart guido

# Humo sin Telegram (read-only): debe devolver el stock real por talle
docker exec guido hermes chat -Q -q "Usá consultar_stock para la baby tee blanca. No modifiques nada."
```

## 3. Probar desde Telegram

1. "¿cuánto stock hay de la baby tee blanca?" → lista por talle.
2. "vendí una remera logo rojo M en la feria" → **tiene que preguntar** si es la OVERSIZED o la
   STRASS (las dos encajan).
3. Elegir una → muestra `4 → 3` y pide confirmación. **No** tiene que aplicar nada todavía.
4. "dale" → aplica. "últimos movimientos" → aparece con tu nombre y la nota.
5. "deshacé eso" → propone `3 → 4`, confirmar, y el stock vuelve.
6. Desde otra cuenta de Telegram (no habilitada): el bot no responde.

## Actualizar

```bash
cd /srv/guido/wido-agent && git pull
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
# Si cambió SOUL/AGENTS: repetir los docker cp + docker restart guido
```
