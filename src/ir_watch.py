"""
ir_watch.py — vigilante diario de relacion con inversores.

Cada dia comprueba, para las 70 empresas de la watchlist, si ha aparecido algo nuevo:
presentaciones de resultados, informes anuales, hechos relevantes, cambios en el equipo
directivo, o un cambio en la fecha prevista de resultados. Devuelve una lista de cosas
que hay que meter en watchlist_ratings.xlsx.

TRES CAPAS, de mas fiable a menos:

  1. SEC EDGAR (`sec`)      — para los que reportan en EE.UU. API JSON oficial, estructurada,
                              con tipo de documento y fecha. Es la buena. Resuelve el CIK sola.
  2. Pagina de RI (`page`)  — para los europeos. Descarga la pagina de resultados/comunicados
                              y busca enlaces a PDF/HTML nuevos respecto a la ultima pasada.
  3. Noticias (`news`)      — red de seguridad universal via yfinance. Sin configuracion.

Ademas: **deriva de calendario**. Compara la fecha de proximos resultados que da el mercado
contra la que hay en el Excel (columna BP) y avisa si han cambiado. Esa es la causa de que
`earnings.json` se quedara congelado meses.

ESTADO: data/ir_state.json  (lo que ya se ha visto; no se vuelve a avisar)
SALIDA: docs/data/ir_alerts.json

Uso:
    py -m src.ir_watch                      # pasada completa
    py -m src.ir_watch --tickers CSU VEEV   # solo unos pocos
    py -m src.ir_watch --dry-run            # no escribe estado (para probar)
    py -m src.ir_watch --seed               # primera pasada: marca todo como visto sin avisar

Se llama desde src/build.py despues de alerts.py, y reutiliza notify_email / notify_whatsapp.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
STATE_PATH = REPO / "data" / "ir_state.json"
OUT_PATH = REPO / "docs" / "data" / "ir_alerts.json"
WATCHLIST_JSON = REPO / "docs" / "data" / "watchlist.json"
CONFIG_PATH = REPO / "data" / "ir_sources.json"

# La SEC exige un User-Agent identificable con un contacto. Sin el devuelve 403.
# El correo NO va en el codigo: este repo sirve GitHub Pages y es publico. Se pone en
# la variable de entorno SEC_CONTACT_EMAIL (en local, o como secret en Actions).
UA = "watchlist-dashboard/1.0 (%s)" % os.environ.get(
    "SEC_CONTACT_EMAIL", "contacto-no-configurado@example.com")
TIMEOUT = 20
SLEEP_SEC = 0.15          # la SEC pide <10 peticiones/segundo

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Tipos de documento de la SEC que interesan y como de urgentes son
SEC_FORMS = {
    "10-K": ("alta", "Informe anual"),
    "10-Q": ("alta", "Informe trimestral"),
    "20-F": ("alta", "Informe anual (extranjero)"),
    "40-F": ("alta", "Informe anual (Canada)"),
    "6-K":  ("media", "Hecho relevante (extranjero)"),
    "8-K":  ("media", "Hecho relevante"),
    "DEF 14A": ("media", "Convocatoria de junta (retribucion e incentivos)"),
    "SC 13D": ("media", "Participacion significativa activista"),
    "SC 13G": ("baja", "Participacion significativa pasiva"),
    "4": ("baja", "Operacion de un insider"),
}

# Palabras que hacen que un documento suba de prioridad, en varios idiomas.
KEYWORDS_HIGH = [
    "results", "resultat", "resultado", "resultaten", "ergebnis", "interim", "quarterly",
    "half-year", "half year", "full year", "annual report", "informe anual", "jaarverslag",
    "trading update", "capital markets day", "guidance", "outlook", "profit warning",
    "bokslut", "delarsrapport", "arsredovisning", "geschaftsbericht", "rapport annuel",
    "presentacion", "presentation", "earnings call", "webcast",
]
KEYWORDS_MED = [
    "acquisition", "acquires", "adquisicion", "merger", "divestment", "disposal",
    "chief executive", "ceo", "cfo", "chief financial", "board of directors", "consejo",
    "dimision", "resignation", "appoint", "nombramiento", "buyback", "recompra",
    "dividend", "dividendo", "share repurchase", "capital increase", "ampliacion de capital",
]

DOC_EXT = re.compile(r"\.(pdf|htm|html)(\?|$)", re.I)
LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------- utilidades

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", text or "")).strip()


def _priority(title: str, base: str = "baja") -> str:
    t = (title or "").lower()
    if any(k in t for k in KEYWORDS_HIGH):
        return "alta"
    if any(k in t for k in KEYWORDS_MED):
        return "media"
    return base


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    return s


# --------------------------------------------------------------------- capa 1: SEC

_CIK_CACHE = {}


def _sec_cik_map(session):
    global _CIK_CACHE
    if _CIK_CACHE:
        return _CIK_CACHE
    try:
        r = session.get(SEC_TICKERS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        _CIK_CACHE = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
    except Exception as exc:
        log.warning("No se pudo cargar el mapa de CIK de la SEC: %s", exc)
        _CIK_CACHE = {}
    return _CIK_CACHE


def check_sec(ticker: str, sec_symbol: str, session, since: date) -> list[dict]:
    """Devuelve los documentos presentados ante la SEC desde `since`."""
    cik = _sec_cik_map(session).get(sec_symbol.upper())
    if not cik:
        return []
    try:
        r = session.get(SEC_SUBMISSIONS.format(cik=cik), timeout=TIMEOUT)
        r.raise_for_status()
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception as exc:
        log.warning("%s: SEC fallo (%s)", ticker, exc)
        return []
    time.sleep(SLEEP_SEC)

    out = []
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        try:
            filed = date.fromisoformat(recent["filingDate"][i])
        except Exception:
            continue
        if filed < since:
            continue
        if form not in SEC_FORMS:
            continue
        prio, label = SEC_FORMS[form]
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        acc = recent.get("accessionNumber", [""] * len(forms))[i].replace("-", "")
        desc = recent.get("primaryDocDescription", [""] * len(forms))[i] or label
        url = ("https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (cik, acc, doc)) if doc else ""
        out.append({
            "id": "sec:%s:%s" % (recent["accessionNumber"][i], form),
            "source": "SEC EDGAR", "form": form, "title": "%s — %s" % (label, _clean(desc)),
            "date": filed.isoformat(), "url": url,
            "priority": _priority(desc, prio),
        })
    return out


# --------------------------------------------------------------------- capa 2: pagina de RI

def check_page(ticker: str, cfg: dict, session) -> list[dict]:
    """Descarga la pagina de RI y devuelve los enlaces a documentos que no habiamos visto."""
    url = cfg.get("url")
    if not url:
        return []
    try:
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        log.warning("%s: pagina de RI fallo (%s)", ticker, exc)
        return []

    include = re.compile(cfg["include"], re.I) if cfg.get("include") else None
    exclude = re.compile(cfg["exclude"], re.I) if cfg.get("exclude") else None
    out = []
    for href, inner in LINK_RE.findall(html):
        if not DOC_EXT.search(href):
            continue
        title = _clean(inner)[:180]
        full = urljoin(url, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        hay = "%s %s" % (title, href)
        if include and not include.search(hay):
            continue
        if exclude and exclude.search(hay):
            continue
        if not title:
            title = href.rsplit("/", 1)[-1]
        out.append({
            "id": "page:%s" % full,
            "source": "RI: %s" % urlparse(url).netloc,
            "form": "documento", "title": title,
            "date": date.today().isoformat(), "url": full,
            "priority": _priority(title),
        })
    # una pagina de RI suele repetir enlaces; dedup por URL
    seen, uniq = set(), []
    for d in out:
        if d["id"] not in seen:
            seen.add(d["id"])
            uniq.append(d)
    return uniq[:60]


# --------------------------------------------------------------------- capa 3: noticias

def check_news(ticker: str, yf_symbol: str, since: date, name_tokens=()) -> list[dict]:
    """Red de seguridad universal: titulares de yfinance.

    Regla dura: una NOTICIA nunca es de prioridad alta. Solo un documento presentado ante
    el regulador o publicado en la web de RI dispara "actualiza el Excel". Sin esta regla,
    un articulo sobre los resultados de Walmart disparaba una alerta de Costco.
    """
    try:
        import yfinance as yf
        items = yf.Ticker(yf_symbol).news or []
    except Exception as exc:
        log.debug("%s: news fallo (%s)", ticker, exc)
        return []
    out = []
    for n in items:
        c = n.get("content", n)
        title = c.get("title") or ""
        if not title:
            continue
        pub = c.get("pubDate") or c.get("providerPublishTime")
        try:
            d = (datetime.fromisoformat(str(pub).replace("Z", "+00:00")).date()
                 if isinstance(pub, str)
                 else datetime.fromtimestamp(int(pub), tz=timezone.utc).date())
        except Exception:
            d = date.today()
        if d < since:
            continue
        low = title.lower()
        if name_tokens and not any(t in low for t in name_tokens):
            continue                    # la noticia no va de esta empresa
        prio = _priority(title, "baja")
        if prio == "baja":
            continue                    # el ruido de prensa no interesa
        prio = "media"                  # techo duro para las noticias
        link = (c.get("canonicalUrl") or {}).get("url") or c.get("link") or ""
        out.append({
            "id": "news:%s" % (c.get("id") or link or title),
            "source": "Noticias", "form": "noticia", "title": title[:180],
            "date": d.isoformat(), "url": link, "priority": prio,
        })
    return out


# ------------------------------------------------- capa 0: deriva de las CUENTAS

def check_financials_drift(ticker, yf_symbol, wl_rec, tol_rev=0.03, tol_fcf=0.10):
    """La comprobacion mas util de todas, y no necesita configuracion.

    Suma los 4 ultimos trimestres publicados y los compara con lo que hay en el Excel.
    Si el mercado ya tiene un trimestre que el Excel no tiene, o si el LTM difiere mas de
    un `tol`, es que la empresa ha publicado y watchlist_ratings.xlsx esta desfasado.

    Funciona para las 70 empresas por igual: nordicos, britanicos, japoneses y polacos
    incluidos, sin depender de que la web de RI siga viva.
    """
    try:
        import pandas as pd
        import yfinance as yf
        tk = yf.Ticker(yf_symbol)
        qi, qc = tk.quarterly_income_stmt, tk.quarterly_cashflow
    except Exception:
        return None
    if qi is None or getattr(qi, "empty", True):
        return None

    def ttm(df, rows):
        if df is None or getattr(df, "empty", True):
            return None
        for r in rows:
            if r in df.index:
                v = df.loc[r].dropna()
                if len(v) >= 4:
                    return float(v.iloc[:4].sum()) / 1e6
        return None

    try:
        last_q = pd.Timestamp(max(qi.columns)).date()
    except Exception:
        return None

    rev = ttm(qi, ["Total Revenue", "Operating Revenue"])
    fcf = ttm(qc, ["Free Cash Flow"])
    if fcf is None:
        ocf = ttm(qc, ["Operating Cash Flow"])
        cap = ttm(qc, ["Capital Expenditure"])
        fcf = (ocf + cap) if (ocf is not None and cap is not None) else None

    xl_rev = wl_rec.get("revenue_ltm")
    xl_fcf = wl_rec.get("fcf_ltm")
    try:
        xl_last = date.fromisoformat(wl_rec["earnings_last_date"])
    except Exception:
        xl_last = None

    def gap(new, old):
        if not new or not old:
            return None
        return (new - old) / abs(old)

    d_rev, d_fcf = gap(rev, xl_rev), gap(fcf, xl_fcf)

    # Un desvio superior al 200% no es "estan desfasadas": es que la moneda o la escala
    # no coinciden (yfinance devuelve TSM en TWD y el Excel lo tiene en USD, Corticeira
    # en escala distinta, Verallia con trimestres parciales). Se clasifica aparte para no
    # ahogar la lista util.
    units = any(d is not None and abs(d) > 2.0 for d in (d_rev, d_fcf))

    # xl_last es la fecha en que la empresa PUBLICO; last_q es el cierre del trimestre.
    # Publicar es siempre posterior a cerrar, asi que solo hay trimestre nuevo si el cierre
    # es POSTERIOR a la ultima publicacion registrada.
    quarter_new = bool(xl_last and last_q > xl_last)

    material = ((d_rev is not None and abs(d_rev) > tol_rev)
                or (d_fcf is not None and abs(d_fcf) > tol_fcf))
    if not (quarter_new or material):
        return None

    return {
        "ticker": ticker,
        "ultimo_trimestre_publicado": last_q.isoformat(),
        "ultimos_resultados_en_excel": xl_last.isoformat() if xl_last else None,
        "revenue_ltm_mercado": None if rev is None else round(rev, 1),
        "revenue_ltm_excel": xl_rev,
        "desvio_revenue": None if d_rev is None else round(d_rev, 4),
        "fcf_ltm_mercado": None if fcf is None else round(fcf, 1),
        "fcf_ltm_excel": xl_fcf,
        "desvio_fcf": None if d_fcf is None else round(d_fcf, 4),
        "trimestre_nuevo": quarter_new,
        "sospecha_unidades": units,
        "severidad": "unidades" if units else ("alta" if quarter_new else "media"),
    }


# --------------------------------------------------------------------- calendario

def check_calendar(ticker: str, yf_symbol: str, wl_rec: dict) -> dict | None:
    """Compara la fecha de proximos resultados del mercado contra la del Excel."""
    try:
        import yfinance as yf
        cal = yf.Ticker(yf_symbol).calendar or {}
        dates = cal.get("Earnings Date") or []
        if not dates:
            return None
        nxt = dates[0]
        nxt = nxt.date() if hasattr(nxt, "date") else nxt
    except Exception:
        return None

    excel_raw = wl_rec.get("earnings_next_date")
    try:
        excel = date.fromisoformat(excel_raw) if excel_raw else None
    except Exception:
        excel = None
    if excel is not None and abs((nxt - excel).days) <= 3:
        return None
    return {
        "ticker": ticker, "excel": excel.isoformat() if excel else None,
        "market": nxt.isoformat(),
        "estimated": bool(wl_rec.get("earnings_next_estimated")),
        "delta_days": (nxt - excel).days if excel else None,
    }


# --------------------------------------------------------------------- orquestacion

def _name_tokens(ticker: str, wl_rec: dict, cfg: dict) -> tuple:
    """Palabras que deben aparecer en un titular para que sea de esta empresa."""
    toks = set(cfg.get("aliases", []))
    toks.add(ticker.split()[0].lower())
    for src in (wl_rec.get("name"), cfg.get("name")):
        for w in re.split(r"[^A-Za-z0-9]+", (src or "").lower()):
            if len(w) >= 4:
                toks.add(w)
    return tuple(t.lower() for t in toks if t)


def default_source(ticker: str, wl_rec: dict) -> dict:
    """Si no hay entrada en ir_sources.json, deduce la mejor capa disponible."""
    exch = (wl_rec.get("exchange") or "").upper()
    if exch.startswith(("XNYS", "XNAS", "XASE", "ARCX", "BATS")):
        return {"type": "sec", "sec_symbol": ticker}
    return {"type": "news"}


def run(tickers=None, days_back=10, seed=False, dry_run=False):
    wl = {c["ticker"]: c for c in _load_json(WATCHLIST_JSON, {"companies": []})["companies"]}
    sources = _load_json(CONFIG_PATH, {})
    state = _load_json(STATE_PATH, {"seen": {}, "last_run": None})
    seen: dict = state.setdefault("seen", {})

    targets = tickers or list(wl)
    since = date.today() - timedelta(days=days_back)
    session = _session()

    # el override de simbolo de precios vale tambien aqui
    try:
        from .tickers import TICKER_YF_OVERRIDE
    except Exception:
        try:
            from src.tickers import TICKER_YF_OVERRIDE
        except Exception:
            TICKER_YF_OVERRIDE = {}

    found, cal_drift, fin_drift, errors = [], [], [], []
    for tk in targets:
        rec = wl.get(tk)
        if not rec:
            continue
        cfg = sources.get(tk) or default_source(tk, rec)
        yf_sym = TICKER_YF_OVERRIDE.get(tk, tk)
        docs = []
        try:
            kind = cfg.get("type", "news")
            if kind == "sec":
                docs += check_sec(tk, cfg.get("sec_symbol", tk), session, since)
            elif kind == "page":
                docs += check_page(tk, cfg, session)
            if cfg.get("also_news", True):
                docs += check_news(tk, yf_sym, since, _name_tokens(tk, rec, cfg))
        except Exception as exc:
            errors.append({"ticker": tk, "error": str(exc)[:200]})
            log.warning("%s: %s", tk, exc)

        known = set(seen.get(tk, []))
        fresh = [d for d in docs if d["id"] not in known]
        seen[tk] = sorted(known | {d["id"] for d in docs})[-400:]
        if not seed:
            for d in fresh:
                d["ticker"] = tk
                d["name"] = rec.get("name") or tk
                found.append(d)

        drift = check_calendar(tk, yf_sym, rec)
        if drift:
            cal_drift.append(drift)
        fin = check_financials_drift(tk, yf_sym, rec)
        if fin:
            fin_drift.append(fin)

    order = {"alta": 0, "media": 1, "baja": 2}
    found.sort(key=lambda d: (order.get(d["priority"], 3), d["date"]), reverse=False)

    todo = _build_todo(found, cal_drift, fin_drift, wl)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_tickers": len(targets), "days_back": days_back,
            "n_documents": len(found), "n_calendar_drift": len(cal_drift),
            "n_financial_drift": len(fin_drift),
            "n_errors": len(errors), "seeded": seed,
        },
        "documents": found,
        "financial_drift": fin_drift,
        "calendar_drift": cal_drift,
        "todo_excel": todo,
        "errors": errors,
    }
    if not dry_run:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        state["last_run"] = payload["meta"]["generated_at"]
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=0, ensure_ascii=False), encoding="utf-8")
    return payload


def _build_todo(docs, drift, fin, wl):
    """Traduce los hallazgos a acciones concretas sobre watchlist_ratings.xlsx."""
    todo = []
    by_tk = {}
    for d in docs:
        if d["priority"] == "alta":
            by_tk.setdefault(d["ticker"], []).append(d)
    for tk, ds in sorted(by_tk.items()):
        rec = wl.get(tk, {})
        todo.append({
            "ticker": tk, "accion": "Actualizar cuentas en el Excel",
            "motivo": "%d documento(s) de prioridad alta: %s" % (
                len(ds), "; ".join(d["title"][:70] for d in ds[:3])),
            "columnas": "AR-BC (cuentas LTM), BD/BF (FCF@5y), BO (fecha ultimos resultados)",
            "ultimos_resultados_excel": rec.get("earnings_last_date"),
            "urls": [d["url"] for d in ds[:3] if d["url"]],
        })
    for f in fin:
        bits = []
        if f.get("sospecha_unidades"):
            todo.append({
                "ticker": f["ticker"],
                "accion": "DESCUADRE DE MONEDA O ESCALA (no es que este desfasado)",
                "motivo": "El LTM del mercado y el del Excel difieren en mas de un 200%%: "
                          "ingresos %s vs %s, FCF %s vs %s. Revisar en que moneda reporta "
                          "y el factor de Framework Notes." % (
                              f["revenue_ltm_excel"], f["revenue_ltm_mercado"],
                              f["fcf_ltm_excel"], f["fcf_ltm_mercado"]),
                "columnas": "AR-BC y Framework Notes (factor de conversion)",
                "urls": [],
            })
            continue
        if f["trimestre_nuevo"]:
            bits.append("hay un trimestre publicado (%s) posterior a la fecha de ultimos "
                        "resultados del Excel (%s)" % (f["ultimo_trimestre_publicado"],
                                                       f["ultimos_resultados_en_excel"]))
        if f["desvio_revenue"] is not None:
            bits.append("ingresos LTM: Excel %s vs mercado %s (%+.1f%%)" % (
                f["revenue_ltm_excel"], f["revenue_ltm_mercado"], f["desvio_revenue"] * 100))
        if f["desvio_fcf"] is not None:
            bits.append("FCF LTM: Excel %s vs mercado %s (%+.1f%%)" % (
                f["fcf_ltm_excel"], f["fcf_ltm_mercado"], f["desvio_fcf"] * 100))
        todo.append({
            "ticker": f["ticker"], "accion": "CUENTAS DESFASADAS en el Excel",
            "motivo": "; ".join(bits),
            "columnas": "AR-BC (cuentas LTM) y BO (fecha de ultimos resultados)",
            "urls": [],
        })

    for d in drift:
        todo.append({
            "ticker": d["ticker"], "accion": "Corregir la fecha de proximos resultados",
            "motivo": "El Excel dice %s y el mercado dice %s (%s dias de diferencia)%s" % (
                d["excel"] or "nada", d["market"],
                d["delta_days"] if d["delta_days"] is not None else "?",
                " — la del Excel era una estimacion" if d["estimated"] else ""),
            "columnas": "BP (proximos resultados). Formato TEXTO dd/mm/yyyy: si se escribe "
                        "como fecha, COM la parsea en en-US y voltea los dias <= 12.",
            "urls": [],
        })
    return todo


def format_text(payload) -> tuple[str, str]:
    """Asunto y cuerpo para el email/WhatsApp diario."""
    m = payload["meta"]
    docs = payload["documents"]
    alta = [d for d in docs if d["priority"] == "alta"]
    subject = "RI: %d docs (%d altos) · %d con cuentas desfasadas · %d fechas a corregir" % (
        m["n_documents"], len(alta), m.get("n_financial_drift", 0), m["n_calendar_drift"])
    lines = ["Vigilante de relacion con inversores — %s" % m["generated_at"][:10], ""]
    if alta:
        lines.append("PRIORIDAD ALTA")
        for d in alta[:20]:
            lines.append("  [%s] %s — %s" % (d["ticker"], d["date"], d["title"][:90]))
            if d["url"]:
                lines.append("        %s" % d["url"])
        lines.append("")
    med = [d for d in docs if d["priority"] == "media"]
    if med:
        lines.append("PRIORIDAD MEDIA (%d)" % len(med))
        for d in med[:15]:
            lines.append("  [%s] %s — %s" % (d["ticker"], d["date"], d["title"][:90]))
        lines.append("")
    if payload["todo_excel"]:
        lines.append("QUE HAY QUE TOCAR EN EL EXCEL")
        for t in payload["todo_excel"][:25]:
            lines.append("  %-8s %s" % (t["ticker"], t["accion"]))
            lines.append("           %s" % t["motivo"][:150])
            lines.append("           columnas: %s" % t["columnas"])
        lines.append("")
    fin = payload.get("financial_drift") or []
    units = [f for f in fin if f.get("sospecha_unidades")]
    fin = [f for f in fin if not f.get("sospecha_unidades")]
    if units:
        lines.append("DESCUADRE DE MONEDA O ESCALA (%d) — revisar antes de creerse nada"
                     % len(units))
        for f in units:
            lines.append("  %-8s ingresos Excel %s vs mercado %s" % (
                f["ticker"], f["revenue_ltm_excel"], f["revenue_ltm_mercado"]))
        lines.append("")
    if fin:
        lines.append("CUENTAS DESFASADAS EN EL EXCEL (%d)" % len(fin))
        fin.sort(key=lambda f: -abs(f.get("desvio_fcf") or 0))
        for f in fin[:30]:
            lines.append("  %-8s ultimo trimestre %s · Excel dice %s%s" % (
                f["ticker"], f["ultimo_trimestre_publicado"],
                f["ultimos_resultados_en_excel"] or "nada",
                "".join([
                    "" if f["desvio_revenue"] is None
                    else " · ingresos %+.1f%%" % (f["desvio_revenue"] * 100),
                    "" if f["desvio_fcf"] is None
                    else " · FCF %+.1f%%" % (f["desvio_fcf"] * 100)])))
        lines.append("")
    if payload["errors"]:
        lines.append("FALLOS (%d): %s" % (
            len(payload["errors"]), ", ".join(e["ticker"] for e in payload["errors"][:15])))
    return subject, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Vigilante diario de relacion con inversores")
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--days-back", type=int, default=10)
    ap.add_argument("--seed", action="store_true",
                    help="primera pasada: marca todo como visto y no avisa de nada")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--notify", action="store_true", help="manda email/WhatsApp si hay algo")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    payload = run(args.tickers, args.days_back, args.seed, args.dry_run)
    subject, body = format_text(payload)
    print(subject)
    print()
    print(body)

    if args.notify and (payload["documents"] or payload["calendar_drift"]
                        or payload.get("financial_drift")):
        try:
            from . import alerts
        except Exception:
            from src import alerts
        fake = [{"severity": "high", "ticker": d["ticker"], "type": "ir_document",
                 "message": "%s: %s" % (d["ticker"], d["title"]), "metrics": {}}
                for d in payload["documents"] if d["priority"] == "alta"]
        if fake:
            try:
                alerts.notify_email(fake)
            except Exception as exc:
                log.warning("email fallo: %s", exc)


if __name__ == "__main__":
    main()
