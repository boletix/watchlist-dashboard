.PHONY: install build build-quick build-offline test clean serve snapshot backtest history alerts

PYTHON := python3

install:
	$(PYTHON) -m pip install -r requirements.txt

# Build completo: enrichment + analytics + backtest + history + alerts
# Tiempo: ~5-10 min (yfinance fetches)
build:
	$(PYTHON) -m src.build

# Build rápido: solo watchlist principal sin backtest/history/alerts
# Tiempo: ~30 segundos
build-quick:
	$(PYTHON) -m src.build --quick

# Build sin red (útil en desarrollo offline)
build-offline:
	$(PYTHON) -m src.build --skip-enrichment --quick

# Solo backtest (Q4)
backtest:
	$(PYTHON) -m src.backtest

# Solo history (Q3)
history:
	$(PYTHON) -m src.history

# Solo alerts (rápido, sin re-fetch)
alerts:
	$(PYTHON) -m src.alerts

test:
	$(PYTHON) -m pytest tests/ -v

# Servir localmente para testing visual
serve:
	@echo "→ http://localhost:8000"
	cd docs && $(PYTHON) -m http.server 8000

# Crea snapshot manual (además del cron semanal)
snapshot:
	@mkdir -p data/snapshots
	@DATE=$$(date -u +%Y-%m-%d); \
	cp docs/data/watchlist.json data/snapshots/$${DATE}_watchlist.json; \
	echo "Snapshot creado: data/snapshots/$${DATE}_watchlist.json"

clean:
	rm -rf .pytest_cache __pycache__ src/__pycache__ tests/__pycache__
	rm -f docs/data/*.json data/processed/*.json
