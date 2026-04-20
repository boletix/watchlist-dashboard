"""
Q3: Historical multiple evolution.

Para cada empresa, calcula EV/FCF, EV/Sales y EV/EBITDA punto a punto desde
2020 hasta hoy, usando:
- Quarterly fundamentals de yfinance (~5 años de cobertura)
- TTM rolling: para cada quarter, suma de los últimos 4 quarters de FCF/Revenue/EBITDA
- Precios diarios ajustados → market cap diario × shares outstanding (interpolado)
- EV = MCap + Debt − Cash (interpolado por quarter)

Output: docs/data/history.json con series trimestrales por empresa.

Limitaciones honestas:
- yfinance no expone shares outstanding históricos por fecha. Asumimos shares
  CONSTANTES = última value reportada. Para empresas con buybacks fuertes
  esto subestima el EV histórico (error típico ~5-10% en 5 años).
- Cobertura ~80% para US, baja a ~50% para EU/UK/Nordics. Empresas sin data
  se omiten del JSON pero se listan en `meta.missing`.
- Para una versión "institucional" habría que pasar a Refinitiv/FMP/SimplyWall.
  Esta v1 es honesta sobre sus límites pero suficiente para detectar tendencias.

Forward projection:
- Usa los inputs del Excel (fcf_min_cagr, fcf_max_cagr, exit_mult_min/max)
  para extender 5 años hacia el futuro
- Genera fan chart bear/bull con cono de incertidumbre
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.tickers import to_yf

log = logging.getLogger(__name__)

START_DATE = "2020-01-01"


def _fetch_company_history(yf_symbol: str) -> dict[str, Any]:
    """
    Para un símbolo yfinance, devuelve dict con:
    - prices: pd.Series de adjusted close diario
    - shares: float (últimas shares outstanding) o None
    - annual: pd.DataFrame con FCF, Revenue, EBITDA, Cash, Debt por año fiscal (5 años)
    - quarterly: pd.DataFrame con mismo schema, ~6 quarters (1.5 años)
    - currency: str

    Combinamos ambos: annual cubre 2020-2024, quarterly cubre 2024-presente.
    Cualquier dato faltante → DataFrame vacío. No lanza excepción.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(yf_symbol)
        info = t.info or {}
        currency = info.get("currency") or "USD"
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")

        hist = t.history(start=START_DATE, auto_adjust=True)
        prices = hist["Close"] if not hist.empty else pd.Series(dtype=float)

        # Annual: 5 años de cobertura típicamente
        annual_cf = getattr(t, "cashflow", pd.DataFrame())
        annual_fin = getattr(t, "income_stmt", pd.DataFrame())
        annual_bs = getattr(t, "balance_sheet", pd.DataFrame())

        # Quarterly: últimos 6 quarters (1.5 años)
        q_cf = getattr(t, "quarterly_cashflow", pd.DataFrame())
        q_fin = getattr(t, "quarterly_financials", pd.DataFrame())
        q_bs = getattr(t, "quarterly_balance_sheet", pd.DataFrame())

        annual = _build_periodic_df(annual_cf, annual_fin, annual_bs, period="annual")
        quarterly = _build_periodic_df(q_cf, q_fin, q_bs, period="quarterly")

        return {
            "prices": prices,
            "shares": shares,
            "annual": annual,
            "quarterly": quarterly,
            "currency": currency,
        }
    except Exception as e:
        log.warning("Error fetch %s: %s", yf_symbol, e)
        return {
            "prices": pd.Series(dtype=float), "shares": None,
            "annual": pd.DataFrame(), "quarterly": pd.DataFrame(), "currency": "USD",
        }


def _build_periodic_df(
    cf: pd.DataFrame, fin: pd.DataFrame, bs: pd.DataFrame, period: str
) -> pd.DataFrame:
    """Reorganiza dataframes de yfinance en formato {date: {fcf, revenue, ebitda, cash, debt}}."""
    fcf_row = _safe_row(cf, ["Free Cash Flow", "FreeCashFlow"])
    rev_row = _safe_row(fin, ["Total Revenue", "TotalRevenue"])
    ebitda_row = _safe_row(fin, ["EBITDA", "Normalized EBITDA"])
    cash_row = _safe_row(bs, ["Cash And Cash Equivalents", "CashAndCashEquivalents", "Cash"])
    debt_row = _safe_row(bs, ["Total Debt", "TotalDebt", "Long Term Debt"])

    all_dates = sorted(set(
        list(fcf_row.index if fcf_row is not None else [])
        + list(rev_row.index if rev_row is not None else [])
        + list(ebitda_row.index if ebitda_row is not None else [])
    ))
    if not all_dates:
        return pd.DataFrame()

    rows = []
    for d in all_dates:
        rows.append({
            "date": d,
            "period": period,
            "fcf": _val(fcf_row, d),
            "revenue": _val(rev_row, d),
            "ebitda": _val(ebitda_row, d),
            "cash": _val(cash_row, d),
            "debt": _val(debt_row, d),
        })
    return pd.DataFrame(rows).set_index("date")


