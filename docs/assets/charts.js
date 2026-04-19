/* =====================================================================
   CHARTS — ECharts configurations
   Every chart reads from the shared DATA object and filters.
   ===================================================================== */

const THEME = {
  bg: '#121317',
  text0: '#e8e6e0',
  text1: '#a8a39b',
  text2: '#6b6761',
  border: '#2a2d34',
  accent: '#c77d46',
  accentDim: '#8a5530',
  positive: '#7ca878',
  negative: '#b85a5a',
  neutral: '#6b80a8',
  qHunt: '#c77d46',
  qWonderful: '#7a8fb8',
  qTrap: '#8a6b4a',
  qAvoid: '#4a4743',
  font: 'Instrument Sans, system-ui, sans-serif',
  fontMono: 'JetBrains Mono, monospace',
};

const QUADRANT_COLOR = {
  hunting_ground: THEME.qHunt,
  wonderful_expensive: THEME.qWonderful,
  value_trap: THEME.qTrap,
  avoid: THEME.qAvoid,
  unknown: THEME.text2,
};

const QUADRANT_LABEL = {
  hunting_ground: 'Hunting Ground',
  wonderful_expensive: 'Wonderful · Expensive',
  value_trap: 'Value Trap Risk',
  avoid: 'Avoid',
  unknown: 'N/A',
};

const CATEGORY_COLORS = [
  '#c77d46', '#7a8fb8', '#7ca878', '#b85a5a', '#a88c5a',
  '#5a8a8a', '#8a5a8a', '#b88a46', '#6b80a8', '#8a7a5a',
  '#5a7a8a', '#a85a6b', '#7a5a8a', '#8a6b5a', '#5a8a6b',
];

/* ---------- Formatting helpers ---------- */
const fmt = {
  pct: (v, digits = 1) =>
    v == null || isNaN(v) ? '—' : (v * 100).toFixed(digits) + '%',
  num: (v, digits = 2) =>
    v == null || isNaN(v) ? '—' : v.toFixed(digits),
  multiple: (v, digits = 1) =>
    v == null || isNaN(v) ? '—' : v.toFixed(digits) + 'x',
  mcap: (v) => {
    if (v == null || isNaN(v)) return '—';
    if (v >= 1000) return (v / 1000).toFixed(1) + 'B';
    return v.toFixed(0) + 'M';
  },
  rating: (v) => (v == null || isNaN(v) ? '—' : v.toFixed(2)),
};

/* ---------- Base option shared across charts ---------- */
function baseOption() {
  return {
    backgroundColor: 'transparent',
    textStyle: { color: THEME.text0, fontFamily: THEME.font },
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut',
    grid: {
      left: 60,
      right: 30,
      top: 30,
      bottom: 50,
      containLabel: false,
    },
    tooltip: {
      backgroundColor: THEME.bg,
      borderColor: THEME.border,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: {
        color: THEME.text0,
        fontFamily: THEME.fontMono,
        fontSize: 11,
      },
      extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.6);',
    },
  };
}

function axisStyle() {
  return {
    axisLine: { lineStyle: { color: THEME.border } },
    axisTick: { lineStyle: { color: THEME.border } },
    axisLabel: {
      color: THEME.text2,
      fontFamily: THEME.fontMono,
      fontSize: 10,
    },
    splitLine: { lineStyle: { color: THEME.border, type: 'dashed', opacity: 0.5 } },
    nameTextStyle: {
      color: THEME.text2,
      fontFamily: THEME.fontMono,
      fontSize: 10,
    },
  };
}

/* =====================================================================
   Helper: compute smart axis bounds for log scale.
   Uses P2/P98 to trim outliers, falls back to full range with padding.
   Returns {min, max, outliers: [{value, ticker, side}]}.
   ===================================================================== */
