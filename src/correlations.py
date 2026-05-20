"""Correlaciones de retornos diarios + clusters jerarquicos (diversificacion)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.tickers import to_yf

log = logging.getLogger(__name__)


def _download_returns(yf_symbols, start_period="1y"):
    import yfinance as yf
    raw = yf.download(" ".join(yf_symbols), period=start_period,
                      progress=False, auto_adjust=True, threads=True, group_by="column")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = yf_symbols
    bad = [c for c in close.columns if close[c].isna().all()]
    if bad:
        close = close.drop(columns=bad)
    return close.pct_change().dropna(how="all")


def _hierarchical_clusters(corr_matrix, threshold=0.75):
    try:
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import squareform
    except ImportError:
        log.warning("scipy no disponible - skip clustering")
        return {}
    tickers = corr_matrix.columns.tolist()
    if len(tickers) < 3:
        return {t: 0 for t in tickers}
    dist = 1.0 - corr_matrix.abs().values
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2.0
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=1.0 - threshold, criterion="distance")
    return {t: int(c) for t, c in zip(tickers, labels)}


def _redundant_with(corr_matrix, threshold=0.75):
    out = {}
    for t in corr_matrix.columns:
        peers = []
        for u in corr_matrix.columns:
            if u == t:
                continue
            c = corr_matrix.loc[t, u]
            if pd.isna(c):
                continue
            if abs(c) > threshold:
                peers.append({"ticker": u, "corr": round(float(c), 3)})
        peers.sort(key=lambda x: abs(x["corr"]), reverse=True)
        out[t] = peers[:5]
    return out


def build_correlations(df_meta, output_path="docs/data/correlations.json"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    excel_tickers = df_meta["ticker"].tolist()
    yf_tickers = [to_yf(t) for t in excel_tickers]
    yf_to_excel = dict(zip(yf_tickers, excel_tickers))

    try:
        returns_1y = _download_returns(yf_tickers, start_period="1y")
    except Exception as e:
        log.error("No se pudo descargar retornos: %s", e)
        payload = {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "error": str(e)},
                   "tickers": [], "matrix_1y": [], "clusters": {}, "redundant_with": {}}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return payload["meta"]

    valid_yf = [c for c in returns_1y.columns if c in yf_to_excel]
    returns_1y = returns_1y[valid_yf]
    returns_1y.columns = [yf_to_excel[c] for c in returns_1y.columns]
    corr_1y = returns_1y.corr()

    clusters = _hierarchical_clusters(corr_1y, threshold=0.75)
    redundant = _redundant_with(corr_1y, threshold=0.75)
    tickers = corr_1y.columns.tolist()
    matrix = corr_1y.round(3).fillna(0).values.tolist()

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_tickers": len(tickers),
            "n_clusters": len(set(clusters.values())) if clusters else 0,
            "redundant_threshold": 0.75,
        },
        "tickers": tickers,
        "matrix_1y": matrix,
        "clusters": clusters,
        "redundant_with": redundant,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("correlations.json -> %s (%d tickers, %d clusters)",
             output_path, len(tickers), payload["meta"]["n_clusters"])
    return payload["meta"]
