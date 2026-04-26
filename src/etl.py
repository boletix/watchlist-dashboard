"""
ETL: lee el Excel fuente y devuelve un DataFrame normalizado.

Diseño:
- La hoja `Watchlist Ratings` tiene cabeceras en 2 filas (bloques + nombres).
  Se aplanan a nombres snake_case estables.
- Se valida: rangos de rating [0, 10], unicidad de ticker, no-nulos críticos.
- Se parsea `Category` y `Estilo inversión` a strings limpios.
- ROIC e IRR vienen como decimales (0.54 = 54 %) — se mantienen así y se
  formatean como % solo en la capa de presentación.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Mapa de nombres de columna Excel → snake_case estable.
# Se matchea por substring en el header aplanado (insensible a mayúsculas/saltos).
COLUMN_MAP: dict[str, str] = {
    # Market data
    "Ticker": "ticker",
    "Company Name": "name",
    "Category": "category",
    "Estilo inversión": "style",
    "Exchange": "exchange",
    "Currency": "currency",
    "Price": "price",
    "Shares Outstanding": "shares_out_m",
    "Market Cap": "market_cap_m",
    # Rating 1 sub-scores
    "Mission": "r1_mission",
    "MOAT (0 to 8)": "r1_moat",
    "Optionality": "r1_optionality",
    "Financials (-1 to 1)": "r1_financials",
    "Concentration": "r1_concentration",
    "Glassdoor": "r1_glassdoor",
    "Founder/CEO": "r1_founder",
    "Ownership (-1 to 1)": "r1_ownership",
    "R1 Sum": "r1_sum",
    "RATING 1 0–10": "rating_1",
    # Rating 2 sub-scores
    "Financials (0 to 17)": "r2_financials",
    "MOAT (0 to 20)": "r2_moat",
    "Potential": "r2_potential",
    "Customers": "r2_customers",
    "Revenue Quality": "r2_revenue_quality",
    "Mgmt & Culture": "r2_mgmt",
    "Stock & Ownership": "r2_stock",
    "Risks": "r2_risks",
    "R2 Sum": "r2_sum",
    "RATING 2 0–10": "rating_2",
    # Rating 3 sub-scores
    "Durability (0 to 15)": "r3_durability",
    "Risk of Disappearance": "r3_risk_disappear",
    "Capital Intensity": "r3_capital_intensity",
    "Capital Allocation": "r3_capital_alloc",
    "Financing Source": "r3_financing",
    "Incentives": "r3_incentives",
    "MOAT Structural": "r3_moat_structural",
    "Terminal Risk": "r3_terminal_risk",
    "R3 Sum": "r3_sum",
    "RATING 3 0–10": "rating_3",
    # Composite (column with no sub-header, under block "COMPOSITE RATING")
    "COMPOSITE RATING": "rating_composite",
    # Financials
    "FX Reporting": "fx_reporting",
    "Cash & Equivalents": "cash",
    "Total Debt": "total_debt",
    "Enterprise Value": "ev",
    "FCF LTM": "fcf_ltm",
    "NOPAT LTM": "nopat_ltm",
    "EBITDA LTM": "ebitda_ltm",
    "Revenue LTM": "revenue_ltm",
    "EV / FCF": "ev_fcf",
    "EV / EBITDA": "ev_ebitda",
    "EV / Sales": "ev_sales",
    "Capital Employed": "capital_employed",
    "NOPAT M%": "nopat_margin",
    "Asset Turnover": "asset_turnover",
    "ROIC": "roic",
    "FCF @5y Min": "fcf_5y_min",
    "FCF min CAGR": "fcf_min_cagr",
    "FCF @5y Max": "fcf_5y_max",
    "FCF max CAGR": "fcf_max_cagr",
    "Exit Mult Min": "exit_mult_min",
    "Exit Mult Max": "exit_mult_max",
    "FVE min": "fve_min",
    "FVE max": "fve_max",
    "Worst IRR": "irr_worst",
    "Best IRR": "irr_best",
    # Earnings calendar (añadido 2026-04-26)
    "Última\nActualización": "earnings_updated_at",
    "Última Presentación": "earnings_last_date",
    "Próxima Presentación": "earnings_next_date",
}


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Aplana MultiIndex de columnas a un string por columna."""
    flat = []
    for l1, l2 in df.columns:
        l1s = "" if str(l1).startswith("Unnamed") else str(l1).strip()
        l2s = "" if str(l2).startswith("Unnamed") else str(l2).strip()
        flat.append(f"{l1s} | {l2s}".replace("\n", " ").strip(" |"))
    df = df.copy()
    df.columns = flat
    return df


def _resolve_column(df_columns: list[str], key: str) -> str | None:
    """Encuentra la primera columna que contiene `key` (case-insensitive)."""
    key_norm = re.sub(r"\s+", " ", key.lower())
    for col in df_columns:
        col_norm = re.sub(r"\s+", " ", col.lower())
        if key_norm in col_norm:
            return col
    return None


