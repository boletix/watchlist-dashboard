/* =====================================================================
   APP — filter state, rendering, interactivity
   ===================================================================== */

const STATE = {
  raw: null,
  backtest: null,
  history: null,
  alerts: null,
  filtered: [],
  charts: {},
  filters: {
    categories: new Set(),
    styles: new Set(),
    exchanges: new Set(),
    minComposite: 0,
    maxEvFcf: 999,
    minBestIrr: -1,
    onlyPositiveWorst: false,
    onlyTopTier: false,
    onlyHuntingGround: false,
    search: '',
  },
  sortKey: 'rating_composite',
  sortDir: 'desc',
  radarSelection: [],
  // Backtest UI state
  backtestActive: new Set(['All Watchlist', 'S&P 500', 'NASDAQ 100']),
  // History UI state
  historyTicker: null,
  historyMetric: 'ev_fcf',
};

/* ---------- Utilities ---------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function debounce(fn, ms = 150) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/* =====================================================================
   DATA LOADING
   ===================================================================== */
async function loadData() {
  // watchlist.json es OBLIGATORIO. Los otros son opcionales.
  const [watchlist, backtest, history, alerts] = await Promise.all([
    fetch('data/watchlist.json?v=' + Date.now()).then((r) => {
      if (!r.ok) throw new Error('No se pudo cargar watchlist.json');
      return r.json();
    }),
    fetch('data/backtest.json?v=' + Date.now())
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('data/history.json?v=' + Date.now())
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('data/alerts.json?v=' + Date.now())
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
  ]);
  return { watchlist, backtest, history, alerts };
}

/* =====================================================================
   FILTERING
   ===================================================================== */
function applyFilters() {
  const f = STATE.filters;
  STATE.filtered = STATE.raw.companies.filter((c) => {
    if (f.categories.size > 0 && !f.categories.has(c.category)) return false;
    if (f.styles.size > 0 && !f.styles.has(c.style)) return false;
    if (f.exchanges.size > 0 && !f.exchanges.has(c.exchange)) return false;
    if ((c.rating_composite || 0) < f.minComposite) return false;
    if (c.ev_fcf != null && c.ev_fcf > 0 && c.ev_fcf > f.maxEvFcf) return false;
    if ((c.irr_best || -1) < f.minBestIrr) return false;
    if (f.onlyPositiveWorst && !(c.irr_worst > 0)) return false;
    if (f.onlyTopTier && !(c.rating_composite >= 7.5)) return false;
    if (f.onlyHuntingGround && c.quadrant !== 'hunting_ground') return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      if (
        !(c.ticker || '').toLowerCase().includes(q) &&
        !(c.name || '').toLowerCase().includes(q) &&
        !(c.category || '').toLowerCase().includes(q)
      )
        return false;
    }
    return true;
  });
}

/* =====================================================================
   RENDER: header & KPIs
   ===================================================================== */
function renderHeader() {
  const meta = STATE.raw.meta;
  const d = new Date(meta.generated_at);
  const dateStr = d.toISOString().split('T')[0];
  const timeStr = d.toISOString().split('T')[1].substring(0, 5);
  $('#topbar-meta').innerHTML = `
    <span>${STATE.filtered.length} <em style="color:var(--text-2)">of</em> ${meta.n_companies}</span>
    <span class="divider"></span>
    <span>${dateStr} · ${timeStr} UTC</span>
    <span class="divider"></span>
    <span style="color:${meta.enrichment_stats.yfinance > 0 ? 'var(--positive)' : 'var(--text-2)'}">
      yf: ${meta.enrichment_stats.yfinance}/${meta.n_companies}
    </span>
  `;
}

