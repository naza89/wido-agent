"""
Transferencias bancarias: el cliente eligió "transferencia" en el checkout de la web,
la orden quedó en `esperando_transferencia`, y alguien del equipo tiene que confirmarla
(o cancelarla) cuando llega (o no llega) el comprobante.

El cambio de estado NO se hace acá contra Supabase: se le pide a la web, por
`POST /api/ordenes/{id}/transferencia` con `x-admin-token`. La web corre el post-pago
de siempre (descontar stock, mail de confirmación al cliente, aviso interno y a
Telegram). Si el agente escribiera `estado = 'pagado'` directo, el cliente no recibiría
su mail ni bajaría el stock hasta que alguien abriera la orden.

Misma regla de oro que el stock: preparar → "sí" explícito → confirmar.

Variables (en el mismo archivo de secretos que Supabase, ver deploy/mcp_launch.sh):
    GUIDO_WEB_URL        default https://www.xn--gidocapuzzi-thb.com
    GUIDO_ADMIN_TOKEN    el ADMIN_API_TOKEN de Vercel (Production)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

ESTADO_ESPERANDO = "esperando_transferencia"
ACCIONES = ("confirmar", "cancelar")
WEB_DEFAULT = "https://www.xn--gidocapuzzi-thb.com"


class TransferenciaInvalida(ValueError):
    pass


class ErrorWeb(RuntimeError):
    pass


def pesos(centavos: int | None) -> int:
    return round((centavos or 0) / 100)


def resumir_orden(o: dict) -> dict:
    """Fila de `ordenes` (con clientes e items embebidos) → lo que ve el equipo."""
    cli = o.get("clientes") or {}
    return {
        "orden": o.get("numero_orden"),
        "id": o.get("id"),
        "estado": o.get("estado"),
        "creada": o.get("created_at"),
        "a_transferir_ars": pesos(o.get("total_centavos")),
        "descuento_ars": pesos(o.get("descuento_centavos")),
        "envio": o.get("tipo_envio"),
        "cliente": " ".join(x for x in (cli.get("nombre"), cli.get("apellido")) if x),
        "email": cli.get("email"),
        "telefono": cli.get("telefono"),
        "items": [
            f'{i.get("cantidad")}× {i.get("nombre_producto")} — {i.get("color")} · talle {i.get("talle")}'
            for i in (o.get("items_orden") or [])
        ],
    }


@dataclass
class PropuestaTransferencia:
    orden_id: str
    numero_orden: int
    accion: str
    nota: str
    actor: str
    resumen_orden: dict

    def resumen(self) -> dict:
        efecto = (
            "pasa a PAGADA: se descuenta el stock y le llega al cliente el mail de confirmación"
            if self.accion == "confirmar"
            else "pasa a CANCELADA: se libera la reserva (el stock nunca se había descontado)"
        )
        return {
            "accion": self.accion,
            "efecto": efecto,
            "nota": self.nota or None,
            "quien": self.actor or None,
            **self.resumen_orden,
        }


def armar_propuesta_transferencia(
    orden: dict | None, accion: str, nota: str = "", actor: str = ""
) -> PropuestaTransferencia:
    accion = (accion or "").strip().lower()
    if accion not in ACCIONES:
        raise TransferenciaInvalida("accion tiene que ser 'confirmar' o 'cancelar'")
    if not orden:
        raise TransferenciaInvalida("no existe esa orden — mirá transferencias_pendientes")
    if orden.get("estado") != ESTADO_ESPERANDO:
        raise TransferenciaInvalida(
            f"la orden #{orden.get('numero_orden')} no está esperando transferencia (estado: {orden.get('estado')})"
        )
    nota = (nota or "").strip()
    if accion == "confirmar" and not nota:
        raise TransferenciaInvalida(
            "para confirmar hace falta una nota con el comprobante (monto, fecha, banco o n° de operación)"
        )
    return PropuestaTransferencia(
        orden_id=str(orden["id"]),
        numero_orden=int(orden["numero_orden"]),
        accion=accion,
        nota=nota[:500],
        actor=(actor or "").strip(),
        resumen_orden=resumir_orden(orden),
    )


class Tienda:
    """Cliente de la API de backoffice de la web."""

    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 40.0):
        base_url = base_url or os.environ.get("GUIDO_WEB_URL") or WEB_DEFAULT
        token = token or os.environ.get("GUIDO_ADMIN_TOKEN")
        if not token:
            raise ErrorWeb("Falta GUIDO_ADMIN_TOKEN en el entorno del server MCP")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"x-admin-token": token},
            timeout=timeout,
        )

    def resolver_transferencia(self, orden_id: str, accion: str, nota: str) -> dict:
        r = self._http.post(f"/api/ordenes/{orden_id}/transferencia", json={"accion": accion, "nota": nota})
        try:
            cuerpo = r.json()
        except ValueError:
            raise ErrorWeb(f"la web respondió HTTP {r.status_code} sin JSON") from None
        if r.status_code >= 400:
            raise ErrorWeb(cuerpo.get("error") or f"HTTP {r.status_code}")
        return cuerpo
