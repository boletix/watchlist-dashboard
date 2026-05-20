"""
Analytics v2.0 - Asymmetry & Terminal Safety
============================================

Mantiene compatibilidad con el frontend antiguo (todas las columnas legacy
siguen existiendo) y agrega nuevas metricas que reflejan la filosofia
explicita del inversor: largo plazo, asimetria positiva, riesgo de valor
terminal = 0.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

COMPOSITE_HIGH_QUALITY = 7.5
EV_FCF_REASONABLE = 20.0

TIER_THRESHOLDS = [
    (8.0, "best_in_class"),
    (7.0, "high"),
    (6.0, "above_avg"),
    (5.0, "mixed"),
    (-float("inf"), "low"),
]

# Escalas REALES del Excel (verificadas leyendo headers + min/max):
#   r3_durability         : [0, 15]   (mayor = mejor)
#   r3_risk_disappear     : [-20, 0]  (mas cerca de 0 = mejor; penalizacion)
#   r3_terminal_risk      : [-20, 0]  (mas cerca de 0 = mejor; penalizacion)
#   r3_capital_intensity  : [0, 10]
#   r3_capital_alloc      : [0, 15]
#   r3_financing          : [-10, 5]
#   r3_incentives         : [0, 10]
#   r3_moat_structural    : [0, 15]
R3_SCALES = {
    "r3_durability":         (0,   15),
    "r3_risk_disappear":     (-20, 0),
    "r3_capital_intensity":  (0,   10),
    "r3_capital_alloc":      (0,   15),
    "r3_financing":          (-10, 5),
    "r3_incentives":         (0,   10),
    "r3_moat_structural":    (0,   15),
    "r3_terminal_risk":      (-20, 0),
}

SURVIVAL_SUBSCORES = ["r3_durability", "r3_risk_disappear", "r3_terminal_risk"]

KILL_SURVIVAL_THRESHOLD = 0.50
KILL_TERMINAL_THRESHOLD = -10.0


def _adaptive_evfcf_cutoff(composite):
    if pd.isna(composite):
        return EV_FCF_REASONABLE
    if composite >= 8.5:
        return 35.0
    if composite >= 7.5:
        return 25.0
    if composite >= 7.0:
        return 20.0
    return 15.0


def _irr_asymmetry_ratio(worst, best):
    if pd.isna(worst) or pd.isna(best):
        return np.nan
    floor = max(abs(worst), 0.05)
    ratio = (best - worst) / floor
    return float(np.clip(ratio, -10, 50))


def _classify_quadrant(rating, ev_fcf):
    if pd.isna(rating) or pd.isna(ev_fcf):
        return "unknown"
    high_q = rating >= COMPOSITE_HIGH_QUALITY
    cheap = ev_fcf <= EV_FCF_REASONABLE
    if ev_fcf < 0:
        cheap = False
    if high_q and cheap:
        return "hunting_ground"
    if high_q and not cheap:
        return "wonderful_expensive"
    if not high_q and cheap:
        return "value_trap"
    return "avoid"


def _classify_tier(composite):
    if pd.isna(composite):
        return "unknown"
    for threshold, tier in TIER_THRESHOLDS:
        if composite >= threshold:
            return tier
    return "low"


def _zscore_by_group(s, g):
    def z(x):
        if len(x) < 2 or x.std(ddof=0) == 0:
            return pd.Series(0.0, index=x.index)
        return (x - x.mean()) / x.std(ddof=0)
    return s.groupby(g).transform(z).fillna(0.0)


def _norm_subscore(value, scale):
    if value is None or pd.isna(value):
        return None
    mn, mx = scale
    if mx == mn:
        return None
    v = max(min(float(value), mx), mn)
    return (v - mn) / (mx - mn)


def _survival_score(row):
    parts = []
    for k in SURVIVAL_SUBSCORES:
        n = _norm_subscore(row.get(k), R3_SCALES[k])
        if n is None:
            return np.nan
        parts.append(n)
    return sum(parts) / len(parts)


def _quality_score(row):
    r1 = row.get("rating_1"); r2 = row.get("rating_2")
    if pd.isna(r1) or pd.isna(r2):
        return np.nan
    return (float(r1) + float(r2)) / 20.0


def _composite_geometric(quality, survival):
    if pd.isna(quality) or pd.isna(survival):
        return np.nan
    q = max(quality, 1e-6); s = max(survival, 1e-6)
    g = (q ** (2 / 3)) * (s ** (1 / 3))
    return float(g * 10.0)


def _kill_flag(row, survival):
    if pd.isna(survival):
        return False
    if survival < KILL_SURVIVAL_THRESHOLD:
        return True
    tr = row.get("r3_terminal_risk")
    if tr is not None and not pd.isna(tr) and tr < KILL_TERMINAL_THRESHOLD:
        return True
    return False


def _rating_dispersion(row):
    vals = []
    for k in ("rating_1", "rating_2", "rating_3"):
        v = row.get(k)
        if v is not None and not pd.isna(v):
            vals.append(float(v))
    if len(vals) < 2:
        return np.nan
    return float(np.std(vals, ddof=0))



def _safe_float(x):
    """Convierte a float manejando comas como separadores de miles."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except (ValueError, TypeError):
        try:
            return float(str(x).replace(",", "").replace(" ", "").replace("'", ""))
        except Exception:
            return None


