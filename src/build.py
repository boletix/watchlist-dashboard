"""
Build: orquesta ETL + enrichment + analytics y escribe JSON al frontend.

Output:
- docs/data/watchlist.json       (consumido por el frontend)
- data/processed/watchlist.json  (copia para inspección / git diff)

Formato del JSON:
{
  "meta": {
    "generated_at": "2026-04-19T10:30:00Z",
    "n_companies": 61,
    "source_file": "watchlist_ratings.xlsx",
    "validation_issues": [],
    "enrichment_stats": {"yfinance": 45, "stale": 16}
  },
  "kpis": { ... headline_kpis ... },
  "category_stats": [ ... ],
  "deltas": { ... cambios vs snapshot previo ... },
  "companies": [ { ...61 filas... } ]
}
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.analytics import (
    category_stats,
    compute_deltas,
    enrich as enrich_analytics,
    headline_kpis,
)
from src.enrich import apply_quotes, fetch_quotes
from src.etl import load_watchlist, validate

log = logging.getLogger(__name__)


def _to_jsonable(value):
    """Convierte tipos numpy/pandas a JSON-friendly. Preserva None para NaN."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value) if not isinstance(value, (list, dict)) else False:
        return None
    return value


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convierte DataFrame a lista de dicts con NaN → None."""
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col, val in row.items():
            try:
                rec[col] = _to_jsonable(val)
            except (TypeError, ValueError):
                rec[col] = str(val) if val is not None else None
        records.append(rec)
    return records


def load_previous_snapshot(snapshots_dir: Path) -> pd.DataFrame | None:
    """Carga el snapshot más reciente si existe."""
    if not snapshots_dir.exists():
        return None
    snapshots = sorted(snapshots_dir.glob("*_watchlist.json"))
    if not snapshots:
        return None
    latest = snapshots[-1]
    log.info("Snapshot previo: %s", latest.name)
    try:
        with open(latest) as f:
            data = json.load(f)
        return pd.DataFrame(data.get("companies", []))
    except Exception as e:
        log.warning("No se pudo leer snapshot previo: %s", e)
        return None


def build(
    xlsx_path: str | Path = "data/raw/watchlist_ratings.xlsx",
    output_dir: str | Path = "docs/data",
    processed_dir: str | Path = "data/processed",
    snapshots_dir: str | Path = "data/snapshots",
    skip_enrichment: bool = False,
    skip_backtest: bool = False,
    skip_history: bool = False,
    skip_alerts: bool = False,
) -> dict:
    """Pipeline completo. Devuelve el dict de meta."""
    xlsx_path = Path(xlsx_path)
    output_dir = Path(output_dir)
    processed_dir = Path(processed_dir)
    snapshots_dir = Path(snapshots_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # 1. ETL
    df = load_watchlist(xlsx_path)
    issues = validate(df)
    if issues:
        log.warning("Validación con %d issues: %s", len(issues), issues)

    # 2. Enrichment (yfinance)
    enrich_stats = {"yfinance": 0, "stale": len(df), "skipped": 0}
    if not skip_enrichment:
        quotes = fetch_quotes(df["ticker"].tolist())
        df = apply_quotes(df, quotes)
        enrich_stats = {
            "yfinance": int((df["price_source"] == "yfinance").sum()),
            "stale": int((df["price_source"] == "stale").sum()),
            "skipped": int((df["price_source"] == "skipped").sum()),
        }
    else:
        df["price_source"] = "manual"

    # 3. Analytics
    df = enrich_analytics(df)

    # 4. Deltas vs snapshot previo
    prev_df = load_previous_snapshot(snapshots_dir)
    deltas = compute_deltas(df, prev_df)

    # 5. KPIs y stats
    kpis = headline_kpis(df)
    cat_stats = category_stats(df)

    # 6. Meta
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_companies": len(df),
        "source_file": xlsx_path.name,
        "validation_issues": issues,
        "enrichment_stats": enrich_stats,
    }

    # 7a. Inyectar earnings dates desde data/earnings.json (fuente canónica)
    earnings_path = Path("data/earnings.json")
    earnings_map: dict = {}
    if earnings_path.exists():
        with open(earnings_path, encoding="utf-8") as f:
            earnings_raw = json.load(f)
        earnings_map = earnings_raw.get("companies", {})
        log.info("📅 earnings.json: %d tickers cargados", len(earnings_map))
    else:
        log.warning("data/earnings.json no encontrado — earnings fields omitidos")

    companies_records = df_to_records(df)
    for rec in companies_records:
        ticker = rec.get("ticker", "")
        ed = earnings_map.get(ticker, {})
        rec["earnings_last_date"]  = ed.get("earnings_last_date")
        rec["earnings_next_date"]  = ed.get("earnings_next_date")
        rec["earnings_updated_at"] = ed.get("earnings_updated_at")

    # 7. Construir payload del watchlist principal
    payload = {
        "meta": meta,
        "kpis": kpis,
        "category_stats": cat_stats,
        "deltas": deltas,
        "companies": companies_records,
    }

    # 8. Escribir watchlist.json
    target_frontend = output_dir / "watchlist.json"
    target_processed = processed_dir / "watchlist.json"
    with open(target_frontend, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    shutil.copy(target_frontend, target_processed)
    log.info("✅ watchlist.json → %s (%d empresas)", target_frontend, len(df))

    # 9. Backtest (Q4): NAVs vs benchmarks desde 2020
    if not skip_backtest:
        try:
            from src.backtest import build_backtest
            backtest_meta = build_backtest(df, output_path=output_dir / "backtest.json")
            meta["backtest"] = backtest_meta
        except Exception as e:
            log.error("❌ Backtest falló: %s", e)
            meta["backtest_error"] = str(e)

    # 10. History (Q3): multiples evolution
    if not skip_history:
        try:
            from src.history import build_history
            history_meta = build_history(df, output_path=output_dir / "history.json")
            meta["history"] = history_meta
        except Exception as e:
            log.error("❌ History falló: %s", e)
            meta["history_error"] = str(e)

    # 11. Alerts: detectar eventos vs snapshot previo
    if not skip_alerts:
        try:
            from src.alerts import detect_alerts, write_alerts_json, notify_email, notify_whatsapp
            alerts = detect_alerts(df, prev_df)
            write_alerts_json(alerts, output_path=output_dir / "alerts.json")
            meta["n_alerts"] = len(alerts)
            # Notificaciones (silentes si no hay credenciales)
            notify_email(alerts)
            notify_whatsapp(alerts)
        except Exception as e:
            log.error("❌ Alerts falló: %s", e)
            meta["alerts_error"] = str(e)

    log.info(
        "✅ Build completo (%s) — empresas: %d, alerts: %d",
        meta["generated_at"], len(df), meta.get("n_alerts", 0),
    )
    return meta


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build watchlist dashboard JSON")
    parser.add_argument("--xlsx", default="data/raw/watchlist_ratings.xlsx")
    parser.add_argument("--out", default="docs/data")
    parser.add_argument("--skip-enrichment", action="store_true",
                        help="Omitir yfinance price refresh (más rápido)")
    parser.add_argument("--skip-backtest", action="store_true",
                        help="Omitir backtest (Q4) — descarga ~5min")
    parser.add_argument("--skip-history", action="store_true",
                        help="Omitir historical multiples (Q3) — descarga ~10min")
    parser.add_argument("--skip-alerts", action="store_true",
                        help="Omitir generación de alertas")
    parser.add_argument("--quick", action="store_true",
                        help="Solo watchlist principal (skip backtest, history, alerts)")
    args = parser.parse_args()
    if args.quick:
        args.skip_backtest = True
        args.skip_history = True
        args.skip_alerts = True
    build(
        xlsx_path=args.xlsx,
        output_dir=args.out,
        skip_enrichment=args.skip_enrichment,
        skip_backtest=args.skip_backtest,
        skip_history=args.skip_history,
        skip_alerts=args.skip_alerts,
    )


if __name__ == "__main__":
    main()
