"""
Shareholder return: dilucion neta, buybacks, dividendos.

Para cada ticker computa:
  - buyback_yield_ttm   : (shares_t-1 - shares_t) / shares_t-1 anualizado
  - dividend_yield      : dividendos LTM / market_cap actual
  - sbc_dilution_pct    : stock-based comp LTM / revenue LTM (no dilucion exacta,
                          pero proxy fuerte; SBC reportado neto bajaria buybacks)
  - net_shareholder_return : buyback_yield + dividend_yield - sbc_dilution_pct

Output: docs/data/shareholder.json
Inyectado en watchlist.json para que aparezca en la tarjeta empresa.

Fuentes yfinance:
  Ticker.info -> dividendYield, sharesOutstanding
  Ticker.dividends -> historial dividendos
  Ticker.income_stmt -> StockBasedCompensation (anual)
  Ticker.balance_sheet / quarterly_balance_sheet -> shares history (imperfecto)

Limitaciones:
  - yfinance no expone shares_outstanding historicos por fecha. Usamos el
    cambio reportado en balance_sheet annual (>=2 anos) como proxy.
  - SBC no esta siempre desglosado en yfinance; cobertura ~70% US.
  - Empresas EU/UK con cobertura ~50%.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.tickers import to_yf

log = logging.getLogger(__name__)


def _safe(v):
    try:
        if v is None or pd.isna(v):
            return None
    except Exception:
        return None
    try:
        return float(v)
    except Exception:
        return None


def fetch_shareholder_return(yf_symbol: str) -> dict:
    """Computa los 4 numeros para un ticker via yfinance."""
    import yfinance as yf
    out = {
        "buyback_yield_ttm":     None,
        "dividend_yield":        None,
        "sbc_dilution_pct":      None,
        "net_shareholder_return": None,
        "currency":              None,
    }
    try:
        t = yf.Ticker(yf_symbol)
        info = t.info or {}
        out["currency"] = info.get("currency") or "USD"

        # Dividend yield: info.dividendYield es ratio (0.02 = 2%)
        div_y = info.get("dividendYield")
        if div_y is not None:
            try:
                div_y = float(div_y)
                # yfinance a veces devuelve % (5.0) y otras ratio (0.05); normalizamos
                if div_y > 1:
                    div_y = div_y / 100.0
                out["dividend_yield"] = float(div_y)
            except Exception:
                pass

        # Buyback yield: comparar shares de annual_balance_sheet (>= 2 anos)
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty and "Ordinary Shares Number" in bs.index:
                shares_series = bs.loc["Ordinary Shares Number"].dropna()
                if len(shares_series) >= 2:
                    shares_series = shares_series.sort_index()
                    last = float(shares_series.iloc[-1])
                    prev = float(shares_series.iloc[-2])
                    if prev > 0:
                        # Annualizar segun gap (1 ano por defecto)
                        out["buyback_yield_ttm"] = float((prev - last) / prev)
        except Exception as e:
            log.debug("buyback fetch fail %s: %s", yf_symbol, e)

        # SBC: income_stmt -> Stock Based Compensation (anual mas reciente) / Revenue
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                sbc_keys = ["Stock Based Compensation", "StockBasedCompensation"]
                rev_keys = ["Total Revenue", "TotalRevenue"]
                sbc = None; rev = None
                for k in sbc_keys:
                    if k in inc.index:
                        s = inc.loc[k].dropna()
                        if len(s) > 0:
                            sbc = float(s.iloc[0])
                            break
                for k in rev_keys:
                    if k in inc.index:
                        s = inc.loc[k].dropna()
                        if len(s) > 0:
                            rev = float(s.iloc[0])
                            break
                if sbc is not None and rev is not None and rev > 0:
                    out["sbc_dilution_pct"] = float(sbc / rev)
        except Exception as e:
            log.debug("sbc fetch fail %s: %s", yf_symbol, e)

        # Net shareholder return = buyback + div - sbc
        parts = []
        for k in ("buyback_yield_ttm", "dividend_yield", "sbc_dilution_pct"):
            v = out.get(k)
            if v is not None:
                parts.append((k, v))
        if parts:
            net = sum(v if k != "sbc_dilution_pct" else -v for k, v in parts)
            out["net_shareholder_return"] = float(net)
    except Exception as e:
        log.warning("shareholder fetch fail %s: %s", yf_symbol, e)
    return out


def build_shareholder(df_meta: pd.DataFrame,
                      output_path: str | Path = "docs/data/shareholder.json",
                      rate_limit_seconds: float = 0.3) -> dict:
    """Pipeline: para cada ticker, fetch shareholder return numbers."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    companies = {}
    n_with_data = 0
    for idx, row in df_meta.iterrows():
        t = row["ticker"]
        yf_sym = to_yf(t)
        log.info("[%d/%d] shareholder %s (%s)", idx + 1, len(df_meta), t, yf_sym)
        d = fetch_shareholder_return(yf_sym)
        companies[t] = d
        if any(d.get(k) is not None for k in ("buyback_yield_ttm", "dividend_yield", "sbc_dilution_pct")):
            n_with_data += 1
        time.sleep(rate_limit_seconds)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_tickers": len(df_meta),
            "n_with_data": n_with_data,
        },
        "companies": companies,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("shareholder.json -> %s (%d/%d with data)", output_path, n_with_data, len(df_meta))
    return payload["meta"]
