"""Tests del DCF de 3 escenarios y de los precios de compra (src/valuation.py)."""
import math

from src import valuation as V

FILA = {"ticker": "TEST", "fcf_ltm_normalized": 100.0, "fcf_5y_min": 110.0, "fcf_5y_max": 200.0,
        "shares_out_m": 10.0, "cash": 50.0, "total_debt": 150.0}


def test_flujos_llegan_al_fcf_del_ano_5_y_se_desvanecen():
    f = V.flujos(100.0, 161.05, 0.025)
    assert len(f) == 10
    assert math.isclose(f[4], 161.05, rel_tol=1e-6)
    crec = [f[k] / f[k - 1] - 1 for k in range(5, 10)]
    assert crec[0] > crec[-1] and math.isclose(crec[-1], 0.025, rel_tol=1e-6)


def test_valor_resta_deuda_neta_y_baja_con_la_tasa():
    v10 = V.valor_por_accion(FILA, 0.10)
    v14 = V.valor_por_accion(FILA, 0.14)
    assert v10["bajista"] < v10["base"] < v10["alcista"]
    assert v14["ponderado"] < v10["ponderado"]
    sin_deuda = V.valor_por_accion(dict(FILA, total_debt=50.0), 0.10)
    assert math.isclose(sin_deuda["base"] - v10["base"], 100.0 / 10.0, rel_tol=1e-9)


def test_tir_implicita_devuelve_la_tasa_que_iguala_el_precio():
    precio = V.valor_por_accion(FILA, 0.12)["ponderado"]
    assert math.isclose(V.tir_implicita(FILA, precio), 0.12, abs_tol=1e-6)
    r, lim = V.tir_implicita(FILA, precio * 50, con_limite=True)
    assert lim == "suelo"


def test_precio_compra_mc_y_tir_desde_precio_compra_son_inversas():
    esc = [(0.25, 80.0), (0.5, 150.0), (0.25, 260.0)]
    h = 0.11
    pc = V.precio_compra_mc(esc, h)
    tir_pc = sum(w * (v / pc) ** 0.2 for w, v in esc) - 1
    assert math.isclose(tir_pc, h, abs_tol=1e-9)
    p = 120.0
    directa = sum(w * (v / p) ** 0.2 for w, v in esc) - 1
    assert math.isclose(V.tir_desde_precio_compra(pc, p, h), directa, abs_tol=1e-9)


def test_activo_que_se_agota_usa_crecimiento_negativo():
    assert V.crecimiento_terminal("KIST")[1] < 0
    assert V.crecimiento_terminal("CSU") == V.G_DEFECTO


def test_depreciacion_de_la_moneda_de_reporte_rebaja_el_dcf_y_el_factor_futuro():
    """Kaspi (9-nov-2026): el FCF en tenge se convierte al tipo esperado de cada año; tras el año 5 se congela."""
    import pytest
    assert V.depreciacion("KSPI") == pytest.approx(0.05)
    assert V.depreciacion("TEST") == 0.0
    assert V.factor_futuro("KSPI", 1.0) == pytest.approx(1 / 1.05 ** 5)
    assert V.factor_futuro("TEST", 0.5) == 0.5
    sin = V.valor_por_accion(dict(FILA, total_debt=50.0, cash=50.0), 0.12)
    con = V.valor_por_accion(dict(FILA, ticker="KSPI", total_debt=50.0, cash=50.0), 0.12)
    assert con["ponderado"] < sin["ponderado"]
    # todo el valor (flujos y terminal) queda, como mucho, al tipo del año 5
    assert con["ponderado"] >= sin["ponderado"] / 1.05 ** 5 - 1e-9