def _reprice_valuation(row):
    out = {"fve_min_repriced": np.nan, "fve_max_repriced": np.nan,
           "irr_worst_repriced": np.nan, "irr_best_repriced": np.nan}
    _v = _safe_float
    price = _v(row.get("price")); shares = _v(row.get("shares_out_m"))
    cash = _v(row.get("cash")); debt = _v(row.get("total_debt"))
    fcf_min = _v(row.get("fcf_5y_min")); fcf_max = _v(row.get("fcf_5y_max"))
    em_min = _v(row.get("exit_mult_min")); em_max = _v(row.get("exit_mult_max"))
    if any(v is None for v in (price, shares, cash, debt)):
        return out
    if price <= 0 or shares <= 0:
        return out
    if fcf_min is not None and em_min is not None:
        fve_min = (fcf_min * em_min + cash - debt) / shares
        out["fve_min_repriced"] = float(fve_min)
        if fve_min > 0:
            out["irr_worst_repriced"] = float((fve_min / price) ** (1 / 5) - 1)
        else:
            out["irr_worst_repriced"] = -0.99
    if fcf_max is not None and em_max is not None:
        fve_max = (fcf_max * em_max + cash - debt) / shares
        out["fve_max_repriced"] = float(fve_max)
        if fve_max > 0:
            out["irr_best_repriced"] = float((fve_max / price) ** (1 / 4) - 1)
        else:
            out["irr_best_repriced"] = -0.99
    return out


def _quality_adjusted_multiple(row):
    out = {"ev_nopat": np.nan, "quality_multiple_a": np.nan,
           "quality_multiple_b": np.nan, "quality_adjusted_multiple": np.nan}
    _v = _safe_float
    ev = _v(row.get("ev")); nopat = _v(row.get("nopat_ltm"))
    roic = _v(row.get("roic")); ev_fcf = _v(row.get("ev_fcf"))
    g_min = _v(row.get("fcf_min_cagr")); g_max = _v(row.get("fcf_max_cagr"))
    durab = _v(row.get("r3_durability"))
    if ev is not None and nopat is not None and nopat > 0:
        out["ev_nopat"] = ev / nopat
        if roic is not None and roic > 0.01:
            out["quality_multiple_a"] = (ev / nopat) / (roic * 100)
    if ev_fcf is not None and ev_fcf > 0:
        if g_min is not None and g_max is not None and g_min > 0 and g_max > 0:
            g_base = (g_min * g_max) ** 0.5
        elif g_min is not None and g_max is not None:
            g_base = (g_min + g_max) / 2
        else:
            g_base = None
        duration_years = max(3.0, (durab / 15.0) * 10.0) if durab is not None else 5.0
        if g_base is not None and g_base > -0.5:
            denom = g_base + 1.0 / duration_years
            if denom > 0:
                out["quality_multiple_b"] = ev_fcf / (denom * 100)
    a, b = out["quality_multiple_a"], out["quality_multiple_b"]
    if a is not None and not pd.isna(a) and b is not None and not pd.isna(b):
        out["quality_adjusted_multiple"] = 0.5 * a + 0.5 * b
    elif a is not None and not pd.isna(a):
        out["quality_adjusted_multiple"] = a
    elif b is not None and not pd.isna(b):
        out["quality_adjusted_multiple"] = b
    return out