function renderKPIs() {
  const list = STATE.filtered;
  const n = list.length;
  if (n === 0) {
    $('#kpis').innerHTML = `<div class="kpi"><div class="kpi__label">Empty</div><div class="kpi__value">—</div></div>`;
    return;
  }
  const avg = (k) => list.reduce((s, c) => s + (c[k] || 0), 0) / n;
  const weightedRoic = (() => {
    const items = list.filter((c) => c.market_cap_m > 0 && c.roic != null);
    if (!items.length) return null;
    const sumW = items.reduce((s, c) => s + c.market_cap_m, 0);
    return items.reduce((s, c) => s + c.roic * c.market_cap_m, 0) / sumW;
  })();
  const medianEvFcf = (() => {
    const vals = list.filter((c) => c.ev_fcf > 0).map((c) => c.ev_fcf).sort((a, b) => a - b);
    return vals.length ? vals[Math.floor(vals.length / 2)] : null;
  })();
  const pctBullish = list.filter((c) => c.irr_best > 0.15).length / n;
  const topTier = list.filter((c) => c.rating_composite >= 7.5).length;
  const huntCount = list.filter((c) => c.quadrant === 'hunting_ground').length;

  const F = CHARTS.fmt;
  $('#kpis').innerHTML = `
    <div class="kpi">
      <div class="kpi__label">Companies</div>
      <div class="kpi__value">${n}<span class="unit">/ ${STATE.raw.meta.n_companies}</span></div>
      <div class="kpi__sub">${topTier} top tier · ${huntCount} hunt</div>
    </div>
    <div class="kpi">
      <div class="kpi__label">Avg Composite</div>
      <div class="kpi__value">${F.rating(avg('rating_composite'))}</div>
      <div class="kpi__sub">0 → 10 scale</div>
    </div>
    <div class="kpi">
      <div class="kpi__label">Weighted ROIC</div>
      <div class="kpi__value">${F.pct(weightedRoic, 1)}</div>
      <div class="kpi__sub">MCap-weighted</div>
    </div>
    <div class="kpi">
      <div class="kpi__label">Median EV/FCF</div>
      <div class="kpi__value">${F.multiple(medianEvFcf, 1)}</div>
      <div class="kpi__sub">positives only</div>
    </div>
    <div class="kpi">
      <div class="kpi__label">Best IRR &gt; 15%</div>
      <div class="kpi__value">${F.pct(pctBullish, 0)}</div>
      <div class="kpi__sub">${list.filter((c) => c.irr_best > 0.15).length} of ${n}</div>
    </div>
  `;
}

/* =====================================================================
   RENDER: sidebar filters
   ===================================================================== */
function renderSidebar() {
  const all = STATE.raw.companies;
  const categories = [...new Set(all.map((c) => c.category).filter(Boolean))].sort();
  const styles = [...new Set(all.map((c) => c.style).filter(Boolean))].sort();

  // Categories
  $('#filter-category').innerHTML = categories
    .map(
      (c) =>
        `<button class="chip ${STATE.filters.categories.has(c) ? 'active' : ''}" data-cat="${c}">${c}</button>`
    )
    .join('');
  $$('#filter-category .chip').forEach((el) => {
    el.addEventListener('click', () => {
      const cat = el.dataset.cat;
      STATE.filters.categories.has(cat)
        ? STATE.filters.categories.delete(cat)
        : STATE.filters.categories.add(cat);
      el.classList.toggle('active');
      refresh();
    });
  });

  // Styles
  $('#filter-style').innerHTML = styles
    .map(
      (s) =>
        `<button class="chip ${STATE.filters.styles.has(s) ? 'active' : ''}" data-style="${s}">${s}</button>`
    )
    .join('');
  $$('#filter-style .chip').forEach((el) => {
    el.addEventListener('click', () => {
      const s = el.dataset.style;
      STATE.filters.styles.has(s)
        ? STATE.filters.styles.delete(s)
        : STATE.filters.styles.add(s);
      el.classList.toggle('active');
      refresh();
    });
  });
}

/* =====================================================================
   RENDER: table
   ===================================================================== */