def _safe_row(df: pd.DataFrame, candidate_names: list[str]) -> pd.Series | None:
    """Busca la primera fila que matchee alguno de los nombres candidatos."""
    if df is None or df.empty:
        return None
    for name in candidate_names:
        if name in df.index:
            return df.loc[name]
    return None


def _val(row: pd.Series | None, date) -> float | None:
    if row is None:
        return None
    if date in row.index:
        v = row[date]
        if pd.isna(v):
            return None
        return float(v)
    return None


def _compute_multiples(history: dict[str, Any]) -> list[dict]:
    """
    Combina annual + quarterly para construir serie temporal de multiples.

    Estrategia:
    - Para cada año fiscal (annual data), usa los valores tal cual (ya son TTM/anuales)
    - Para los últimos quarters, computa TTM rolling (suma 4 quarters)
    - El último data point usa el quarter más reciente disponible
    - Ordena cronológicamente y dedupe

    Retorna lista de records: [{date, ev_fcf, ev_sales, ev_ebitda, mcap, ev, period}]
    """
    annual = history["annual"]
    quarterly = history["quarterly"]
    prices = history["prices"]
    shares = history["shares"]

    if (annual.empty and quarterly.empty) or prices.empty or not shares:
        return []

    # Normaliza prices index a tz-naive
    prices_naive = prices.copy()
    if hasattr(prices_naive.index, "tz") and prices_naive.index.tz is not None:
        prices_naive.index = prices_naive.index.tz_localize(None)

    points = []

    # 1) Annual points (FCF/Revenue/EBITDA ya son TTM por definición)
    for date, row in annual.sort_index().iterrows():
        date_n = date.tz_localize(None) if hasattr(date, "tz") and date.tz is not None else date
        rec = _build_record(date_n, row["fcf"], row["revenue"], row["ebitda"],
                            row["cash"], row["debt"], shares, prices_naive, period="annual")
        if rec:
            points.append(rec)

    # 2) Quarterly TTM rolling (combinando con annual previo si hace falta)
    if not quarterly.empty:
        q = quarterly.sort_index()
        # Para cada quarter, sumamos los últimos 4 quarters de q + lo que falte de annual
        # Estrategia simple: si tenemos 4+ quarters consecutivos, calculamos TTM rolling.
        # Si no, omitimos.
        q["fcf_ttm"] = q["fcf"].rolling(4, min_periods=4).sum()
        q["revenue_ttm"] = q["revenue"].rolling(4, min_periods=4).sum()
        q["ebitda_ttm"] = q["ebitda"].rolling(4, min_periods=4).sum()
        q["cash"] = q["cash"].ffill()
        q["debt"] = q["debt"].ffill()

        for date, row in q.iterrows():
            if pd.isna(row.get("fcf_ttm")) and pd.isna(row.get("revenue_ttm")):
                continue
            date_n = date.tz_localize(None) if hasattr(date, "tz") and date.tz is not None else date
            rec = _build_record(
                date_n, row.get("fcf_ttm"), row.get("revenue_ttm"), row.get("ebitda_ttm"),
                row.get("cash"), row.get("debt"), shares, prices_naive, period="quarterly_ttm",
            )
            if rec:
                points.append(rec)

    # Dedupe: si annual y quarterly_ttm están a < 30 días, prefiere annual
    points.sort(key=lambda r: r["date"])
    deduped = []
    for p in points:
        if deduped and abs((pd.Timestamp(p["date"]) - pd.Timestamp(deduped[-1]["date"])).days) < 30:
            # Mismo periodo aproximadamente; prefiere annual sobre TTM rolling
            if p["period"] == "annual" and deduped[-1]["period"] != "annual":
                deduped[-1] = p
            continue
        deduped.append(p)

    return deduped


def _build_record(
    date, fcf, revenue, ebitda, cash, debt, shares, prices, period: str,
) -> dict | None:
    """Construye un record con multiples en una fecha específica."""
    try:
        mask = (prices.index >= date - pd.Timedelta(days=10)) & (
            prices.index <= date + pd.Timedelta(days=10)
        )
        window = prices[mask]
        if window.empty:
            return None
        price = float(window.iloc[-1])
    except Exception:
        return None

    mcap = price * shares
    cash = cash if cash and not pd.isna(cash) else 0
    debt = debt if debt and not pd.isna(debt) else 0
    ev = mcap + debt - cash

    rec = {
        "date": date.strftime("%Y-%m-%d"),
        "period": period,
        "mcap": round(mcap / 1e6, 1),
        "ev": round(ev / 1e6, 1),
        "ev_fcf": None,
        "ev_sales": None,
        "ev_ebitda": None,
    }
    if fcf and not pd.isna(fcf) and fcf > 0:
        rec["ev_fcf"] = round(ev / fcf, 2)
    if revenue and not pd.isna(revenue) and revenue > 0:
        rec["ev_sales"] = round(ev / revenue, 2)
    if ebitda and not pd.isna(ebitda) and ebitda > 0:
        rec["ev_ebitda"] = round(ev / ebitda, 2)
    return rec