function smartLogBounds(values, tickers, pMin = 0.02, pMax = 0.98, padFactor = 1.2) {
  if (!values.length) return { min: 1, max: 100, outliers: [] };
  const sorted = [...values.map((v, i) => ({ v, t: tickers[i] }))].sort((a, b) => a.v - b.v);
  const loIdx = Math.floor(sorted.length * pMin);
  const hiIdx = Math.min(sorted.length - 1, Math.ceil(sorted.length * pMax));
  const lo = sorted[loIdx].v;
  const hi = sorted[hiIdx].v;
  // Round to nice log boundaries
  const niceMin = Math.pow(10, Math.floor(Math.log10(lo / padFactor)));
  const niceMax = Math.pow(10, Math.ceil(Math.log10(hi * padFactor)));
  const outliers = sorted
    .filter((x) => x.v < niceMin || x.v > niceMax)
    .map((x) => ({ value: x.v, ticker: x.t, side: x.v < niceMin ? 'low' : 'high' }));
  return { min: niceMin, max: niceMax, outliers };
}

/* =====================================================================
   1. QUALITY-VALUE QUADRANT (headline scatter)
   ===================================================================== */
function quadrantChartOption(companies) {
  const THRESH_Q = 7.5;
  const THRESH_EV = 20;

  const valid = companies.filter(
    (c) => c.rating_composite != null && c.ev_fcf != null && c.ev_fcf > 0
  );

  // Smart bounds: trim extreme outliers so the cluster breathes
  const { min: xMin, max: xMax, outliers } = smartLogBounds(
    valid.map((c) => c.ev_fcf),
    valid.map((c) => c.ticker),
    0.02,
    0.95, // clip at P95 to keep chart readable
    1.15
  );

  // Clip outlier points to the edge, mark them visually so they aren't lost
  const data = valid.map((c) => {
    const clipped = Math.max(xMin * 1.02, Math.min(xMax * 0.98, c.ev_fcf));
    const isOutlier = c.ev_fcf > xMax;
    return {
      value: [clipped, c.rating_composite],
      name: c.ticker,
      company: c,
      itemStyle: {
        color: QUADRANT_COLOR[c.quadrant] || THEME.text2,
        borderColor:
          c.quadrant === 'hunting_ground'
            ? THEME.accent
            : isOutlier
            ? THEME.negative
            : 'transparent',
        borderWidth:
          c.quadrant === 'hunting_ground' || isOutlier ? 2 : 0,
        opacity: c.quadrant === 'hunting_ground' ? 1 : 0.75,
      },
      symbol: isOutlier ? 'triangle' : 'circle',
      symbolSize: Math.max(
        8,
        Math.min(28, Math.sqrt(Math.max(c.market_cap_m || 1000, 100) / 500))
      ),
      _isOutlier: isOutlier,
    };
  });

  // Y-axis bounds from rating data
  const ratings = valid.map((c) => c.rating_composite);
  const yMin = Math.max(0, Math.floor(Math.min(...ratings) - 0.5));
  const yMax = Math.min(10, Math.ceil(Math.max(...ratings) + 0.5));

  return {
    ...baseOption(),
    grid: { left: 70, right: 30, top: 30, bottom: 55 },
    xAxis: {
      type: 'log',
      name: `EV / FCF (log) ${outliers.length ? `· ${outliers.length} outliers ▲` : ''}`,
      nameLocation: 'middle',
      nameGap: 32,
      min: xMin,
      max: xMax,
      ...axisStyle(),
    },
    yAxis: {
      type: 'value',
      name: 'Composite Rating',
      nameLocation: 'middle',
      nameGap: 42,
      min: yMin,
      max: yMax,
      ...axisStyle(),
    },
    tooltip: {
      ...baseOption().tooltip,
      formatter: (p) => {
        const c = p.data.company;
        const isOut = p.data._isOutlier;
        return `
          <div style="font-family:${THEME.font};margin-bottom:4px;">
            <span style="color:${THEME.accent};font-weight:500;">${c.ticker}</span>
            <span style="color:${THEME.text2};margin-left:6px;font-size:10px;">${c.category || ''}</span>
            ${isOut ? `<span style="color:${THEME.negative};margin-left:6px;font-size:10px;">▲ outlier</span>` : ''}
          </div>
          <div style="border-top:1px solid ${THEME.border};padding-top:4px;">
            Rating&nbsp;&nbsp; <b>${fmt.rating(c.rating_composite)}</b><br/>
            EV/FCF&nbsp;&nbsp; <b>${fmt.multiple(c.ev_fcf)}</b>${isOut ? ' <span style="color:'+THEME.negative+'">(off-chart)</span>' : ''}<br/>
            ROIC&nbsp;&nbsp;&nbsp;&nbsp; <b>${fmt.pct(c.roic)}</b><br/>
            MCap&nbsp;&nbsp;&nbsp;&nbsp; <b>${fmt.mcap(c.market_cap_m)}</b><br/>
            Best IRR&nbsp; <b style="color:${c.irr_best > 0.15 ? THEME.positive : THEME.text1}">${fmt.pct(c.irr_best)}</b><br/>
            <span style="color:${THEME.text2};font-size:10px;">${QUADRANT_LABEL[c.quadrant]}</span>
          </div>
        `;
      },
    },
    series: [
      {
        type: 'scatter',
        data,
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: THEME.accentDim, type: 'dashed', width: 1 },
          label: {
            color: THEME.text2,
            fontFamily: THEME.fontMono,
            fontSize: 9,
          },
          data: [
            { yAxis: THRESH_Q, label: { formatter: `Top Tier ${THRESH_Q}`, position: 'end' } },
            { xAxis: THRESH_EV, label: { formatter: `EV/FCF ${THRESH_EV}x`, position: 'end' } },
          ],
        },
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(199, 125, 70, 0.05)' },
          data: [
            [
              { xAxis: 5, yAxis: THRESH_Q, name: 'Hunting Ground',
                label: {
                  position: 'insideTopLeft',
                  color: THEME.accent,
                  fontFamily: THEME.fontMono,
                  fontSize: 10,
                  distance: 8,
                  formatter: 'HUNTING GROUND',
                } },
              { xAxis: THRESH_EV, yAxis: 10 },
            ],
          ],
        },
      },
    ],
  };
}

