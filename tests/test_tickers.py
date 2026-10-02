"""
Tests del mapeo de tickers del Excel a simbolos de yfinance.

Contexto: el 2-oct-2026 se descubrio que COR (Corticeira Amorim, Lisboa) y DNP (Dino
Polska, Varsovia) no tenian override y yfinance los resolvia en Nueva York: Cencora y un
fondo de renta. El panel publico enseno durante semanas el precio de otras empresas.

Regla: una fila cuya moneda en el Excel no es USD no puede resolverse en un ticker sin
sufijo de bolsa (los tickers de EE.UU. no llevan sufijo).

No toca la red: lee el JSON que genera el pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tickers import TICKER_YF_OVERRIDE, to_yf

WATCHLIST = Path(__file__).resolve().parents[1] / "docs" / "data" / "watchlist.json"

# Filas no-USD que SI cotizan sin sufijo y es correcto (ninguna hoy). Anadir con motivo.
EXCEPCIONES: dict[str, str] = {}


def _companies():
    if not WATCHLIST.exists():
        pytest.skip("docs/data/watchlist.json no existe todavia")
    return json.loads(WATCHLIST.read_text(encoding="utf-8"))["companies"]


def test_non_usd_rows_resolve_to_a_non_us_listing():
    malos = []
    for c in _companies():
        ccy = c.get("currency")
        t = c["ticker"]
        if ccy in (None, "", "USD") or t in EXCEPCIONES:
            continue
        if "." not in to_yf(t):
            malos.append(f"{t} (Excel {ccy}) -> {to_yf(t)}")
    assert not malos, "Filas no-USD sin override de bolsa: " + ", ".join(malos)


@pytest.mark.parametrize("excel,yf", [
    ("COR", "COR.LS"),
    ("DNP", "DNP.WA"),
    ("IP", "IP.MI"),     # International Paper si falta
    ("LR", "LR.PA"),     # Leroy Seafood si falta
    ("SAP", "SAP.DE"),   # el ADR en USD si falta
    ("VRLA", "VRLA.PA"), # VLA.PA es Valneva: estuvo mal hasta el 2-oct-2026
])
def test_ambiguous_tickers_have_the_right_listing(excel, yf):
    assert TICKER_YF_OVERRIDE[excel] == yf


def test_price_guard_keeps_excel_price_when_yfinance_is_another_company():
    import pandas as pd
    from src.enrich import apply_quotes
    df = pd.DataFrame([{"ticker": "VRLA", "price": 16.4, "shares_out_m": 127.6},
                       {"ticker": "ITX", "price": 53.0, "shares_out_m": 3116.7}])
    quotes = {"VRLA": {"price": 2.53, "source": "yfinance"},   # Valneva
              "ITX": {"price": 53.9, "source": "yfinance"}}
    out = apply_quotes(df, quotes, {"VRLA": "EUR", "ITX": "EUR"}).set_index("ticker")
    assert out.loc["VRLA", "price"] == 16.4
    assert out.loc["VRLA", "price_source"] == "excel (guarda)"
    assert out.loc["ITX", "price"] == 53.9
