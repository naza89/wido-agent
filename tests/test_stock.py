"""Lógica pura del stock del agente: búsqueda, propuesta de ajuste y tokens."""
import time

import pytest

from guido_mcp.stock import AjusteInvalido, TokenStore, armar_propuesta, filtrar, normalizar

CATALOGO = [
    {"sku": "REM-LOGO-NRO-M", "producto": "REMERA GÜIDO OVERSIZED", "colorway": "NEGRO LOGO ROJO", "color": "Negro", "talle": "M", "stock": 4, "one_of_one": False},
    {"sku": "REM-LOGO-NRO-L", "producto": "REMERA GÜIDO OVERSIZED", "colorway": "NEGRO LOGO ROJO", "color": "Negro", "talle": "L", "stock": 2, "one_of_one": False},
    {"sku": "REM-LOGO-NBL-M", "producto": "REMERA GÜIDO OVERSIZED", "colorway": "NEGRO LOGO BLANCO", "color": "Negro", "talle": "M", "stock": 5, "one_of_one": False},
    {"sku": "REM-BBY-BLA-XS", "producto": "REMERA BABY TEE REGISTRADA", "colorway": "BLANCO", "color": "Blanco", "talle": "XS", "stock": 9, "one_of_one": False},
    {"sku": "JEA-IND-SUE-M", "producto": "JEAN DE DENIM SELVEDGE JAPONES FIT SUELTO", "colorway": "ÍNDIGO", "color": "Índigo", "talle": "M", "stock": 4, "one_of_one": False},
    {"sku": "JEA-1/1-WAX-M", "producto": "JEAN ENCERADO", "colorway": "1/1", "color": "Verde Encerado", "talle": "M", "stock": 1, "one_of_one": True},
]
POR_SKU = {v["sku"]: v for v in CATALOGO}


def skus(resultado):
    return sorted(v["sku"] for v in resultado)


class TestBusqueda:
    def test_vacia_devuelve_todo(self):
        assert len(filtrar(CATALOGO, "")) == len(CATALOGO)

    def test_talle_corto_es_palabra_exacta(self):
        # "m" no puede matchear la "m" de "remera" ni de "denim"
        assert skus(filtrar(CATALOGO, "remera logo rojo m")) == ["REM-LOGO-NRO-M"]

    def test_genero_y_acentos(self):
        assert skus(filtrar(CATALOGO, "baby tee blanca xs")) == ["REM-BBY-BLA-XS"]
        assert skus(filtrar(CATALOGO, "jean japonés suelto")) == ["JEA-IND-SUE-M"]
        assert skus(filtrar(CATALOGO, "indigo")) == ["JEA-IND-SUE-M"]

    def test_ambigua_devuelve_todas_las_candidatas(self):
        assert skus(filtrar(CATALOGO, "remera negra m")) == ["REM-LOGO-NBL-M", "REM-LOGO-NRO-M"]

    def test_por_sku(self):
        assert skus(filtrar(CATALOGO, "REM-LOGO-NBL-M")) == ["REM-LOGO-NBL-M"]

    def test_normalizar(self):
        assert normalizar("Negra ROJA Índigo") == ["negr", "roj", "indig"]


class TestPropuesta:
    def test_venta_manual_descuenta(self):
        p = armar_propuesta([{"sku": "rem-logo-nro-m", "cantidad": 1}], "descontar", "venta_manual", POR_SKU, nota="feria")
        (l,) = p.lineas
        assert (l.sku, l.delta, l.stock_actual, l.stock_resultante) == ("REM-LOGO-NRO-M", -1, 4, 3)
        assert p.avisos == []

    def test_mismo_sku_repetido_se_suma(self):
        p = armar_propuesta([{"sku": "REM-LOGO-NRO-M", "cantidad": 1}, {"sku": "REM-LOGO-NRO-M", "cantidad": 2}],
                            "descontar", "venta_manual", POR_SKU)
        assert [l.delta for l in p.lineas] == [-3]

    def test_no_deja_stock_negativo(self):
        with pytest.raises(AjusteInvalido, match="no alcanza"):
            armar_propuesta([{"sku": "REM-LOGO-NRO-L", "cantidad": 3}], "descontar", "venta_manual", POR_SKU)

    def test_quedar_en_cero_avisa_lo_de_la_web(self):
        p = armar_propuesta([{"sku": "JEA-1/1-WAX-M", "cantidad": 1}], "descontar", "venta_manual", POR_SKU)
        assert any("soldOut" in a for a in p.avisos)

    def test_motivo_y_direccion_coherentes(self):
        with pytest.raises(AjusteInvalido):
            armar_propuesta([{"sku": "REM-LOGO-NRO-M", "cantidad": 1}], "sumar", "venta_manual", POR_SKU)
        with pytest.raises(AjusteInvalido):
            armar_propuesta([{"sku": "REM-LOGO-NRO-M", "cantidad": 1}], "descontar", "reposicion", POR_SKU)
        armar_propuesta([{"sku": "REM-LOGO-NRO-M", "cantidad": 1}], "sumar", "correccion", POR_SKU)

    @pytest.mark.parametrize("item", [
        {"sku": "NO-EXISTE-M", "cantidad": 1},
        {"sku": "REM-LOGO-NRO-M", "cantidad": 0},
        {"sku": "REM-LOGO-NRO-M", "cantidad": -2},
        {"sku": "REM-LOGO-NRO-M", "cantidad": "dos"},
        {"sku": "", "cantidad": 1},
    ])
    def test_items_invalidos(self, item):
        with pytest.raises(AjusteInvalido):
            armar_propuesta([item], "descontar", "venta_manual", POR_SKU)

    def test_sin_items(self):
        with pytest.raises(AjusteInvalido):
            armar_propuesta([], "descontar", "venta_manual", POR_SKU)


class TestTokens:
    def _propuesta(self):
        return armar_propuesta([{"sku": "REM-LOGO-NRO-M", "cantidad": 1}], "descontar", "venta_manual", POR_SKU)

    def test_un_token_sirve_una_sola_vez(self):
        store = TokenStore()
        t = store.guardar(self._propuesta())
        assert store.tomar(t) is not None
        assert store.tomar(t) is None

    def test_vence(self):
        store = TokenStore(ttl_segundos=0)
        t = store.guardar(self._propuesta())
        time.sleep(0.01)
        assert store.tomar(t) is None

    def test_token_desconocido(self):
        assert TokenStore().tomar("nada") is None
