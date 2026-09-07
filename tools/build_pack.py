"""
Genera el "pack" completo de una empresa de la watchlist:

    Inversión Roger/<Empresa>/Deep Dive 2026-08/
        <TICKER>_Model_2019-2030.xlsx     12 hojas, estandar Prysmian
        <TICKER>_Dashboard.html           autosuficiente
        README.md                          que es cada fichero y que falta

Los escenarios se DERIVAN del Excel de Roger, no se inventan: el margen de FCF de
salida se calcula para que el FCF del anio terminal reproduzca exactamente
fcf_5y_min / fcf_5y_max de watchlist_ratings.xlsx, y los multiplos de salida son los
suyos. Lo que anade el modelo es el MECANISMO (ingresos -> margen -> caja) que en el
Excel es una sola celda.

Uso:
    py build_pack.py CSU
    py build_pack.py --all-top          (las 23 con compuesto >= 7)
    py build_pack.py CSU COST DSGX --no-model
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import company_data as CDATA
from model_builder import ModelBuilder

ROOT = Path(__file__).resolve().parents[3]          # BOLSA E INVERSIÓN
INV = ROOT / "Inversión Roger"
TODAY = date.today().isoformat()

# ticker -> carpeta en "Inversión Roger"
FOLDER = {
    "CSU": "Constellation Software", "VEEV": "Veeva", "COST": "Costco", "BN": "Brookfield",
    "DSGX": "Descartes Systems", "LIFCO B": "Lifco", "MSFT": "Microsoft",
    "LOTB": "Lotus Bakeries", "AMZN": "Amazon", "ADYEN": "Adyen", "RAA": "Rational AG",
    "HLMA": "Halma", "ITX": "Inditex", "NTO": "Nintendo", "SU": "Schneider Electric",
    "MNST": "Monster", "DNP": "Dino Polska", "VLTO": "Veralto", "ABNB": "Airbnb",
    "ZS": "Zscaler", "SAP": "SAP", "FICO": "Fair Isaac", "LR": "Legrand",
    "PRY": "Prysmian", "RBT": "Robertet", "ROKO B": "Roko AB", "IP": "Interpump Group",
    "USPH": "US Physical Therapy", "SOM": "Somero", "KKR": "KKR", "META": "Meta",
    "GOOG": "Alphabet", "NFLX": "Netflix", "SPOT": "Spotify", "UBER": "Uber",
}
NICE = {
    "CSU": "Constellation Software", "VEEV": "Veeva Systems", "COST": "Costco Wholesale",
    "BN": "Brookfield Corporation", "DSGX": "The Descartes Systems Group", "LIFCO B": "Lifco",
    "MSFT": "Microsoft", "LOTB": "Lotus Bakeries", "AMZN": "Amazon", "ADYEN": "Adyen",
    "RAA": "Rational AG", "HLMA": "Halma", "ITX": "Industria de Diseño Textil (Inditex)",
    "NTO": "Nintendo", "SU": "Schneider Electric", "MNST": "Monster Beverage",
    "DNP": "Dino Polska", "VLTO": "Veralto", "ABNB": "Airbnb", "ZS": "Zscaler",
    "SAP": "SAP SE", "FICO": "Fair Isaac Corporation", "LR": "Legrand",
}

# Empresas cuyo crecimiento viene sobre todo de comprar, no de crecer organicamente.
SERIAL_ACQUIRERS = {"CSU", "LIFCO B", "ROKO B", "HLMA", "VLTO", "IP", "DSGX", "RAA"}

def load_fx():
    """factor = moneda de REPORTE -> moneda de COTIZACION, del meta de watchlist.json."""
    d = json.loads((CDATA.WATCHLIST_JSON).read_text(encoding="utf-8"))
    return {m["ticker"]: m["factor"] for m in d["meta"].get("currency_mismatches", [])
            if m.get("resolved")}


FX = None

TOP23 = ["CSU", "VEEV", "COST", "BN", "DSGX", "LIFCO B", "MSFT", "LOTB", "AMZN", "ADYEN",
         "RAA", "HLMA", "ITX", "NTO", "SU", "MNST", "DNP", "VLTO", "ABNB", "ZS", "SAP",
         "FICO", "LR"]


# ------------------------------------------------------------------ helpers

def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _ratio(num, den, default=0.0, lo=-5.0, hi=5.0):
    n, d = _safe(num, None), _safe(den, None)
    if n is None or d in (None, 0):
        return default
    r = n / d
    return default if not (lo <= r <= hi) else r


def _last(cd, metric):
    for y in reversed(cd.years):
        v = cd.h(metric, y)
        if v is not None:
            return v
    return None


def _avg(cd, metric, n=3):
    vals = [cd.h(metric, y) for y in cd.years[-n:]]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _cagr(cd, metric, n=4):
    ys = [y for y in cd.years if cd.h(metric, y) is not None][-n:]
    if len(ys) < 2:
        return None
    a, b = cd.h(metric, ys[0]), cd.h(metric, ys[-1])
    if not a or a <= 0 or b <= 0:
        return None
    return (b / a) ** (1 / (len(ys) - 1)) - 1


# ------------------------------------------------------------------ escenarios

def derive_config(cd):
    """Deriva los 15 supuestos x 3 escenarios desde el historico + el Excel de Roger."""
    wl = cd.wl
    # Base de calibracion: el ULTIMO EJERCICIO REPORTADO, que es de donde arranca
    # la proyeccion del modelo. Usar el LTM aqui descuadraba el FCF terminal un 9%.
    rev_base = _last(cd, "revenue") or _safe(wl.get("revenue_ltm")) or 0.0
    rev_ltm = _safe(wl.get("revenue_ltm")) or rev_base
    fcf_ltm = _safe(wl.get("fcf_ltm")) or _last(cd, "fcf") or 0.0
    fcf_min = _safe(wl.get("fcf_5y_min"), fcf_ltm)
    fcf_max = _safe(wl.get("fcf_5y_max"), fcf_ltm * 1.5)
    m_min = _safe(wl.get("exit_mult_min"), 12.0)
    m_max = _safe(wl.get("exit_mult_max"), 22.0)

    hist_g = _cagr(cd, "revenue") or 0.06
    hist_g = max(-0.05, min(0.30, hist_g))
    g_base = hist_g * 0.7
    g_bear = max(0.0, hist_g * 0.30)
    g_bull = hist_g * 0.95

    if cd.ticker in SERIAL_ACQUIRERS:
        split = (0.35, 0.65)          # organico / M&A
    else:
        split = (0.90, 0.10)

    def gsplit(g):
        return round(g * split[0], 4), round(g * split[1], 4)

    org = [gsplit(g)[0] for g in (g_bear, g_base, g_bull)]
    acq = [gsplit(g)[1] for g in (g_bear, g_base, g_bull)]

    # Margen de FCF de salida: lo fijamos para reproducir el FCF@5y del Excel.
    def term_rev(g):
        return rev_base * (1 + g) ** 5 if rev_base else 0.0

    fcf_base = (fcf_min + fcf_max) / 2
    mfcf = []
    for g, target in ((g_bear, fcf_min), (g_base, fcf_base), (g_bull, fcf_max)):
        tr = term_rev(g)
        mfcf.append(round(target / tr, 4) if tr else 0.10)

    gm = _ratio(_last(cd, "gross_profit"), _last(cd, "revenue"), 0.40)
    opex = _ratio(abs(_safe(_last(cd, "gross_profit")) - _safe(_last(cd, "ebit"))),
                  _last(cd, "revenue"), 0.25)
    da = _ratio(_avg(cd, "da"), _avg(cd, "revenue"), 0.04, lo=0, hi=0.6)
    capex = _ratio(abs(_safe(_avg(cd, "capex"))), _avg(cd, "revenue"), 0.03, lo=0, hi=0.6)
    wc = _ratio(
        (_safe(_last(cd, "receivables")) + _safe(_last(cd, "inventory"))
         - _safe(_last(cd, "payables"))), _last(cd, "revenue"), 0.05, lo=-1, hi=1)
    tax = _ratio(abs(_safe(_avg(cd, "tax"))), _avg(cd, "pretax"), 0.22, lo=0, hi=0.6)
    kd = _ratio(abs(_safe(_avg(cd, "interest"))), _avg(cd, "debt"), 0.045, lo=0, hi=0.25)
    sbc = _ratio(_avg(cd, "sbc"), _avg(cd, "revenue"), 0.0, lo=0, hi=0.6)
    ma = _ratio(abs(_safe(_avg(cd, "ma"))), _avg(cd, "fcf"), 0.0, lo=0, hi=3)
    div = _ratio(abs(_safe(_avg(cd, "dividends"))), _avg(cd, "fcf"), 0.0, lo=0, hi=2)
    bb = _ratio(abs(_safe(_avg(cd, "buybacks"))), _avg(cd, "fcf"), 0.0, lo=0, hi=2)

    # Capex de mantenimiento: el minimo entre lo que gasta y lo que amortiza. No puedes
    # estar sobreinvirtiendo si el capex es menor que el D&A. Cuando capex > D&A, la
    # diferencia es inversion de crecimiento y el bloque de normalizacion se activa solo.
    da_pct = _ratio(_avg(cd, "cf_da") or _avg(cd, "da"), _avg(cd, "revenue"), capex,
                    lo=0, hi=0.6)
    maint_capex = min(capex, da_pct)
    rnd_pct = _ratio(_avg(cd, "rnd"), _avg(cd, "revenue"), 0.0, lo=0, hi=0.6)

    A = {
        "Crecimiento organico anual": tuple(org),
        "Crecimiento por adquisiciones anual": tuple(acq),
        "Margen bruto de salida": (round(gm * 0.96, 4), round(gm, 4), round(gm * 1.04, 4)),
        "Opex de salida (% ingresos)": (round(opex * 1.06, 4), round(opex, 4),
                                        round(opex * 0.92, 4)),
        "D&A (% ingresos)": (round(da, 4),) * 3,
        "Capex (% ingresos)": (round(capex * 1.15, 4), round(capex, 4), round(capex * 0.9, 4)),
        "Circulante neto (% ingresos)": (round(wc, 4),) * 3,
        "Tasa fiscal efectiva": (round(min(0.35, tax + 0.02), 4), round(tax, 4),
                                 round(max(0.05, tax - 0.02), 4)),
        "Coste medio de la deuda": (round(kd + 0.01, 4), round(kd, 4), round(max(0.0, kd - 0.005), 4)),
        "SBC (% ingresos)": (round(sbc, 4), round(sbc * 0.9, 4), round(sbc * 0.7, 4)),
        "M&A (% del FCF)": (round(min(1.2, ma), 4),) * 3,
        "Dividendos (% del FCF)": (round(min(1.0, div), 4),) * 3,
        "Recompras (% del FCF)": (round(min(1.0, bb), 4),) * 3,
        "Margen FCF de salida": tuple(mfcf),
        "Multiplo de salida EV/FCF": (m_min, round((m_min + m_max) / 2, 1), m_max),
        # Por defecto INERTES: mantenimiento = lo que gasta hoy, asi que el "crecimiento"
        # sale cero y el FCF normalizado = FCF. Solo se activa cuando D&A < capex, que es
        # la definicion contable de estar invirtiendo por encima de lo que se consume.
        "Capex de MANTENIMIENTO (% ingresos)": (round(maint_capex, 4),) * 3,
        "I+D de MANTENIMIENTO (% ingresos)": (round(rnd_pct, 4),) * 3,
    }

    notes = [
        "El margen de FCF de salida esta calibrado para reproducir el FCF@5y "
        "que Roger tiene en watchlist_ratings.xlsx (%s / %s). Si cambias el crecimiento, "
        "recalibra el margen o el FCF terminal dejara de coincidir con el Excel."
        % (f"{fcf_min:,.0f}", f"{fcf_max:,.0f}"),
        "Los multiplos de salida son los del Excel (%.0fx / %.0fx). Regla de Roger: en un "
        "ciclico el multiplo es ALTO en el suelo y BAJO en el pico; lo que debe crecer es el "
        "FCF, no el multiplo." % (m_min, m_max),
        "Crecimiento historico de ingresos (CAGR %d ejercicios): %.1f%%. Bajista %.1f%%, "
        "base %.1f%%, alcista %.1f%%." % (len(cd.years), hist_g * 100, g_bear * 100,
                                          g_base * 100, g_bull * 100),
    ]
    if capex > maint_capex * 1.05 and capex > 0.02:
        notes.append(
            "SOBREINVERSION DETECTADA: capex del %.1f%% de los ingresos contra un D&A del "
            "%.1f%%. El bloque de FCF normalizado de Cash_Flow esta ACTIVO y devuelve el capex "
            "de crecimiento. Si lo usas para valorar, BAJA el multiplo de salida."
            % (capex * 100, da_pct * 100))
    if sbc > 0.10:
        notes.append(
            "OJO: el SBC es el %.1f%% de los ingresos. La fila 'FCF menos SBC' de Cash_Flow "
            "es la buena para valorar; el FCF a secas sobreestima." % (sbc * 100))
    if cd.ticker in SERIAL_ACQUIRERS:
        notes.append(
            "Serial acquirer: el crecimiento se reparte %.0f%% organico / %.0f%% comprado. "
            "El ROIIC de la hoja Capital_Alloc es la metrica que decide la tesis."
            % (split[0] * 100, split[1] * 100))

    global FX
    if FX is None:
        FX = load_fx()
    fx = FX.get(cd.ticker, 1.0)

    for label, trio in OVERRIDES.get(cd.ticker, {}).items():
        A[label] = trio
        notes.append("AJUSTE MANUAL en '%s': %s (la cifra derivada del historico enganaba)."
                     % (label, ", ".join("%.1f%%" % (x * 100) for x in trio)))
    if cd.ticker in FRAME_WARNINGS:
        notes.insert(0, "AVISO DE MARCO — " + FRAME_WARNINGS[cd.ticker])

    return {
        "fx": fx,
        "price": round(_safe(wl.get("price")), 4),
        "shares": round(_safe(wl.get("shares_out_m")), 4),
        "debt": round(_safe(wl.get("total_debt"))),
        "cash": round(_safe(wl.get("cash"))),
        "fcf_ltm": round(fcf_ltm),
        "quote_ccy": wl.get("currency", cd.currency),
        "assumptions": A,
        "scenario_notes": notes,
        "verdict": VERDICTS.get(cd.ticker, {}),
        "_derived": dict(hist_g=hist_g, g=(g_bear, g_base, g_bull), mfcf=mfcf,
                         sbc=sbc, ma=ma, capex=capex, rev_ltm=rev_ltm, fcf_ltm=fcf_ltm,
                         fcf_min=fcf_min, fcf_max=fcf_max, m_min=m_min, m_max=m_max,
                         rev_base=rev_base, fx=fx, maint_capex=maint_capex, capex_pct=capex,
                         rnd_pct=rnd_pct),
    }


# Ajustes manuales por empresa. Se aplican DESPUES de derivar del historico, porque hay
# casos donde la cifra automatica es enganosa y ya sabemos por que.
OVERRIDES = {
    # La tasa fiscal GAAP de CSU (37,6%) esta inflada: el denominador esta deprimido por
    # amortizacion de intangibles no deducible. Sobre EBIT paga un 16-17% estable.
    "CSU": {"Tasa fiscal efectiva": (0.18, 0.17, 0.16)},
    # Zscaler: el SBC es el 24,7% de los ingresos. El caso alcista EXIGE que baje; si no,
    # no hay beneficio economico. Ver la nota de GAAP vs no-GAAP.
    "ZS": {"SBC (% ingresos)": (0.24, 0.18, 0.11)},
    "ABNB": {"SBC (% ingresos)": (0.12, 0.09, 0.06)},
}

# Empresas donde este marco (EV/FCF operativo) NO es el correcto, y por que.
FRAME_WARNINGS = {
    "BN": "Brookfield es una holding de activos financieros y aseguradoras. La deuda que "
          "aparece en el balance consolidado es en su mayor parte pasivo de las filiales, no "
          "del accionista, igual que pasa con KKR (56.164 M$ que son sobre todo Global "
          "Atlantic). Un modelo EV/FCF operativo NO es la herramienta correcta: hay que "
          "valorarla por suma de partes sobre el NAV y los distributable earnings. Este "
          "libro sirve como recopilacion de datos, no como valoracion.",
    "KKR": "Igual que Brookfield: la deuda consolidada es sobre todo de Global Atlantic. "
           "El EV/FCF esta estructuralmente inflado.",
    "NTO": "Nintendo fabrica e inventaria consolas antes de venderlas, asi que el FCF se "
           "deprime en el PICO de ventas. La metrica honesta es EV/EBIT sobre beneficio "
           "medio de ciclo, no el FCF de un ejercicio.",
    "ZS": "El SBC es el 24,7% de los ingresos: el FCF reportado NO es beneficio economico. "
          "Usa la fila 'FCF menos SBC' de Cash_Flow. Ver la nota sobre GAAP vs no-GAAP.",
}

# Veredictos escritos (de los deep dives). Se vuelcan en el Dashboard del Excel y del HTML.
VERDICTS = {
    "CSU":  dict(conviction="4/5", terminal="BAJO", sizing="2,5-3,5%",
                 alert="ampliar < 2.800 CAD", catalyst="Q3 2026 (nov) — margen y ritmo de M&A"),
    "VEEV": dict(conviction="4/5", terminal="MEDIO", sizing="1,5-2,0%",
                 alert="entrada atractiva < 230 USD", catalyst="Q2 FY27 (ago-sep 2026)"),
    "COST": dict(conviction="5/5", terminal="MUY BAJO", sizing="3-5%",
                 alert="—", catalyst="Q4 FY26 (sep 2026)"),
    "DSGX": dict(conviction="3/5", terminal="BAJO-MEDIO", sizing="1,5-2,5%",
                 alert="—", catalyst="Resultados 10-sep-2026 (organico)"),
    "BN":   dict(conviction="3,5/5", terminal="MEDIO", sizing="1,5-2,5%",
                 alert="—", catalyst="Investor Day"),
    "LIFCO B": dict(conviction="4/5", terminal="MUY BAJO", sizing="0-1%",
                    alert="—", catalyst="Q3 2026"),
    "LOTB": dict(conviction="4,5/5", terminal="MUY BAJO", sizing="0%",
                 alert="—", catalyst="Resultados semestrales"),
    "HLMA": dict(conviction="4/5", terminal="MUY BAJO", sizing="0-1%", alert="—", catalyst="—"),
    "ITX":  dict(conviction="4,5/5", terminal="BAJO", sizing="3-5%", alert="—", catalyst="Q2 FY26"),
    "NTO":  dict(conviction="4/5", terminal="MUY BAJO", sizing="0%",
                 alert="—", catalyst="Ciclo Switch 2"),
    "SU":   dict(conviction="4/5", terminal="BAJO", sizing="2-3%", alert="—", catalyst="Q3 2026"),
    "MNST": dict(conviction="4/5", terminal="MUY BAJO", sizing="0%", alert="—", catalyst="—"),
    "VLTO": dict(conviction="4/5", terminal="MUY BAJO", sizing="1-2%", alert="—", catalyst="—"),
    "ABNB": dict(conviction="4/5", terminal="BAJO-MEDIO", sizing="3-5%", alert="—",
                 catalyst="Q3 2026"),
    "SAP":  dict(conviction="4/5", terminal="BAJO", sizing="2-3%", alert="—", catalyst="—"),
    "FICO": dict(conviction="4/5", terminal="BAJO-MEDIO", sizing="1,5-2%",
                 alert="—", catalyst="Decision FHFA sobre scores alternativos"),
    "LR":   dict(conviction="3,5/5", terminal="BAJO", sizing="1%", alert="—", catalyst="—"),
    "ZS":   dict(conviction="pendiente", terminal="MEDIO", sizing="0% hasta resolver SBC",
                 alert="—", catalyst="Q4 FY26 (sep 2026)"),
    "MSFT": dict(conviction="pendiente", terminal="BAJO", sizing="pendiente", alert="—",
                 catalyst="Q1 FY27 (oct 2026)"),
    "AMZN": dict(conviction="pendiente", terminal="BAJO-MEDIO", sizing="pendiente", alert="—",
                 catalyst="Q3 2026"),
    "ADYEN": dict(conviction="pendiente", terminal="MEDIO", sizing="pendiente", alert="—",
                  catalyst="Resultados semestrales"),
    "RAA":  dict(conviction="pendiente", terminal="MUY BAJO", sizing="pendiente", alert="—",
                 catalyst="—"),
    "DNP":  dict(conviction="pendiente", terminal="BAJO", sizing="pendiente", alert="—",
                 catalyst="Q3 2026"),
}


# ------------------------------------------------------------------ HTML

def _fmt(v, kind="num", dec=1):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if kind == "pct":
        return ("%.*f%%" % (dec, v * 100)).replace(".", ",")
    if kind == "mult":
        return ("%.*fx" % (dec, v)).replace(".", ",")
    if kind == "ratio":
        return ("%.2f:1" % v).replace(".", ",")
    s = "%,.0f" % v if False else "{:,.0f}".format(v)
    return s.replace(",", ".")


def _spark(vals, w=260, h=64, color="#2563eb"):
    """Mini grafico de barras en SVG, sin dependencias."""
    vs = [v for v in vals if v is not None]
    if not vs:
        return ""
    lo, hi = min(min(vs), 0), max(vs)
    rng = (hi - lo) or 1
    n = len(vals)
    bw = w / max(n, 1) * 0.62
    gap = w / max(n, 1)
    zero = h - (0 - lo) / rng * h
    bars = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        y = h - (v - lo) / rng * h
        top, height = (y, zero - y) if v >= 0 else (zero, y - zero)
        c = color if v >= 0 else "#dc2626"
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="%s"/>'
                    % (i * gap + gap * 0.19, top, bw, max(abs(height), 1), c))
    return ('<svg viewBox="0 0 %d %d" width="100%%" height="%d" preserveAspectRatio="none">'
            '%s<line x1="0" y1="%.1f" x2="%d" y2="%.1f" stroke="#94a3b8" stroke-width="0.7"/>'
            '</svg>' % (w, h, h, "".join(bars), zero, w, zero))


HTML_CSS = """
:root{--bg:#ffffff;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--card:#f8fafc;
--accent:#1f3864;--good:#15803d;--bad:#b91c1c;--warn:#b45309;--chip:#eef2ff;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b1120;--fg:#e2e8f0;
--muted:#94a3b8;--line:#1e293b;--card:#111c33;--accent:#93c5fd;--good:#4ade80;--bad:#f87171;
--warn:#fbbf24;--chip:#172554;}}
:root[data-theme="dark"]{--bg:#0b1120;--fg:#e2e8f0;--muted:#94a3b8;--line:#1e293b;--card:#111c33;
--accent:#93c5fd;--good:#4ade80;--bad:#f87171;--warn:#fbbf24;--chip:#172554;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:30px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
margin:38px 0 12px;font-weight:700}
.sub{color:var(--muted);margin:0 0 6px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;
padding:4px 12px;font-size:12px;font-weight:600}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(168px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.k{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
font-weight:700}
.v{font-size:25px;font-weight:700;letter-spacing:-.02em;margin-top:4px}
.v small{font-size:13px;font-weight:600;color:var(--muted)}
.n{font-size:12px;color:var(--muted);margin-top:3px}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:14px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
thead th{background:var(--card);font-size:11px;text-transform:uppercase;letter-spacing:.05em;
color:var(--muted)}
tbody tr:last-child td{border-bottom:none}
tr.tot td{font-weight:700;background:var(--card)}
.two{display:grid;gap:16px;grid-template-columns:1fr 1fr}
@media(max-width:760px){.two{grid-template-columns:1fr}}
.note{background:var(--card);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
padding:12px 16px;font-size:14px;margin:10px 0}
.note.w{border-left-color:var(--warn)}
ul{padding-left:20px;margin:8px 0}li{margin:5px 0}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);
font-size:12px;color:var(--muted)}
"""


def build_html(cd, cfg, out_path):
    wl, d = cd.wl, cfg["_derived"]
    ccy = cd.currency
    yrs = cd.years
    rev = [cd.h("revenue", y) for y in yrs]
    fcf = [cd.h("fcf", y) for y in yrs]
    ebit = [cd.h("ebit", y) for y in yrs]
    sbc = [cd.h("sbc", y) for y in yrs]

    irr_w = wl.get("irr_worst")
    irr_b = wl.get("irr_best")
    asym = wl.get("irr_asymmetry_ratio")
    v = cfg.get("verdict", {})

    def cls(x, good=0):
        if x is None:
            return ""
        return "good" if x > good else "bad"

    hist_rows = []
    metrics = [("Ingresos", "revenue", "num"), ("Beneficio bruto", "gross_profit", "num"),
               ("EBIT", "ebit", "num"), ("Margen EBIT", None, "mebit"),
               ("EBITDA", "ebitda", "num"), ("Beneficio neto", "net_income", "num"),
               ("Flujo de explotacion", "ocf", "num"), ("Capex", "capex", "num"),
               ("Free cash flow", "fcf", "num"), ("Margen FCF", None, "mfcf"),
               ("SBC", "sbc", "num"), ("M&A neto", "ma", "num"),
               ("Caja", "cash", "num"), ("Deuda total", "debt", "num"),
               ("Deuda neta", "net_debt", "num")]
    for label, key, kind in metrics:
        cells = []
        for y in yrs:
            if kind == "mebit":
                a, b = cd.h("ebit", y), cd.h("revenue", y)
                cells.append(_fmt(a / b, "pct") if a is not None and b else "—")
            elif kind == "mfcf":
                a, b = cd.h("fcf", y), cd.h("revenue", y)
                cells.append(_fmt(a / b, "pct") if a is not None and b else "—")
            else:
                cells.append(_fmt(cd.h(key, y)))
        if all(c == "—" for c in cells):
            continue
        strong = label in ("Ingresos", "Free cash flow", "EBIT")
        hist_rows.append("<tr%s><td>%s</td>%s</tr>" % (
            ' class="tot"' if strong else "", label,
            "".join("<td>%s</td>" % c for c in cells)))

    sc_names = ("Conservador", "Base", "Alcista")
    term = yrs[-1] + 5 if yrs else 2030
    sc_rows = []
    for i, nm in enumerate(sc_names):
        g = d["g"][i]
        tr = d["rev_base"] * (1 + g) ** 5
        f = tr * d["mfcf"][i]
        m = [d["m_min"], (d["m_min"] + d["m_max"]) / 2, d["m_max"]][i]
        ev = f * m
        eq = ev - (_safe(wl.get("total_debt")) - _safe(wl.get("cash")))
        ps = eq / _safe(wl.get("shares_out_m"), 1) * d["fx"]
        px = _safe(wl.get("price"), 1)
        irr = (ps / px) ** 0.2 - 1 if ps > 0 and px else None
        sc_rows.append(
            "<tr%s><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td class='%s'><b>%s</b></td></tr>" % (
                ' class="tot"' if i == 1 else "", nm, _fmt(g, "pct"), _fmt(tr),
                _fmt(f), _fmt(m, "mult"), _fmt(ps, "num") if ps > 1000 else
                ("%.2f" % ps).replace(".", ","),
                cls(irr), _fmt(irr, "pct")))

    notes = "".join("<li>%s</li>" % n for n in cfg.get("scenario_notes", []))
    sbc_warn = ""
    if d["sbc"] > 0.10:
        sbc_warn = (
            '<div class="note w"><b>El SBC es el %s de los ingresos.</b> El EV/FCF publicado '
            'sobreestima el negocio: la retribucion en acciones es un coste real que se paga '
            'con dilucion, no con caja. En este dashboard mira siempre la fila '
            '<i>FCF menos SBC</i>.</div>' % _fmt(d["sbc"], "pct"))

    html = """<title>{tk} — Deep Dive</title>
