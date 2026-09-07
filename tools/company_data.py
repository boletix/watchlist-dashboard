"""
Extraccion de datos financieros historicos por ticker para el generador de packs.

Fuentes, en orden de preferencia:
  1. yfinance annual income_stmt / cashflow / balance_sheet  (4-5 ejercicios reportados)
  2. yfinance quarterly_*  -> TTM
  3. docs/data/watchlist.json  (LTM y escenarios que Roger mantiene a mano en el Excel)

Todo se devuelve en MILLONES de la moneda de REPORTE de la empresa (fx_reporting del
watchlist.json), que no siempre es la moneda de cotizacion. Ver Framework Notes E9.
"""
from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
WATCHLIST_JSON = REPO / "docs" / "data" / "watchlist.json"

# Ticker del Excel -> simbolo yfinance para DATOS FINANCIEROS.
# Ojo: no siempre coincide con el override de precios de src/tickers.py, porque
# para las cuentas queremos la linea primaria (la que publica los estados), no la
# linea de cotizacion europea. Nintendo es el caso claro: NTO.F da precio pero
# 7974.T da las cuentas.
FIN_OVERRIDE = {
    "CSU": "CSU.TO", "NTO": "7974.T", "LIFCO B": "LIFCO-B.ST", "ROKO B": "ROKO-B.ST",
    "ADYEN": "ADYEN.AS", "ITX": "ITX.MC", "SU": "SU.PA", "RAA": "RAA.DE", "EVD": "EVD.DE",
    "HLMA": "HLMA.L", "JDG": "JDG.L", "SOM": "SOM.L", "WOSG": "WOSG.L", "KIST": "KIST.L",
    "LOTB": "LOTB.BR", "PRY": "PRY.MI", "CPR": "CPR.MI", "TGYM": "TGYM.MI", "IP": "IP.MI",
    "VID": "VID.MC", "CBAV": "CBAV.MC", "RBT": "RBT.PA", "LR": "LR.PA", "SGO": "SGO.PA",
    "TFF": "TFF.PA", "VRLA": "VLA.PA", "MIPS": "MIPS.ST", "ABBNE": "ABBN.SW",
    "STMN": "STMN.SW", "SIKA": "SIKA.SW", "JFN": "JFN.SW", "BFIT": "BFIT.AS",
    "DNP": "DNP.WA", "KSPI": "KSPI", "TFPM": "TFPM.TO", "IPCO": "IPCO.TO",
    "COR": "COR.LS", "KRX": "KRX.IR", "TOI": "TOI.V", "LMN": "LMN.V",
}

# Filas de yfinance -> nombre canonico. Se prueban en orden y gana la primera que exista.
INCOME_MAP = {
    "revenue":      ["Total Revenue", "Operating Revenue"],
    "cogs":         ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "opex":         ["Operating Expense", "Total Expenses"],
    "rnd":          ["Research And Development"],
    "sgna":         ["Selling General And Administration", "Selling General Administrative"],
    "ebit":         ["Operating Income", "Total Operating Income As Reported"],
    "da":           ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"],
    "interest":     ["Interest Expense", "Interest Expense Non Operating"],
    "pretax":       ["Pretax Income"],
    "tax":          ["Tax Provision"],
    "net_income":   ["Net Income Common Stockholders", "Net Income"],
    "shares":       ["Diluted Average Shares", "Basic Average Shares"],
}
CASHFLOW_MAP = {
    "ocf":        ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex":      ["Capital Expenditure", "Purchase Of PPE"],
    "fcf":        ["Free Cash Flow"],
    "cf_da":      ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
    "d_wc":       ["Change In Working Capital"],
    "sbc":        ["Stock Based Compensation"],
    "ma":         ["Net Business Purchase And Sale", "Purchase Of Business"],
    "dividends":  ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "buybacks":   ["Repurchase Of Capital Stock"],
}
BALANCE_MAP = {
    "assets":       ["Total Assets"],
    "cash":         ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
    "debt":         ["Total Debt"],
    "equity":       ["Stockholders Equity"],
    "minority":     ["Minority Interest"],
    "goodwill":     ["Goodwill"],
    "receivables":  ["Accounts Receivable", "Receivables"],
    "inventory":    ["Inventory"],
    "payables":     ["Accounts Payable", "Payables"],
    "cur_assets":   ["Current Assets"],
    "cur_liab":     ["Current Liabilities"],
    "invested_cap": ["Invested Capital"],
}