def _edge_to_fair(row):
    price = row.get("price")
    fmin = row.get("fve_min_repriced"); fmax = row.get("fve_max_repriced")
    if pd.isna(price) or price <= 0 or pd.isna(fmin) or pd.isna(fmax):
        return np.nan
    if fmin <= 0 or fmax <= 0:
        return np.nan
    fve_base = (fmin * fmax) ** 0.5
    return float(fve_base / price - 1.0)


def _quality_zone(row):
    rating = row.get("rating_composite"); ev_fcf = row.get("ev_fcf")
    kill = bool(row.get("kill_flag", False))
    if pd.isna(rating) or pd.isna(ev_fcf):
        return "unknown"
    if kill:
        return "avoid"
    cutoff = _adaptive_evfcf_cutoff(rating)
    high_q = rating >= COMPOSITE_HIGH_QUALITY
    cheap = (0 < ev_fcf <= cutoff)
    if high_q and cheap:
        return "hunting_ground"
    if high_q and not cheap:
        return "wonderful_expensive"
    if not high_q and cheap:
        return "value_trap"
    return "avoid"


def _kelly_fractional(row, fraction=0.25, p_win=0.55):
    best = row.get("irr_best_repriced")
    if best is None or pd.isna(best):
        best = row.get("irr_best")
    worst = row.get("irr_worst_repriced")
    if worst is None or pd.isna(worst):
        worst = row.get("irr_worst")
    if best is None or worst is None or pd.isna(best) or pd.isna(worst):
        return np.nan
    if best <= 0:
        return 0.0
    a = abs(worst); b = best
    if a < 1e-6:
        return float(fraction * 1.0)
    f_star = (p_win * (b / a) - (1 - p_win)) / (b / a)
    return float(max(0.0, fraction * f_star))


def _suggested_weight(row):
    k = row.get("kelly_fraction"); s = row.get("survival_score")
    if k is None or s is None or pd.isna(k) or pd.isna(s):
        return np.nan
    w = k * s
    return float(min(max(w, 0.0), 0.10))


def _ols_slope_significance(years, values):
    if len(years) != len(values) or len(years) < 3:
        return (float("nan"), float("nan"))
    x = np.asarray(years, dtype=float); y = np.asarray(values, dtype=float)
    mask = ~np.isnan(x) & ~np.isnan(y)
    if mask.sum() < 3:
        return (float("nan"), float("nan"))
    x, y = x[mask], y[mask]
    n = len(x)
    x_mean = x.mean(); y_mean = y.mean()
    Sxx = ((x - x_mean) ** 2).sum()
    if Sxx == 0:
        return (float("nan"), float("nan"))
    slope = ((x - x_mean) * (y - y_mean)).sum() / Sxx
    intercept = y_mean - slope * x_mean
    y_pred = intercept + slope * x
    resid = y - y_pred
    if n <= 2:
        return (float(slope), float("nan"))
    s_err = float(np.sqrt((resid ** 2).sum() / (n - 2)))
    if s_err == 0:
        return (float(slope), 0.0)
    se_slope = s_err / float(np.sqrt(Sxx))
    if se_slope == 0:
        return (float(slope), 0.0)
    t_stat = slope / se_slope
    from math import erf, sqrt
    p_one_sided = 0.5 * (1.0 + erf(t_stat / sqrt(2)))
    return (float(slope), float(p_one_sided))


def detect_moat_erosion(history_payload, df, p_threshold=0.20):
    out = {}
    if not history_payload or "companies" not in history_payload:
        return out
    for ticker, payload in history_payload["companies"].items():
        records = payload.get("history") or []
        if len(records) < 3:
            continue
        df_h = pd.DataFrame(records)
        if "date" not in df_h or "ev_fcf" not in df_h:
            continue
        df_h["date"] = pd.to_datetime(df_h["date"])
        df_h = df_h.sort_values("date")
        df_h["t_years"] = (df_h["date"] - df_h["date"].iloc[0]).dt.days / 365.25
        roic_slope, roic_p = _ols_slope_significance(
            df_h["t_years"].tolist(),
            [1.0 / v if v and v > 0 else float("nan") for v in df_h["ev_fcf"]])
        if "ev_sales" in df_h and "ev_fcf" in df_h:
            margin_proxy = []
            for s_, f_ in zip(df_h["ev_sales"], df_h["ev_fcf"]):
                if s_ and f_ and s_ > 0 and f_ > 0:
                    margin_proxy.append(s_ / f_ * 100)
                else:
                    margin_proxy.append(float("nan"))
            margin_slope, margin_p = _ols_slope_significance(
                df_h["t_years"].tolist(), margin_proxy)
        else:
            margin_slope, margin_p = (float("nan"), float("nan"))
        flag = False
        if (not pd.isna(roic_slope) and roic_slope < 0
                and not pd.isna(roic_p) and roic_p < p_threshold):
            flag = True
        if (not pd.isna(margin_slope) and margin_slope > 0
                and not pd.isna(margin_p) and margin_p > (1 - p_threshold)):
            flag = True
        out[ticker] = {
            "moat_erosion_flag":   bool(flag),
            "roic_slope_5y":       None if pd.isna(roic_slope) else float(roic_slope),
            "fcf_margin_slope_5y": None if pd.isna(margin_slope) else float(margin_slope),
            "n_points":            int(len(df_h)),
        }
    return out