/* =====================================================================
   2. IRR ASYMMETRY DUMBBELL
   ===================================================================== */
function irrAsymmetryOption(companies, limit = 25) {
  const filtered = companies
    .filter((c) => c.irr_worst != null && c.irr_best != null)
    .sort((a, b) => (b.irr_asymmetry_ratio || 0) - (a.irr_asymmetry_ratio || 0))
    .slice(0, limit)
    .reverse(); // reverse para que el mejor quede arriba en barras horizontales

  const tickers = filtered.map((c) => c.ticker);
  const worstData = filtered.map((c) => c.irr_worst * 100);
  const bestData = filtered.map((c) => c.irr_best * 100);

  // Preparar líneas conectando worst con best por empresa
  const lineData = filtered.map((c, i) => [
    [c.irr_worst * 100, i],
    [c.irr_best * 100, i],
  ]);

  return {
    ...baseOption(),
    grid: { left: 65, right: 50, top: 20, bottom: 50 },
    xAxis: {
      type: 'value',
      name: 'IRR %',
      nameLocation: 'middle',
      nameGap: 30,
      axisLabel: {
        ...axisStyle().axisLabel,
        formatter: '{value}%',
      },
      ...axisStyle(),
    },
    yAxis: {
      type: 'category',
      data: tickers,
      axisLabel: {
        color: THEME.text1,
        fontFamily: THEME.fontMono,
        fontSize: 10,
      },
      axisLine: { lineStyle: { color: THEME.border } },
      axisTick: { show: false },
    },
    tooltip: {
      ...baseOption().tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const c = filtered[params[0].dataIndex];
        return `
          <div>
            <span style="color:${THEME.accent};">${c.ticker}</span>
            <span style="color:${THEME.text2};margin-left:4px;">${c.category || ''}</span><br/>
            Worst <b style="color:${c.irr_worst > 0 ? THEME.positive : THEME.negative}">${fmt.pct(c.irr_worst)}</b><br/>
            Best&nbsp; <b style="color:${THEME.positive}">${fmt.pct(c.irr_best)}</b><br/>
            Ratio <b>${c.irr_asymmetry_ratio ? c.irr_asymmetry_ratio.toFixed(1) : '—'}x</b>
          </div>
        `;
      },
    },
    series: [
      // Connecting lines
      {
        type: 'custom',
        renderItem: (params, api) => {
          const x0 = api.coord([api.value(0), api.value(2)])[0];
          const x1 = api.coord([api.value(1), api.value(2)])[0];
          const y = api.coord([api.value(0), api.value(2)])[1];
          return {
            type: 'line',
            shape: { x1: x0, y1: y, x2: x1, y2: y },
            style: {
              stroke: THEME.accentDim,
              lineWidth: 1,
              opacity: 0.6,
            },
          };
        },
        data: filtered.map((c, i) => [c.irr_worst * 100, c.irr_best * 100, i]),
        z: 1,
      },
      // Worst IRR dot
      {
        type: 'scatter',
        name: 'Worst',
        data: worstData.map((v, i) => [v, i]),
        symbolSize: 9,
        itemStyle: {
          color: (p) => (p.value[0] >= 0 ? THEME.positive : THEME.negative),
          borderWidth: 0,
        },
        z: 2,
      },
      // Best IRR dot
      {
        type: 'scatter',
        name: 'Best',
        data: bestData.map((v, i) => [v, i]),
        symbolSize: 11,
        itemStyle: {
          color: THEME.accent,
          borderColor: THEME.accent,
          borderWidth: 1,
        },
        z: 3,
      },
      // Zero reference line
      {
        type: 'line',
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: THEME.border, type: 'solid', width: 1 },
          data: [{ xAxis: 0 }],
        },
      },
    ],
  };
}

