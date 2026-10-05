# Agente de GÜIDO — Hermes + Telegram

Primera función del agente de operaciones de la marca:

1. **Avisos de compra** — cada orden pagada llega al chat con todos los datos (items, SKU, stock
   que quedó, cliente, entrega, montos). Lo manda **la web**, no el agente:
   `src/lib/telegram/notificar-compra.ts`, disparado desde el webhook de NAVE y desde la red de
   seguridad del GET de `/api/ordenes/[id]` (que también corre el cron de conciliación).
   Idempotente con `ordenes.notificado_telegram`; si falla, se reintenta en el próximo pase.
2. **Stock por chat** — "vendí una remera en la feria" → el agente propone `4 → 3` y aplica
   recién con un "sí". Cada movimiento queda registrado en `movimientos_stock` (quién, cuándo,
   motivo, antes → después) y se puede deshacer.

## Qué hay acá

| Ruta | Qué es |
|---|---|
| `guido_mcp/server.py` | Server MCP `guido` (FastMCP, stdio) — las 7 tools que usa Hermes |
| `guido_mcp/stock.py` | Lógica pura: búsqueda de variantes, propuesta de ajuste, tokens |
| `guido_mcp/supabase_rest.py` | Acceso a Supabase por PostgREST (httpx, service_role) |
| `tests/` | `python -m pytest` (desde `agente/`) |
| `deploy/` | Dockerfile, compose, launcher del MCP, identidad (SOUL/AGENTS) y runbook |

La base: `backend/sql/24_movimientos_stock_y_aviso_telegram.sql` (tabla `movimientos_stock`,
función `ajustar_stock` — atómica, nunca deja stock negativo, cerrada a anon — y el flag del aviso).

## Las tools

| Tool | Tipo | Qué hace |
|---|---|---|
| `estado` | read | Salud: Supabase, variantes, fecha/hora AR |
| `consultar_stock(busqueda)` | read | Stock por variante + SKU, búsqueda libre sin acentos ni género |
| `ventas_recientes(dias)` | read | Órdenes web pagadas |
| `movimientos_recientes(limite, sku)` | read | Últimos ajustes manuales |
| `preparar_ajuste_stock(items, operacion, motivo, nota, quien)` | **dry-run** | Propuesta antes → después + token |
| `preparar_deshacer(movimiento_id, quien)` | **dry-run** | Reversión de un ajuste + token |
| `confirmar_ajuste(token)` | **escribe** | Aplica vía `ajustar_stock`. Sólo tras un "sí" |

## Correr local

```bash
cd agente
pip install -r requirements.txt
python -m pytest
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python -m guido_mcp.server   # stdio
```

## Límite conocido

La vidriera **no lee el stock de Supabase**: decide "vendido" con `soldOut` en `start.js`.
Descontar por Telegram deja la base bien, pero la web no se entera sola. Por eso el aviso de
compra y el agente gritan cuando una variante queda en 0. La solución de fondo (hidratar
`soldOut` desde Supabase) toca `start.js` y está pendiente de decidir.