<style>{css}</style>
<div class="wrap">
<h1>{name}</h1>
<p class="sub">{tk} · {cat} · {ccy} · precio {px} {qccy} · datos a {today}</p>
<div class="chips">
  <span class="chip">Compuesto {comp}</span>
  <span class="chip">EV/FCF {evfcf}</span>
  <span class="chip">ROIC {roic}</span>
  <span class="chip">Asimetria {asym}</span>
  <span class="chip">{quad}</span>
</div>

<h2>Eje 1 — Calidad (no depende del precio)</h2>
<div class="grid">
  <div class="card"><div class="k">Rating compuesto</div><div class="v">{comp}</div>
    <div class="n">puesto {rank} de 70</div></div>
  <div class="card"><div class="k">R1 estructural</div><div class="v">{r1}</div>
    <div class="n">mision, moat, propiedad</div></div>
  <div class="card"><div class="k">R2 calidad economica</div><div class="v">{r2}</div>
    <div class="n">finanzas, clientes, gestion</div></div>
  <div class="card"><div class="k">R3 durabilidad</div><div class="v">{r3}</div>
    <div class="n">riesgo existencial</div></div>
  <div class="card"><div class="k">ROIC LTM</div><div class="v">{roic}</div>
    <div class="n">z vs categoria {zroic}</div></div>
  <div class="card"><div class="k">Riesgo terminal</div><div class="v">{termr}</div>
    <div class="n">componente de R3</div></div>