/* =====================================================================
   3. ROIC vs EV/FCF BUBBLE
   ===================================================================== */
function roicVsValuationOption(companies) {
  const valid = companies.filter(
    (c) => c.roic != null && c.ev_fcf != null && c.ev_fcf > 0
  );

  const { min: xMin, max: xMax } = smartLogBounds(
    valid.map((c) => c.ev_fcf),
    valid.map((c) => c.ticker),
    0.02,
    0.95,
    1.15
  );

  // Y bounds from ROIC data (already in decimal, will ×100 for display)
  const roicValues = valid.map((c) => c.roic * 100);
  const yMin = Math.floor(Math.min(...roicValues, 0) / 10) * 10;
  const yMax = Math.ceil(Math.max(...roicValues) / 10) * 10;

  // Series por categoría para leyenda interactiva
  const byCategory = {};
  valid.forEach((c) => {
    if (!byCategory[c.category]) byCategory[c.category] = [];
    byCategory[c.category].push(c);
  });

  const series = Object.entries(byCategory).map(([cat, items], idx) => ({
    type: 'scatter',
    name: cat,
    data: items.map((c) => {
      const clipped = Math.max(xMin * 1.02, Math.min(xMax * 0.98, c.ev_fcf));
      const isOut = c.ev_fcf > xMax;
      return {
        value: [clipped, c.roic * 100, c.rating_composite, c.ticker],
        company: c,
        _isOutlier: isOut,
        symbol: isOut ? 'triangle' : 'circle',
      };
    }),
    symbolSize: (val) => Math.max(10, Math.min(38, val[2] * 3.5)),
    itemStyle: {
      color: CATEGORY_COLORS[idx % CATEGORY_COLORS.length],
      opacity: 0.75,
      borderColor: THEME.bg,
      borderWidth: 1,
    },
    emphasis: {
      itemStyle: { opacity: 1, borderColor: THEME.accent, borderWidth: 2 },
    },
  }));

  return {
    ...baseOption(),
    grid: { left: 70, right: 30, top: 40, bottom: 55 },
    legend: {
      type: 'scroll',
      top: 0,
      textStyle: { color: THEME.text1, fontFamily: THEME.fontMono, fontSize: 10 },
      pageTextStyle: { color: THEME.text2 },
      pageIconColor: THEME.accent,
      pageIconInactiveColor: THEME.text3,
    },
    xAxis: {
      type: 'log',
      name: 'EV / FCF (log)',
      nameLocation: 'middle',
      nameGap: 32,
      min: xMin,
      max: xMax,
      ...axisStyle(),
    },
    yAxis: {
      type: 'value',
      name: 'ROIC %',
      nameLocation: 'middle',
      nameGap: 45,
      min: yMin,
      max: yMax,
      axisLabel: { ...axisStyle().axisLabel, formatter: '{value}%' },
      ...axisStyle(),
    },
    tooltip: {
      ...baseOption().tooltip,
      formatter: (p) => {
        const c = p.data.company;
        const isOut = p.data._isOutlier;
        return `
          <div>
            <span style="color:${THEME.accent};">${c.ticker}</span>
            <span style="color:${THEME.text2};margin-left:4px;">${c.category}</span>
            ${isOut ? `<span style="color:${THEME.negative};margin-left:4px;">▲</span>` : ''}<br/>
            ROIC&nbsp;&nbsp;&nbsp; <b>${fmt.pct(c.roic)}</b><br/>
            EV/FCF&nbsp; <b>${fmt.multiple(c.ev_fcf)}</b>${isOut ? ' <span style="color:'+THEME.negative+'">(off-chart)</span>' : ''}<br/>
            Rating&nbsp; <b>${fmt.rating(c.rating_composite)}</b><br/>
            MCap&nbsp;&nbsp;&nbsp; <b>${fmt.mcap(c.market_cap_m)}</b>
          </div>
        `;
      },
    },
    series,
  };
}

