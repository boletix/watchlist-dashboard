"""Snapshots completos + backtest del PROCESO (rating drift)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _jsonify(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return str(v)


def _df_to_records(df):
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col, val in row.items():
            if val is None:
                rec[col] = None
                continue
            try:
                if pd.isna(val):
                    rec[col] = None
                    continue
            except Exception:
                pass
            try:
                rec[col] = _jsonify(val)
            except Exception:
                rec[col] = str(val)
        records.append(rec)
    return records


def save_full_snapshot(df, snapshots_dir, prefix="watchlist"):
    snapshots_dir = Path(snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = snapshots_dir / f"{today}_{prefix}.json"
    payload = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "n_companies": int(len(df)), "columns": list(df.columns)},
        "companies": _df_to_records(df),
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_jsonify)
    log.info("Snapshot guardado: %s", target)
    return target


def load_all_snapshots(snapshots_dir, prefix="watchlist"):
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.exists():
        return []
    out = []
    for f in sorted(snapshots_dir.glob(f"*_{prefix}.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except Exception as e:
            log.warning("No se pudo leer %s: %s", f, e)
            continue
        date_str = f.stem.split("_")[0]
        out.append((date_str, pd.DataFrame(data.get("companies", []))))
    return out


def _safe_num(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except Exception:
        return None


def compute_rating_drift(snapshots):
    if not snapshots:
        return {"available": False, "series": {}, "drift_summary": []}
    timelines = {}
    for date_str, df in snapshots:
        if "ticker" not in df.columns:
            continue
        for _, row in df.iterrows():
            t = row.get("ticker")
            if not t:
                continue
            timelines.setdefault(t, []).append({
                "date": date_str,
                "rating_composite": _safe_num(row.get("rating_composite")),
                "composite_geometric": _safe_num(row.get("composite_geometric")),
                "survival_score": _safe_num(row.get("survival_score")),
                "score_v2": _safe_num(row.get("score_v2")),
                "irr_best_repriced": _safe_num(row.get("irr_best_repriced")),
                "ev_fcf": _safe_num(row.get("ev_fcf")),
                "edge_to_fair": _safe_num(row.get("edge_to_fair")),
                "price": _safe_num(row.get("price")),
            })
    drift_summary = []
    for t, series in timelines.items():
        if len(series) < 2:
            continue
        first = series[0]; last = series[-1]
        d_rating = (last["rating_composite"] - first["rating_composite"]
                    if first["rating_composite"] is not None and last["rating_composite"] is not None else None)
        d_geom = (last["composite_geometric"] - first["composite_geometric"]
                  if first["composite_geometric"] is not None and last["composite_geometric"] is not None else None)
        d_price = (last["price"] / first["price"] - 1 if first["price"] and last["price"] else None)
        drift_summary.append({
            "ticker": t, "first_date": first["date"], "last_date": last["date"], "n_obs": len(series),
            "rating_first": first["rating_composite"], "rating_last": last["rating_composite"],
            "rating_delta": d_rating, "geom_first": first["composite_geometric"],
            "geom_last": last["composite_geometric"], "geom_delta": d_geom,
            "price_pct_change": d_price,
        })
    drift_summary.sort(key=lambda x: abs(x["rating_delta"] or 0), reverse=True)
    return {"available": True, "series": timelines, "drift_summary": drift_summary}


def build_process_backtest(snapshots_dir, output_path="docs/data/process_backtest.json"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots = load_all_snapshots(snapshots_dir)
    drift = compute_rating_drift(snapshots)
    n_snapshots = len(snapshots)
    has_enough = n_snapshots >= 6
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_snapshots": n_snapshots,
            "first_snapshot": snapshots[0][0] if snapshots else None,
            "last_snapshot": snapshots[-1][0] if snapshots else None,
            "has_enough_data": has_enough,
            "notice": (None if has_enough else
                       "Acumulando snapshots. El process backtest mostrara bucket returns "
                       "cuando haya al menos 6 meses de data."),
        },
        "drift_summary": drift["drift_summary"][:50] if drift["available"] else [],
        "rating_timelines": drift["series"] if drift["available"] else {},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_jsonify)
    log.info("process_backtest.json -> %s (%d snapshots)", output_path, n_snapshots)
    return payload["meta"]