const TABLE_COLS = [
  { key: 'composite_rank', label: '#', num: true, fmt: (v) => v ?? '—' },
  { key: 'ticker', label: 'Ticker', fmt: (v) => v },
  { key: 'category', label: 'Category', fmt: (v) => v || '—', cls: 'category' },
  {
    key: 'rating_composite',
    label: 'Rating',
    num: true,
    fmt: (v, c) =>
      `<span class="rating-badge tier-${c.rating_tier}">${CHARTS.fmt.rating(v)}</span>`,
  },
  { key: 'rating_1', label: 'R1', num: true, fmt: (v) => CHARTS.fmt.rating(v) },
  { key: 'rating_2', label: 'R2', num: true, fmt: (v) => CHARTS.fmt.rating(v) },
  { key: 'rating_3', label: 'R3', num: true, fmt: (v) => CHARTS.fmt.rating(v) },
  { key: 'roic', label: 'ROIC', num: true, fmt: (v) => CHARTS.fmt.pct(v, 1) },
  { key: 'ev_fcf', label: 'EV/FCF', num: true, fmt: (v) => CHARTS.fmt.multiple(v, 1) },
  { key: 'ev_ebitda', label: 'EV/EBITDA', num: true, fmt: (v) => CHARTS.fmt.multiple(v, 1) },
  { key: 'irr_worst', label: 'Worst', num: true, fmt: (v) => CHARTS.fmt.pct(v, 1) },
  { key: 'irr_best', label: 'Best', num: true, fmt: (v) => CHARTS.fmt.pct(v, 1) },
  {
    key: 'irr_asymmetry_ratio',
    label: 'Asym',
    num: true,
    fmt: (v) => (v != null ? v.toFixed(1) + 'x' : '—'),
  },
  {
    key: 'quadrant',
    label: 'Quadrant',
    fmt: (v) => `<span class="quadrant-pill q-${v}">${CHARTS.QUADRANT_LABEL[v] || v}</span>`,
  },
];

function renderTable() {
  // Header
  $('#table-head').innerHTML =
    '<tr>' +
    TABLE_COLS.map(
      (col) =>
        `<th class="${col.num ? 'num' : ''} ${STATE.sortKey === col.key ? 'sorted' : ''}" data-key="${col.key}">${col.label}${
          STATE.sortKey === col.key ? (STATE.sortDir === 'desc' ? ' ↓' : ' ↑') : ''
        }</th>`
    ).join('') +
    '</tr>';
  $$('#table-head th').forEach((th) => {
    th.addEventListener('click', () => {
      const k = th.dataset.key;
      if (STATE.sortKey === k) {
        STATE.sortDir = STATE.sortDir === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.sortKey = k;
        STATE.sortDir = 'desc';
      }
      renderTable();
    });
  });

  // Sort
  const sorted = [...STATE.filtered].sort((a, b) => {
    const va = a[STATE.sortKey];
    const vb = b[STATE.sortKey];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') {
      return STATE.sortDir === 'desc' ? vb.localeCompare(va) : va.localeCompare(vb);
    }
    return STATE.sortDir === 'desc' ? vb - va : va - vb;
  });

  // Body
  $('#table-body').innerHTML = sorted
    .map(
      (c) =>
        '<tr data-ticker="' +
        c.ticker +
        '">' +
        TABLE_COLS.map(
          (col) =>
            `<td class="${col.num ? 'num' : ''} ${col.cls || ''} ${col.key === 'ticker' ? 'ticker' : ''}">${
              col.fmt(c[col.key], c) ?? '—'
            }</td>`
        ).join('') +
        '</tr>'
    )
    .join('');

  $$('#table-body tr').forEach((tr) => {
    tr.addEventListener('click', () => openDrawer(tr.dataset.ticker));
  });
}

/* =====================================================================
   CHART RENDERING
   ===================================================================== */