def compute_zscore_self_history(history_payload):
    out = {}
    if not history_payload or "companies" not in history_payload:
        return out
    for ticker, payload in history_payload["companies"].items():
        records = payload.get("history") or []
        if len(records) < 3:
            continue
        vals_evfcf = [r.get("ev_fcf") for r in records if r.get("ev_fcf") and r["ev_fcf"] > 0]
        vals_evsales = [r.get("ev_sales") for r in records if r.get("ev_sales") and r["ev_sales"] > 0]
        d = {}
        if len(vals_evfcf) >= 3:
            arr = np.asarray(vals_evfcf, dtype=float)
            mu, sd = arr.mean(), arr.std(ddof=0)
            if sd > 0:
                d["ev_fcf_mean_5y"] = float(mu)
                d["ev_fcf_std_5y"] = float(sd)
                d["ev_fcf_zscore_self_5y"] = float((vals_evfcf[-1] - mu) / sd)
        if len(vals_evsales) >= 3:
            arr = np.asarray(vals_evsales, dtype=float)
            mu, sd = arr.mean(), arr.std(ddof=0)
            if sd > 0:
                d["ev_sales_zscore_self_5y"] = float((vals_evsales[-1] - mu) / sd)
        if d:
            out[ticker] = d
    return out



ASYM_V2_CAP = 30.0
EV_FCF_5Y_EXPENSIVE = 25.0  # >= 25x EV/FCF a 5y base = caro


def _asymmetry_v2(row):
    """Asimetria normalizada que respeta 'pure upside' (worst IRR > 0)."""
    best = row.get("irr_best_repriced")
    if best is None or pd.isna(best):
        best = row.get("irr_best")
    worst = row.get("irr_worst_repriced")
    if worst is None or pd.isna(worst):
        worst = row.get("irr_worst")
    if best is None or worst is None or pd.isna(best) or pd.isna(worst):
        return np.nan
    downside_risk = max(0.0, -float(worst))
    asym = (float(best) - float(worst)) / max(downside_risk, 0.01)
    return float(min(max(asym, -ASYM_V2_CAP), ASYM_V2_CAP))


def _pure_upside(row):
    """True si incluso el peor IRR es positivo (no hay downside modelado)."""
    worst = row.get("irr_worst_repriced")
    if worst is None or pd.isna(worst):
        worst = row.get("irr_worst")
    if worst is None or pd.isna(worst):
        return False
    return bool(float(worst) > 0)


def _ev_today(row):
    """EV recalculado con precio live: price*shares + debt - cash."""
    price = _safe_float(row.get("price"))
    shares = _safe_float(row.get("shares_out_m"))
    cash = _safe_float(row.get("cash"))
    debt = _safe_float(row.get("total_debt"))
    if None in (price, shares, cash, debt):
        # fallback al EV cached del Excel
        return _safe_float(row.get("ev"))
    return price * shares + debt - cash


def _ev_fcf_5y_base(row):
    """EV hoy / FCF proyectado a 5y (geom mean del cono bear/bull del Excel)."""
    ev = _ev_today(row)
    fcf_min = _safe_float(row.get("fcf_5y_min"))
    fcf_max = _safe_float(row.get("fcf_5y_max"))
    if ev is None or fcf_min is None or fcf_max is None:
        return np.nan
    if fcf_min <= 0 or fcf_max <= 0:
        return np.nan
    fcf_5y_base = (fcf_min * fcf_max) ** 0.5
    if fcf_5y_base <= 0:
        return np.nan
    return float(ev / fcf_5y_base)


