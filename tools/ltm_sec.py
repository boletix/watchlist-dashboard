# -*- coding: utf-8 -*-
"""
ltm_sec.py — cifras LTM de FUENTE PRIMARIA desde EDGAR (XBRL companyfacts).

Regla de Roger (27-sep-2026): los LTM NUNCA salen de yfinance. Para las empresas que presentan
en la SEC con XBRL (10-K/10-Q, y 40-F/6-K cuando llevan XBRL), las cifras son las que la propia
compania etiqueta en sus estados. Este script las lee y calcula:

    LTM = acumulado del ejercicio en curso + ejercicio anterior - mismo acumulado del anterior

y para los saldos (caja, deuda, acciones) el ultimo valor. Imprime CADA componente con su
periodo y su formulario, para contrastarlo contra la nota de prensa antes de escribir nada.

    py tools/ltm_sec.py VEEV
    py tools/ltm_sec.py COST --json      # ademas guarda data/_ltm_sec_<TICKER>.json

No decide por ti que etiqueta de deuda o de capex es la buena: las ensenia todas.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import urllib.request
from datetime import date

UA = "watchlist-dashboard/1.0 (%s)" % os.environ.get("SEC_CONTACT_EMAIL", "contacto-no-configurado@example.com")

FLOWS = {
    "ingresos": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "ebit": ["OperatingIncomeLoss"],
    "beneficio_neto": ["NetIncomeLoss", "ProfitLoss"],
    "bai": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "impuestos": ["IncomeTaxExpenseBenefit"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex_ppe": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "capex_software": ["PaymentsToDevelopSoftware", "PaymentsForSoftware"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortization", "Depreciation", "DepreciationAmortizationAndOther",
           "DepreciationNonproduction", "AmortizationOfIntangibleAssets"],
    "recompras": ["PaymentsForRepurchaseOfCommonStock"],
    "dividendos": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "adquisiciones": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
}
STOCKS = {
    "caja": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "inversiones_cp": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "deuda_lp": ["LongTermDebtNoncurrent", "LongTermDebt", "ConvertibleNotesPayable",
                 "ConvertibleDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "deuda_cp": ["LongTermDebtCurrent", "DebtCurrent", "ConvertibleNotesPayableCurrent"],
    "arrend_financiero": ["FinanceLeaseLiability", "FinanceLeaseLiabilityNoncurrent"],
    "arrend_operativo": ["OperatingLeaseLiability"],
}
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "40-F", "6-K", "20-F", "8-K"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    r = urllib.request.urlopen(req, timeout=60)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def cik_of(ticker):
    m = _get("https://www.sec.gov/files/company_tickers.json")
    t = ticker.upper().replace(" ", "-")
    for v in m.values():
        if v["ticker"].upper() == t:
            return int(v["cik_str"])
    raise SystemExit(f"{ticker}: no esta en company_tickers.json de la SEC")


def _d(s):
    return date.fromisoformat(s)


def _facts(cf, concept):
    for tax in ("us-gaap", "ifrs-full"):
        node = cf["facts"].get(tax, {}).get(concept)
        if node:
            for unit, vals in node["units"].items():
                if unit in ("USD", "EUR", "CAD", "GBP", "CHF", "KZT", "shares"):
                    return [v for v in vals if v.get("form") in FORMS], unit, tax
    return [], None, None


def ltm_flow(cf, concepts):
    """Devuelve (valor, detalle) o (None, motivo). Elige la primera etiqueta con dato reciente."""
    best = None
    for c in concepts:
        vals, unit, tax = _facts(cf, c)
        vals = [v for v in vals if v.get("start")]
        if not vals:
            continue
        end = max(_d(v["end"]) for v in vals)
        if best is None or end > best[0]:
            best = (end, c, vals, unit)
    if best is None:
        return None, "sin dato"
    end, c, vals, unit = best
    at_end = [v for v in vals if _d(v["end"]) == end]
    ytd = max(at_end, key=lambda v: (_d(v["end"]) - _d(v["start"])).days)
    dur = (_d(ytd["end"]) - _d(ytd["start"])).days
    if dur >= 350:
        return ytd["val"], f"{c}: ejercicio {ytd['start']}..{ytd['end']} ({ytd['form']} {ytd.get('accn','')})"
    fys = [v for v in vals if 350 <= (_d(v["end"]) - _d(v["start"])).days <= 380 and _d(v["end"]) < _d(ytd["start"]) + __import__("datetime").timedelta(days=5)]
    if not fys:
        return None, f"{c}: falta el ejercicio anterior"
    fy = max(fys, key=lambda v: _d(v["end"]))
    prev = [v for v in vals if abs((_d(v["end"]) - _d(ytd["end"])).days - (-364)) <= 10
            and abs((_d(v["end"]) - _d(v["start"])).days - dur) <= 10]
    prev = [v for v in vals if abs(((_d(ytd["end"]) - _d(v["end"])).days) - 364) <= 10
            and abs((_d(v["end"]) - _d(v["start"])).days - dur) <= 10]
    if not prev:
        return None, f"{c}: falta el acumulado comparable del anio anterior"
    pv = max(prev, key=lambda v: v.get("filed", ""))
    val = ytd["val"] + fy["val"] - pv["val"]
    det = (f"{c}: YTD {ytd['start']}..{ytd['end']} {ytd['val']/1e6:,.1f} + FY {fy['start']}..{fy['end']} "
           f"{fy['val']/1e6:,.1f} - YTD ant. {pv['start']}..{pv['end']} {pv['val']/1e6:,.1f}  ({ytd['form']} {ytd.get('accn','')})")
    return val, det


def last_stock(cf, concepts):
    out = []
    for c in concepts:
        vals, unit, tax = _facts(cf, c)
        vals = [v for v in vals if not v.get("start")]
        if not vals:
            continue
        v = max(vals, key=lambda v: (v["end"], v.get("filed", "")))
        out.append((c, v["end"], v["val"], v["form"]))
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    tk = sys.argv[1]
    cik = cik_of(tk)
    cf = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    print(f"== {tk} · {cf['entityName']} · CIK {cik}")
    res = {"ticker": tk, "cik": cik, "entity": cf["entityName"], "flows": {}, "stocks": {}}
    ref = None
    for k in ("ocf", "ingresos"):
        _, det0 = ltm_flow(cf, FLOWS[k])
        import re as _re
        m = _re.findall(r"\.\.(\d{4}-\d{2}-\d{2})", det0 or "")
        if m:
            ref = max([_d(x) for x in m] + ([ref] if ref else []))
    for k, cs in FLOWS.items():
        v, det = ltm_flow(cf, cs)
        import re as _re
        ends = [_d(x) for x in _re.findall(r"\.\.(\d{4}-\d{2}-\d{2})", det or "")]
        stale = bool(ref and ends and max(ends) < ref - __import__("datetime").timedelta(days=100))
        if stale:
            det = "ETIQUETA OBSOLETA, NO USAR (" + det + ")"
        res["flows"][k] = {"ltm": None if stale else v, "detalle": det}
        print(f"  {k:15} {'—' if (v is None or stale) else f'{v/1e6:>12,.1f}'}   {det}")
    for k, cs in STOCKS.items():
        rows = last_stock(cf, cs)
        rows = [r for r in rows if not ref or _d(r[1]) >= ref - __import__("datetime").timedelta(days=100)]
        res["stocks"][k] = rows
        for c, end, val, form in rows:
            print(f"  {k:15} {val/1e6:>12,.1f}   {c} a {end} ({form})")
    sh = cf["facts"].get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if sh:
        v = max(sh["units"]["shares"], key=lambda v: v["end"])
        res["acciones"] = (v["end"], v["val"])
        print(f"  {'acciones':15} {v['val']/1e6:>12,.1f}   dei:EntityCommonStockSharesOutstanding a {v['end']}")
    if "--json" in sys.argv:
        p = os.path.join(os.path.dirname(__file__), "..", "data", f"_ltm_sec_{tk.replace(' ', '_')}.json")
        json.dump(res, open(p, "w", encoding="utf-8"), indent=1, default=str)
        print("  guardado", os.path.normpath(p))


if __name__ == "__main__":
    main()