function renderCharts() {
  const data = STATE.filtered;
  const allData = STATE.raw.companies;

  for (const [id, optFn, useAll] of [
    ['chart-quadrant', CHARTS.quadrant, false],
    ['chart-asymmetry', CHARTS.irrAsymmetry, false],
    ['chart-bubble', CHARTS.roicVsValuation, false],
    ['chart-heatmap', CHARTS.heatmap, true],  // heatmap uses full universe
    ['chart-sunburst', CHARTS.sunburst, true],
  ]) {
    const el = document.getElementById(id);
    if (!el) continue;
    let chart = STATE.charts[id];
    if (!chart) {
      chart = echarts.init(el, null, { renderer: 'canvas' });
      STATE.charts[id] = chart;
      chart.on('click', (p) => {
        if (p.data && p.data.company) openDrawer(p.data.company.ticker);
      });
    }
    chart.setOption(optFn(useAll ? allData : data), true);
  }

  // Radar is special: uses selection state
  const radarEl = $('#chart-radar');
  if (radarEl) {
    if (!STATE.charts['chart-radar']) {
      STATE.charts['chart-radar'] = echarts.init(radarEl, null, { renderer: 'canvas' });
    }
    // Default: top 4 by composite if none selected
    if (STATE.radarSelection.length === 0) {
      STATE.radarSelection = [...STATE.filtered]
        .sort((a, b) => (b.rating_composite || 0) - (a.rating_composite || 0))
        .slice(0, 4)
        .map((c) => c.ticker);
    }
    const opt = CHARTS.radar(allData, STATE.radarSelection);
    if (opt) STATE.charts['chart-radar'].setOption(opt, true);
    renderRadarSelector();
  }
}

function renderRadarSelector() {
  const sel = $('#radar-selector');
  if (!sel) return;
  const tickers = STATE.filtered.map((c) => c.ticker).sort();
  sel.innerHTML = tickers
    .map(
      (t) =>
        `<button class="chip ${STATE.radarSelection.includes(t) ? 'active' : ''}" data-t="${t}">${t}</button>`
    )
    .join('');
  $$('#radar-selector .chip').forEach((el) => {
    el.addEventListener('click', () => {
      const t = el.dataset.t;
      if (STATE.radarSelection.includes(t)) {
        STATE.radarSelection = STATE.radarSelection.filter((x) => x !== t);
      } else if (STATE.radarSelection.length < 4) {
        STATE.radarSelection.push(t);
      } else {
        // rotate: drop oldest
        STATE.radarSelection.shift();
        STATE.radarSelection.push(t);
      }
      renderCharts();
    });
  });
}

/* =====================================================================
   DRAWER — company detail
   ===================================================================== */
