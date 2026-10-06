"""
Lógica pura del stock para el agente: búsqueda de variantes, armado de una propuesta
de ajuste (dry-run) y el almacén de tokens de confirmación.

Sin red ni Supabase acá — eso vive en `supabase_rest.py`. Así esto se testea solo
(`tests/test_stock.py`).

Regla de oro (la misma que Mercedino): nada se escribe sin que alguien diga "sí".
    preparar_ajuste_stock  →  propuesta + token   (no toca nada)
    el agente la muestra y espera confirmación explícita
    confirmar_ajuste(token) → aplica
"""
from __future__ import annotations

import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, field

# Motivos válidos (espejo del CHECK de movimientos_stock, migración 24) y en qué
# dirección puede ir cada uno. `correccion` va para los dos lados: es el comodín
# de "el número estaba mal".
MOTIVOS: dict[str, set[str]] = {
    "venta_manual": {"descontar"},
    "reposicion": {"sumar"},
    "devolucion": {"sumar"},
    "correccion": {"descontar", "sumar"},
}

MAX_UNIDADES_POR_ITEM = 50


# ── Búsqueda ────────────────────────────────────────────────────────────────────

def _raiz(palabra: str) -> str:
    """'negra'/'negro' → 'negr', 'blancas' → 'blanc'. Solo palabras de 4+ letras:
    los talles (xs, s, m, l) quedan intactos."""
    if len(palabra) >= 4:
        for suf in ("as", "os", "a", "o"):
            if palabra.endswith(suf) and len(palabra) - len(suf) >= 3:
                return palabra[: -len(suf)]
    return palabra


def normalizar(texto: str) -> list[str]:
    sin_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    limpio = "".join(c if c.isalnum() or c == "/" else " " for c in sin_acentos.lower())
    return [_raiz(p) for p in limpio.split() if p]


def coincide(busqueda: str, variante: dict) -> bool:
    """Todas las palabras de la búsqueda tienen que estar en la variante.
    Las cortas (talles: 'm', 'xs') matchean palabra exacta; las largas, también
    como parte de una palabra ('remer' matchea 'remera')."""
    pajar = normalizar(" ".join(str(variante.get(k) or "") for k in ("producto", "colorway", "color", "talle", "sku")))
    sku_partes = normalizar((variante.get("sku") or "").replace("-", " "))
    palabras = set(pajar) | set(sku_partes)
    texto = " ".join(pajar)
    for q in normalizar(busqueda):
        if q in palabras:
            continue
        if len(q) >= 3 and q in texto:
            continue
        return False
    return True


def filtrar(variantes: list[dict], busqueda: str) -> list[dict]:
    if not (busqueda or "").strip():
        return list(variantes)
    return [v for v in variantes if coincide(busqueda, v)]


# ── Propuesta de ajuste ─────────────────────────────────────────────────────────

class AjusteInvalido(ValueError):
    pass


@dataclass
class LineaAjuste:
    sku: str
    producto: str
    colorway: str
    talle: str
    delta: int
    stock_actual: int
    one_of_one: bool

    @property
    def stock_resultante(self) -> int:
        return self.stock_actual + self.delta


@dataclass
class Propuesta:
    motivo: str
    nota: str
    actor: str
    lineas: list[LineaAjuste]
    revierte_a: str | None = None
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> dict:
        return {
            "motivo": self.motivo,
            "nota": self.nota or None,
            "quien": self.actor or None,
            "revierte_a": self.revierte_a,
            "lineas": [
                {
                    "sku": linea.sku,
                    "producto": linea.producto,
                    "colorway": linea.colorway,
                    "talle": linea.talle,
                    "cambio": linea.delta,
                    "stock_actual": linea.stock_actual,
                    "stock_resultante": linea.stock_resultante,
                }
                for linea in self.lineas
            ],
            "avisos": self.avisos,
        }


