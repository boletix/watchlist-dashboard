"""
Valoración por DCF de 3 escenarios y precios de compra a la TIR exigida (8-nov-2026).

Es el segundo método de valoración del sistema, junto al Monte Carlo de múltiplos:
  - Monte Carlo: FCF del año 5 × múltiplo de salida + caja neta de hoy (sistema/motor/montecarlo.py).
  - DCF (este módulo): se descuentan los flujos de caja año a año.

Un solo código para el sistema local (sistema/motor/dcf.py lo importa) y para el build de GitHub.

Cómo se calcula, por escenario:
  1. Años 1-5: el FCF va del FCF de hoy (BS, o AS si no hay BS) al FCF del año 5 del escenario
     (bajista = BD, base = media geométrica de BD y BF, alcista = BF), con crecimiento constante.
  2. Años 6-10: el crecimiento se desvanece en línea recta desde el de los años 1-5 (acotado entre
     −10% y +20%) hasta el crecimiento terminal.
  3. Valor terminal al final del año 10: FCF del año 11 / (r − g).
  4. Valor de la empresa = flujos y valor terminal descontados a r.
  5. Valor por acción = (valor de la empresa + caja − deuda) × tipo de cambio / acciones (H).
     Con valor negativo, la acción vale 0 (responsabilidad limitada).
Pesos 25/50/25. r es la TIR exigida de cada empresa (columna BU): el resultado es el precio
máximo que se puede pagar para obtener esa TIR si se cumplen los flujos.
"""
from __future__ import annotations

import math

PESOS = (0.25, 0.50, 0.25)
NOMBRES = ("bajista", "base", "alcista")
G_DEFECTO = (0.010, 0.025, 0.035)
# Activos que se agotan o de ciclo: crecimiento terminal propio (bajista, base, alcista).
G_ESPECIAL = {
    "KIST": (-0.08, -0.05, -0.03),   # gas y crudo del Mar del Norte y Noruega: manda el modelo por activos
    "IPCO": (-0.08, -0.05, -0.03),   # crudo y gas: activos que se agotan
    "LUN": (0.0, 0.01, 0.02),        # minera de cobre de vida larga
    "TFPM": (0.0, 0.01, 0.02),       # regalías de oro
    "HOME": (0.0, 0.01, 0.02),       # promotora: renta de ciclo
}
AGOTABLES = {"KIST", "IPCO"}
# Filas donde el DCF de la fila es solo orientativo (el valor está en otro sitio).
NOTAS_DCF = {
    "KIST": "activo que se agota: manda el modelo por activos",
    "IPCO": "activo que se agota: pendiente de modelo por activos",
    "HOME": "promotora: el valor está en el suelo, no en un FCF perpetuo",
}
EXPLICITOS = 5
FADE = 5
CAGR_MIN, CAGR_MAX = -0.10, 0.20


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def crecimiento_terminal(ticker: str) -> tuple:
    return G_ESPECIAL.get(str(ticker).strip(), G_DEFECTO)


def flujos(fcf0: float, fcf5: float, g: float, agotable: bool = False) -> list:
    """FCF de los años 1 a 10 de un escenario."""
    if fcf0 > 0 and fcf5 > 0:
        cagr = (fcf5 / fcf0) ** (1 / EXPLICITOS) - 1
        f = [fcf0 * (1 + cagr) ** k for k in range(1, EXPLICITOS + 1)]
    else:
        cagr = 0.0
        f = [fcf0 + (fcf5 - fcf0) * k / EXPLICITOS for k in range(1, EXPLICITOS + 1)]
    s = min(max(cagr, CAGR_MIN), CAGR_MAX)
    if agotable:
        s = min(s, g)
    for k in range(1, FADE + 1):
        gk = s + (g - s) * k / FADE
        f.append(f[-1] * (1 + gk))
    return f


def valor_empresa(fl: list, g: float, r: float) -> float | None:
    """Valor presente de los flujos más el valor terminal (Gordon) a la tasa r."""
    if r <= g + 0.005:
        return None
    vp = sum(x / (1 + r) ** k for k, x in enumerate(fl, start=1))
    tv = fl[-1] * (1 + g) / (r - g)
    return vp + tv / (1 + r) ** len(fl)