function openDrawer(ticker) {
  const c = STATE.raw.companies.find((x) => x.ticker === ticker);
  if (!c) return;
  const F = CHARTS.fmt;

  const r1Dims = [
    { label: 'Mission', key: 'r1_mission', max: 2 },
    { label: 'MOAT', key: 'r1_moat', max: 8 },
    { label: 'Optionality', key: 'r1_optionality', max: 3 },
    { label: 'Financials', key: 'r1_financials', max: 1 },
    { label: 'Glassdoor', key: 'r1_glassdoor', max: 1 },
    { label: 'Founder/CEO', key: 'r1_founder', max: 1 },
    { label: 'Ownership', key: 'r1_ownership', max: 1 },
  ];

  const r2Dims = [
    { label: 'Financials', key: 'r2_financials', max: 17 },
    { label: 'MOAT', key: 'r2_moat', max: 20 },
    { label: 'Potential', key: 'r2_potential', max: 18 },
    { label: 'Customers', key: 'r2_customers', max: 10 },
    { label: 'Rev Quality', key: 'r2_revenue_quality', max: 10 },
    { label: 'Mgmt', key: 'r2_mgmt', max: 14 },
    { label: 'Ownership', key: 'r2_stock', max: 11 },
  ];

  const r3Dims = [
    { label: 'Durability', key: 'r3_durability', max: 15 },
    { label: 'Capital Alloc', key: 'r3_capital_alloc', max: 15 },
    { label: 'MOAT Struct', key: 'r3_moat_structural', max: 15 },
    { label: 'Incentives', key: 'r3_incentives', max: 10 },
    { label: 'Low Cap Int.', key: 'r3_capital_intensity', max: 10 },
    { label: 'Financing', key: 'r3_financing', max: 5 },
  ];

  const ratingBar = (d) => {
    const v = c[d.key];
    if (v == null) return '';
    const pct = Math.max(0, Math.min(100, (v / d.max) * 100));
    return `
      <div class="rating-bar">
        <div class="rating-bar__label">${d.label}</div>
        <div class="rating-bar__track"><div class="rating-bar__fill" style="width:${pct}%"></div></div>
        <div class="rating-bar__value">${v.toFixed(1)} / ${d.max}</div>
      </div>
    `;
  };

  $('#drawer').innerHTML = `
    <div class="drawer__header">
      <button class="drawer__close" aria-label="Close">✕</button>
      <div class="drawer__ticker">${c.ticker}</div>
      <div class="drawer__name">${c.name || c.ticker}</div>
      <div class="drawer__meta">
        ${c.category || '—'} · ${c.style || '—'} · ${c.exchange || '—'} · ${c.currency || ''}
      </div>
    </div>
    <div class="drawer__body">
      <div class="drawer__section">
        <h3>Rating Summary</h3>
        <div class="stat-grid">
          <div class="stat">
            <div class="stat__label">Composite</div>
            <div class="stat__value">${F.rating(c.rating_composite)} <span style="color:var(--text-2);font-size:11px">#${c.composite_rank ?? '—'}</span></div>
          </div>
          <div class="stat">
            <div class="stat__label">Quadrant</div>
            <div class="stat__value" style="color:${CHARTS.QUADRANT_COLOR[c.quadrant]}">${CHARTS.QUADRANT_LABEL[c.quadrant]}</div>
          </div>
          <div class="stat">
            <div class="stat__label">R1 Structural</div>
            <div class="stat__value">${F.rating(c.rating_1)}</div>
          </div>
          <div class="stat">
            <div class="stat__label">R2 Economic</div>
            <div class="stat__value">${F.rating(c.rating_2)}</div>
          </div>
          <div class="stat">
            <div class="stat__label">R3 Durability</div>
            <div class="stat__value">${F.rating(c.rating_3)}</div>
          </div>
          <div class="stat">
            <div class="stat__label">Tier</div>
            <div class="stat__value"><span class="rating-badge tier-${c.rating_tier}">${(c.rating_tier || '').replace(/_/g, ' ')}</span></div>
          </div>
        </div>
      </div>

      <div class="drawer__section">
        <h3>Valuation & Returns</h3>
        <div class="stat-grid">
          <div class="stat"><div class="stat__label">Price</div><div class="stat__value">${F.num(c.price)}</div></div>
          <div class="stat"><div class="stat__label">Market Cap</div><div class="stat__value">${F.mcap(c.market_cap_m)}</div></div>
          <div class="stat"><div class="stat__label">ROIC</div><div class="stat__value positive">${F.pct(c.roic)}</div></div>
          <div class="stat"><div class="stat__label">EV/FCF</div><div class="stat__value">${F.multiple(c.ev_fcf)}</div></div>
          <div class="stat"><div class="stat__label">EV/EBITDA</div><div class="stat__value">${F.multiple(c.ev_ebitda)}</div></div>
          <div class="stat"><div class="stat__label">EV/Sales</div><div class="stat__value">${F.multiple(c.ev_sales)}</div></div>
          <div class="stat"><div class="stat__label">Worst IRR</div><div class="stat__value ${c.irr_worst > 0 ? 'positive' : 'negative'}">${F.pct(c.irr_worst)}</div></div>
          <div class="stat"><div class="stat__label">Best IRR</div><div class="stat__value positive">${F.pct(c.irr_best)}</div></div>
          <div class="stat"><div class="stat__label">IRR Asymmetry</div><div class="stat__value">${c.irr_asymmetry_ratio ? c.irr_asymmetry_ratio.toFixed(1) + 'x' : '—'}</div></div>
          <div class="stat"><div class="stat__label">FCF CAGR (5y)</div><div class="stat__value">${F.pct(c.fcf_min_cagr)} → ${F.pct(c.fcf_max_cagr)}</div></div>
        </div>
      </div>

      <div class="drawer__section">
        <h3>R1 — Structural Quality Breakdown</h3>
        ${r1Dims.map(ratingBar).join('')}
      </div>

      <div class="drawer__section">
        <h3>R2 — Economic Quality Breakdown</h3>
        ${r2Dims.map(ratingBar).join('')}
      </div>

      <div class="drawer__section">
        <h3>R3 — Durability Breakdown</h3>
        ${r3Dims.map(ratingBar).join('')}
      </div>
    </div>
  `;

  $('.drawer__close').addEventListener('click', closeDrawer);
  $('#drawer').classList.add('open');
  $('#drawer-backdrop').classList.add('open');
}