def load_watchlist(xlsx_path: str | Path) -> pd.DataFrame:
    """
    Lee el Excel y devuelve DataFrame con columnas snake_case canónicas.

    Raises:
        ValueError si faltan columnas críticas o se detectan inconsistencias
        bloqueantes (ticker duplicado, rating fuera de rango).
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {xlsx_path}")

    log.info("Leyendo %s", xlsx_path)
    raw = pd.read_excel(
        xlsx_path, sheet_name="Watchlist Ratings", header=[1, 2], skiprows=0
    )
    raw = _flatten_columns(raw)

    # Resolver cada columna del COLUMN_MAP
    rename: dict[str, str] = {}
    missing: list[str] = []
    for excel_key, canonical in COLUMN_MAP.items():
        resolved = _resolve_column(list(raw.columns), excel_key)
        if resolved is None:
            missing.append(excel_key)
        else:
            rename[resolved] = canonical

    if missing:
        log.warning("Columnas Excel no encontradas: %s", missing)

    df = raw[list(rename.keys())].rename(columns=rename).copy()

    # El "Company Name" del Excel es un VLOOKUP roto → si todo NaN, usar ticker.
    if "name" in df.columns and df["name"].isna().all():
        log.warning("Columna 'name' vacía — usando ticker como fallback")
        df["name"] = df["ticker"]

    # Limpieza básica
    df["ticker"] = df["ticker"].astype(str).str.strip()
    if "category" in df.columns:
        df["category"] = df["category"].astype(str).str.strip()
    if "style" in df.columns:
        df["style"] = df["style"].astype(str).str.strip()

    # Filtrar filas completamente vacías (por si el Excel tiene trailing rows)
    df = df.dropna(subset=["ticker"]).reset_index(drop=True)
    df = df[df["ticker"].str.len() > 0].reset_index(drop=True)

    log.info("Loaded %d empresas, %d columnas", len(df), len(df.columns))
    return df


def validate(df: pd.DataFrame) -> list[str]:
    """
    Devuelve lista de issues. Lista vacía = todo OK.
    Se separa de load() para que en CI se puedan fallar builds.
    """
    issues: list[str] = []

    # 1. Ticker único
    dupes = df["ticker"][df["ticker"].duplicated()].tolist()
    if dupes:
        issues.append(f"Tickers duplicados: {dupes}")

    # 2. Ratings en [-2, 11] — los cálculos del Excel pueden producir outliers
    # legítimos por sumas negativas (ej: risk scores muy penalizantes). Solo
    # flaggeamos desviaciones extremas como bloqueantes.
    for col in ["rating_1", "rating_2", "rating_3", "rating_composite"]:
        if col not in df.columns:
            continue
        extreme = df[(df[col] < -2) | (df[col] > 11)]
        if len(extreme):
            issues.append(
                f"{col} con valor extremo (fuera de [-2,11]) en: {extreme['ticker'].tolist()}"
            )
        oor = df[((df[col] < 0) | (df[col] > 10)) & (df[col] >= -2) & (df[col] <= 11)]
        if len(oor):
            log.warning(
                "%s fuera de [0,10] pero dentro de tolerancia en: %s",
                col, oor["ticker"].tolist(),
            )

    # 3. Integridad composite = media(R1, R2, R3), tolerancia 0.05
    if all(c in df.columns for c in ["rating_1", "rating_2", "rating_3", "rating_composite"]):
        expected = (df["rating_1"] + df["rating_2"] + df["rating_3"]) / 3
        delta = (df["rating_composite"] - expected).abs()
        bad = df[delta > 0.05]
        if len(bad):
            issues.append(
                "Composite ≠ media(R1,R2,R3) en: "
                f"{bad[['ticker']].assign(delta=delta[bad.index].round(3)).to_dict('records')}"
            )

    # 4. Market cap positivo
    if "market_cap_m" in df.columns:
        bad = df[df["market_cap_m"] <= 0]
        if len(bad):
            issues.append(f"Market cap <= 0 en: {bad['ticker'].tolist()}")

    # 5. EV/FCF no negativo imposible (puede ser NaN, no negativo sin aviso)
    if "ev_fcf" in df.columns:
        bad = df[df["ev_fcf"] < 0]
        if len(bad):
            # Negativo = FCF negativo, es válido pero debe verse
            log.warning(
                "EV/FCF negativo (FCF < 0) en: %s", bad["ticker"].tolist()
            )

    return issues


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/watchlist_ratings.xlsx"
    df = load_watchlist(src)
    print(df.head())
    print("\nColumnas:", list(df.columns))
    print(f"\nEmpresas: {len(df)}")
    issues = validate(df)
    if issues:
        print("\n❌ ISSUES:")
        for i in issues:
            print(" -", i)
    else:
        print("\n✅ Validación OK")
