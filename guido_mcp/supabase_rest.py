"""
Acceso a Supabase por PostgREST, con httpx (ya viene con el SDK de MCP: no suma
dependencias).

Usa la service_role key: la tabla `movimientos_stock` y la función `ajustar_stock`
están cerradas para anon/authenticated (migración 24). La key vive SOLO en el .env
del VPS; el modelo nunca la ve — sólo ve lo que devuelven las tools.

Variables:
    SUPABASE_URL                 https://<proyecto>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY    service_role
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

ESTADOS_PAGADOS = ("pagado", "preparando", "enviado", "entregado")


class ErrorSupabase(RuntimeError):
    pass


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 15.0):
        url = url or os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ErrorSupabase("Faltan SUPABASE_URL y/o SUPABASE_SERVICE_ROLE_KEY en el entorno del server MCP")
        self._http = httpx.Client(
            base_url=url.rstrip("/") + "/rest/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=timeout,
        )

    # ── helpers ──
    def _get(self, ruta: str, params: dict) -> list[dict]:
        r = self._http.get(ruta, params=params)
        if r.status_code >= 400:
            raise ErrorSupabase(_mensaje_error(r))
        return r.json()

    def _rpc(self, funcion: str, cuerpo: dict):
        r = self._http.post(f"/rpc/{funcion}", json=cuerpo)
        if r.status_code >= 400:
            raise ErrorSupabase(_mensaje_error(r))
        return r.json()

    # ── lecturas ──
    def variantes(self) -> list[dict]:
        filas = self._get("/variantes_producto", {
            "select": "sku,color,colorway,talle,stock,one_of_one,productos(nombre,activo)",
            "order": "sku.asc",
        })
        salida = []
        for f in filas:
            prod = f.pop("productos", None) or {}
            f["producto"] = prod.get("nombre") or ""
            f["activo"] = bool(prod.get("activo", True))
            salida.append(f)
        return salida

    def movimientos(self, limite: int = 10, sku: str = "") -> list[dict]:
        params = {
            "select": "id,sku,delta,stock_antes,stock_despues,motivo,nota,actor,origen,revierte_a,created_at",
            "order": "created_at.desc",
            "limit": str(limite),
        }
        if sku:
            params["sku"] = f"eq.{sku}"
        return self._get("/movimientos_stock", params)

    def movimiento(self, movimiento_id: str) -> dict | None:
        filas = self._get("/movimientos_stock", {
            "select": "id,sku,delta,motivo,revierte_a,created_at",
            "id": f"eq.{movimiento_id}",
        })
        return filas[0] if filas else None

    def ya_revertido(self, movimiento_id: str) -> bool:
        return bool(self._get("/movimientos_stock", {"select": "id", "revierte_a": f"eq.{movimiento_id}"}))

    def ventas(self, dias: int = 7, limite: int = 30) -> list[dict]:
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        return self._get("/ordenes", {
            "select": (
                "numero_orden,estado,pagado_at,total_centavos,tipo_envio,estado_envio,nro_envio_oca,"
                "clientes(nombre,apellido),items_orden(nombre_producto,color,talle,cantidad)"
            ),
            "estado": f"in.({','.join(ESTADOS_PAGADOS)})",
            "pagado_at": f"gte.{desde}",
            "order": "pagado_at.desc",
            "limit": str(limite),
        })

    # ── escritura ──
    def ajustar_stock(self, sku: str, delta: int, motivo: str, nota: str | None,
                      actor: str | None, revierte_a: str | None = None) -> dict:
        return self._rpc("ajustar_stock", {
            "p_sku": sku,
            "p_delta": delta,
            "p_motivo": motivo,
            "p_nota": nota or None,
            "p_origen": "telegram",
            "p_actor": actor or None,
            "p_revierte_a": revierte_a,
        })


def _mensaje_error(r: httpx.Response) -> str:
    try:
        cuerpo = r.json()
        return cuerpo.get("message") or cuerpo.get("hint") or str(cuerpo)
    except ValueError:
        return f"HTTP {r.status_code}"