def armar_propuesta(
    items: list[dict],
    operacion: str,
    motivo: str,
    variantes_por_sku: dict[str, dict],
    nota: str = "",
    actor: str = "",
) -> Propuesta:
    """`items`: [{"sku": ..., "cantidad": n}] con cantidad > 0. `operacion`: descontar|sumar."""
    if operacion not in ("descontar", "sumar"):
        raise AjusteInvalido("operacion tiene que ser 'descontar' o 'sumar'")
    if motivo not in MOTIVOS:
        raise AjusteInvalido(f"motivo inválido: {motivo!r}. Válidos: {', '.join(MOTIVOS)}")
    if operacion not in MOTIVOS[motivo]:
        raise AjusteInvalido(f"el motivo {motivo!r} no admite '{operacion}'")
    if not items:
        raise AjusteInvalido("no hay ningún item para ajustar")

    signo = -1 if operacion == "descontar" else 1
    acumulado: dict[str, int] = {}
    for it in items:
        sku = str(it.get("sku") or "").strip().upper()
        try:
            cantidad = int(it.get("cantidad", 0))
        except (TypeError, ValueError):
            raise AjusteInvalido(f"cantidad inválida para {sku or '?'}") from None
        if not sku:
            raise AjusteInvalido("falta el SKU de un item — buscalo antes con consultar_stock")
        if sku not in variantes_por_sku:
            raise AjusteInvalido(f"no existe el SKU {sku} — buscalo con consultar_stock")
        if cantidad <= 0 or cantidad > MAX_UNIDADES_POR_ITEM:
            raise AjusteInvalido(f"cantidad fuera de rango para {sku}: {cantidad} (1 a {MAX_UNIDADES_POR_ITEM})")
        acumulado[sku] = acumulado.get(sku, 0) + cantidad

    lineas: list[LineaAjuste] = []
    avisos: list[str] = []
    for sku, cantidad in acumulado.items():
        v = variantes_por_sku[sku]
        linea = LineaAjuste(
            sku=sku,
            producto=v.get("producto") or "",
            colorway=v.get("colorway") or "",
            talle=v.get("talle") or "",
            delta=signo * cantidad,
            stock_actual=int(v.get("stock") or 0),
            one_of_one=bool(v.get("one_of_one")),
        )
        if linea.stock_resultante < 0:
            raise AjusteInvalido(
                f"no alcanza el stock de {sku}: hay {linea.stock_actual}, se pidió descontar {cantidad}"
            )
        if linea.stock_resultante == 0 and linea.delta < 0:
            avisos.append(
                f"{sku} queda en 0. La web NO se entera sola: hay que marcarlo vendido (soldOut en start.js) "
                "o se sigue vendiendo."
            )
        if linea.stock_actual == 0 and linea.delta > 0:
            avisos.append(f"{sku} vuelve a tener stock. Si en la web está marcado vendido, hay que desmarcarlo.")
        lineas.append(linea)

    return Propuesta(motivo=motivo, nota=nota.strip(), actor=actor.strip(), lineas=lineas, avisos=avisos)


# ── Tokens de confirmación ──────────────────────────────────────────────────────

class TokenStore:
    """Propuestas pendientes en memoria, con vencimiento. El server MCP es un proceso
    largo (Hermes lo lanza una vez), así que alcanza; si se reinicia entre la propuesta
    y el "sí", el token se pierde y se vuelve a preparar — es lo seguro."""

    def __init__(self, ttl_segundos: int = 600):
        self.ttl = ttl_segundos
        self._pendientes: dict[str, tuple[Propuesta, float]] = {}
        self._lock = threading.Lock()

    def guardar(self, propuesta: Propuesta) -> str:
        token = secrets.token_hex(4)
        with self._lock:
            self._purgar()
            self._pendientes[token] = (propuesta, time.monotonic() + self.ttl)
        return token

    def tomar(self, token: str) -> Propuesta | None:
        """Devuelve y CONSUME la propuesta: un token sirve una sola vez."""
        with self._lock:
            self._purgar()
            entrada = self._pendientes.pop((token or "").strip(), None)
        return entrada[0] if entrada else None

    def _purgar(self) -> None:
        ahora = time.monotonic()
        for t in [t for t, (_, vence) in self._pendientes.items() if vence < ahora]:
            del self._pendientes[t]
