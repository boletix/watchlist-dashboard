"""Tests del módulo de analytics."""
import pandas as pd
import pytest

from src.analytics import (
    _classify_quadrant,
    _classify_tier,
    _irr_asymmetry_ratio,
    category_stats,
    compute_deltas,
    enrich,
    headline_kpis,
)


def _mk_df() -> pd.DataFrame:
    """DataFrame mínimo válido para tests."""
    return pd.DataFrame(
        [
            {
                "ticker": "AAA", "name": "Alpha", "category": "SaaS", "style": "Compounder",
                "rating_1": 8.0, "rating_2": 8.0, "rating_3": 8.0, "rating_composite": 8.0,
                "roic": 0.30, "ev_fcf": 15.0, "ev_ebitda": 12.0,
                "market_cap_m": 10000, "irr_worst": 0.05, "irr_best": 0.25,
            },
            {
                "ticker": "BBB", "name": "Beta", "category": "SaaS", "style": "Compounder",
                "rating_1": 9.0, "rating_2": 9.0, "rating_3": 9.0, "rating_composite": 9.0,
                "roic": 0.50, "ev_fcf": 45.0, "ev_ebitda": 30.0,
                "market_cap_m": 50000, "irr_worst": -0.10, "irr_best": 0.18,
            },
            {
                "ticker": "CCC", "name": "Gamma", "category": "Defensive", "style": "Defensive",
                "rating_1": 5.0, "rating_2": 5.0, "rating_3": 5.0, "rating_composite": 5.0,
                "roic": 0.10, "ev_fcf": 12.0, "ev_ebitda": 8.0,
                "market_cap_m": 5000, "irr_worst": -0.15, "irr_best": 0.05,
            },
            {
                "ticker": "DDD", "name": "Delta", "category": "Defensive", "style": "Defensive",
                "rating_1": 4.0, "rating_2": 4.0, "rating_3": 4.0, "rating_composite": 4.0,
                "roic": 0.05, "ev_fcf": 50.0, "ev_ebitda": 25.0,
                "market_cap_m": 2000, "irr_worst": -0.25, "irr_best": -0.05,
            },
        ]
    )


def test_classify_quadrant():
    assert _classify_quadrant(8.0, 15.0) == "hunting_ground"
    assert _classify_quadrant(9.0, 45.0) == "wonderful_expensive"
    assert _classify_quadrant(5.0, 12.0) == "value_trap"
    assert _classify_quadrant(4.0, 50.0) == "avoid"
    assert _classify_quadrant(8.0, -5.0) == "wonderful_expensive"  # FCF<0 no es barato


def test_classify_tier():
    assert _classify_tier(8.5) == "best_in_class"
    assert _classify_tier(7.2) == "high"
    assert _classify_tier(6.5) == "above_avg"
    assert _classify_tier(5.5) == "mixed"
    assert _classify_tier(3.0) == "low"


def test_irr_asymmetry_ratio():
    # Upside puro (worst positivo): (0.25 - 0.05) / max(0.05, 0.05) = 4.0
    assert abs(_irr_asymmetry_ratio(0.05, 0.25) - 4.0) < 0.01
    # Caso normal: (0.18 - (-0.10)) / 0.10 = 2.8
    assert abs(_irr_asymmetry_ratio(-0.10, 0.18) - 2.8) < 0.01
    # Asimetría negativa: (-0.05 - (-0.25)) / 0.25 = 0.8
    assert abs(_irr_asymmetry_ratio(-0.25, -0.05) - 0.8) < 0.01
    # Cap a 50x para evitar explosión cuando worst→0
    assert _irr_asymmetry_ratio(0.0001, 10.0) <= 50


def test_enrich_adds_expected_columns():
    df = _mk_df()
    out = enrich(df)
    for col in [
        "irr_spread", "irr_asymmetry_ratio", "quadrant", "rating_tier",
        "composite_rank", "roic_zscore_by_category", "ev_fcf_zscore_by_category",
    ]:
        assert col in out.columns, f"Falta columna: {col}"


def test_enrich_composite_rank_is_correct():
    df = _mk_df()
    out = enrich(df).set_index("ticker")
    assert out.loc["BBB", "composite_rank"] == 1  # rating 9.0
    assert out.loc["AAA", "composite_rank"] == 2  # rating 8.0
    assert out.loc["CCC", "composite_rank"] == 3  # rating 5.0
    assert out.loc["DDD", "composite_rank"] == 4  # rating 4.0


def test_enrich_quadrants():
    df = _mk_df()
    out = enrich(df).set_index("ticker")
    assert out.loc["AAA", "quadrant"] == "hunting_ground"
    assert out.loc["BBB", "quadrant"] == "wonderful_expensive"
    assert out.loc["CCC", "quadrant"] == "value_trap"
    assert out.loc["DDD", "quadrant"] == "avoid"


def test_headline_kpis():
    df = enrich(_mk_df())
    kpis = headline_kpis(df)
    assert kpis["n_companies"] == 4
    assert kpis["n_top_tier"] == 2  # AAA (8.0) y BBB (9.0)
    assert kpis["n_hunting_ground"] == 1  # AAA
    # Weighted ROIC: (0.30*10k + 0.50*50k + 0.10*5k + 0.05*2k) / 67k ≈ 0.427
    assert 0.40 < kpis["weighted_avg_roic"] < 0.44


def test_category_stats():
    df = _mk_df()
    stats = category_stats(df)
    assert len(stats) == 2  # SaaS + Defensive
    saas = next(s for s in stats if s["category"] == "SaaS")
    assert saas["count"] == 2
    assert abs(saas["avg_composite"] - 8.5) < 0.01


def test_compute_deltas_detects_changes():
    prev = _mk_df()
    curr = _mk_df()
    # Simular cambio de rating en AAA y nueva empresa EEE
    curr.loc[curr["ticker"] == "AAA", "rating_composite"] = 7.5
    new_row = {"ticker": "EEE", "name": "Epsilon", "category": "SaaS", "style": "Compounder",
               "rating_composite": 6.0, "rating_1": 6, "rating_2": 6, "rating_3": 6,
               "roic": 0.2, "ev_fcf": 20, "ev_ebitda": 15, "market_cap_m": 1000,
               "irr_worst": 0, "irr_best": 0.1, "ev_sales": 0}
    curr = pd.concat([curr, pd.DataFrame([new_row])], ignore_index=True)

    deltas = compute_deltas(curr, prev)
    assert deltas["available"] is True
    assert "EEE" in deltas["entered"]
    tickers_changed = [r["ticker"] for r in deltas["rating_changes"]]
    assert "AAA" in tickers_changed


def test_compute_deltas_with_no_previous():
    df = _mk_df()
    deltas = compute_deltas(df, None)
    assert deltas["available"] is False