</div>

<h2>Eje 2 — Asimetria (depende del precio de hoy)</h2>
<div class="grid">
  <div class="card"><div class="k">TIR conservadora</div>
    <div class="v {cw}">{irrw}</div><div class="n">anualizada a 5 anios</div></div>
  <div class="card"><div class="k">TIR alcista</div>
    <div class="v {cb}">{irrb}</div><div class="n">anualizada a 5 anios</div></div>
  <div class="card"><div class="k">Asimetria</div><div class="v">{asym}</div>
    <div class="n">minimo del marco 2,00:1</div></div>
  <div class="card"><div class="k">EV/FCF hoy</div><div class="v">{evfcf}</div>
    <div class="n">media 5 anios {ev5}</div></div>
  <div class="card"><div class="k">Barato vs si misma</div><div class="v">{zself}</div>
    <div class="n">desviaciones tipicas</div></div>
  <div class="card"><div class="k">Cuadrante</div><div class="v" style="font-size:17px">{quad}</div>
    <div class="n">del sistema cuantitativo</div></div>
</div>
{sbcwarn}

<h2>Historico reportado ({ccy} M)</h2>
<div class="two">
  <div class="card"><div class="k">Ingresos</div>{sp_rev}
    <div class="n">{y0}–{y1}</div></div>
  <div class="card"><div class="k">Free cash flow</div>{sp_fcf}
    <div class="n">{y0}–{y1}</div></div>
