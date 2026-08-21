"""
Mapeo centralizado de tickers Excel → símbolo yfinance.

Se importa desde enrich.py, backtest.py y history.py para mantener consistencia.

Cuando descubras un ticker nuevo que yfinance no reconoce con el mismo símbolo
del Excel, añade aquí el override. La verificación rápida es:
    python -c "import yfinance as yf; print(yf.Ticker('SYMBOL.SUFFIX').history(period='5d'))"
"""
from __future__ import annotations

# Mapeo Excel ticker → yfinance symbol
# Incluye todos los overrides necesarios para los 68 tickers actuales.
TICKER_YF_OVERRIDE: dict[str, str] = {
    # Europa Continental
    "ADYEN": "ADYEN.AS",
    "ITX": "ITX.MC",
    "BFIT": "BFIT.AS",
    "SU": "SU.PA",
    "SGO": "SGO.PA",
    "TFF": "TFF.PA",
    "VRLA": "VLA.PA",
    "RAA": "RAA.DE",
    "EVD": "EVD.DE",
    "ABBNE": "ABBN.SW",
    "STMN": "STMN.SW",
    "SIKA": "SIKA.SW",
    "LOTB": "LOTB.BR",
    "PRY": "PRY.MI",
    "CPR": "CPR.MI",
    "TGYM": "TGYM.MI",
    "IP": "IP.MI",       # Interpump Group (Milán) — ojo: "IP" a secas es International Paper en NYSE
    "VID": "VID.MC",
    "CBAV": "CBAV.MC",   # Clínica Baviera (Madrid)
    "RBT": "RBT.PA",     # Robertet, acciones ordinarias (los certificados son CBE.PA)
    # Asia
    # Nintendo: el Excel lleva la linea de Frankfurt (XFRA, EUR, ~46 EUR) y convierte
    # EUR->JPY con Framework Notes E4. Si aqui se apuntara a 7974.T el precio llegaria
    # en yenes (~13.000) contra unas cuentas ya convertidas: descuadre de 2 ordenes.
    "NTO": "NTO.DE",     # Nintendo, linea de Frankfurt (EUR). Reporta en JPY.
    # Nórdicos
    "LIFCO B": "LIFCO-B.ST",
    "MIPS": "MIPS.ST",
    "ROKO B": "ROKO-B.ST",   # Röko AB, acción B (Nasdaq Stockholm, cotiza desde mar-2025)
    "LR": "LR.PA",       # Legrand (Francia, no Lerøy)
    # UK. Todas cotizan en peniques (GBp) y hay que mirar la moneda de REPORTE una a una:
    # HLMA, WOSG y JDG reportan en libras; KIST reporta en dolares desde el 1-ene-2024 y
    # SOM tambien (Somero Enterprise Inc. es sociedad de Delaware). Ver Framework Notes E9.
    "HLMA": "HLMA.L",
    "WOSG": "WOSG.L",
    "KIST": "KIST.L",
    "JDG": "JDG.L",
    "SOM": "SOM.L",      # Somero Enterprises (AIM). Faltaba desde el alta del 20-ago-2026
    "KSPI": "KSPI",      # Kaspi.kz cotiza en NASDAQ desde 2024
    # Suiza adicional
    "JFN": "JFN.SW",     # Jungfraubahn
    # Otros
    # International Petroleum cotiza en Toronto (CAD) y en Estocolmo (SEK). El Excel
    # lleva la linea de Toronto y convierte CAD->USD con Framework Notes E7; apuntar a
    # IPCO.ST traeria el precio en coronas contra una conversion pensada para dolares.
    "IPCO": "IPCO.TO",   # Toronto (CAD). Reporta en USD.
    "TFPM": "TFPM.TO",   # Triple Flag, Toronto
    "CSU": "CSU.TO",     # Constellation Software, Toronto
    "KRX": "KRX.IR",     # Kingspan, Irlanda
}


def to_yf(excel_ticker: str) -> str:
    """Convierte ticker Excel a símbolo yfinance. Aplica override si existe."""
    return TICKER_YF_OVERRIDE.get(excel_ticker, excel_ticker)


def from_yf(yf_ticker: str) -> str | None:
    """Reverso: símbolo yfinance → ticker Excel original. None si no hay match."""
    for excel, yf in TICKER_YF_OVERRIDE.items():
        if yf == yf_ticker:
            return excel
    return None
