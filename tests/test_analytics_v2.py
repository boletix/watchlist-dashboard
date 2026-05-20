"""Tests para analytics v2.0 - composite geometrico, reprice IRR, kelly, etc."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import math
import numpy as np
import pandas as pd
import pytest

from src.analytics import (
    _norm_subscore, _survival_score, _quality_score, _composite_geometric,
    _kill_flag, _reprice_valuation, _quality_adjusted_multiple, _edge_to_fair,
    _quality_zone, _kelly_fractional, _suggested_weight,
    _adaptive_evfcf_cutoff, _ols_slope_significance, R3_SCALES, enrich,
)


# ---- Survival score ----
def test_norm_subscore_durability_max():
    assert _norm_subscore(15, (0, 15)) == 1.0

def test_norm_subscore_durability_mid():
    assert _norm_subscore(7.5, (0, 15)) == 0.5

def test_norm_subscore_terminal_zero():
    # -20..0; v=0 -> 1.0
    assert _norm_subscore(0, (-20, 0)) == 1.0

def test_norm_subscore_terminal_minus_10():
    assert _norm_subscore(-10, (-20, 0)) == 0.5

def test_survival_csu_top_tier():
    # CSU real: durability=15, risk_disappear=0, terminal_risk=-3
    row = {"r3_durability": 15, "r3_risk_disappear": 0, "r3_terminal_risk": -3}
    s = _survival_score(row)
    # (1.0 + 1.0 + 0.85) / 3 = 0.95
    assert abs(s - 0.95) < 0.01

def test_survival_otly_distressed():
    row = {"r3_durability": 6, "r3_risk_disappear": -12, "r3_terminal_risk": -12}
    s = _survival_score(row)
    # (0.4 + 0.4 + 0.4) / 3 = 0.4
    assert abs(s - 0.4) < 0.01

def test_survival_nan_when_missing():
    row = {"r3_durability": None, "r3_risk_disappear": 0, "r3_terminal_risk": -3}
    assert pd.isna(_survival_score(row))


# ---- Composite geometric ----
def test_composite_geom_balanced():
    # q=0.8, s=0.8 -> 8.0 (igual al composite si todos lo son)
    g = _composite_geometric(0.8, 0.8)
    assert abs(g - 8.0) < 0.001

def test_composite_geom_penalizes_low_survival():
    # quality alta (0.9), survival baja (0.2): debe ser < media aritmetica (0.55*10=5.5)
    g = _composite_geometric(0.9, 0.2)
    # 0.9^(2/3) * 0.2^(1/3) = 0.9322 * 0.5848 = 0.5453 -> 5.45
    assert abs(g - 5.45) < 0.1
    assert g < 5.5

def test_composite_geom_high_when_balanced_high():
    g = _composite_geometric(1.0, 1.0)
    assert abs(g - 10.0) < 0.001


# ---- Kill flag ----
def test_kill_flag_low_survival():
    assert _kill_flag({"r3_terminal_risk": -5}, 0.4) is True

def test_kill_flag_terminal_too_low():
    assert _kill_flag({"r3_terminal_risk": -15}, 0.7) is True  # tr<-10 kills

def test_kill_flag_not_killed():
    assert _kill_flag({"r3_terminal_risk": -3}, 0.85) is False


# ---- Reprice IRR ----
def test_reprice_replicates_excel_veev():
    # VEEV: price=163.58, shares=158.79M aprox, fcf_5y_min/max, etc.
    # Aqui usamos numeros conocidos para verificar la formula
    row = {
        "price": 100, "shares_out_m": 100,
        "cash": 1000, "total_debt": 500,
        "fcf_5y_min": 50, "fcf_5y_max": 100,
        "exit_mult_min": 20, "exit_mult_max": 30,
    }
    # FVE_min = (50*20 + 1000 - 500) / 100 = (1000 + 500) / 100 = 15
    # FVE_max = (100*30 + 1000 - 500) / 100 = (3000 + 500) / 100 = 35
    out = _reprice_valuation(row)
    assert abs(out["fve_min_repriced"] - 15.0) < 1e-9
    assert abs(out["fve_max_repriced"] - 35.0) < 1e-9
    # IRR_worst = (15/100)^(1/5) - 1 = -0.32
    assert abs(out["irr_worst_repriced"] - ((15/100)**(1/5) - 1)) < 1e-9
    # IRR_best = (35/100)^(1/4) - 1
    assert abs(out["irr_best_repriced"] - ((35/100)**(1/4) - 1)) < 1e-9

def test_reprice_missing_returns_nan():
    out = _reprice_valuation({"price": None, "shares_out_m": 100, "cash": 0, "total_debt": 0})
    assert pd.isna(out["fve_min_repriced"])

def test_reprice_handles_string_with_commas():
    # AMZN-style: fcf_5y_min = "72,933"
    row = {
        "price": 263.31, "shares_out_m": 10757.11,
        "cash": 80000, "total_debt": 65000,
        "fcf_5y_min": "72,933", "fcf_5y_max": "109,218",
        "exit_mult_min": 22.5, "exit_mult_max": 30.0,
    }
    out = _reprice_valuation(row)
    assert not pd.isna(out["irr_best_repriced"])


# ---- Quality-adjusted multiple ----
def test_quality_multiple_a_low_when_high_roic():
    # ev=100, nopat=10, roic=0.5 (50%)
    # a = (100/10) / (0.5*100) = 10/50 = 0.2 -> "barato" para reinvertor
    row = {"ev": 100, "nopat_ltm": 10, "roic": 0.5,
           "ev_fcf": 25, "fcf_min_cagr": 0.10, "fcf_max_cagr": 0.20,
           "r3_durability": 10}
    out = _quality_adjusted_multiple(row)
    assert abs(out["ev_nopat"] - 10) < 1e-9
    assert abs(out["quality_multiple_a"] - 0.2) < 1e-9

def test_quality_adjusted_blend():
    row = {"ev": 100, "nopat_ltm": 10, "roic": 0.5,
           "ev_fcf": 25, "fcf_min_cagr": 0.10, "fcf_max_cagr": 0.20,
           "r3_durability": 10}
    out = _quality_adjusted_multiple(row)
    a, b = out["quality_multiple_a"], out["quality_multiple_b"]
    blend = out["quality_adjusted_multiple"]
    assert abs(blend - 0.5 * (a + b)) < 1e-9


# ---- Adaptive cutoff ----
def test_adaptive_cutoff_excellent():
    assert _adaptive_evfcf_cutoff(9.0) == 35.0

def test_adaptive_cutoff_good():
    assert _adaptive_evfcf_cutoff(7.8) == 25.0

def test_adaptive_cutoff_mid():
    assert _adaptive_evfcf_cutoff(7.2) == 20.0

def test_adaptive_cutoff_low():
    assert _adaptive_evfcf_cutoff(6.0) == 15.0


# ---- Quality zone ----
def test_zone_hunting_when_adaptive_cheap():
    # composite 8 -> cutoff 25; ev_fcf 22 -> hunt
    row = {"rating_composite": 8.0, "ev_fcf": 22, "kill_flag": False}
    assert _quality_zone(row) == "hunting_ground"

def test_zone_avoid_when_kill():
    row = {"rating_composite": 9.0, "ev_fcf": 15, "kill_flag": True}
    assert _quality_zone(row) == "avoid"

def test_zone_wonderful_expensive_above_cutoff():
    row = {"rating_composite": 8.0, "ev_fcf": 40, "kill_flag": False}
    assert _quality_zone(row) == "wonderful_expensive"


# ---- Kelly + suggested weight ----
def test_kelly_zero_when_negative_best():
    row = {"irr_best_repriced": -0.1, "irr_worst_repriced": -0.2}
    assert _kelly_fractional(row) == 0.0

def test_kelly_positive_when_favorable_asym():
    # best 30%, worst -5%
    row = {"irr_best_repriced": 0.30, "irr_worst_repriced": -0.05}
    k = _kelly_fractional(row)
    assert k > 0

def test_suggested_weight_capped_at_10pct():
    row = {"kelly_fraction": 1.0, "survival_score": 0.95}
    w = _suggested_weight(row)
    assert w == 0.10

def test_suggested_weight_zero_when_low_survival():
    # weight = kelly * survival = 0.1 * 0.2 = 0.02
    row = {"kelly_fraction": 0.1, "survival_score": 0.2}
    w = _suggested_weight(row)
    assert abs(w - 0.02) < 1e-9


# ---- OLS slope ----
def test_ols_zero_slope():
    slope, p = _ols_slope_significance([0, 1, 2, 3], [5, 5, 5, 5])
    assert pd.isna(slope) or abs(slope) < 1e-9

def test_ols_positive_slope():
    slope, p = _ols_slope_significance([0, 1, 2, 3], [10, 15, 20, 25])
    assert slope > 0
    assert abs(slope - 5.0) < 1e-9


# ---- Edge to fair ----
def test_edge_to_fair_basic():
    row = {"price": 100, "fve_min_repriced": 80, "fve_max_repriced": 200}
    # geom = sqrt(80*200) = 126.49
    # edge = 126.49/100 - 1 = 0.2649
    e = _edge_to_fair(row)
    assert abs(e - (math.sqrt(16000)/100 - 1)) < 1e-9


# ---- Integration: enrich() smoke test ----
def test_enrich_adds_v2_columns():
    df = pd.DataFrame([{
        "ticker": "TEST", "category": "Tech", "rating_composite": 8.0,
        "rating_1": 8, "rating_2": 8, "rating_3": 8,
        "r3_durability": 14, "r3_risk_disappear": 0, "r3_terminal_risk": -3,
        "irr_worst": 0.05, "irr_best": 0.30, "ev_fcf": 22,
        "price": 100, "shares_out_m": 100, "cash": 1000, "total_debt": 500,
        "fcf_5y_min": 50, "fcf_5y_max": 100, "exit_mult_min": 20, "exit_mult_max": 30,
        "ev": 100, "nopat_ltm": 10, "roic": 0.4, "fcf_min_cagr": 0.10, "fcf_max_cagr": 0.20,
        "market_cap_m": 10000,
    }])
    out = enrich(df)
    for col in ["composite_geometric", "survival_score", "kill_flag",
                "quality_zone", "irr_best_repriced", "edge_to_fair",
                "suggested_weight_pct", "quality_adjusted_multiple",
                "rating_dispersion"]:
        assert col in out.columns, f"missing {col}"
    assert out.iloc[0]["composite_geometric"] > 0
    assert out.iloc[0]["survival_score"] > 0.8
    assert out.iloc[0]["kill_flag"] is False or out.iloc[0]["kill_flag"] is np.False_


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v"] + sys.argv[1:])


# ---- v2.1: asymmetry_v2, ev_fcf_5y_base, score_v2 ----
from src.analytics import (
    _asymmetry_v2, _pure_upside, _ev_fcf_5y_base, _score_v2, ASYM_V2_CAP,
)

def test_asymmetry_v2_negative_worst():
    # best 30%, worst -10% -> downside 0.10 -> (0.30-(-0.10))/0.10 = 4.0
    row = {"irr_best_repriced": 0.30, "irr_worst_repriced": -0.10}
    assert abs(_asymmetry_v2(row) - 4.0) < 1e-9

def test_asymmetry_v2_pure_upside_capped():
    # worst positive -> downside 0 -> huge -> capped at 30
    row = {"irr_best_repriced": 0.40, "irr_worst_repriced": 0.05}
    assert _asymmetry_v2(row) == ASYM_V2_CAP

def test_asymmetry_v2_cap_is_30():
    assert ASYM_V2_CAP == 30.0

def test_pure_upside_true():
    assert _pure_upside({"irr_worst_repriced": 0.02}) is True

def test_pure_upside_false():
    assert _pure_upside({"irr_worst_repriced": -0.05}) is False

def test_ev_fcf_5y_base_basic():
    # ev = 100*100 + 500 - 1000 = 9500; fcf_5y_base = sqrt(50*200)=100; 9500/100=95
    row = {"price": 100, "shares_out_m": 100, "cash": 1000, "total_debt": 500,
           "fcf_5y_min": 50, "fcf_5y_max": 200}
    assert abs(_ev_fcf_5y_base(row) - 95.0) < 1e-6

def test_score_v2_additive_components():
    # quality 0.8, survival 0.9, ev5 0x (edge 1.0), asym 30 (norm 1.0)
    row = {"composite_geometric": 8.0, "survival_score": 0.9,
           "ev_fcf_5y_base": 0.0001, "asymmetry_v2": 30.0, "kill_flag": False}
    s = _score_v2(row)
    # 0.25*0.8 + 0.25*0.9 + 0.25*~1 + 0.25*1 = ~0.925 -> 92.5
    assert 90 < s < 95

def test_score_v2_kill_zero():
    row = {"composite_geometric": 9.0, "survival_score": 0.9,
           "ev_fcf_5y_base": 10, "asymmetry_v2": 30, "kill_flag": True}
    assert _score_v2(row) == 0.0

def test_score_v2_expensive_5y_zero_edge():
    # ev5 = 25 -> edge_norm = 0
    row = {"composite_geometric": 8.0, "survival_score": 0.8,
           "ev_fcf_5y_base": 25.0, "asymmetry_v2": 0, "kill_flag": False}
    s = _score_v2(row)
    # 0.25*0.8 + 0.25*0.8 + 0 + 0 = 0.4 -> 40
    assert abs(s - 40.0) < 1.0

def test_score_v2_is_additive_not_multiplicative():
    # Una dimension a cero NO anula el score (aditivo)
    row = {"composite_geometric": 8.0, "survival_score": 0.8,
           "ev_fcf_5y_base": 100, "asymmetry_v2": 0, "kill_flag": False}
    s = _score_v2(row)
    # 0.25*0.8 + 0.25*0.8 + ~0 + 0 = 0.4 -> 40, sigue positivo (no se anula)
    assert s > 30
