"""
Tests de la conversion de divisa entre moneda de reporte y moneda de cotizacion.

Contexto: el 17/08/2026 se detecto que `_reprice_valuation` dividia un valor
por accion en moneda de reporte entre un precio en moneda de cotizacion, sin
convertir. Afectaba a 11 de 63 empresas. Estos tests fijan el comportamiento
correcto para que no vuelva a colarse.

Ninguno toca la red: el tipo de cambio se inyecta con `fetcher`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import fx
from src.analytics import (
    _ev_fcf_5y_base, _ev_today, _fx_factor, _reprice_valuation,
    build_fx_map, currency_mismatches, enrich, quote_currency,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    fx.reset_cache()
    yield
    fx.reset_cache()


# --------------------------------------------------------------------------
# Normalizacion de codigos de divisa
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("GBp", ("GBP", 100.0)),    # peniques: el caso de HLMA/JDG/KIST/WOSG
    ("GBX", ("GBP", 100.0)),
    ("GBP", ("GBP", 1.0)),      # libras: se distingue de GBp solo por la caja
    ("USD", ("USD", 1.0)),
    ("KZT", ("KZT", 1.0)),
    ("  eur  ", ("EUR", 1.0)),
    ("ZAc", ("ZAR", 100.0)),
])
def test_normalize_currency(code, expected):
    assert fx.normalize_currency(code) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "EUROS", "X"])
def test_normalize_currency_rejects_garbage(bad):
    assert fx.normalize_currency(bad) is None


def test_gbp_to_pence_is_exactly_100_and_needs_no_network():
    """Libras -> peniques no es un tipo de cambio, es un cambio de unidad."""
    def _explode(a, b):
        raise AssertionError("no deberia pedir tipo de cambio para GBP->GBp")
    assert fx.conversion_factor("GBP", "GBp", fetcher=_explode) == 100.0


def test_same_currency_is_identity():
    assert fx.conversion_factor("USD", "USD") == 1.0


def test_unknown_rate_returns_none_not_one():
    """
    Lo importante del bug: ante la duda hay que devolver None (que se propaga
    como NaN), nunca 1.0, que es lo que producia numeros plausibles y falsos.
    """
    assert fx.conversion_factor("KZT", "USD", fetcher=lambda a, b: None) is None


def test_rate_is_cached_between_calls():
    calls = []

    def _count(a, b):
        calls.append((a, b))
        return 0.0019

    fx.conversion_factor("KZT", "USD", fetcher=_count)
    fx.conversion_factor("KZT", "USD", fetcher=_count)
    assert len(calls) == 1


def test_build_factor_map_deduplicates_pairs():
    calls = []

    def _count(a, b):
        calls.append((a, b))
        return 2.0

    out = fx.build_factor_map([("GBP", "USD")] * 5 + [("EUR", "USD")], fetcher=_count)
    assert len(calls) == 2
    assert out[("GBP", "USD")] == 2.0


# --------------------------------------------------------------------------
# Eleccion de la moneda de cotizacion
# --------------------------------------------------------------------------

def test_price_currency_beats_excel_currency():
    """
    NTO tiene Currency=EUR en el Excel pero cotiza en Tokio (7974.T) y el
    precio llega en JPY. Manda lo que devuelve yfinance.
    """
    row = {"currency": "EUR", "price_currency": "JPY"}
    assert quote_currency(row) == "JPY"


def test_falls_back_to_excel_currency_when_yfinance_silent():
    assert quote_currency({"currency": "USD", "price_currency": None}) == "USD"
    assert quote_currency({"currency": "USD"}) == "USD"


def test_no_currency_anywhere():
    assert quote_currency({"currency": None, "price_currency": np.nan}) is None


def test_fx_factor_identity_when_currencies_match():
    assert _fx_factor({"fx_reporting": "USD", "price_currency": "USD"}) == 1.0


def test_fx_factor_identity_when_reporting_is_missing():
    """Sin dato de moneda de reporte se asume la misma: no rompemos filas viejas."""
    assert _fx_factor({"fx_reporting": None, "price_currency": "USD"}) == 1.0


# --------------------------------------------------------------------------
# Los dos casos reales que estaban rotos
# --------------------------------------------------------------------------

def _kspi_row():
    """Cifras reales de KSPI del 17/08/2026. Reporta en tenge, cotiza en USD."""
    return pd.Series({
        "ticker": "KSPI", "price": 98.48, "shares_out_m": 189.3335,
        "cash": 900000.0, "total_debt": 100000.0,
        "fcf_5y_min": 785000, "fcf_5y_max": 2735000,
        "exit_mult_min": 8.0, "exit_mult_max": 15.0,
        "currency": "USD", "price_currency": "USD", "fx_reporting": "KZT",
    })


def _hlma_row():
    """Halma: cotiza en peniques, reporta en libras. Factor 100."""
    return pd.Series({
        "ticker": "HLMA", "price": 2800.0, "shares_out_m": 380.0,
        "cash": 100.0, "total_debt": 300.0,
        "fcf_5y_min": 400.0, "fcf_5y_max": 700.0,
        "exit_mult_min": 20.0, "exit_mult_max": 30.0,
        "currency": "GBP", "price_currency": "GBp", "fx_reporting": "GBP",
    })


def test_kspi_without_conversion_was_absurd():
    """Documenta el bug: sin convertir, KSPI daba +588% de TIR."""
    row = _kspi_row()
    fve_min_sin_convertir = (row["fcf_5y_min"] * row["exit_mult_min"]
                             + row["cash"] - row["total_debt"]) / row["shares_out_m"]
    assert fve_min_sin_convertir > 37000          # 37.394 tenge por accion
    irr_falsa = (fve_min_sin_convertir / row["price"]) ** (1 / 5) - 1
    assert irr_falsa > 2.0                        # +228% en el peor escenario


def test_kspi_with_conversion_is_sane():
    kzt_usd = 0.0019
    fx_map = {("KZT", "USD"): kzt_usd}
    out = _reprice_valuation(_kspi_row(), fx_map)
    # 37.394 tenge/accion * 0,0019 ~ 71 $, contra un precio de 98,48 $
    assert 60 < out["fve_min_repriced"] < 85
    assert -0.20 < out["irr_worst_repriced"] < 0.05
    assert 0.0 < out["irr_best_repriced"] < 0.60
    assert out["fve_max_repriced"] > out["fve_min_repriced"]


def test_pence_stock_gets_factor_100_not_a_disaster():
    fx_map = build_fx_map(pd.DataFrame([_hlma_row()]))
    assert fx_map[("GBP", "GBp")] == 100.0
    out = _reprice_valuation(_hlma_row(), fx_map)
    # (400*20 + 100 - 300) / 380 = 20,53 GBP = 2.053 peniques, no 20,53
    assert 2000 < out["fve_min_repriced"] < 2100
    assert out["irr_worst_repriced"] > -0.10      # antes salia -64%


def test_missing_rate_produces_nan_not_a_wrong_number():
    out = _reprice_valuation(_kspi_row(), {("KZT", "USD"): None})
    for key in ("fve_min_repriced", "fve_max_repriced",
                "irr_worst_repriced", "irr_best_repriced"):
        assert pd.isna(out[key]), f"{key} deberia ser NaN sin tipo de cambio"


def test_same_currency_row_is_untouched_by_the_fix():
    """Una fila sin desajuste debe dar exactamente lo mismo que antes."""
    row = pd.Series({
        "ticker": "VEEV", "price": 242.19, "shares_out_m": 162.4433,
        "cash": 7313.0, "total_debt": 100.0,
        "fcf_5y_min": 1497, "fcf_5y_max": 3288,
        "exit_mult_min": 18.0, "exit_mult_max": 30.0,
        "currency": "USD", "price_currency": "USD", "fx_reporting": "USD",
    })
    out = _reprice_valuation(row, {})
    esperado = (1497 * 18 + 7313 - 100) / 162.4433
    assert out["fve_min_repriced"] == pytest.approx(esperado)
    assert out["irr_worst_repriced"] == pytest.approx((esperado / 242.19) ** 0.2 - 1)


# --------------------------------------------------------------------------
# EV y multiplo a 5 anos: la misma mezcla de unidades
# --------------------------------------------------------------------------

def test_ev_today_converts_debt_and_cash():
    row = _kspi_row()
    fx_map = {("KZT", "USD"): 0.0019}
    ev = _ev_today(row, fx_map)
    esperado = 98.48 * 189.3335 + (100000 - 900000) * 0.0019
    assert ev == pytest.approx(esperado)


def test_ev_fcf_5y_base_is_a_pure_ratio():
    """EV en dolares dividido entre FCF en tenge no es un multiplo de nada."""
    row = _kspi_row()
    fx_map = {("KZT", "USD"): 0.0019}
    con_fx = _ev_fcf_5y_base(row, fx_map)
    sin_fx = _ev_fcf_5y_base(row, {("KZT", "USD"): 1.0})
    assert con_fx > sin_fx * 100          # el sesgo era de 2-3 ordenes de magnitud
    assert 0 < con_fx < 100               # un multiplo EV/FCF creible


def test_ev_fcf_5y_base_nan_without_rate():
    assert pd.isna(_ev_fcf_5y_base(_kspi_row(), {("KZT", "USD"): None}))


# --------------------------------------------------------------------------
# Integracion: el mapa y el informe de desajustes
# --------------------------------------------------------------------------

def _mini_df():
    return pd.DataFrame([_kspi_row(), _hlma_row(), pd.Series({
        "ticker": "MSFT", "price": 500.0, "shares_out_m": 7400.0,
        "cash": 80000.0, "total_debt": 60000.0,
        "fcf_5y_min": 90000, "fcf_5y_max": 160000,
        "exit_mult_min": 20.0, "exit_mult_max": 30.0,
        "currency": "USD", "price_currency": "USD", "fx_reporting": "USD",
    })])


def test_build_fx_map_skips_matching_currencies():
    calls = []
    fx_map = build_fx_map(_mini_df(), fetcher=lambda a, b: calls.append((a, b)) or 0.0019)
    assert ("USD", "USD") not in fx_map           # MSFT no genera llamada
    assert ("KZT", "USD") in fx_map
    assert ("GBP", "GBp") in fx_map
    assert calls == [("KZT", "USD")]              # GBP->GBp se resuelve sin red


def test_currency_mismatches_lists_only_the_affected():
    df = _mini_df()
    fx_map = build_fx_map(df, fetcher=lambda a, b: 0.0019)
    rows = currency_mismatches(df, fx_map)
    assert {r["ticker"] for r in rows} == {"KSPI", "HLMA"}
    kspi = next(r for r in rows if r["ticker"] == "KSPI")
    assert kspi["reporting"] == "KZT" and kspi["quote"] == "USD"


def test_currency_mismatch_flags_excel_disagreement():
    """HLMA dice GBP en el Excel pero cotiza en GBp: queda registrado."""
    df = _mini_df()
    rows = currency_mismatches(df, build_fx_map(df, fetcher=lambda a, b: 1.0))
    hlma = next(r for r in rows if r["ticker"] == "HLMA")
    assert hlma["excel_currency"] == "GBP"
    assert hlma["quote"] == "GBp"
