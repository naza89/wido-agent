"""
Server MCP `guido` — las tools del agente de GÜIDO CAPUZZI (Hermes + Telegram).

Primera función: control de stock y lectura de ventas. Los avisos de compra NO pasan
por acá: los manda la web directo a Telegram al confirmarse el pago
(`src/lib/telegram/notificar-compra.ts`), para que no dependan de que el agente esté vivo.

Regla de oro (igual que Mercedino): toda escritura es dry-run → token → confirmar.
    preparar_ajuste_stock / preparar_deshacer  →  propuesta + token  (no escribe)
    confirmar_ajuste(token)                    →  aplica
El agente NUNCA llama confirmar_ajuste sin un "sí" explícito (está en su SOUL/AGENTS).

Transporte stdio: Hermes lo lanza como subproceso (ver agente/deploy/mcp_launch.sh).

    python -m guido_mcp.server          (con cwd = agente/)

Variables: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GUIDO_TOKEN_TTL (default 600 s).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from guido_mcp.stock import AjusteInvalido, LineaAjuste, Propuesta, TokenStore, armar_propuesta, filtrar
from guido_mcp.supabase_rest import ErrorSupabase, Supabase

mcp = FastMCP("guido")

TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
_RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_RE_SKU = re.compile(r"^[A-Z0-9/\-]{3,50}$")

_tokens = TokenStore(int(os.environ.get("GUIDO_TOKEN_TTL", "600")))
_db: Supabase | None = None


def _supabase() -> Supabase:
    # Diferido: si faltan las variables, falla la tool con un mensaje claro en vez de
    # tumbar el server entero al arrancar (y Hermes reportando "Connection closed").
    global _db
    if _db is None:
        _db = Supabase()
    return _db


def _hora_ar(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ_AR).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


def _error(msg: str) -> dict:
    return {"ok": False, "error": msg}


# ── Lectura ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def estado() -> dict:
    """Chequeo de salud: conexión con Supabase, cuántas variantes hay y qué hora es en Argentina."""
    ahora = datetime.now(TZ_AR)
    try:
        n = len(_supabase().variantes())
        return {"ok": True, "supabase": "ok", "variantes": n, "hoy": ahora.strftime("%Y-%m-%d"), "hora": ahora.strftime("%H:%M")}
    except ErrorSupabase as e:
        return {"ok": False, "supabase": str(e), "hoy": ahora.strftime("%Y-%m-%d")}


@mcp.tool()
def consultar_stock(busqueda: str = "") -> dict:
    """Stock actual por variante (producto + colorway + talle → SKU).

    `busqueda` en lenguaje natural, sin acentos ni mayúsculas: "remera logo rojo m",
    "jean japones suelto", "baby tee blanca". Vacío = todo el catálogo.
    Usala SIEMPRE antes de preparar un ajuste, para obtener el SKU exacto. Si hay más
    de una variante que encaja, preguntá cuál antes de seguir."""
    try:
        variantes = _supabase().variantes()
    except ErrorSupabase as e:
        return _error(str(e))
    encontradas = filtrar(variantes, busqueda)
    return {
        "ok": True,
        "busqueda": busqueda,
        "cantidad": len(encontradas),
        "variantes": [
            {
                "sku": v["sku"],
                "producto": v["producto"],
                "colorway": v.get("colorway"),
                "talle": v.get("talle"),
                "stock": v.get("stock"),
                "pieza_unica": bool(v.get("one_of_one")),
                "activo": v.get("activo", True),
            }
            for v in encontradas
        ],
        "nota": None if encontradas else "Sin coincidencias. Probá con menos palabras o con consultar_stock() vacío.",
    }


@mcp.tool()
def movimientos_recientes(limite: int = 10, sku: str = "") -> dict:
    """Últimos ajustes manuales de stock (quién, cuándo, motivo, antes → después). Opcional: filtrar por SKU.
    Las ventas web no aparecen acá: para eso está ventas_recientes."""
    sku = sku.strip().upper()
    if sku and not _RE_SKU.match(sku):
        return _error(f"SKU con formato inválido: {sku!r}")
    try:
        filas = _supabase().movimientos(max(1, min(int(limite), 50)), sku)
    except ErrorSupabase as e:
        return _error(str(e))
    for f in filas:
        f["cuando"] = _hora_ar(f.pop("created_at", None))
    return {"ok": True, "movimientos": filas}


@mcp.tool()
def ventas_recientes(dias: int = 7) -> dict:
    """Órdenes web pagadas en los últimos `dias` días (número, fecha, total, cliente, items, estado de envío)."""
    dias = max(1, min(int(dias), 90))
    try:
        filas = _supabase().ventas(dias)
    except ErrorSupabase as e:
        return _error(str(e))
    ventas = []
    total = 0
    for o in filas:
        cli = o.get("clientes") or {}
        total += int(o.get("total_centavos") or 0)
        ventas.append({
            "orden": o.get("numero_orden"),
            "pagada": _hora_ar(o.get("pagado_at")),
            "total_ars": round((o.get("total_centavos") or 0) / 100),
            "estado": o.get("estado"),
            "envio": o.get("tipo_envio"),
            "estado_envio": o.get("estado_envio"),
            "nro_envio_oca": o.get("nro_envio_oca"),
            "cliente": " ".join(x for x in (cli.get("nombre"), cli.get("apellido")) if x),
            "items": [
                f'{i.get("cantidad")}× {i.get("nombre_producto")} — {i.get("color")} · talle {i.get("talle")}'
                for i in (o.get("items_orden") or [])
            ],
        })
    return {"ok": True, "dias": dias, "cantidad": len(ventas), "total_ars": round(total / 100), "ventas": ventas}


# ── Mutación (dry-run → token → confirmar) ──────────────────────────────────────

@mcp.tool()
def preparar_ajuste_stock(items: list[dict], operacion: str, motivo: str, nota: str = "", quien: str = "") -> dict:
    """Prepara un ajuste de stock SIN aplicarlo. Devuelve la propuesta (antes → después) y un `token`.

    - `items`: [{"sku": "REM-LOGO-NRO-M", "cantidad": 1}, ...] — SKUs exactos de consultar_stock.
    - `operacion`: "descontar" o "sumar".
    - `motivo`: "venta_manual" (descontar), "reposicion" o "devolucion" (sumar), "correccion" (cualquiera).
    - `nota`: contexto libre ("feria del sábado", "le vendí a Juli", precio cobrado, etc.).
    - `quien`: el nombre de quien lo pide en el chat.

    Mostrale la propuesta a la persona y esperá un "sí" explícito. Recién ahí llamá
    confirmar_ajuste(token). Si dice que no o cambia algo, prepará una nueva."""
    try:
        variantes = {v["sku"]: v for v in _supabase().variantes()}
        propuesta = armar_propuesta(items, operacion, motivo, variantes, nota=nota, actor=quien)
    except AjusteInvalido as e:
        return _error(str(e))
    except ErrorSupabase as e:
        return _error(str(e))
    token = _tokens.guardar(propuesta)
    return {
        "ok": True,
        "token": token,
        "vence_en_min": _tokens.ttl // 60,
        "propuesta": propuesta.resumen(),
        "nota": "Dry-run: no se aplicó nada. Pedí confirmación y llamá confirmar_ajuste(token).",
    }


@mcp.tool()
def preparar_deshacer(movimiento_id: str, quien: str = "") -> dict:
    """Prepara la reversión de un ajuste manual anterior (el id sale de movimientos_recientes).
    Mismo circuito: devuelve propuesta + token, y se aplica con confirmar_ajuste(token)."""
    movimiento_id = movimiento_id.strip()
    if not _RE_UUID.match(movimiento_id):
        return _error("movimiento_id inválido — copialo de movimientos_recientes")
    try:
        db = _supabase()
        mov = db.movimiento(movimiento_id)
        if not mov:
            return _error("no existe ese movimiento")
        if mov.get("revierte_a"):
            return _error("ese movimiento ya es una reversión; para volver atrás prepará un ajuste nuevo")
        if db.ya_revertido(movimiento_id):
            return _error("ese movimiento ya fue deshecho")
        variante = next((v for v in db.variantes() if v["sku"] == mov["sku"]), None)
    except ErrorSupabase as e:
        return _error(str(e))
    if not variante:
        return _error(f"la variante {mov['sku']} ya no existe")

    delta = -int(mov["delta"])
    linea = LineaAjuste(
        sku=mov["sku"], producto=variante["producto"], colorway=variante.get("colorway") or "",
        talle=variante.get("talle") or "", delta=delta, stock_actual=int(variante.get("stock") or 0),
        one_of_one=bool(variante.get("one_of_one")),
    )
    if linea.stock_resultante < 0:
        return _error(f"no se puede deshacer: hoy hay {linea.stock_actual} de {mov['sku']} y habría que restar {-delta}")
    propuesta = Propuesta(
        motivo="correccion",
        nota=f"deshace el movimiento del {_hora_ar(mov.get('created_at'))} ({mov['motivo']})",
        actor=quien.strip(),
        lineas=[linea],
        revierte_a=movimiento_id,
    )
    token = _tokens.guardar(propuesta)
    return {"ok": True, "token": token, "vence_en_min": _tokens.ttl // 60, "propuesta": propuesta.resumen()}


@mcp.tool()
def confirmar_ajuste(token: str) -> dict:
    """Aplica una propuesta de preparar_ajuste_stock / preparar_deshacer.
    SOLO después de que la persona confirmó explícitamente ("sí", "dale", "confirmá").
    El token sirve una vez y vence a los 10 minutos."""
    propuesta = _tokens.tomar(token)
    if propuesta is None:
        return _error("token inexistente, ya usado o vencido — prepará el ajuste de nuevo")

    aplicados, fallidos = [], []
    for linea in propuesta.lineas:
        try:
            r = _supabase().ajustar_stock(
                linea.sku, linea.delta, propuesta.motivo, propuesta.nota, propuesta.actor, propuesta.revierte_a,
            )
            aplicados.append({**r, "producto": linea.producto, "talle": linea.talle})
        except ErrorSupabase as e:
            fallidos.append({"sku": linea.sku, "error": str(e)})

    avisos = []
    for a in aplicados:
        if a.get("stock_despues") == 0:
            avisos.append(f"{a['sku']} quedó en 0: marcarlo vendido en la web (soldOut en start.js).")
    return {
        "ok": not fallidos,
        "aplicados": aplicados,
        "fallidos": fallidos,
        "avisos": avisos,
        "nota": None if not fallidos else "Algunos items no se aplicaron (los demás sí). Revisá con consultar_stock.",
    }


if __name__ == "__main__":
    mcp.run()