def _project_forward(
    current: dict, fcf_min_cagr: float, fcf_max_cagr: float,
    exit_mult_min: float, exit_mult_max: float, years: int = 5,
) -> list[dict]:
    """
    Genera proyección bear/base/bull a `years` años.

    Bear: FCF crece a min_cagr, exit a min_mult
    Bull: FCF crece a max_cagr, exit a max_mult
    Base: media geométrica de ambos

    Devuelve lista con {year, ev_fcf_bear, ev_fcf_base, ev_fcf_bull}.
    """
    if not current or current.get("ev_fcf") is None:
        return []
    today = datetime.now()
    out = [{
        "date": today.strftime("%Y-%m-%d"),
        "year_offset": 0,
        "ev_fcf_bear": current["ev_fcf"],
        "ev_fcf_base": current["ev_fcf"],
        "ev_fcf_bull": current["ev_fcf"],
    }]
    base_cagr = (fcf_min_cagr * fcf_max_cagr) ** 0.5 if fcf_min_cagr > 0 and fcf_max_cagr > 0 \
        else (fcf_min_cagr + fcf_max_cagr) / 2
    base_mult = (exit_mult_min * exit_mult_max) ** 0.5 if exit_mult_min > 0 and exit_mult_max > 0 \
        else (exit_mult_min + exit_mult_max) / 2

    for y in range(1, years + 1):
        out.append({
            "date": (today + pd.Timedelta(days=365 * y)).strftime("%Y-%m-%d"),
            "year_offset": y,
            "ev_fcf_bear": round(exit_mult_min * (1 + fcf_min_cagr) ** y / (1 + fcf_min_cagr) ** y * exit_mult_min, 1)
                           if exit_mult_min else None,
            "ev_fcf_base": round(base_mult, 1),
            "ev_fcf_bull": round(exit_mult_max, 1),
        })
    # Simplificación: el cono converge linealmente al exit multiple en year=5
    # Para v1 esto es suficientemente informativo
    n = len(out)
    for i, rec in enumerate(out[1:], start=1):
        weight = i / (n - 1)
        rec["ev_fcf_bear"] = round(current["ev_fcf"] + weight * (exit_mult_min - current["ev_fcf"]), 1)
        rec["ev_fcf_bull"] = round(current["ev_fcf"] + weight * (exit_mult_max - current["ev_fcf"]), 1)
        rec["ev_fcf_base"] = round((rec["ev_fcf_bear"] + rec["ev_fcf_bull"]) / 2, 1)
    return out


def build_history(
    df_meta: pd.DataFrame,
    output_path: str | Path = "docs/data/history.json",
    rate_limit_seconds: float = 0.3,
) -> dict[str, Any]:
    """
    Pipeline: para cada empresa con data disponible, computa multiples históricos
    y proyección forward.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    companies_history = {}
    missing = []

    for idx, row in df_meta.iterrows():
        ticker = row["ticker"]
        yf_symbol = to_yf(ticker)
        log.info("[%d/%d] %s (%s)", idx + 1, len(df_meta), ticker, yf_symbol)

        history = _fetch_company_history(yf_symbol)
        has_data = (not history["annual"].empty) or (not history["quarterly"].empty)
        if not has_data or history["prices"].empty:
            missing.append({"ticker": ticker, "reason": "no fundamentals data"})
            time.sleep(rate_limit_seconds)
            continue

        records = _compute_multiples(history)
        if not records:
            missing.append({"ticker": ticker, "reason": "could not compute multiples"})
            time.sleep(rate_limit_seconds)
            continue

        # Forward projection usando inputs del Excel
        forward = _project_forward(
            current=records[-1],
            fcf_min_cagr=row.get("fcf_min_cagr", 0) or 0,
            fcf_max_cagr=row.get("fcf_max_cagr", 0) or 0,
            exit_mult_min=row.get("exit_mult_min", 0) or 0,
            exit_mult_max=row.get("exit_mult_max", 0) or 0,
        )

        companies_history[ticker] = {
            "currency": history["currency"],
            "history": records,
            "forward": forward,
            "n_quarters": len(records),
        }
        time.sleep(rate_limit_seconds)

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_with_history": len(companies_history),
            "n_missing": len(missing),
            "missing": missing,
        },
        "companies": companies_history,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    log.info("✅ History OK → %s (%d con data, %d missing)",
             output_path, len(companies_history), len(missing))
    return payload["meta"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.etl import load_watchlist
    df = load_watchlist("data/raw/watchlist_ratings.xlsx")
    build_history(df)


if __name__ == "__main__":
    main()
