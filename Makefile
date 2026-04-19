.PHONY: install build build-offline test clean serve snapshot

PYTHON := python3

install:
	$(PYTHON) -m pip install -r requirements.txt

# Build completo con yfinance enrichment
build:
	$(PYTHON) -m src.build

# Build sin red (útil en desarrollo offline)
build-offline:
	$(PYTHON) -m src.build --skip-enrichment

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
	rm -f docs/data/watchlist.json data/processed/watchlist.json
