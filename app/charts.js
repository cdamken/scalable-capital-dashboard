/* global Chart */
/**
 * Shared Chart.js drawing helpers for Scalable Capital (wealth + analytics).
 *
 * Self-contained: depends ONLY on the global `Chart` (vendored
 * js/vendor/chart.umd.min.js, loaded before this file by PageController).
 * No page scope, no _shared.js — so this file is byte-identical between
 * Scalable-Capital-Dashboard/app/charts.js and Scalable-Capital-owncloud/js/charts.js.
 *
 * Styling (gradient fills, axis, tooltip, easing) mirrors
 * Trade-Republic-owncloud/js/analytics.js so the three trios feel like one app.
 *
 * The render* names + signatures match the old hand-rolled SVG helpers they
 * replace, so per-page call sites (wealth.js / analytics.js) are unchanged.
 */
(function () {
  'use strict';

  // Resolve a CSS custom property (e.g. 'var(--blue)') to its computed value.
  // Chart.js needs a real color string, not the var() token.
  function cssColor(v, fallback) {
    if (typeof v === 'string' && v.indexOf('var(') === 0) {
      const name = v.slice(4, v.lastIndexOf(')')).trim();
      const got = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return got || fallback || '#00b8a9';
    }
    return v || fallback || '#00b8a9';
  }

  // Vertical gradient for area fills. Accepts #rrggbb (or #rrggbbaa).
  function vGradient(ctx, area, hex, alphaTop, alphaBottom) {
    if (!area) return hex;
    const rgb = hex.length === 9 ? hex.slice(0, 7) : hex;
    if (rgb[0] !== '#' || rgb.length < 7) return hex;
    const toRgba = (h, a) => 'rgba(' + parseInt(h.slice(1, 3), 16) + ',' +
      parseInt(h.slice(3, 5), 16) + ',' + parseInt(h.slice(5, 7), 16) + ',' + a + ')';
    const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, toRgba(rgb, alphaTop == null ? 0.28 : alphaTop));
    g.addColorStop(1, toRgba(rgb, alphaBottom == null ? 0.0 : alphaBottom));
    return g;
  }

  const AXIS_BASE = {
    grid: { color: 'rgba(255,255,255,0.04)', drawTicks: false, tickLength: 0 },
    border: { display: false },
    ticks: { color: '#7a8599', font: { size: 12, weight: '500' }, padding: 8 },
  };
  const TOOLTIP = {
    backgroundColor: 'rgba(15, 20, 25, 0.95)',
    titleColor: '#e8eef5', titleFont: { size: 12, weight: '600' },
    bodyColor: '#e8eef5', bodyFont: { size: 13 },
    padding: 12, borderColor: 'rgba(255,255,255,0.08)', borderWidth: 1,
    cornerRadius: 8, displayColors: true, boxPadding: 6,
  };
  const ANIMATION = { duration: 700, easing: 'easeOutQuart' };

  const fmtEUR = (n) => (n == null || isNaN(n)) ? '—' : new Intl.NumberFormat('en-US',
    { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  const fmtLabelDate = (iso) => {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso)
      : d.toLocaleDateString('en-GB', { year: '2-digit', month: 'short', day: '2-digit' });
  };

  // Destroy any chart bound to this canvas before re-rendering (range pills).
  function freshCanvas(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const existing = (Chart.getChart ? Chart.getChart(el) : null);
    if (existing) existing.destroy();
    return el;
  }

  // ---- Single line (area + gradient). Signature matches the old SVG helper:
  //   renderLineChart(canvasId, series, getValue, fmtTick, color, opts)
  //   series: [{date, ...}]  getValue(item)->number  fmtTick(v)->string
  function renderLineChart(canvasId, series, getValue, fmtTick, color, opts) {
    opts = opts || {};
    const el = freshCanvas(canvasId);
    if (!el || typeof Chart === 'undefined') return;
    const col = cssColor(color);
    const labels = (series || []).map(s => fmtLabelDate(s.date));
    const data = (series || []).map(s => Number(getValue(s)));
    const fmtY = fmtTick || ((v) => v);
    new Chart(el, {
      type: 'line',
      data: { labels, datasets: [{
        data, borderColor: col, borderWidth: 2, tension: 0.3,
        pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: col,
        pointBorderColor: '#0f1419', pointBorderWidth: 2,
        fill: true,
        backgroundColor: (c) => vGradient(c.chart.ctx, c.chart.chartArea, col, 0.25, 0.0),
      }] },
      options: {
        maintainAspectRatio: false, animation: ANIMATION,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { ...TOOLTIP, callbacks: { label: (ctx) => ' ' + fmtY(ctx.parsed.y) } },
        },
        scales: {
          y: { ...AXIS_BASE, ...(opts.isPct ? { suggestedMin: 0 } : {}),
               ticks: { ...AXIS_BASE.ticks, callback: (v) => fmtY(v) } },
          x: { ...AXIS_BASE, grid: { display: false },
               ticks: { ...AXIS_BASE.ticks, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 } },
        },
      },
    });
  }

  // ---- Two lines: main (solid value, gradient) + reference (dashed capital).
  //   renderTwoLineChart(canvasId, mainSeries, refSeries)
  //   mainSeries: [{date, valuation}]   refSeries: [{date, value}]
  function renderTwoLineChart(canvasId, mainSeries, refSeries) {
    const el = freshCanvas(canvasId);
    if (!el || typeof Chart === 'undefined') return;
    const blue = cssColor('var(--blue)');
    const muted = cssColor('var(--muted)', '#7a8599');
    const labels = (mainSeries || []).map(s => fmtLabelDate(s.date));
    const mainData = (mainSeries || []).map(s => Number(s.valuation) || 0);
    const refByDate = {};
    (refSeries || []).forEach(s => { refByDate[s.date] = Number(s.value) || 0; });
    const refData = (mainSeries || []).map(s => (s.date in refByDate ? refByDate[s.date] : null));
    new Chart(el, {
      type: 'line',
      data: { labels, datasets: [
        { label: 'Portfolio value', data: mainData, borderColor: blue, borderWidth: 2,
          tension: 0.3, pointRadius: 0, pointHoverRadius: 5, pointBackgroundColor: blue,
          pointBorderColor: '#0f1419', pointBorderWidth: 2, fill: true,
          backgroundColor: (c) => vGradient(c.chart.ctx, c.chart.chartArea, blue, 0.22, 0.0) },
        { label: 'Capital invested', data: refData, borderColor: muted, borderWidth: 1.5,
          borderDash: [6, 4], tension: 0, pointRadius: 0, pointHoverRadius: 4,
          fill: false, spanGaps: true },
      ] },
      options: {
        maintainAspectRatio: false, animation: ANIMATION,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, labels: { color: '#e8eef5', font: { size: 12, weight: '500' },
                    usePointStyle: true, pointStyle: 'rectRounded', padding: 12 } },
          tooltip: { ...TOOLTIP, callbacks: {
            label: (ctx) => ' ' + (ctx.dataset.label || '') + ': ' + fmtEUR(ctx.parsed.y) } },
        },
        scales: {
          y: { ...AXIS_BASE, ticks: { ...AXIS_BASE.ticks, callback: (v) => fmtEUR(v) } },
          x: { ...AXIS_BASE, grid: { display: false },
               ticks: { ...AXIS_BASE.ticks, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 } },
        },
      },
    });
  }

  // Draws the value above each bar (Chart.js has no built-in datalabels).
  const barValueLabels = {
    id: 'scBarValueLabels',
    afterDatasetsDraw: (chart) => {
      const { ctx } = chart;
      const meta = chart.getDatasetMeta(0);
      if (!meta || meta.hidden) return;
      ctx.save();
      ctx.fillStyle = '#e8eef5';
      ctx.font = '600 12px system-ui';
      ctx.textAlign = 'center';
      meta.data.forEach((bar, i) => {
        const v = chart.data.datasets[0].data[i];
        if (v == null) return;
        ctx.fillText(fmtEUR(v), bar.x, bar.y - 8);
      });
      ctx.restore();
    },
  };

  // ---- Bar chart from a {key: value} map (sorted by key). Money y-axis,
  // value label above each bar. Signature matches the old SVG helper.
  function renderBarChart(canvasId, byKey) {
    const el = freshCanvas(canvasId);
    if (!el || typeof Chart === 'undefined') return;
    const keys = Object.keys(byKey || {}).sort();
    const values = keys.map(k => Number(byKey[k]) || 0);
    const blue = cssColor('var(--blue)');
    new Chart(el, {
      type: 'bar',
      data: { labels: keys, datasets: [{
        data: values, borderRadius: 6, maxBarThickness: 120, borderWidth: 0,
        backgroundColor: (c) => vGradient(c.chart.ctx, c.chart.chartArea, blue, 0.95, 0.45),
      }] },
      options: {
        maintainAspectRatio: false, animation: ANIMATION,
        layout: { padding: { top: 22 } },
        plugins: {
          legend: { display: false },
          tooltip: { ...TOOLTIP, callbacks: { label: (ctx) => ' ' + fmtEUR(ctx.parsed.y) } },
        },
        scales: {
          y: { ...AXIS_BASE, beginAtZero: true,
               ticks: { ...AXIS_BASE.ticks, callback: (v) => fmtEUR(v) } },
          x: { ...AXIS_BASE, grid: { display: false },
               ticks: { ...AXIS_BASE.ticks, maxRotation: 0, autoSkip: false } },
        },
      },
      plugins: [barValueLabels],
    });
  }

  // ---- Doughnut with a centered TOTAL. labels/values/colors are parallel.
  function scDonut(canvasId, labels, values, colors) {
    const el = freshCanvas(canvasId);
    if (!el || typeof Chart === 'undefined') return;
    const total = (values || []).reduce((s, v) => s + (Number(v) || 0), 0);
    new Chart(el, {
      type: 'doughnut',
      data: { labels: labels || [], datasets: [{
        data: values || [], backgroundColor: colors || [],
        borderColor: '#0f1419', borderWidth: 2 }] },
      options: {
        maintainAspectRatio: false, animation: ANIMATION, cutout: '66%',
        plugins: {
          legend: { display: false },
          tooltip: { ...TOOLTIP, callbacks: { label: (ctx) => ' ' + ctx.label + ': ' +
            fmtEUR(ctx.parsed) + ' (' + (total ? (ctx.parsed / total * 100).toFixed(1) : 0) + '%)' } },
        },
      },
      plugins: [{
        id: 'scDonutCenter',
        afterDraw: (chart) => {
          const area = chart.chartArea;
          if (!area) return;
          const ctx = chart.ctx;
          const cx = (area.left + area.right) / 2, cy = (area.top + area.bottom) / 2;
          ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillStyle = '#7a8599'; ctx.font = '600 10px system-ui';
          ctx.fillText('TOTAL', cx, cy - 9);
          ctx.fillStyle = '#e8eef5'; ctx.font = '700 15px system-ui';
          ctx.fillText(fmtEUR(total), cx, cy + 8);
          ctx.restore();
        },
      }],
    });
  }

  // ---- Stepped "net capital committed" line + optional dashed reference
  // (today's market value). series: [{date: Date|string, value: number}].
  function scStepLine(canvasId, series, refValue) {
    const el = freshCanvas(canvasId);
    if (!el || typeof Chart === 'undefined') return;
    const blue = cssColor('var(--blue)');
    const green = cssColor('var(--green)', '#4ade80');
    const labels = (series || []).map(s =>
      fmtLabelDate(s.date instanceof Date ? s.date.toISOString() : s.date));
    const data = (series || []).map(s => Number(s.value) || 0);
    const datasets = [{
      label: 'Net capital committed', data, borderColor: blue, borderWidth: 2,
      stepped: true, pointRadius: 0, pointHoverRadius: 4, fill: true,
      backgroundColor: (c) => vGradient(c.chart.ctx, c.chart.chartArea, blue, 0.18, 0.0),
    }];
    if (refValue != null && data.length) {
      datasets.push({
        label: 'Market value (today)', data: data.map(() => Number(refValue)),
        borderColor: green, borderWidth: 1.5, borderDash: [5, 4],
        pointRadius: 0, pointHoverRadius: 0, fill: false,
      });
    }
    new Chart(el, {
      type: 'line', data: { labels, datasets },
      options: {
        maintainAspectRatio: false, animation: ANIMATION,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: datasets.length > 1, labels: { color: '#e8eef5',
            font: { size: 12, weight: '500' }, usePointStyle: true, pointStyle: 'rectRounded', padding: 12 } },
          tooltip: { ...TOOLTIP, callbacks: {
            label: (ctx) => ' ' + (ctx.dataset.label || '') + ': ' + fmtEUR(ctx.parsed.y) } },
        },
        scales: {
          y: { ...AXIS_BASE, ticks: { ...AXIS_BASE.ticks, callback: (v) => fmtEUR(v) } },
          x: { ...AXIS_BASE, grid: { display: false },
               ticks: { ...AXIS_BASE.ticks, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } },
        },
      },
    });
  }

  // Expose globally (per-page scripts call these by name).
  window.renderLineChart = renderLineChart;
  window.renderTwoLineChart = renderTwoLineChart;
  window.renderBarChart = renderBarChart;
  window.scDonut = scDonut;
  window.scStepLine = scStepLine;
  window.scCssColor = cssColor;
  window.scVGradient = vGradient;
  window.SC_AXIS_BASE = AXIS_BASE;
  window.SC_TOOLTIP = TOOLTIP;
  window.SC_ANIMATION = ANIMATION;
})();