</div>
<div class="scroll" style="margin-top:12px">
<table><thead><tr><th>Metrica</th>{ths}</tr></thead><tbody>{hist}</tbody></table>
</div>

<h2>Escenarios a {term}</h2>
<div class="scroll">
<table><thead><tr><th>Escenario</th><th>Crec. ingresos</th><th>Ingresos {term}</th>
<th>FCF {term}</th><th>Multiplo salida</th><th>Valor/accion</th><th>TIR 5a</th></tr></thead>
<tbody>{sc}</tbody></table>
</div>
<div class="note"><b>Como se han calibrado.</b><ul>{notes}</ul></div>

<h2>Veredicto</h2>
<div class="grid">
  <div class="card"><div class="k">Conviccion</div><div class="v">{conv}</div></div>
  <div class="card"><div class="k">Riesgo terminal</div>
    <div class="v" style="font-size:19px">{termv}</div></div>
  <div class="card"><div class="k">Sizing</div><div class="v" style="font-size:19px">{siz}</div></div>
  <div class="card"><div class="k">Alerta de precio</div>
    <div class="v" style="font-size:15px">{alert}</div></div>
  <div class="card"><div class="k">Proximo catalizador</div>
    <div class="v" style="font-size:15px">{cat2}</div></div>
</div>

