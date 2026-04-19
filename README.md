# Watchlist Dashboard

Dashboard estático de calidad institucional para una watchlist de quality compounders, servido desde **GitHub Pages** y alimentado por un **Excel local** + **pipeline Python** automatizado vía **GitHub Actions**.

Diseñado para responder preguntas de decisión:

- ¿Qué empresas combinan calidad alta **y** valuation razonable? (Quality-Value Quadrant)
- ¿Dónde está la mayor asimetría IRR upside/downside?
- ¿Cómo se compara una empresa frente a peers de su categoría?
- ¿Qué sesgos sistemáticos tiene mi framework por categoría? (heatmap)

---

## Arquitectura

```
Excel (fuente de verdad)
    │
    │  git push data/raw/watchlist_ratings.xlsx
    ▼
GitHub Actions (.github/workflows/build.yml)
    │
    ├─ src/etl.py         → carga + valida Excel
    ├─ src/enrich.py      → refresca precios vía yfinance
    ├─ src/analytics.py   → IRR asymmetry, quadrants, z-scores, deltas
    └─ src/build.py       → escribe docs/data/watchlist.json
    │
    ▼
GitHub Pages (docs/)
    │
    ├─ index.html         → shell del dashboard
    ├─ assets/charts.js   → 6 ECharts configurations
    ├─ assets/app.js      → filtros, tabla, drawer
    └─ assets/style.css   → editorial institutional dark theme
```

**Filosofía:**
- Excel es la fuente de verdad. Los ratings cualitativos son tuyos y no se tocan en CI.
- yfinance actualiza solo precio + market cap. Si falla (403, rate-limit), el build sigue adelante con `price_source='stale'` — nunca bloquea.
- Snapshots semanales automáticos habilitan análisis de drift de rating en el futuro.

---

## Setup

```bash
# 1. Clonar
git clone <repo-url> watchlist-dashboard
cd watchlist-dashboard

# 2. Instalar deps
make install

# 3. Build local (sin red)
make build-offline

# 4. Ver localmente
make serve      # abre http://localhost:8000

# 5. Ejecutar tests
make test
```

---

## Workflow de edición

1. Editas `data/raw/watchlist_ratings.xlsx` en Excel (con Refinitiv integrado como tienes).
2. Commit & push:
   ```bash
   git add data/raw/watchlist_ratings.xlsx
   git commit -m "watchlist: upgrade Adyen R2 to 8.7 post Q3"
   git push
   ```
3. GitHub Actions ejecuta `build.yml`:
   - Corre tests (falla si hay inconsistencias).
   - Ejecuta ETL + enrichment + analytics.
   - Commitea `docs/data/watchlist.json` si cambió.
   - Deploya a GitHub Pages.
4. En 30–60 segundos el dashboard está actualizado.

---

## Estructura de carpetas

```
watchlist-dashboard/
├── .github/workflows/
│   ├── build.yml           # pipeline principal (push + cron diario)
│   └── snapshot.yml        # snapshot semanal para rating drift
├── data/
│   ├── raw/                # Excel fuente (commit manual)
│   ├── processed/          # copia del JSON para inspección
│   └── snapshots/          # snapshots versionados (series temporal)
├── src/
│   ├── etl.py              # Excel → DataFrame normalizado
│   ├── analytics.py        # métricas derivadas
│   ├── enrich.py           # yfinance price refresh
│   └── build.py            # orquestador
├── docs/                   # root de GitHub Pages
│   ├── index.html
│   ├── assets/
│   └── data/watchlist.json # generado por build.py
├── tests/
│   ├── test_etl.py
│   └── test_analytics.py
├── requirements.txt
├── Makefile
└── README.md
```

---

## El JSON que consume el frontend

```json
{
  "meta": {
    "generated_at": "2026-04-19T08:30:00+00:00",
    "n_companies": 61,
    "source_file": "watchlist_ratings.xlsx",
    "validation_issues": [],
    "enrichment_stats": {"yfinance": 45, "stale": 16, "skipped": 0}
  },
  "kpis": {
    "n_companies": 61,
    "avg_composite": 5.83,
    "weighted_avg_roic": 0.40,
    "median_ev_fcf": 32.08,
    "pct_best_irr_gt_15pct": 31.1,
    "n_top_tier": 16,
    "n_hunting_ground": 2,
    ...
  },
  "category_stats": [...],
  "deltas": {...},
  "companies": [
    {
      "ticker": "VEEV",
      "name": "VEEV",
      "category": "Vertical Saas",
      "rating_composite": 8.41,
      "quadrant": "wonderful_expensive",
      "rating_tier": "best_in_class",
      "irr_asymmetry_ratio": 5.8,
      ...
    },
    ...
  ]
}
```

---

## Decisiones de arquitectura

| Decisión | Razón |
|---|---|
| Static SPA en GitHub Pages (vs Streamlit) | Coste cero, consistencia con tu macro dashboard, latencia sub-segundo. |
| Vanilla JS (vs React/Vue) | Sin bundler, debug fácil, carga instantánea. El dashboard no necesita state complejo. |
| ECharts (vs Chart.js/Plotly) | Mejor soporte para scatter log, heatmaps, sunburst y parallel coords. Tooltips más ricos. |
| yfinance con fallback (vs Refinitiv) | Gratis, sin credenciales en CI. El Excel con Refinitiv sigue siendo tu source of truth. |
| Excel → JSON (vs DB) | 61 empresas × ~70 columnas = 80 KB. Base de datos es overkill. |
| Validación con tolerancia en CI | Ratings fuera de [0,10] permitidos hasta [-2,11] (Excel produce outliers legítimos). |

---

## Roadmap

- [x] v1.0 — Static SPA + 6 charts + tabla filtrable + drawer de detalle
- [ ] v1.1 — Rating drift engine (visualiza cambios de rating sobre snapshots semanales)
- [ ] v1.2 — Portfolio overlay (cruce con DeGiro para marcar holdings)
- [ ] v1.3 — Alertas Telegram/email (precio alcanza umbral de Best IRR > 20%)
- [ ] v1.4 — Enrichment con insider transactions + short interest
- [ ] v1.5 — Monte Carlo sobre IRR scenarios
- [ ] v1.6 — Ratings consistency engine (ML self-challenge)
- [ ] v1.7 — Multi-user / shareable read-only mode
- [ ] v1.8 — Cross-link con macro dashboard

---

## Licencia & disclaimers

Uso personal. No es investment advice.