def _score_v2(row):
    """
    Score ADITIVO 0-100 = 25% calidad + 25% supervivencia + 25% edge a 5y + 25% asimetria.
    kill_flag fuerza score = 0.
    """
    if bool(row.get("kill_flag", False)):
        return 0.0
    cg = _safe_float(row.get("composite_geometric"))
    sv = _safe_float(row.get("survival_score"))
    ev5 = _safe_float(row.get("ev_fcf_5y_base"))
    asym = _safe_float(row.get("asymmetry_v2"))
    if cg is None or sv is None:
        return np.nan
    quality_norm  = max(0.0, min(1.0, cg / 10.0))
    survival_norm = max(0.0, min(1.0, sv))
    if ev5 is None or ev5 <= 0:
        edge_norm = 0.0
    else:
        edge_norm = max(0.0, min(1.0, (EV_FCF_5Y_EXPENSIVE - ev5) / EV_FCF_5Y_EXPENSIVE))
    if asym is None:
        asym_norm = 0.0
    else:
        asym_norm = max(0.0, min(1.0, asym / ASYM_V2_CAP))
    score = 0.25 * quality_norm + 0.25 * survival_norm + 0.25 * edge_norm + 0.25 * asym_norm
    return float(score * 100.0)


def enrich(df):
    out = df.copy()
    out["irr_spread"] = out["irr_best"] - out["irr_worst"]
    out["irr_asymmetry_ratio"] = out.apply(
        lambda r: _irr_asymmetry_ratio(r["irr_worst"], r["irr_best"]), axis=1)
    out["quadrant"] = out.apply(
        lambda r: _classify_quadrant(r["rating_composite"], r["ev_fcf"]), axis=1)
    out["rating_tier"] = out["rating_composite"].apply(_classify_tier)
    if "category" in out.columns:
        if "roic" in out.columns:
            out["roic_zscore_by_category"] = _zscore_by_group(out["roic"], out["category"])
        if "ev_fcf" in out.columns:
            zs = _zscore_by_group(
                out["ev_fcf"].where(out["ev_fcf"] > 0), out["category"]).fillna(0.0)
            out["ev_fcf_zscore_by_category"] = zs
            out["ev_fcf_zscore_sector"] = zs
    out["composite_rank"] = out["rating_composite"].rank(
        method="min", ascending=False).astype("Int64")
    out["survival_score"] = out.apply(_survival_score, axis=1)
    out["quality_score"]  = out.apply(_quality_score, axis=1)
    out["composite_geometric"] = out.apply(
        lambda r: _composite_geometric(r.get("quality_score"), r.get("survival_score")), axis=1)
    out["kill_flag"] = out.apply(
        lambda r: _kill_flag(r, r.get("survival_score")), axis=1)
    out["rating_dispersion"] = out.apply(_rating_dispersion, axis=1)
    reprice_records = [_reprice_valuation(r) for _, r in out.iterrows()]
    for col in ["fve_min_repriced", "fve_max_repriced",
                "irr_worst_repriced", "irr_best_repriced"]:
        out[col] = [rec[col] for rec in reprice_records]
    out["irr_repriced_delta"] = out["irr_best_repriced"] - out["irr_best"]
    qa_records = [_quality_adjusted_multiple(r) for _, r in out.iterrows()]
    for col in ["ev_nopat", "quality_multiple_a", "quality_multiple_b",
                "quality_adjusted_multiple"]:
        out[col] = [rec[col] for rec in qa_records]
    out["edge_to_fair"] = out.apply(_edge_to_fair, axis=1)
    out["quality_zone"] = out.apply(_quality_zone, axis=1)
    out["kelly_fraction"] = out.apply(_kelly_fractional, axis=1)
    out["suggested_weight_pct"] = out.apply(_suggested_weight, axis=1)
    # Score v2 (aditivo) + asimetria normalizada + EV/FCF 5y proyectado
    out["asymmetry_v2"] = out.apply(_asymmetry_v2, axis=1)
    out["pure_upside"] = out.apply(_pure_upside, axis=1)
    out["ev_fcf_5y_base"] = out.apply(_ev_fcf_5y_base, axis=1)
    out["score_v2"] = out.apply(_score_v2, axis=1)
    out["score_v2_rank"] = out["score_v2"].rank(method="min", ascending=False).astype("Int64")
    return out


