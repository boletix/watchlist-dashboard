"""
Enrich: actualiza precio + market cap vía yfinance.

Diseñado para fallar con gracia:
- 403 / rate-limit → mantiene valor del Excel, añade flag `price_stale=True`
- ticker no reconocido → mantiene valor, flag `price_stale=True`
- red apagada en CI → skip con warning

No actualiza ratings ni financials derivados (son tuyos, cualitativos).
Solo toca: price, market_cap_m (recalculado con shares_out_m × price_new).

Mapeo ticker → yfinance:
- US tickers directos (MSFT, AMZN...)
- Europa: necesita sufijo (ADYEN.AS, ITX.MC, NESN.SW...)
- UK: .L para LSE
El mapeo se extiende en TICKER_YF_OVERRIDE cuando haga falta.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from src.tickers import TICKER_YF_OVERRIDE, to_yf

log = logging.getLogger(__name__)


def _map_ticker(ticker: str) -> str:
    """Aplica override si existe, si no devuelve el ticker tal cual."""
    return to_yf(ticker)


def fetch_quotes(tickers: list[str], max_retries: int = 2) -> dict[str, dict[str, Any]]:
    """
    Descarga precio actual para cada ticker.

    Returns: dict[ticker_excel] → {'price': float, 'source': 'yfinance'|'stale'}
    Nunca lanza excepción a la salida: garantiza un dict para cada ticker.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance no instalado — skip enrichment")
        return {t: {"price": None, "source": "skipped"} for t in tickers}

    result: dict[str, dict[str, Any]] = {}
    yf_symbols = {t: _map_ticker(t) for t in tickers}

    # Descarga en batch (más eficiente, menos susceptible a rate-limit)
    symbols_str = " ".join(set(yf_symbols.values()))
    prices: dict[str, float] = {}

    for attempt in range(max_retries + 1):
        try:
            data = yf.download(
                symbols_str,
                period="1d",
                progress=False,
                auto_adjust=False,
                threads=True,
            )
            if data.empty:
                raise ValueError("yfinance devolvió DataFrame vacío")
            # yfinance retorna MultiIndex si hay varios tickers
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"].iloc[-1]
                prices = close.to_dict()
            else:
                # Un solo ticker
                only = list(set(yf_symbols.values()))[0]
                prices = {only: float(data["Close"].iloc[-1])}
            break
        except Exception as e:
            log.warning("yfinance attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                log.error("yfinance agotó retries — enrichment skipped")

    # Mapear de vuelta a tickers Excel
    for excel_t, yf_t in yf_symbols.items():
        p = prices.get(yf_t)
        if p is not None and not pd.isna(p):
            result[excel_t] = {"price": float(p), "source": "yfinance"}
        else:
            result[excel_t] = {"price": None, "source": "stale"}

    n_success = sum(1 for v in result.values() if v["source"] == "yfinance")
    log.info("yfinance: %d/%d precios actualizados", n_success, len(tickers))
    return result


def apply_quotes(df: pd.DataFrame, quotes: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """
    Aplica precios de yfinance al DataFrame.
    Recalcula market_cap_m si shares_out_m está disponible.
    Añade columna `price_source` = 'yfinance' | 'stale' | 'skipped'.
    """
    out = df.copy()
    out["price_source"] = "stale"

    for idx, row in out.iterrows():
        quote = quotes.get(row["ticker"])
        if not quote or quote["price"] is None:
            continue
        new_price = quote["price"]
        out.at[idx, "price"] = new_price
        out.at[idx, "price_source"] = quote["source"]
        if "shares_out_m" in out.columns and pd.notna(row["shares_out_m"]):
            out.at[idx, "market_cap_m"] = new_price * row["shares_out_m"]

    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.etl import load_watchlist

    df = load_watchlist("data/raw/watchlist_ratings.xlsx")
    quotes = fetch_quotes(df["ticker"].tolist()[:5])
    print(quotes)
