"""Tests del ETL."""
from pathlib import Path

import pandas as pd
import pytest

from src.etl import load_watchlist, validate

FIXTURE = Path("data/raw/watchlist_ratings.xlsx")


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    if not FIXTURE.exists():
        pytest.skip(f"Fixture no disponible: {FIXTURE}")
    return load_watchlist(FIXTURE)


def test_shape(df):
    """El ETL debe cargar ≥ 50 empresas sin fila vacía trailing."""
    assert len(df) >= 50
    assert df["ticker"].notna().all()
    assert (df["ticker"].str.len() > 0).all()


def test_canonical_columns(df):
    """Columnas clave con nombres snake_case canónicos."""
    expected = [
        "ticker", "name", "category", "style",
        "price", "market_cap_m",
        "rating_1", "rating_2", "rating_3", "rating_composite",
        "roic", "ev_fcf", "ev_ebitda",
        "irr_worst", "irr_best",
    ]
    missing = [c for c in expected if c not in df.columns]
    assert not missing, f"Columnas faltantes: {missing}"


def test_ticker_uniqueness(df):
    dupes = df["ticker"][df["ticker"].duplicated()].tolist()
    assert not dupes, f"Tickers duplicados: {dupes}"


def test_ratings_in_range(df):
    """Ratings dentro de tolerancia amplia (-2, 11) permitiendo outliers Excel."""
    for col in ["rating_1", "rating_2", "rating_3", "rating_composite"]:
        extreme = df[(df[col] < -2) | (df[col] > 11)]
        assert len(extreme) <= 1, (
            f"{col} con >1 outlier extremo: {extreme['ticker'].tolist()}"
        )


def test_composite_equals_mean_of_r1_r2_r3(df):
    """Integridad: composite = media(R1, R2, R3) con tolerancia 0.05."""
    expected = (df["rating_1"] + df["rating_2"] + df["rating_3"]) / 3
    delta = (df["rating_composite"] - expected).abs()
    bad = df[delta > 0.05]
    assert bad.empty, (
        f"Composite ≠ media en: {bad[['ticker']].to_dict('records')}"
    )


def test_percentages_are_decimals(df):
    """ROIC e IRR deben estar en decimal, no en porcentaje."""
    # ROIC razonable: -50% a +200% en decimal → -0.5 a 2.0
    roic_valid = df["roic"].dropna()
    assert roic_valid.abs().max() < 5, "ROIC parece estar en % en lugar de decimal"
    # IRR best razonable: hasta 100% = 1.0
    irr_valid = df["irr_best"].dropna()
    assert irr_valid.abs().max() < 5, "IRR parece estar en % en lugar de decimal"


def test_validate_reports_issues_or_clean(df):
    """validate() devuelve lista (posiblemente vacía). No lanza excepción."""
    issues = validate(df)
    assert isinstance(issues, list)
