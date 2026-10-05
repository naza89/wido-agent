# Imagen del agente de GÜIDO: Hermes Agent (oficial) + el server MCP `guido`.
#
# Mismo esquema que Mercedino (Pelusa): Hermes lanza el server MCP (stdio) como
# subproceso DENTRO de este contenedor, así que todo vive en una sola imagen.
# El contexto de build es agente/ — NO el repo entero: la web (Next.js) no entra.
#
# Build (desde la raíz del repo):
#   docker compose -f agente/deploy/docker-compose.yml --env-file agente/deploy/.env up -d --build

FROM nousresearch/hermes-agent:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=hermes:hermes . /srv/guido/agente

RUN python3 -m venv /srv/guido/venv \
    && /srv/guido/venv/bin/pip install --no-cache-dir -r /srv/guido/agente/requirements.txt \
    && chmod +x /srv/guido/agente/deploy/mcp_launch.sh \
    && chown -R hermes:hermes /srv/guido

USER hermes
