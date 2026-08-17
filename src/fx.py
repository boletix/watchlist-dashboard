"""
Conversion de divisa entre la moneda de REPORTE (con la que la empresa publica
sus cuentas: FCF, caja, deuda) y la moneda de COTIZACION (en la que se publica
el precio de la accion).

Por que existe este modulo
--------------------------
Hasta el 17/08/2026 `analytics.py` calculaba el valor por accion como

    fve = (fcf * multiplo + caja - deuda) / acciones

con cifras en la moneda de reporte, y lo dividia directamente entre un precio
en la moneda de cotizacion. Cuando las dos no coinciden el resultado no
significa nada. Afectaba a 11 de las 63 empresas de la watchlist. Los dos
casos graves:

  * KSPI  - reporta en tenge (KZT) y cotiza en dolares en el Nasdaq.
            Salia un FVE min de 37.394 $ contra un precio de 98 $, y una TIR
            "mejor" de +588%: encabezaba el ranking de asimetria del dashboard.
  * HLMA, JDG, KIST, WOSG - cotizan en peniques (GBp) y reportan en libras
            (GBP). Factor 100. Salian con TIR de -57% a -69%: parecian
            desastres sin serlo.

Principio de diseno
-------------------
Si no se puede determinar el tipo de cambio con certeza, estas funciones
devuelven None y quien las llama debe propagar NaN. Un hueco visible es
preferible a un numero plausible y falso: este bug sobrevivio meses
justamente porque los numeros erroneos parecian razonables a primera vista.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Divisas que se cotizan en unidad menor. El valor es (divisa mayor, unidades
# menores por unidad mayor). Los tickers de Londres son el caso habitual: el
# precio viene en peniques mientras las cuentas estan en libras.
MINOR_UNIT_CURRENCIES: dict[str, tuple[str, float]] = {
    "GBP": ("GBP", 100.0),   # yfinance devuelve "GBp"; normalizamos en mayusculas
    "GBX": ("GBP", 100.0),   # alias de peniques usado por algunos brokers
    "ZAC": ("ZAR", 100.0),   # centimos de rand sudafricano
    "ILA": ("ILS", 100.0),   # agorot israelies
}

# Cache de tipos de cambio de la ejecucion en curso: (origen, destino) -> tasa
_RATE_CACHE: dict[tuple[str, str], float | None] = {}


def normalize_currency(code) -> tuple[str, float] | None:
    """
    Devuelve (divisa_mayor, unidades_menores_por_mayor) o None si no se puede leer.

        normalize_currency("GBp") -> ("GBP", 100.0)   # peniques
        normalize_currency("GBP") -> ("GBP", 1.0)     # libras
        normalize_currency("USD") -> ("USD", 1.0)

    Ojo con el caso GBp/GBP: se distinguen SOLO por la caja de la ultima letra,
    asi que la comparacion no puede ser case-insensitive a secas.
    """
    if code is None:
        return None
    s = str(code).strip()
    if not s:
        return None
    # "GBp" y "GBX" (peniques) frente a "GBP" (libras): la 'p' minuscula manda
    if s in ("GBp", "GBx", "gbp", "gbx", "GBX"):
        return ("GBP", 100.0)
    upper = s.upper()
    if upper in ("ZAC", "ILA"):
        return MINOR_UNIT_CURRENCIES[upper]
    if len(upper) != 3:
        log.debug("Codigo de divisa no reconocido: %r", code)
        return None
    return (upper, 1.0)


def _fetch_rate_yf(base: str, quote: str) -> float | None:
    """Tipo de cambio base->quote via yfinance. None si no se puede obtener."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance no disponible: no se pueden convertir divisas")
        return None
    for symbol, invert in ((f"{base}{quote}=X", False), (f"{quote}{base}=X", True)):
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if hist is None or hist.empty:
                continue
            value = float(hist["Close"].dropna().iloc[-1])
            if value <= 0:
                continue
            return 1.0 / value if invert else value
        except Exception as e:  # noqa: BLE001 - la red puede fallar de mil formas
            log.debug("fx %s fallo: %s", symbol, e)
    log.warning("No se pudo obtener el tipo de cambio %s->%s", base, quote)
    return None


def get_rate(base: str, quote: str, fetcher=None) -> float | None:
    """
    Unidades de `quote` por 1 unidad de `base`, con cache por ejecucion.
    `fetcher` permite inyectar una fuente distinta en los tests.
    """
    if base == quote:
        return 1.0
    key = (base, quote)
    if key in _RATE_CACHE:
        return _RATE_CACHE[key]
    rate = (fetcher or _fetch_rate_yf)(base, quote)
    _RATE_CACHE[key] = rate
    return rate


def conversion_factor(report_ccy, quote_ccy, fetcher=None) -> float | None:
    """
    Multiplicador que lleva un importe expresado en la moneda de REPORTE a la
    moneda de COTIZACION tal y como se cotiza (incluida la unidad menor).

        conversion_factor("GBP", "GBp") -> 100.0     # libras -> peniques
        conversion_factor("KZT", "USD") -> ~0.0019   # tenge  -> dolares
        conversion_factor("USD", "USD") -> 1.0

    Devuelve None si falta algun codigo o no hay tipo de cambio: el llamante
    debe traducir eso a NaN, nunca a 1.0.
    """
    rep = normalize_currency(report_ccy)
    quo = normalize_currency(quote_ccy)
    if rep is None or quo is None:
        return None
    rep_major, rep_minor = rep
    quo_major, quo_minor = quo
    rate = get_rate(rep_major, quo_major, fetcher=fetcher)
    if rate is None:
        return None
    return float(rate) * quo_minor / rep_minor


def build_factor_map(pairs, fetcher=None) -> dict[tuple, float | None]:
    """
    Resuelve de una vez todos los pares (moneda_reporte, moneda_cotizacion) que
    aparecen en la watchlist, para no pedir el mismo tipo de cambio 63 veces.
    Devuelve un dict con los codigos ORIGINALES como clave.
    """
    out: dict[tuple, float | None] = {}
    for rep, quo in set(pairs):
        out[(rep, quo)] = conversion_factor(rep, quo, fetcher=fetcher)
    unresolved = [k for k, v in out.items() if v is None]
    if unresolved:
        log.warning("Sin tipo de cambio para %d par(es): %s", len(unresolved), unresolved)
    return out


def reset_cache() -> None:
    """Vacia el cache de tipos de cambio (usado por los tests)."""
    _RATE_CACHE.clear()
