"""
Analytics: calcula métricas derivadas a partir del DataFrame ETL.

Añade columnas:
- irr_asymmetry_ratio      : (best - worst) / max(|worst|, 0.05). Cap a [-10, 50].
- irr_spread               : best - worst (en puntos porcentuales absolutos).
- quadrant                 : {hunting_ground, wonderful_expensive, value_trap, avoid}
                             según Composite ≥ 7.5 y EV/FCF ≤ 20.
- rating_tier              : {best_in_class, high, above_avg, mixed, low}
- roic_zscore_by_category  : z-score del ROIC dentro de su categoría.
- ev_fcf_zscore_by_category: z-score de EV/FCF dentro de su categoría.
- composite_rank           : ranking global por composite (1 = mejor).

Calcula también:
- category_stats           : dict con aggregaciones por categoría.
- headline_kpis            : KPIs para la cintilla superior.
- deltas vs snapshot previo: si se provee snapshot anterior.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Umbrales del Quality-Value Quadrant
COMPOSITE_HIGH_QUALITY = 7.5
EV_FCF_REASONABLE = 20.0

# Tiers según framework del Excel
TIER_THRESHOLDS = [
    (8.0, "best_in_class"),
    (7.0, "high"),
    (6.0, "above_avg"),
    (5.0, "mixed"),
    (-float("inf"), "low"),
]


def _irr_asymmetry_ratio(worst: float, best: float) -> float:
    """
    Ratio de asimetría: ganancia potencial por unidad de pérdida potencial.

    Si worst > 0 (caso base positivo), la asimetría es "pura upside".
    Si worst ≈ 0, usamos floor de 5 % para evitar divisiones explosivas.
    """
    if pd.isna(worst) or pd.isna(best):
        return np.nan
    floor = max(abs(worst), 0.05)
    ratio = (best - worst) / floor
    return float(np.clip(ratio, -10, 50))


def _classify_quadrant(rating: float, ev_fcf: float) -> str:
    if pd.isna(rating) or pd.isna(ev_fcf):
        return "unknown"
    high_q = rating >= COMPOSITE_HIGH_QUALITY
    cheap = ev_fcf <= EV_FCF_REASONABLE
    # EV/FCF negativo = FCF negativo → no es "barato", es "sin FCF"
    if ev_fcf < 0:
        cheap = False
    if high_q and cheap:
        return "hunting_ground"
    if high_q and not cheap:
        return "wonderful_expensive"
    if not high_q and cheap:
        return "value_trap"
    return "avoid"


def _classify_tier(composite: float) -> str:
    if pd.isna(composite):
        return "unknown"
    for threshold, tier in TIER_THRESHOLDS:
        if composite >= threshold:
            return tier
    return "low"


def _zscore_by_group(s: pd.Series, g: pd.Series) -> pd.Series:
    """Z-score de `s` dentro de cada grupo de `g`. Si el grupo tiene 1 solo elemento
    o std=0, devuelve 0."""
    def z(x):
        if len(x) < 2 or x.std(ddof=0) == 0:
            return pd.Series(0.0, index=x.index)
        return (x - x.mean()) / x.std(ddof=0)

    return s.groupby(g).transform(z).fillna(0.0)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Añade métricas derivadas al DataFrame."""
    out = df.copy()

    # IRR asymmetry
    out["irr_spread"] = out["irr_best"] - out["irr_worst"]
    out["irr_asymmetry_ratio"] = out.apply(
        lambda r: _irr_asymmetry_ratio(r["irr_worst"], r["irr_best"]), axis=1
    )

    # Quadrant & tier
    out["quadrant"] = out.apply(
        lambda r: _classify_quadrant(r["rating_composite"], r["ev_fcf"]), axis=1
    )
    out["rating_tier"] = out["rating_composite"].apply(_classify_tier)

    # Z-scores por categoría
    if "category" in out.columns:
        if "roic" in out.columns:
            out["roic_zscore_by_category"] = _zscore_by_group(
                out["roic"], out["category"]
            )
        if "ev_fcf" in out.columns:
            out["ev_fcf_zscore_by_category"] = _zscore_by_group(
                out["ev_fcf"].where(out["ev_fcf"] > 0), out["category"]
            ).fillna(0.0)

    # Ranking global por composite
    out["composite_rank"] = out["rating_composite"].rank(
        method="min", ascending=False
    ).astype("Int64")

    return out


def category_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Agregaciones por categoría: count, avg rating, avg ROIC, avg EV/FCF."""
    if "category" not in df.columns:
        return []
    agg = (
        df.groupby("category")
        .agg(
            count=("ticker", "count"),
            avg_composite=("rating_composite", "mean"),
            avg_roic=("roic", "mean"),
            median_ev_fcf=("ev_fcf", "median"),
            avg_irr_best=("irr_best", "mean"),
            avg_irr_worst=("irr_worst", "mean"),
        )
        .reset_index()
        .round(4)
    )
    return agg.to_dict(orient="records")


def headline_kpis(df: pd.DataFrame) -> dict[str, Any]:
    """KPIs para la cintilla superior."""
    if "market_cap_m" in df.columns and "roic" in df.columns:
        mask = df["market_cap_m"].notna() & df["roic"].notna()
        if mask.any():
            roic_weighted = (
                df.loc[mask, "roic"] * df.loc[mask, "market_cap_m"]
            ).sum() / df.loc[mask, "market_cap_m"].sum()
        else:
            roic_weighted = float("nan")
    else:
        roic_weighted = float("nan")

    kpis = {
        "n_companies": int(len(df)),
        "avg_composite": float(df["rating_composite"].mean()),
        "median_composite": float(df["rating_composite"].median()),
        "weighted_avg_roic": float(roic_weighted),
        "median_ev_fcf": float(df.loc[df["ev_fcf"] > 0, "ev_fcf"].median()),
        "pct_best_irr_gt_15pct": float((df["irr_best"] > 0.15).mean() * 100),
        "n_top_tier": int((df["rating_composite"] >= 7.5).sum()),
        "n_hunting_ground": int((df.get("quadrant") == "hunting_ground").sum())
        if "quadrant" in df.columns
        else 0,
        "pct_positive_worst_irr": float((df["irr_worst"] > 0).mean() * 100),
    }
    return kpis


def compute_deltas(
    current: pd.DataFrame, previous: pd.DataFrame | None
) -> dict[str, Any]:
    """
    Compara snapshot actual con anterior (si existe).
    Devuelve: cambios de rating, nuevas empresas, salidas, price moves.
    """
    if previous is None or previous.empty:
        return {"available": False}

    curr = current.set_index("ticker")
    prev = previous.set_index("ticker")

    entered = list(set(curr.index) - set(prev.index))
    exited = list(set(prev.index) - set(curr.index))

    common = list(set(curr.index) & set(prev.index))
    rating_changes = []
    for t in common:
        delta = curr.loc[t, "rating_composite"] - prev.loc[t, "rating_composite"]
        if abs(delta) >= 0.1:
            rating_changes.append(
                {
                    "ticker": t,
                    "name": curr.loc[t].get("name", t),
                    "from": round(float(prev.loc[t, "rating_composite"]), 2),
                    "to": round(float(curr.loc[t, "rating_composite"]), 2),
                    "delta": round(float(delta), 2),
                }
            )
    rating_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

    return {
        "available": True,
        "entered": entered,
        "exited": exited,
        "rating_changes": rating_changes[:20],
    }