function closeDrawer() {
  $('#drawer').classList.remove('open');
  $('#drawer-backdrop').classList.remove('open');
}

/* =====================================================================
   ALERTS BANNER
   ===================================================================== */
function renderAlertsBanner() {
  const banner = $('#alerts-banner');
  if (!STATE.alerts || !STATE.alerts.alerts || STATE.alerts.alerts.length === 0) {
    banner.style.display = 'none';
    return;
  }
  const high = STATE.alerts.alerts.filter((a) => a.severity === 'high');
  const med = STATE.alerts.alerts.filter((a) => a.severity === 'medium');
  if (high.length === 0 && med.length === 0) {
    banner.style.display = 'none';
    return;
  }
  // Top 6 alertas como chips clicables
  const topAlerts = [...high, ...med].slice(0, 6);
  banner.innerHTML = `
    <div class="alerts-banner__icon">●</div>
    <div class="alerts-banner__text">
      <strong>${high.length} high</strong> · ${med.length} medium alerts
      <div class="alerts-banner__list">
        ${topAlerts
          .map(
            (a) =>
              `<span class="alerts-banner__chip" data-ticker="${a.ticker}" title="${a.message.replace(/"/g, '&quot;')}">
                <span class="ticker">${a.ticker}</span>${a.type.replace(/_/g, ' ')}
              </span>`
          )
          .join('')}
      </div>
    </div>
    <button class="alerts-banner__close">dismiss</button>
  `;
  banner.style.display = 'flex';
  // Click en un chip → abre el drawer de esa empresa
  banner.querySelectorAll('.alerts-banner__chip').forEach((chip) => {
    chip.addEventListener('click', () => openDrawer(chip.dataset.ticker));
  });
  banner.querySelector('.alerts-banner__close').addEventListener('click', () => {
    banner.style.display = 'none';
  });
}

/* =====================================================================
   BACKTEST PANEL
   ===================================================================== */
function renderBacktestSelector() {
  const sel = $('#backtest-selector');
  if (!sel || !STATE.backtest) return;
  const series = Object.keys(STATE.backtest.series);
  sel.innerHTML = series
    .map(
      (name) =>
        `<button class="chip ${STATE.backtestActive.has(name) ? 'active' : ''}" data-series="${name.replace(/"/g, '&quot;')}">${name}</button>`
    )
    .join('');
  sel.querySelectorAll('.chip').forEach((el) => {
    el.addEventListener('click', () => {
      const name = el.dataset.series;
      STATE.backtestActive.has(name)
        ? STATE.backtestActive.delete(name)
        : STATE.backtestActive.add(name);
      el.classList.toggle('active');
      renderBacktestChart();
      renderBacktestStatsTable();
    });
  });
}

function renderBacktestChart() {
  if (!STATE.backtest) return;
  const el = $('#chart-backtest');
  if (!el) return;
  if (!STATE.charts['chart-backtest']) {
    STATE.charts['chart-backtest'] = echarts.init(el, null, { renderer: 'canvas' });
  }
  const opt = CHARTS.backtest(STATE.backtest.series, [...STATE.backtestActive]);
  STATE.charts['chart-backtest'].setOption(opt, true);
  // Header summary
  const meta = STATE.backtest.meta;
  $('#backtest-stats').textContent = `${meta.start_date} → ${meta.end_date} · ${meta.n_companies_total} empresas · ${meta.currencies_converted.length} FX`;
}

