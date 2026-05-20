"""Shareholder return: dilucion neta, buybacks, dividendos (yfinance)."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.tickers import to_yf

log = logging.getLogger(__name__)


def fetch_shareholder_return(yf_symbol):
    import yfinance as yf
    out = {"buyback_yield_ttm": None, "dividend_yield": None,
           "sbc_dilution_pct": None, "net_shareholder_return": None, "currency": None}
    try:
        t = yf.Ticker(yf_symbol)
        info = t.info or {}
        out["currency"] = info.get("currency") or "USD"
        div_y = info.get("dividendYield")
        if div_y is not None:
            try:
                div_y = float(div_y)
                if div_y > 1:
                    div_y = div_y / 100.0
                out["dividend_yield"] = float(div_y)
            except Exception:
                pass
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty and "Ordinary Shares Number" in bs.index:
                shares_series = bs.loc["Ordinary Shares Number"].dropna()
                if len(shares_series) >= 2:
                    shares_series = shares_series.sort_index()
                    last = float(shares_series.iloc[-1])
                    prev = float(shares_series.iloc[-2])
                    if prev > 0:
                        out["buyback_yield_ttm"] = float((prev - last) / prev)
        except Exception as e:
            log.debug("buyback fail %s: %s", yf_symbol, e)
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                sbc = None
                rev = None
                for k in ("Stock Based Compensation", "StockBasedCompensation"):
                    if k in inc.index:
                        s = inc.loc[k].dropna()
                        if len(s) > 0:
                            sbc = float(s.iloc[0]); break
                for k in ("Total Revenue", "TotalRevenue"):
                    if k in inc.index:
                        s = inc.loc[k].dropna()
                        if len(s) > 0:
                            rev = float(s.iloc[0]); break
                if sbc is not None and rev is not None and rev > 0:
                    out["sbc_dilution_pct"] = float(sbc / rev)
        except Exception as e:
            log.debug("sbc fail %s: %s", yf_symbol, e)
        parts = []
        for k in ("buyback_yield_ttm", "dividend_yield", "sbc_dilution_pct"):
            v = out.get(k)
            if v is not None:
                parts.append((k, v))
        if parts:
            net = sum(v if k != "sbc_dilution_pct" else -v for k, v in parts)
            out["net_shareholder_return"] = float(net)
    except Exception as e:
        log.warning("shareholder fail %s: %s", yf_symbol, e)
    return out


def build_shareholder(df_meta, output_path="docs/data/shareholder.json", rate_limit_seconds=0.3):
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
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "n_tickers": len(df_meta), "n_with_data": n_with_data},
        "companies": companies,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("shareholder.json -> %s (%d/%d with data)", output_path, n_with_data, len(df_meta))
    return payload["meta"]
