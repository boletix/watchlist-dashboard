"""
Mapeo centralizado de tickers Excel → símbolo yfinance.

Se importa desde enrich.py, backtest.py y history.py para mantener consistencia.

Cuando descubras un ticker nuevo que yfinance no reconoce con el mismo símbolo
del Excel, añade aquí el override. La verificación rápida es:
    python -c "import yfinance as yf; print(yf.Ticker('SYMBOL.SUFFIX').history(period='5d'))"
"""
from __future__ import annotations

# Mapeo Excel ticker → yfinance symbol
# Incluye todos los overrides necesarios para los 61 tickers actuales.
TICKER_YF_OVERRIDE: dict[str, str] = {
    # Europa Continental
    "ADYEN": "ADYEN.AS",
    "ITX": "ITX.MC",
    "BFIT": "BFIT.AS",
    "CBAV": "CBAV.AS",
    "SU": "SU.PA",
    "SGO": "SGO.PA",
    "TFF": "TFF.PA",
    "VRLA": "VLA.PA",
    "JFN": "JFN.PA",
    "RAA": "RAA.DE",
    "EVD": "EVD.DE",
    "ABBNE": "ABBN.SW",
    "STMN": "STMN.SW",
    "SIKA": "SIKA.SW",
    "LOTB": "LOTB.BR",
    "PRY": "PRY.MI",
    "CPR": "CPR.MI",
    "TGYM": "TGYM.MI",
    "VID": "VID.MC",
    "CBAV": "CBAV.MC",   # Clínica Baviera (Madrid)
    # Asia
    "NTO": "7974.T",     # Nintendo (Tokyo, JPY)
    # Nórdicos
    "IPCO": "IPCO.ST",
    "LIFCO B": "LIFCO-B.ST",
    "MIPS": "MIPS.ST",
    "LR": "LR.PA",       # Legrand (Francia, no Lerøy)
    # UK
    "HLMA": "HLMA.L",
    "WOSG": "WOSG.L",
    "KIST": "KIST.L",
    "JDG": "JDG.L",
    "KSPI": "KSPI",      # Kaspi.kz cotiza en NASDAQ desde 2024
    # Suiza adicional
    "JFN": "JFN.SW",     # Jungfraubahn
    # Otros
    "TFPM": "TFPM.TO",   # Triple Flag, Toronto
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