<h2>Que falta para que esto sea nivel Prysmian</h2>
<div class="note"><ul>
<li>Desglose de <b>ingresos por segmento / producto / geografia</b> en la hoja Revenue_Build.</li>
<li><b>Comentario de fuente celda a celda</b> en el historico (pagina del informe anual).</li>
<li>Las <b>11 secciones escritas</b> del deep dive, con el scuttlebutt del equipo gestor.</li>
<li>Calibracion manual de los escenarios contra la guia de la compania.</li>
</ul></div>

<footer>Generado por <code>tools/build_pack.py</code> el {today}. Historico: yfinance sobre
{sym}. Precio, escenarios y ratings: <code>watchlist_ratings.xlsx</code>. Este fichero es
autosuficiente: se puede abrir sin conexion.</footer>
</div>"""

    out = html.format(
        css=HTML_CSS, tk=cd.ticker, name=NICE.get(cd.ticker, cd.name),
        cat=wl.get("category", ""), ccy=ccy, qccy=cfg.get("quote_ccy", ccy),
        px=("%.2f" % _safe(wl.get("price"))).replace(".", ","), today=TODAY,
        comp=("%.2f" % _safe(wl.get("rating_composite"))).replace(".", ","),
        rank=wl.get("composite_rank", "—"),
        r1=("%.2f" % _safe(wl.get("rating_1"))).replace(".", ","),
        r2=("%.2f" % _safe(wl.get("rating_2"))).replace(".", ","),
        r3=("%.2f" % _safe(wl.get("rating_3"))).replace(".", ","),
        roic=_fmt(wl.get("roic"), "pct"),
        zroic=("%+.2f" % _safe(wl.get("roic_zscore_by_category"))).replace(".", ","),
        termr=wl.get("r3_terminal_risk", "—"),
        irrw=_fmt(irr_w, "pct"), irrb=_fmt(irr_b, "pct"),
        cw=cls(irr_w), cb=cls(irr_b),
        asym=_fmt(asym, "ratio"), evfcf=_fmt(wl.get("ev_fcf"), "mult"),
        ev5=_fmt(wl.get("ev_fcf_mean_5y"), "mult"),
        zself=("%+.2f" % _safe(wl.get("ev_fcf_zscore_self_5y"))).replace(".", ","),
        quad=(wl.get("quadrant") or "").replace("_", " "),
        sp_rev=_spark(rev), sp_fcf=_spark(fcf),
        y0=yrs[0] if yrs else "", y1=yrs[-1] if yrs else "",
        ths="".join("<th>%s</th>" % y for y in yrs), hist="".join(hist_rows),
        term=term, sc="".join(sc_rows), notes=notes, sbcwarn=sbc_warn,
        conv=v.get("conviction", "pendiente"), termv=v.get("terminal", "—"),
        siz=v.get("sizing", "pendiente"), alert=v.get("alert", "—"),
        cat2=v.get("catalyst", "—"), sym=cd.yf_symbol,
    )
    out_path.write_text(out, encoding="utf-8")
    return out_path


README_TMPL = """# {name} — Deep Dive, agosto 2026

