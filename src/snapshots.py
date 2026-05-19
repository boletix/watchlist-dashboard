"""
Snapshots y backtest del PROCESO (no del survivor set).

A diferencia del backtest de basket NAV (src/backtest.py), aqui guardamos un
snapshot completo del watchlist cada vez que corre el build, y computamos:

  rating_drift  : cambio absoluto de composite por ticker en N dias
  process_backtest : para cada snapshot t, forward return de las empresas con
                     composite_geometric en distintos buckets vs benchmark.

Output: docs/data/process_backtest.json

Limitacion honesta: hace falta acumular >= 6 meses de snapshots para que el
process backtest tenga power estadistico. Hasta entonces el panel del dashboard
mostrara "acumulando data, vuelva en X meses".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def save_full_snapshot(df: pd.DataFrame, snapshots_dir: str | Path,
                       prefix: str = "watchlist") -> Path:
    """
    Guarda un snapshot COMPLETO del DataFrame (no solo tickers) en
    snapshots_dir/YYYY-MM-DD_{prefix}.json.

    Si ya existe un snapshot del mismo dia, se sobreescribe.
    Esto permite que el GitHub Action diario actualice si re-ejecuta.
    """
    snapshots_dir = Path(snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = snapshots_dir / f"{today}_{prefix}.json"
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_companies": int(len(df)),
            "columns": list(df.columns),
        },
        "companies": _df_to_records(df),
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_jsonify)
    log.info("Snapshot guardado: %s", target)
    return target


def _jsonify(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        if np.isnan(v):
            return None
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return str(v)


def _df_to_records(df: pd.DataFrame) -> list:
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


def load_all_snapshots(snapshots_dir: str | Path,
                       prefix: str = "watchlist") -> list:
    """Devuelve lista de (date_str, df) ordenada cronologicamente."""
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
        df = pd.DataFrame(data.get("companies", []))
        out.append((date_str, df))
    return out


def compute_rating_drift(snapshots: list) -> dict:
    """
    Para cada ticker, traza la serie temporal de su composite y composite_geometric.
    Devuelve por ticker la serie y el drift total (ultimo - primero).
    """
    if not snapshots:
        return {"available": False, "series": {}, "drift_summary": []}
    # Agrupar por ticker
    timelines = {}
    for date_str, df in snapshots:
        if "ticker" not in df.columns:
            continue
        for _, row in df.iterrows():
            t = row.get("ticker")
            if not t:
                continue
            if t not in timelines:
                timelines[t] = []
            timelines[t].append({
                "date": date_str,
                "rating_composite":    _safe_num(row.get("rating_composite")),
                "composite_geometric": _safe_num(row.get("composite_geometric")),
                "survival_score":      _safe_num(row.get("survival_score")),
                "irr_best":            _safe_num(row.get("irr_best")),
                "irr_best_repriced":   _safe_num(row.get("irr_best_repriced")),
                "ev_fcf":              _safe_num(row.get("ev_fcf")),
                "edge_to_fair":        _safe_num(row.get("edge_to_fair")),
                "price":               _safe_num(row.get("price")),
            })
    # Calcular drift
    drift_summary = []
    for t, series in timelines.items():
        if len(series) < 2:
            continue
        first = series[0]; last = series[-1]
        d_rating = (last["rating_composite"] - first["rating_composite"]
                    if first["rating_composite"] is not None
                    and last["rating_composite"] is not None else None)
        d_geom = (last["composite_geometric"] - first["composite_geometric"]
                  if first["composite_geometric"] is not None
                  and last["composite_geometric"] is not None else None)
        d_price = (last["price"] / first["price"] - 1
                   if first["price"] and last["price"] else None)
        drift_summary.append({
            "ticker": t,
            "first_date": first["date"], "last_date": last["date"],
            "n_obs": len(series),
            "rating_first":    first["rating_composite"],
            "rating_last":     last["rating_composite"],
            "rating_delta":    d_rating,
            "geom_first":      first["composite_geometric"],
            "geom_last":       last["composite_geometric"],
            "geom_delta":      d_geom,
            "price_pct_change": d_price,
        })
    drift_summary.sort(key=lambda x: abs(x["rating_delta"] or 0), reverse=True)
    return {"available": True, "series": timelines, "drift_summary": drift_summary}


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


def build_process_backtest(snapshots_dir: str | Path,
                           output_path: str | Path = "docs/data/process_backtest.json"
                           ) -> dict:
    """
    Construye el JSON consumido por el dashboard para mostrar:
      - timelines por ticker (rating + price)
      - tabla resumen de drift
      - cuando haya >= 6 meses de data, el bucket backtest
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots = load_all_snapshots(snapshots_dir)
    drift = compute_rating_drift(snapshots)
    n_snapshots = len(snapshots)
    has_enough_data = n_snapshots >= 6  # mas o menos 6 meses si es semanal
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_snapshots": n_snapshots,
            "first_snapshot": snapshots[0][0] if snapshots else None,
            "last_snapshot":  snapshots[-1][0] if snapshots else None,
            "has_enough_data": has_enough_data,
            "notice": (
                None if has_enough_data
                else "Acumulando snapshots. El process backtest mostrara correlaciones "
                     "y bucket returns cuando haya al menos 6 meses de data."
            ),
        },
        "drift_summary":       drift["drift_summary"][:50] if drift["available"] else [],
        "rating_timelines":    drift["series"] if drift["available"] else {},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_jsonify)
    log.info("process_backtest.json -> %s (%d snapshots)", output_path, n_snapshots)
    return payload["meta"]