function renderBacktestStatsTable() {
  if (!STATE.backtest) return;
  const target = $('#backtest-stats-table');
  if (!target) return;
  const active = [...STATE.backtestActive];
  if (active.length === 0) {
    target.innerHTML = '';
    return;
  }
  const rows = active
    .map((name) => {
      const s = STATE.backtest.series[name];
      if (!s) return null;
      const st = s.stats;
      return { name, ...st, type: s.type };
    })
    .filter(Boolean)
    .sort((a, b) => b.cagr - a.cagr);

  let html = `
    <div class="stats-mini-table">
      <div class="header">Series</div>
      <div class="header num">CAGR</div>
      <div class="header num">Sharpe</div>
      <div class="header num">Max DD</div>
      <div class="header num">Total Return</div>
  `;
  rows.forEach((r) => {
    const isWatchlist = r.name === 'All Watchlist';
    const nameCls = isWatchlist ? 'name accent' : (r.type === 'benchmark' ? 'name' : 'name');
    html += `
      <div class="${nameCls}">${r.name}${r.type === 'benchmark' ? ' <span style="color:var(--text-2);font-size:9px;">[bench]</span>' : ''}</div>
      <div class="num ${r.cagr >= 0 ? 'positive' : 'negative'}">${(r.cagr * 100).toFixed(1)}%</div>
      <div class="num">${r.sharpe.toFixed(2)}</div>
      <div class="num negative">${(r.max_dd * 100).toFixed(1)}%</div>
      <div class="num ${r.total_return >= 0 ? 'positive' : 'negative'}">${(r.total_return * 100).toFixed(0)}%</div>
    `;
  });
  html += '</div>';
  target.innerHTML = html;
}

/* =====================================================================
   HISTORY PANEL
   ===================================================================== */
function renderHistorySelector() {
  if (!STATE.history) return;
  const sel = $('#history-ticker');
  if (!sel) return;
  const tickers = Object.keys(STATE.history.companies).sort();
  if (!STATE.historyTicker || !tickers.includes(STATE.historyTicker)) {
    // Default: la primera empresa de tu top tier
    const topTier = STATE.raw.companies
      .filter((c) => c.rating_composite >= 7.5 && tickers.includes(c.ticker))
      .sort((a, b) => b.rating_composite - a.rating_composite);
    STATE.historyTicker = topTier[0]?.ticker || tickers[0];
  }
  sel.innerHTML = tickers
    .map((t) => `<option value="${t}" ${t === STATE.historyTicker ? 'selected' : ''}>${t}</option>`)
    .join('');
  sel.addEventListener('change', () => {
    STATE.historyTicker = sel.value;
    renderHistoryChart();
  });

  // Metric chips
  $$('.metric-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      $$('.metric-chip').forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      STATE.historyMetric = chip.dataset.metric;
      renderHistoryChart();
    });
  });
}

function renderHistoryChart() {
  if (!STATE.history || !STATE.historyTicker) return;
  const el = $('#chart-history');
  if (!el) return;
  if (!STATE.charts['chart-history']) {
    STATE.charts['chart-history'] = echarts.init(el, null, { renderer: 'canvas' });
  }
  const opt = CHARTS.multipleHistory(STATE.history, STATE.historyTicker, STATE.historyMetric);
  if (opt) {
    STATE.charts['chart-history'].setOption(opt, true);
  } else {
    STATE.charts['chart-history'].clear();
  }
}

/* =====================================================================
   REFRESH ORCHESTRATOR
   ===================================================================== */
function refresh() {
  applyFilters();
  renderHeader();
  renderKPIs();
  renderTable();
  renderCharts();
}

/* =====================================================================
   EVENT WIRING
   ===================================================================== */