/* =====================================================================
   4. RATING DECOMPOSITION RADAR (compare up to 4)
   ===================================================================== */
function radarOption(companies, selectedTickers) {
  const selected = companies.filter((c) => selectedTickers.includes(c.ticker));
  if (selected.length === 0) return null;

  // Usamos las 8 dims de R2 (la más rica)
  const indicators = [
    { name: 'Financials', max: 17, key: 'r2_financials' },
    { name: 'MOAT', max: 20, key: 'r2_moat' },
    { name: 'Potential', max: 18, key: 'r2_potential' },
    { name: 'Customers', max: 10, key: 'r2_customers' },
    { name: 'Rev Quality', max: 10, key: 'r2_revenue_quality' },
    { name: 'Mgmt', max: 14, key: 'r2_mgmt' },
    { name: 'Ownership', max: 11, key: 'r2_stock' },
    { name: 'Low Risk', max: 44, key: 'r2_risks', invert: true },
  ];

  return {
    ...baseOption(),
    legend: {
      top: 0,
      textStyle: { color: THEME.text1, fontFamily: THEME.fontMono, fontSize: 10 },
    },
    radar: {
      shape: 'polygon',
      indicator: indicators.map((i) => ({ name: i.name, max: i.max })),
      axisName: {
        color: THEME.text1,
        fontFamily: THEME.fontMono,
        fontSize: 10,
      },
      splitLine: { lineStyle: { color: THEME.border } },
      splitArea: { areaStyle: { color: ['transparent', 'rgba(255,255,255,0.015)'] } },
      axisLine: { lineStyle: { color: THEME.border } },
      radius: '60%',
    },
    tooltip: { ...baseOption().tooltip, trigger: 'item' },
    series: [
      {
        type: 'radar',
        data: selected.map((c, i) => ({
          value: indicators.map((ind) => {
            const v = c[ind.key] || 0;
            return ind.invert ? ind.max - Math.abs(v) : v;
          }),
          name: c.ticker,
          lineStyle: {
            color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
            width: 2,
          },
          areaStyle: {
            color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
            opacity: 0.1,
          },
          itemStyle: { color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] },
        })),
      },
    ],
  };
}

/* =====================================================================
   5. CATEGORY × DIMENSION HEATMAP
   ===================================================================== */