Analisis de **{name} ({tk})** a {today}. Ultimo ejercicio reportado disponible: **{lasty}**.

## Ficheros

| Fichero | Que es | Estado |
|---|---|---|
| `{tk}_Deep_Dive.md` | El analisis escrito: 11 secciones + veredicto | {md_state} |
| `{tk}_Model_2019-2030.xlsx` | Modelo de 12 hojas, conectado por formulas, tres escenarios | generado |
| `{tk}_Dashboard.html` | Dashboard autosuficiente de los dos ejes | generado |

## Como usar el Excel

**Cambia el escenario en `Assumptions!B4`:** `1` conservador, `2` base, `3` alcista. Todo el
modelo operativo (Revenue_Build -> COGS_GP -> PL -> Working_Capital -> Cash_Flow -> Balance ->
Capital_Alloc) recalcula. La hoja `Valuation` muestra **los tres a la vez**, porque lee
directamente las columnas C/D/E de `Assumptions`.

**Actualiza el precio en `Assumptions!B8`** antes de usar cualquier conclusion de valoracion.
El libro esta construido sobre **{px} {qccy}**.

Convencion de color: **azul** = input · **verde** = historico reportado · **negro** = formula ·
**amarillo** = supuesto de escenario. Negativos en rojo entre parentesis. Todo en millones de
**{ccy}** (moneda de REPORTE, que no siempre es la de cotizacion).