@dataclass
class CompanyData:
    ticker: str
    yf_symbol: str
    name: str
    currency: str
    years: list = field(default_factory=list)
    hist: dict = field(default_factory=dict)
    ttm: dict = field(default_factory=dict)
    wl: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def h(self, metric, year, default=None):
        return self.hist.get(metric, {}).get(year, default)

    def series(self, metric):
        return [self.hist.get(metric, {}).get(y) for y in self.years]

    def has(self, metric):
        return any(v is not None for v in self.hist.get(metric, {}).values())


def _extract(df, mapping, scale=1e6):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for canon, candidates in mapping.items():
        for row in candidates:
            if row in df.index:
                vals = {}
                for col, v in df.loc[row].items():
                    if pd.isna(v):
                        continue
                    vals[int(pd.Timestamp(col).year)] = round(float(v) / scale, 1)
                if vals:
                    out[canon] = vals
                break
    return out


def _ttm(df, mapping, scale=1e6):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for canon, candidates in mapping.items():
        for row in candidates:
            if row in df.index:
                s = df.loc[row].dropna()
                if len(s) >= 4:
                    out[canon] = round(float(s.iloc[:4].sum()) / scale, 1)
                break
    return out


def load_watchlist():
    d = json.loads(WATCHLIST_JSON.read_text(encoding="utf-8"))
    return {c["ticker"]: c for c in d["companies"]}


def fetch(ticker, wl_rec=None, offline=False):
    """Descarga y normaliza los estados financieros de un ticker de la watchlist."""
    wl_rec = wl_rec if wl_rec is not None else load_watchlist().get(ticker, {})
    sym = FIN_OVERRIDE.get(ticker, ticker)
    cd = CompanyData(
        ticker=ticker, yf_symbol=sym, name=wl_rec.get("name") or ticker,
        currency=wl_rec.get("fx_reporting") or wl_rec.get("currency") or "USD",
        wl=wl_rec,
    )
    if offline:
        cd.notes.append("Modo offline: sin historico de yfinance.")
        return cd

    import yfinance as yf
    tk = yf.Ticker(sym)
    try:
        inc, cfl, bal = tk.income_stmt, tk.cashflow, tk.balance_sheet
        qi, qc = tk.quarterly_income_stmt, tk.quarterly_cashflow
    except Exception as exc:
        cd.notes.append("yfinance fallo: %s" % exc)
        return cd

    for df, mp in ((inc, INCOME_MAP), (cfl, CASHFLOW_MAP), (bal, BALANCE_MAP)):
        cd.hist.update(_extract(df, mp))
    cd.ttm.update(_ttm(qi, INCOME_MAP))
    cd.ttm.update(_ttm(qc, CASHFLOW_MAP))

    yrs = sorted({y for s in cd.hist.values() for y in s})
    rev = cd.hist.get("revenue", {})
    cd.years = [y for y in yrs if rev.get(y) is not None] or yrs

    for y in cd.years:
        gp, rv, cg = cd.h("gross_profit", y), cd.h("revenue", y), cd.h("cogs", y)
        if gp is None and rv is not None and cg is not None:
            cd.hist.setdefault("gross_profit", {})[y] = round(rv - cg, 1)
        ebit = cd.h("ebit", y)
        da = cd.h("da", y) if cd.h("da", y) is not None else cd.h("cf_da", y)
        if ebit is not None and da is not None:
            cd.hist.setdefault("ebitda", {})[y] = round(ebit + da, 1)
        ocf, cap = cd.h("ocf", y), cd.h("capex", y)
        if cd.h("fcf", y) is None and ocf is not None and cap is not None:
            cd.hist.setdefault("fcf", {})[y] = round(ocf + cap, 1)
        csh, dbt = cd.h("cash", y), cd.h("debt", y)
        if csh is not None and dbt is not None:
            cd.hist.setdefault("net_debt", {})[y] = round(dbt - csh, 1)

    if cd.years:
        cd.notes.append(
            "Historico yfinance %d-%d (%d ejercicios), simbolo %s, moneda de reporte %s."
            % (cd.years[0], cd.years[-1], len(cd.years), sym, cd.currency)
        )
    return cd


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    t = sys.argv[1] if len(sys.argv) > 1 else "CSU"
    c = fetch(t)
    print(c.ticker, c.yf_symbol, c.currency, c.years)
    for m in ["revenue", "gross_profit", "ebit", "ebitda", "net_income", "ocf", "capex",
              "fcf", "sbc", "ma", "cash", "debt", "net_debt", "equity"]:
        if c.has(m):
            print("  %-14s" % m, c.series(m))
    print("  TTM:", {k: v for k, v in c.ttm.items() if k in ("revenue", "ebit", "fcf", "sbc", "ocf")})
