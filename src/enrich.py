"""
Enrich v2: actualiza precio + market cap via yfinance.

Mejoras v2:
- Si el batch fetch falla parcialmente, retry por-ticker en paralelo
  (ThreadPoolExecutor) para minimizar single-ticker failures.
- Mantiene el contrato anterior: nunca lanza, garantiza dict por ticker.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from src.tickers import TICKER_YF_OVERRIDE, to_yf

log = logging.getLogger(__name__)


def _map_ticker(ticker: str) -> str:
    return to_yf(ticker)


def _single_ticker_fetch(yf_symbol: str) -> tuple[str, float | None]:
    """Fallback fetch para un solo ticker. Devuelve (symbol, price_or_None)."""
    try:
        import yfinance as yf
        t = yf.Ticker(yf_symbol)
        hist = t.history(period="1d")
        if not hist.empty:
            p = float(hist["Close"].iloc[-1])
            if not pd.isna(p):
                return (yf_symbol, p)
        info = t.info or {}
        for key in ("regularMarketPrice", "currentPrice", "previousClose"):
            v = info.get(key)
            if v is not None and not pd.isna(v):
                return (yf_symbol, float(v))
    except Exception as e:
        log.debug("single fetch fail %s: %s", yf_symbol, e)
    return (yf_symbol, None)


def fetch_quotes(tickers: list, max_retries: int = 2) -> dict:
    """Descarga precio actual con batch primero, single-fallback si falla."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance no instalado - skip enrichment")
        return {t: {"price": None, "source": "skipped"} for t in tickers}

    result: dict = {}
    yf_symbols = {t: _map_ticker(t) for t in tickers}
    unique_yf = list(set(yf_symbols.values()))
    prices: dict = {}

    # 1. Batch fetch
    for attempt in range(max_retries + 1):
        try:
            data = yf.download(" ".join(unique_yf), period="1d",
                               progress=False, auto_adjust=False, threads=True)
            if data.empty:
                raise ValueError("yfinance devolvio DataFrame vacio")
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"].iloc[-1]
                prices = {k: float(v) for k, v in close.to_dict().items()
                          if v is not None and not pd.isna(v)}
            else:
                if unique_yf:
                    prices = {unique_yf[0]: float(data["Close"].iloc[-1])}
            break
        except Exception as e:
            log.warning("batch attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)

    # 2. Single-ticker fallback para los que faltan
    missing = [y for y in unique_yf if y not in prices]
    if missing:
        log.info("Fallback single fetch para %d tickers: %s", len(missing), missing[:5])
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_single_ticker_fetch, y): y for y in missing}
            for fut in as_completed(futs):
                sym, price = fut.result()
                if price is not None:
                    prices[sym] = price

    # 3. Mapear de vuelta a tickers Excel
    for excel_t, yf_t in yf_symbols.items():
        p = prices.get(yf_t)
        if p is not None and not pd.isna(p):
            result[excel_t] = {"price": float(p), "source": "yfinance"}
        else:
            result[excel_t] = {"price": None, "source": "stale"}

    n_success = sum(1 for v in result.values() if v["source"] == "yfinance")
    log.info("yfinance: %d/%d precios actualizados", n_success, len(tickers))
    return result


def apply_quotes(df: pd.DataFrame, quotes: dict) -> pd.DataFrame:
    """Aplica precios al DataFrame y recalcula market_cap_m."""
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
            try:
                out.at[idx, "market_cap_m"] = new_price * float(row["shares_out_m"])
            except (TypeError, ValueError):
                pass
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.etl import load_watchlist
    df = load_watchlist("data/raw/watchlist_ratings.xlsx")
    quotes = fetch_quotes(df["ticker"].tolist()[:5])
    print(quotes)
