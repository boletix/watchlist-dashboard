# Watchlist Dashboard

Dashboard estático de calidad institucional para una watchlist de quality compounders, servido desde **GitHub Pages** y alimentado por un **Excel local** + **pipeline Python** automatizado vía **GitHub Actions**.

Diseñado para responder preguntas de decisión:

- ¿Qué empresas combinan calidad alta **y** valuation razonable? (Quality-Value Quadrant)
- ¿Dónde está la mayor asimetría IRR upside/downside?
- ¿Cómo ha evolucionado mi watchlist vs el S&P 500 desde 2020? (Backtest)
- ¿Cómo han evolucionado los múltiplos (EV/FCF, EV/Sales, EV/EBITDA) de cada empresa? (Multiple History)
- ¿Qué empresas acaban de entrar en Hunting Ground o tienen asimetría favorable? (Alertas)

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
    ├─ src/analytics.py   → IRR asymmetry, quadrants, z-scores
    ├─ src/backtest.py    → NAV equiponderado vs benchmarks desde 2020
    ├─ src/history.py     → multiples históricos + proyección forward
    ├─ src/alerts.py      → detecta eventos + email/WhatsApp notify
    └─ src/build.py       → orquestador
    │
    ▼
docs/data/*.json  (consumidos por el frontend)
    │
    ▼
GitHub Pages
    │
    ├─ watchlist.json   → dashboard principal (8 charts)
    ├─ backtest.json    → panel de backtest
    ├─ history.json     → panel de multiples evolution
    └─ alerts.json      → banner de alertas
```

---

## Setup

```bash
# 1. Clonar
git clone <repo-url> watchlist-dashboard
cd watchlist-dashboard

# 2. Instalar dependencias
make install

# 3. Build rápido (sin red, para dev)
make build-offline

# 4. Ver localmente
make serve      # abre http://localhost:8000

# 5. Tests
make test
```

### Build completo (con red)

```bash
# Todo: ~5-10 min porque descarga prices + fundamentals para 61 tickers
make build

# Solo partes específicas (iteración rápida):
make build-quick   # solo watchlist principal, ~30s
make backtest      # solo Q4
make history       # solo Q3
make alerts        # solo alertas, sin re-fetch
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
   - Corre tests (falla si hay inconsistencias)
   - Ejecuta ETL + enrichment + backtest + history + alerts
   - Commitea JSONs actualizados a `docs/data/`
   - Deploya a GitHub Pages
4. En 5-10 minutos el dashboard está actualizado.

Los domingos a las 21:00 UTC un workflow aparte (`snapshot.yml`) archiva el JSON actual en `data/snapshots/YYYY-MM-DD_watchlist.json` para habilitar análisis de drift temporal.

---

## Añadir una empresa nueva

Hoy el flujo es manual porque tus ratings son juicio cualitativo:

1. Abre `data/raw/watchlist_ratings.xlsx` en Excel
2. Duplica la última fila como template
3. Rellena:
   - **Market data**: ticker, category, style, exchange, currency, price, shares, market cap
   - **Ratings R1 (8 sub-scores)**: mission, moat, optionality, financials, concentration, glassdoor, founder, ownership
   - **Ratings R2 (8 sub-scores)**: financials, moat, potential, customers, revenue quality, mgmt, stock, risks
   - **Ratings R3 (8 sub-scores)**: durability, risk of disappearance, capital intensity, capital allocation, financing, incentives, moat structural, terminal risk
   - **Financials**: cash, debt, FCF LTM, NOPAT, EBITDA, Revenue, y proyecciones (FCF min/max CAGR, exit multiples)
4. Guarda, commit, push

**Si el ticker no es reconocido por yfinance** (empresas europeas/asiáticas), añade el mapeo en `src/tickers.py`:

```python
TICKER_YF_OVERRIDE = {
    ...
    "MI_TICKER": "MI_TICKER.MC",   # Bolsa de Madrid
}
```

Para verificar que yfinance reconoce un símbolo:
```bash
python -c "import yfinance as yf; print(yf.Ticker('SYMBOL.SUFFIX').info.get('shortName'))"
```

Sufijos yfinance comunes: `.MC` (Madrid), `.L` (LSE), `.AS` (Amsterdam), `.PA` (París), `.MI` (Milán), `.SW` (Suiza), `.DE` (Xetra), `.ST` (Estocolmo), `.CO` (Copenhague), `.OL` (Oslo), `.T` (Tokio), `.TO` (Toronto).

---

## Alertas por email y WhatsApp

El módulo `src/alerts.py` detecta eventos cada vez que corre el build y puede enviar notificaciones externas. Si no configuras las credenciales, las alertas siguen apareciendo en el banner del dashboard — simplemente no llegan por email/WhatsApp.

### Tipos de alertas detectadas

| Tipo | Severidad | Trigger |
|---|---|---|
| **hunting_ground_entry** | HIGH | Empresa entra en Composite≥7.5 + EV/FCF≤20 |
| **asymmetry_improved** | HIGH | Best IRR>20% **y** Worst IRR>-5% |
| **best_irr_crossed_25** | HIGH | Best IRR cruza el 25% al alza |
| **new_top_tier** | HIGH | Nueva empresa entra en Composite≥7.5 |
| **composite_upgrade** | MEDIUM | Rating composite sube ≥0.5 puntos |
| **composite_downgrade** | MEDIUM | Rating composite baja ≥0.5 puntos |
| **ev_fcf_drop** | MEDIUM | Top Tier con caída EV/FCF ≥20% |
| **exited_hunting** | LOW | Empresa sale de Hunting Ground |

### Opción A — Email (recomendada)

Funciona con cualquier proveedor SMTP. El ejemplo más común es **Gmail con App Password**:

1. En tu cuenta de Google: activa 2FA
2. Ve a https://myaccount.google.com/apppasswords
3. Crea una App Password llamada "Watchlist Dashboard" → copia el código de 16 caracteres
4. En tu repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Añade:

   | Secret Name | Value |
   |---|---|
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `587` |
   | `SMTP_USER` | `tu-email@gmail.com` |
   | `SMTP_PASSWORD` | el App Password de 16 caracteres (sin espacios) |
   | `EMAIL_TO` | email de destino (puede ser el mismo) |

5. En el siguiente build recibirás un email HTML con formato profesional listando todas las alertas HIGH y MEDIUM.

**Otros SMTP populares**:
- Outlook/Hotmail: `smtp-mail.outlook.com` puerto 587
- iCloud: `smtp.mail.me.com` puerto 587
- Fastmail: `smtp.fastmail.com` puerto 465

### Opción B — WhatsApp (via CallMeBot, gratuito)

CallMeBot es un servicio gratuito que permite enviar WhatsApp desde scripts sin registrar un bot propio. Setup one-time:

1. Añade el contacto **+34 644 67 38 13** en tu agenda como "CallMeBot"
2. Desde tu WhatsApp, envía un mensaje a ese número con el texto exacto:
   ```
   I allow callmebot to send me messages
   ```
3. En unos minutos recibirás un mensaje con tu **API key** (un código numérico)
4. En GitHub Secrets añade:

   | Secret Name | Value |
   |---|---|
   | `WHATSAPP_PHONE` | tu número con código país, sin `+` ni espacios (ej: `34666123456`) |
   | `WHATSAPP_API_KEY` | el código recibido |

5. Solo se envían las alertas de severidad HIGH por WhatsApp (para no spamearte). El mensaje es texto plano compacto, máx 8 alertas por envío.

**Limitaciones CallMeBot**: 5 mensajes/min, plain text only. Suficiente para el caso de uso.

### Opción C — Ambas

Puedes configurar ambas. El orden de prioridad en `alerts.py`: email siempre (si credenciales) + WhatsApp solo si hay alertas HIGH. Ambas silenciosas si no hay credenciales.

### Desactivar notificaciones sin borrar secrets

Edita `.github/workflows/build.yml` y elimina las líneas `env:` bajo el step "Build dashboard JSON". El módulo seguirá generando `alerts.json` (visible en el banner) pero no enviará notificaciones.

---

## El JSON consumido por el frontend

### `docs/data/watchlist.json` (dashboard principal)

```json
{
  "meta": {"generated_at": "...", "n_companies": 61, ...},
  "kpis": {"avg_composite": 5.83, "weighted_avg_roic": 0.40, ...},
  "category_stats": [...],
  "deltas": {"rating_changes": [...], "entered": [], "exited": []},
  "companies": [
    {
      "ticker": "VEEV",
      "rating_composite": 8.41,
      "quadrant": "wonderful_expensive",
      "irr_asymmetry_ratio": 5.8,
      ...
    }
  ]
}
```

### `docs/data/backtest.json` (Q4)

```json
{
  "meta": {"start_date": "2020-01-01", "end_date": "...", ...},
  "series": {
    "All Watchlist": {
      "type": "basket",
      "stats": {"cagr": 0.256, "sharpe": 1.21, "max_dd": -0.38, ...},
      "data": [{"date": "2020-01-31", "nav": 100.0}, ...]
    },
    "S&P 500": {"type": "benchmark", ...},
    ...
  }
}
```

### `docs/data/history.json` (Q3)

```json
{
  "meta": {"n_with_history": 61, "n_missing": 0, ...},
  "companies": {
    "VEEV": {
      "currency": "USD",
      "history": [
        {"date": "2023-01-31", "ev_fcf": 33.86, "ev_sales": 15.15, ...}
      ],
      "forward": [
        {"year_offset": 0, "ev_fcf_bear": 20.3, "ev_fcf_base": 24.0, "ev_fcf_bull": 30.0}
      ]
    }
  }
}
```

### `docs/data/alerts.json`

```json
{
  "meta": {"n_alerts": 11, "by_severity": {"high": 9, "medium": 0, "low": 2}},
  "alerts": [
    {
      "type": "asymmetry_improved",
      "severity": "high",
      "ticker": "ADYEN",
      "message": "ADYEN now has favorable IRR asymmetry (best 28.4%, worst 1.1%)",
      "metrics": {"irr_best": 0.284, "irr_worst": 0.011, ...}
    }
  ]
}
```

---

## Estructura de carpetas

```
watchlist-dashboard/
├── .github/workflows/
│   ├── build.yml           # pipeline principal (push + cron diario)
│   └── snapshot.yml        # snapshot semanal para drift analysis
├── data/
│   ├── raw/                # Excel fuente (commit manual)
│   ├── processed/          # copia JSON para inspección
│   └── snapshots/          # snapshots versionados
├── src/
│   ├── etl.py              # Excel → DataFrame normalizado
│   ├── enrich.py           # yfinance price refresh
│   ├── analytics.py        # métricas derivadas
│   ├── backtest.py         # Q4: NAVs vs benchmarks
│   ├── history.py          # Q3: multiples evolution + forward projection
│   ├── alerts.py           # detecta eventos + email/WhatsApp
│   ├── tickers.py          # mapeo ticker Excel → yfinance
│   └── build.py            # orquestador
├── docs/                   # root de GitHub Pages
│   ├── index.html
│   ├── assets/             # CSS, JS, charts
│   └── data/               # JSONs generados
├── tests/
│   ├── test_etl.py
│   └── test_analytics.py
├── requirements.txt
├── Makefile
└── README.md
```

---

## Decisiones de arquitectura

| Decisión | Razón |
|---|---|
| Static SPA en GitHub Pages | Coste cero, consistencia con macro dashboard, sub-segundo. |
| Vanilla JS (vs React) | Sin bundler, debug fácil, carga instantánea. |
| ECharts (vs Chart.js) | Mejor soporte scatter log, heatmaps, sunburst, tooltips ricos. |
| yfinance (vs Refinitiv) | Gratis, sin credenciales en CI. Excel con Refinitiv = source of truth. |
| Combinar annual + quarterly TTM | yfinance limita quarterly a ~6 períodos. Annual da 5 años + quarterly último año = cobertura real 2020-hoy. |
| NAV equiponderado con rebalanceo diario | Equivalente matemático al mensual en horizonte largo. Empresas entran desde su IPO. |
| Currency desde yfinance (no Excel) | Detecta mismatches que corrompen backtest si se usa campo Excel con errores. |

---

## Limitaciones honestas

- **Shares outstanding históricos** no disponibles en yfinance. Asumimos shares constantes = último valor. Error típico ~5-10% en 5 años por buybacks/dilución. Para precisión institucional → Refinitiv/FMP/SimplyWall.
- **Fundamentals europeos/UK** tienen ~70% cobertura en yfinance (vs ~95% US). Empresas sin data aparecen en `meta.missing`.
- **Survivorship bias** del backtest: tu watchlist *actual* aplicada retroactivamente. No es un backtest puro de selección — es "qué hubiera pasado si hubiera mantenido estas empresas desde 2020 (o su IPO si posterior)".
- **Forward projection cone** es simplista: interpola linealmente entre EV/FCF actual y exit multiples bear/bull. Para rigor, pasar a Monte Carlo (roadmap v1.5).

---

## Roadmap

- [x] v1.0 — Dashboard estático + 6 charts + tabla filtrable
- [x] v1.1 — Backtest (Q4) con 11 cestas y 3 benchmarks
- [x] v1.2 — Multiple history (Q3) con cono forward 5y
- [x] v1.3 — Sistema de alertas + email/WhatsApp
- [ ] v1.4 — Portfolio overlay (cruce con DeGiro para marcar holdings actuales)
- [ ] v1.5 — Monte Carlo sobre IRR scenarios (distribución en lugar de rangos)
- [ ] v1.6 — Rating drift engine (evolución temporal de rating por empresa)
- [ ] v1.7 — Shares outstanding históricos (requiere nuevo data source)

---

## Disclaimers

Uso personal. No es investment advice.

---

## v2.0 — Asymmetry & Terminal Safety (2026-05-19)

Refactor profundo del modelo para alinearlo con la filosofía de inversión: largo plazo, asimetría positiva, riesgo de valor terminal = 0. Todas las métricas legacy se mantienen para compatibilidad (frontend antiguo sigue funcionando); las nuevas se añaden en paralelo.

### Nuevas métricas

| Campo | Cómo se calcula | Para qué sirve |
|---|---|---|
| `composite_geometric` | `quality^(2/3) × survival^(1/3) × 10` | Penaliza no-linealmente cuando el componente de supervivencia colapsa. Reemplaza la media aritmética cuando el riesgo terminal importa. |
| `survival_score` | Promedio normalizado [0,1] de durability + risk_disappear + terminal_risk con sus escalas reales del Excel (`[0,15]`, `[-20,0]`, `[-20,0]`) | 0 = quiebra inminente; 1 = supervivencia perfecta a 10 años |
| `kill_flag` | `True` si `survival_score < 0.5` OR `r3_terminal_risk < -10` | Fuerza `quality_zone = avoid` independientemente del rating |
| `quality_zone` | Quadrant adaptativo: el cutoff EV/FCF depende del composite (35x si ≥8.5, 25x si ≥7.5, 20x si ≥7.0, 15x resto) | Una compounder excepcional puede pagar más múltiplo; un name mediocre no |
| `quality_adjusted_multiple` | 50/50 blend de (EV/NOPAT)/ROIC y (EV/FCF)/(g + 1/duration) | Múltiplo ajustado por calidad de reinversión |
| `irr_worst_repriced` / `irr_best_repriced` | Replica las fórmulas Excel: `FVE = (FCF·exit_mult + Cash − Debt)/Shares`; `IRR_worst = (FVE_min/Price)^(1/5)−1`; `IRR_best = (FVE_max/Price)^(1/4)−1` | IRRs realmente dinámicos al precio post-enrichment |
| `edge_to_fair` | `(geom_mean(FVE_min, FVE_max) / price) − 1` | Upside al fair value base |
| `suggested_weight_pct` | `min(0.25 × Kelly × survival_score, 10%)` | Propuesta de tamaño (decides tú según convicción) |
| `rating_dispersion` | `std(R1, R2, R3)` | Alto = "contested", bajo = consenso analista |
| `ev_fcf_zscore_self_5y` | `(EV/FCF_now − mean_5y)/std_5y` desde `history.json` | Caro/barato vs propia historia |
| `ev_fcf_zscore_sector` | Z-score dentro de la categoría | Caro/barato vs sector |
| `moat_erosion_flag` | OLS slope sobre FCF yield y EV/Sales÷EV/FCF en `history.json`, p<0.20 | Señal de deterioro del moat |
| `buyback_yield_ttm` / `dividend_yield` / `sbc_dilution_pct` / `net_shareholder_return` | yfinance balance sheet + income statement | Retorno entregado al accionista, neto de dilución SBC |

### Nuevos módulos

- `src/snapshots.py` — guarda snapshot completo (todas las columnas) en `data/snapshots/YYYY-MM-DD_watchlist.json` cada build. Construye `docs/data/process_backtest.json` con drift de rating por ticker. En ≥6 meses de snapshots semanales, mostrará correlación entre rating_geom(t) y forward return.
- `src/correlations.py` — matriz de correlación retornos diarios 1y entre la watchlist + clusters jerárquicos. Output: `docs/data/correlations.json` con clusters y pares con |corr|>0.75.
- `src/shareholder.py` — buyback yield + dividend yield + SBC dilution vía yfinance. Output: `docs/data/shareholder.json`.

### Cambios en archivos existentes

- `src/etl.py` — `validate_or_raise()` para fallar CI en blockers (duplicados, market cap negativo, composite ≠ media R1/R2/R3 fuera de tolerancia).
- `src/enrich.py` — fallback single-ticker con `ThreadPoolExecutor(8)` tras batch fallido, para evitar que un ticker corrupto rompa todo el enrichment.
- `src/analytics.py` — todas las funciones nuevas + `inject_history_derived()` que combina watchlist con `history.json`.
- `src/build.py` — orquesta los 3 módulos nuevos. Banderas `--skip-correlations`, `--skip-shareholder`, `--skip-snapshot`.

### Frontend

- Drawer (tarjeta empresa) tiene ahora sección destacada **v2.0 - Asymmetry & Terminal Safety** con composite_geometric, survival_score, kill_flag banner, quality_zone, edge_to_fair, suggested_weight. Sección dedicada **Valuation Z-Scores** muestra los z-scores propio y sectorial. Sección **Shareholder Return** desglosa buyback/div/SBC/neto. Sección **Valuation & Returns** muestra los IRRs cached vs repriced en paralelo.
- Tabla principal añade columnas **Geom** (composite geométrico), **Weight** (suggested_weight), **Kill** (badge), **Zone v2** (quality_zone). Las empresas con moat_erosion_flag llevan un **!** naranja junto al rating.
- Dos nuevos paneles bajo backtest/history: **process backtest · rating drift** y **diversification · correlation clusters**.

### Backup

Se guardó `/sessions/.../.backup_v1/` con todos los archivos pre-v2. Cuando confirmes que todo va bien en GitHub Pages, borra esa carpeta:

```bash
rm -rf .backup_v1/
```

### Limitaciones honestas

- `moat_erosion_flag` usa proxies sobre múltiplos (no márgenes reales) porque `history.json` no expone revenue absoluto. Con p<0.20 puede dar falsos positivos. Para apretar, subir a `p_threshold=0.10` en `detect_moat_erosion()`.
- `suggested_weight_pct` asume `p_win=0.55`. Si tu convicción real es distinta, ajusta `_kelly_fractional(row, p_win=…)` en `analytics.py`.
- `composite_geometric` pondera quality^(2/3) · survival^(1/3). Esto refleja que para 10y holding, supervivencia importa, pero menos que calidad si la calidad ya es alta. Si quieres más castigo terminal, sube el peso a survival^(1/2).
- `KILL_TERMINAL_THRESHOLD = -10` (en escala -20..0). Aprieta o relaja en `analytics.py:54` según veas.

### Roadmap a partir de v2.0

- [ ] v2.1 — acumular 6+ meses de snapshots para activar el process backtest real (correlación rating→forward return)
- [ ] v2.2 — DeGiro overlay (position_pct real para cruce con suggested_weight)
- [ ] v2.3 — Monte Carlo sobre IRR scenarios usando distribución g_min..g_max + exit_mult_min..max
- [ ] v2.4 — Factor decomposition: regresión Fama-French 5-factor del backtest vs S&P; aislar alpha del proceso