Hojas: `Dashboard` · `Assumptions` · `Revenue_Build` · `COGS_GP` · `PL` · `Working_Capital` ·
`Cash_Flow` · `Balance` · `Capital_Alloc` · `Valuation` · `Sensitivities` · `Sources`.

## De donde salen los escenarios

No estan inventados. El **margen de FCF de salida** de cada escenario esta calibrado para que
el FCF del anio terminal reproduzca exactamente el `FCF@5y min/max` que Roger mantiene a mano
en `watchlist_ratings.xlsx`, y los **multiplos de salida** son los suyos ({mmin:.0f}x / {mmax:.0f}x).
Lo que anade el modelo es el **mecanismo**: en el Excel el FCF@5y es una celda; aqui es
ingresos x margen, y se ve que hace falta para llegar.

## Lo que todavia NO es nivel Prysmian

1. `Revenue_Build` no tiene desglose por segmento/producto/geografia — es una sola linea.
2. El historico no lleva comentario de fuente celda a celda.
3. Los escenarios no estan contrastados contra la guia publicada por la compania.

{extra}
"""


def build_readme(cd, cfg, folder, md_state):
    d = cfg["_derived"]
    extra = ""
    if cd.ticker in FRAME_WARNINGS:
        extra += ("## AVISO: este marco no es el correcto para esta empresa\n\n%s\n\n"
                  % FRAME_WARNINGS[cd.ticker])
    if d["sbc"] > 0.10:
        extra = ("## Aviso sobre el SBC\n\nLa retribucion en acciones es el **%s de los "
                 "ingresos**. El `EV/FCF` de la watchlist sobreestima el negocio porque el FCF "
                 "reportado suma el SBC de vuelta. La fila **`FCF menos SBC`** de la hoja "
                 "`Cash_Flow` es la que hay que usar para valorar.\n"
                 % _fmt(d["sbc"], "pct"))
    txt = README_TMPL.format(
        name=NICE.get(cd.ticker, cd.name), tk=cd.ticker, today=TODAY,
        lasty=cd.years[-1] if cd.years else "n/d", md_state=md_state,
        px=("%.2f" % _safe(cd.wl.get("price"))).replace(".", ","),
        qccy=cfg.get("quote_ccy", cd.currency), ccy=cd.currency,
        mmin=d["m_min"], mmax=d["m_max"], extra=extra)
    (folder / "README.md").write_text(txt, encoding="utf-8")


# ------------------------------------------------------------------ main

def build_one(ticker, wl_index, make_model=True, make_html=True, make_readme=True):
    cd = CDATA.fetch(ticker, wl_index.get(ticker))
    if not cd.wl:
        return "%-8s SIN registro en watchlist.json" % ticker
    cfg = derive_config(cd)
    folder_name = FOLDER.get(ticker)
    if not folder_name:
        return "%-8s sin carpeta mapeada" % ticker
    base = INV / folder_name
    dd = base / "Deep Dive 2026-08"
    dd.mkdir(parents=True, exist_ok=True)

    made = []
    if make_model:
        wb = ModelBuilder(cd, cfg).build()
        p = dd / ("%s_Model_2019-2030.xlsx" % ticker.replace(" ", "_"))
        wb.save(p)
        made.append("modelo(%d hojas)" % len(wb.sheetnames))
    if make_html:
        p = dd / ("%s_Dashboard.html" % ticker.replace(" ", "_"))
        build_html(cd, cfg, p)
        made.append("dashboard")
    if make_readme:
        md = list(dd.glob("*Deep_Dive*.md")) + list(base.glob("*Deep_Dive*.md")) \
            + list(base.glob("*deep_dive*.md"))
        size = max([q.stat().st_size for q in md], default=0)
        state = ("completo (%d kB)" % (size // 1024)) if size >= 30000 else (
            "parcial (%d kB) — AMPLIAR" % (size // 1024) if size else "PENDIENTE")
        build_readme(cd, cfg, dd, state)
        made.append("readme")
    return "%-8s %-22s %s | hist %s | %s" % (
        ticker, folder_name[:22], ", ".join(made),
        "%d-%d" % (cd.years[0], cd.years[-1]) if cd.years else "n/d",
        "SBC %s" % _fmt(cfg["_derived"]["sbc"], "pct") if cfg["_derived"]["sbc"] > 0.05 else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--all-top", action="store_true", help="las 23 con compuesto >= 7")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    wl = CDATA.load_watchlist()
    tickers = TOP23 if args.all_top else args.tickers
    if not tickers:
        ap.error("da un ticker o --all-top")
    for t in tickers:
        try:
            print(build_one(t, wl, make_model=not args.no_model, make_html=not args.no_html))
        except Exception as exc:
            import traceback
            print("%-8s ERROR %s" % (t, exc))
            traceback.print_exc(limit=3)


if __name__ == "__main__":
    main()