function heatmapOption(companies) {
  const dims = [
    { name: 'R1 Struct', key: 'rating_1' },
    { name: 'R2 Econ', key: 'rating_2' },
    { name: 'R3 Durab', key: 'rating_3' },
    { name: 'Composite', key: 'rating_composite' },
  ];

  const categories = [...new Set(companies.map((c) => c.category).filter(Boolean))].sort();
  const data = [];

  categories.forEach((cat, y) => {
    dims.forEach((dim, x) => {
      const items = companies.filter((c) => c.category === cat && c[dim.key] != null);
      if (items.length === 0) {
        data.push([x, y, null, 0]);
        return;
      }
      const avg = items.reduce((s, c) => s + c[dim.key], 0) / items.length;
      data.push([x, y, +avg.toFixed(2), items.length]);
    });
  });

  return {
    ...baseOption(),
    grid: { left: 120, right: 40, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: dims.map((d) => d.name),
      axisLabel: { color: THEME.text1, fontFamily: THEME.fontMono, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: THEME.text1, fontFamily: THEME.fontMono, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: 10,
      show: true,
      orient: 'horizontal',
      bottom: 0,
      right: 10,
      itemWidth: 12,
      itemHeight: 80,
      textStyle: { color: THEME.text2, fontFamily: THEME.fontMono, fontSize: 9 },
      inRange: {
        color: ['#2a2d34', '#5a4a3a', '#8a6b4a', '#c77d46'],
      },
    },
    tooltip: {
      ...baseOption().tooltip,
      formatter: (p) => {
        const cat = categories[p.data[1]];
        const dim = dims[p.data[0]];
        return `
          <span style="color:${THEME.accent}">${cat}</span><br/>
          ${dim.name}: <b>${p.data[2] ?? '—'}</b><br/>
          <span style="color:${THEME.text2};font-size:10px">n = ${p.data[3]}</span>
        `;
      },
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: {
          show: true,
          color: THEME.text0,
          fontFamily: THEME.fontMono,
          fontSize: 10,
          formatter: (p) => (p.data[2] == null ? '' : p.data[2].toFixed(1)),
        },
        itemStyle: { borderColor: THEME.bg, borderWidth: 2 },
      },
    ],
  };
}

/* =====================================================================
   6. CATEGORY SUNBURST (composition)
   ===================================================================== */
function sunburstOption(companies) {
  // Agrupa por categoría → estilo
  const byCat = {};
  companies.forEach((c) => {
    const cat = c.category || 'Unknown';
    const style = c.style || 'Unknown';
    if (!byCat[cat]) byCat[cat] = {};
    if (!byCat[cat][style]) byCat[cat][style] = [];
    byCat[cat][style].push(c);
  });

  const data = Object.entries(byCat).map(([cat, styles], ci) => ({
    name: cat,
    itemStyle: { color: CATEGORY_COLORS[ci % CATEGORY_COLORS.length] },
    children: Object.entries(styles).map(([style, items]) => ({
      name: style,
      value: items.length,
      itemStyle: { color: CATEGORY_COLORS[ci % CATEGORY_COLORS.length], opacity: 0.7 },
    })),
  }));

  return {
    ...baseOption(),
    tooltip: {
      ...baseOption().tooltip,
      formatter: (p) => `${p.name}: <b>${p.value}</b>`,
    },
    series: [
      {
        type: 'sunburst',
        radius: ['25%', '90%'],
        data,
        label: {
          color: THEME.text0,
          fontFamily: THEME.fontMono,
          fontSize: 10,
        },
        levels: [
          {},
          {
            r0: '25%', r: '55%',
            label: { rotate: 'tangential', fontSize: 10 },
          },
          {
            r0: '55%', r: '88%',
            label: { rotate: 'radial', fontSize: 9 },
          },
        ],
        emphasis: { focus: 'ancestor' },
      },
    ],
  };
}

/* Expose globals */
window.CHARTS = {
  quadrant: quadrantChartOption,
  irrAsymmetry: irrAsymmetryOption,
  roicVsValuation: roicVsValuationOption,
  radar: radarOption,
  heatmap: heatmapOption,
  sunburst: sunburstOption,
  fmt,
  THEME,
  QUADRANT_COLOR,
  QUADRANT_LABEL,
  CATEGORY_COLORS,
};
