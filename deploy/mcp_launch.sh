#!/bin/sh
# Lanzador del server MCP `guido` para Hermes Agent (transporte stdio).
#
# Por qué un wrapper y no `python -m` directo (lección de Mercedino):
#   - Hermes lanza los servers stdio con cwd=/opt/hermes, que tiene sus propios paquetes.
#     El `cd` fija el cwd en agente/ antes del -m, así se importa guido_mcp y no otra cosa.
#   - Hermes le pasa al server sólo PATH/HOME/LANG/…: ni TZ ni nada más llega solo.
#     Las credenciales de Supabase se leen de /run/guido/supabase.env (montado read-only
#     por el compose), así no quedan guardadas en el config.yaml de Hermes.
#   - stderr va a un log: el canal stdio ES el protocolo JSON-RPC, cualquier warning
#     que se cuele por ahí ensucia la conversación.

set -e
export TZ="${TZ:-America/Argentina/Buenos_Aires}"

SECRETOS="${GUIDO_SUPABASE_ENV:-/run/guido/supabase.env}"
if [ -f "$SECRETOS" ]; then
    set -a
    . "$SECRETOS"
    set +a
fi

AGENTE="${GUIDO_AGENTE:-/srv/guido/agente}"
VENV_PY="${GUIDO_PYTHON:-/srv/guido/venv/bin/python}"
LOG="${GUIDO_MCP_LOG:-/tmp/guido_mcp_stderr.log}"

cd "$AGENTE" || exit 1
exec 2>>"$LOG"
exec "$VENV_PY" -m guido_mcp.server