def category_stats(df):
    if "category" not in df.columns:
        return []
    # Aggregate only columns that exist (compatibilidad con tests legacy)
    candidate_aggs = {
        "count":                  ("ticker", "count"),
        "avg_composite":          ("rating_composite", "mean"),
        "avg_composite_geom":     ("composite_geometric", "mean"),
        "avg_survival":           ("survival_score", "mean"),
        "avg_roic":               ("roic", "mean"),
        "median_ev_fcf":          ("ev_fcf", "median"),
        "avg_irr_best":           ("irr_best", "mean"),
        "avg_irr_worst":          ("irr_worst", "mean"),
        "avg_irr_best_repriced":  ("irr_best_repriced", "mean"),
        "avg_edge_to_fair":       ("edge_to_fair", "mean"),
    }
    aggs = {k: v for k, v in candidate_aggs.items() if v[0] in df.columns}
    agg = df.groupby("category").agg(**aggs).reset_index().round(4)
    return agg.to_dict(orient="records")


def headline_kpis(df):
    if "market_cap_m" in df.columns and "roic" in df.columns:
        mask = df["market_cap_m"].notna() & df["roic"].notna()
        if mask.any():
            roic_weighted = ((df.loc[mask, "roic"] * df.loc[mask, "market_cap_m"]).sum()
                             / df.loc[mask, "market_cap_m"].sum())
        else:
            roic_weighted = float("nan")
    else:
        roic_weighted = float("nan")
    kpis = {
        "n_companies":           int(len(df)),
        "avg_composite":         float(df["rating_composite"].mean()),
        "median_composite":      float(df["rating_composite"].median()),
        "avg_composite_geometric": float(df.get("composite_geometric", pd.Series([np.nan])).mean()),
        "avg_survival_score":    float(df.get("survival_score", pd.Series([np.nan])).mean()),
        "weighted_avg_roic":     float(roic_weighted),
        "median_ev_fcf":         float(df.loc[df["ev_fcf"] > 0, "ev_fcf"].median()),
        "pct_best_irr_gt_15pct": float((df["irr_best"] > 0.15).mean() * 100),
        "n_top_tier":            int((df["rating_composite"] >= 7.5).sum()),
        "n_hunting_ground":      int((df.get("quadrant") == "hunting_ground").sum()) if "quadrant" in df.columns else 0,
        "n_quality_zone_hunt":   int((df.get("quality_zone") == "hunting_ground").sum()) if "quality_zone" in df.columns else 0,
        "n_killed":              int(df.get("kill_flag", pd.Series([False])).fillna(False).sum()) if "kill_flag" in df.columns else 0,
        "pct_positive_worst_irr": float((df["irr_worst"] > 0).mean() * 100),
        "pct_positive_worst_irr_repriced": (
            float((df["irr_worst_repriced"] > 0).mean() * 100)
            if "irr_worst_repriced" in df.columns else float("nan")),
    }
    return kpis


def compute_deltas(current, previous):
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
            rating_changes.append({
                "ticker": t,
                "name": curr.loc[t].get("name", t),
                "from": round(float(prev.loc[t, "rating_composite"]), 2),
                "to":   round(float(curr.loc[t, "rating_composite"]), 2),
                "delta": round(float(delta), 2),
            })
    rating_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return {
        "available": True,
        "entered": entered,
        "exited": exited,
        "rating_changes": rating_changes[:20],
    }


def inject_history_derived(df, history_payload):
    out = df.copy()
    zmap = compute_zscore_self_history(history_payload)
    emap = detect_moat_erosion(history_payload, df)
    def _zget(t, k): return zmap.get(t, {}).get(k)
    def _eget(t, k): return emap.get(t, {}).get(k)
    out["ev_fcf_zscore_self_5y"]   = out["ticker"].map(lambda t: _zget(t, "ev_fcf_zscore_self_5y"))
    out["ev_fcf_mean_5y"]          = out["ticker"].map(lambda t: _zget(t, "ev_fcf_mean_5y"))
    out["ev_fcf_std_5y"]           = out["ticker"].map(lambda t: _zget(t, "ev_fcf_std_5y"))
    out["ev_sales_zscore_self_5y"] = out["ticker"].map(lambda t: _zget(t, "ev_sales_zscore_self_5y"))
    out["moat_erosion_flag"]       = out["ticker"].map(lambda t: _eget(t, "moat_erosion_flag")).fillna(False)
    out["roic_slope_5y"]           = out["ticker"].map(lambda t: _eget(t, "roic_slope_5y"))
    out["fcf_margin_slope_5y"]     = out["ticker"].map(lambda t: _eget(t, "fcf_margin_slope_5y"))
    return out