def entradas(row: dict) -> dict | None:
    """Lee de una fila de la watchlist lo que necesita el DCF (moneda de reporte)."""
    fcf0 = _f(row.get("fcf_ltm_normalized"))
    if fcf0 is None:
        fcf0 = _f(row.get("fcf_ltm"))
    bd, bf = _f(row.get("fcf_5y_min")), _f(row.get("fcf_5y_max"))
    acc = _f(row.get("shares_out_m"))
    caja, deuda = _f(row.get("cash")) or 0.0, _f(row.get("total_debt")) or 0.0
    if None in (fcf0, bd, bf, acc) or acc <= 0:
        return None
    base = math.sqrt(bd * bf) if bd > 0 and bf > 0 else (bd + bf) / 2
    return {"fcf0": fcf0, "fcf5": (bd, base, bf), "acciones": acc, "caja_neta": caja - deuda}


def valor_por_accion(row: dict, r: float, factor: float = 1.0) -> dict | None:
    """Valor por acción de cada escenario y ponderado, descontando a r (moneda de cotización)."""
    e = entradas(row)
    if e is None or factor is None:
        return None
    t = str(row.get("ticker", "")).strip()
    gs = crecimiento_terminal(t)
    out = {}
    for nombre, fcf5, g in zip(NOMBRES, e["fcf5"], gs):
        fl = flujos(e["fcf0"], fcf5, g, agotable=t in AGOTABLES)
        ve = valor_empresa(fl, g, r)
        if ve is None:
            return None
        out[nombre] = max((ve + e["caja_neta"]) * factor / e["acciones"], 0.0)
    out["ponderado"] = sum(w * out[n] for w, n in zip(PESOS, NOMBRES))
    return out


def tir_implicita(row: dict, precio: float, factor: float = 1.0, con_limite: bool = False):
    """La tasa a la que el DCF ponderado vale exactamente el precio de hoy (TIR del DCF).

    Con con_limite=True devuelve (tasa, límite): límite = "suelo" si ni a la tasa mínima calculable
    (crecimiento terminal alcista + 0,6 puntos) el DCF llega al precio (la TIR es menor que la tasa
    devuelta), "techo" si supera el 100%, o None.
    """
    precio = _f(precio)
    res = lambda r, lim=None: (r, lim) if con_limite else r  # noqa: E731
    if not precio or precio <= 0:
        return res(None)
    gmax = max(crecimiento_terminal(str(row.get("ticker", "")).strip()))
    lo, hi = gmax + 0.006, 1.0
    vlo = valor_por_accion(row, lo, factor)
    vhi = valor_por_accion(row, hi, factor)
    if vlo is None or vhi is None:
        return res(None)
    if vlo["ponderado"] < precio:
        return res(lo, "suelo")
    if vhi["ponderado"] > precio:
        return res(hi, "techo")
    for _ in range(60):
        mid = (lo + hi) / 2
        v = valor_por_accion(row, mid, factor)["ponderado"]
        if v > precio:
            lo = mid
        else:
            hi = mid
    return res((lo + hi) / 2)


def tir_desde_precio_compra(precio_compra: float, precio: float, tir_exigida: float) -> float | None:
    """TIR ponderada del Monte Carlo a precio de hoy, a partir de su precio de compra (BV).

    La TIR ponderada es Σ w·(V/P)^(1/5) − 1, así que (1 + TIR(P)) = (1 + h)·(P_compra / P)^(1/5).
    Es exacta cuando todos los escenarios valen más de cero.
    """
    pc, p, h = _f(precio_compra), _f(precio), _f(tir_exigida)
    if None in (pc, p, h) or pc <= 0 or p <= 0:
        return None
    return (1 + h) * (pc / p) ** 0.2 - 1


def precio_compra_mc(escenarios: list, tir_exigida: float) -> float | None:
    """Precio al que la TIR ponderada del Monte Carlo iguala la TIR exigida.

    escenarios = [(peso, valor_central_año_5), ...]. Los escenarios con valor ≤ 0 cuentan como −99%.
    """
    h = _f(tir_exigida)
    if h is None:
        return None
    a = sum(w * v ** 0.2 for w, v in escenarios if v > 0)
    wp = sum(w for w, v in escenarios if v > 0)
    wn = sum(w for w, v in escenarios if v <= 0)
    den = h + wp + 0.99 * wn
    if a <= 0 or den <= 0:
        return None
    return (a / den) ** 5