function wireFilters() {
  $('#filter-min-composite').addEventListener('input', (e) => {
    const v = parseFloat(e.target.value);
    STATE.filters.minComposite = v;
    $('#filter-min-composite-value').textContent = v.toFixed(1);
    refresh();
  });
  $('#filter-max-evfcf').addEventListener('input', (e) => {
    const v = parseFloat(e.target.value);
    STATE.filters.maxEvFcf = v;
    $('#filter-max-evfcf-value').textContent = v === 200 ? '∞' : v.toFixed(0) + 'x';
    refresh();
  });
  $('#filter-min-best-irr').addEventListener('input', (e) => {
    const v = parseFloat(e.target.value);
    STATE.filters.minBestIrr = v;
    $('#filter-min-best-irr-value').textContent = (v * 100).toFixed(0) + '%';
    refresh();
  });
  $('#filter-positive-worst').addEventListener('change', (e) => {
    STATE.filters.onlyPositiveWorst = e.target.checked;
    refresh();
  });
  $('#filter-top-tier').addEventListener('change', (e) => {
    STATE.filters.onlyTopTier = e.target.checked;
    refresh();
  });
  $('#filter-hunting').addEventListener('change', (e) => {
    STATE.filters.onlyHuntingGround = e.target.checked;
    refresh();
  });
  $('#filter-search').addEventListener(
    'input',
    debounce((e) => {
      STATE.filters.search = e.target.value.trim();
      refresh();
    }, 200)
  );
  $('#filter-reset').addEventListener('click', () => {
    STATE.filters.categories.clear();
    STATE.filters.styles.clear();
    STATE.filters.exchanges.clear();
    STATE.filters.minComposite = 0;
    STATE.filters.maxEvFcf = 200;
    STATE.filters.minBestIrr = -1;
    STATE.filters.onlyPositiveWorst = false;
    STATE.filters.onlyTopTier = false;
    STATE.filters.onlyHuntingGround = false;
    STATE.filters.search = '';
    $('#filter-min-composite').value = 0;
    $('#filter-min-composite-value').textContent = '0.0';
    $('#filter-max-evfcf').value = 200;
    $('#filter-max-evfcf-value').textContent = '∞';
    $('#filter-min-best-irr').value = -1;
    $('#filter-min-best-irr-value').textContent = '-100%';
    $('#filter-positive-worst').checked = false;
    $('#filter-top-tier').checked = false;
    $('#filter-hunting').checked = false;
    $('#filter-search').value = '';
    renderSidebar();
    refresh();
  });
  $('#drawer-backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDrawer();
  });
  window.addEventListener(
    'resize',
    debounce(() => {
      Object.values(STATE.charts).forEach((ch) => ch.resize());
    }, 100)
  );
}

/* =====================================================================
   BOOT
   ===================================================================== */
async function boot() {
  try {
    const data = await loadData();
    // STATE.raw mantiene la forma antigua para compatibilidad con el resto del código
    STATE.raw = data.watchlist;
    STATE.backtest = data.backtest;
    STATE.history = data.history;
    STATE.alerts = data.alerts;

    renderSidebar();
    wireFilters();
    // CRITICAL: show shell BEFORE rendering charts. ECharts measures container
    // dims at init time; if container is display:none, canvas gets sized to ~0
    // and all data points collapse to a single pixel position.
    $('#loading').style.display = 'none';
    $('#app-shell').style.display = 'grid';
    // Force layout flush before ECharts reads dims
    void document.body.offsetHeight;
    refresh();

    // Render new panels (only if data is available)
    if (STATE.alerts) renderAlertsBanner();
    if (STATE.backtest) {
      renderBacktestSelector();
      renderBacktestChart();
      renderBacktestStatsTable();
    }
    if (STATE.history) {
      renderHistorySelector();
      renderHistoryChart();
    }

    // Extra safety: resize after one frame in case of any lingering size issues
    requestAnimationFrame(() => {
      Object.values(STATE.charts).forEach((ch) => ch.resize());
    });
  } catch (e) {
    $('#loading').textContent = 'Error: ' + e.message;
    console.error(e);
  }
}

document.addEventListener('DOMContentLoaded', boot);
