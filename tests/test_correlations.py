"""
Correlaciones con una empresa recien listada.

Contexto: el 2-oct-2026 Vylor (escindida de Corteva el 1-oct) entro con dos dias de
cotizacion; su correlacion era NaN con todo, scipy rechazaba la matriz y el build se quedaba
sin clusters para las 71. No toca la red.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.correlations import _hierarchical_clusters

pytest.importorskip("scipy")


def test_clusters_survive_nan_pairs():
    rng = np.random.default_rng(0)
    r = pd.DataFrame(rng.normal(size=(250, 4)), columns=["A", "B", "C", "D"])
    r.loc[:247, "D"] = np.nan                 # D solo tiene dos dias
    corr = r.corr(min_periods=60)
    assert corr["D"].drop("D").isna().all()
    out = _hierarchical_clusters(corr, threshold=0.75)   # antes: ValueError de scipy
    assert set(out) == {"A", "B", "C", "D"}
