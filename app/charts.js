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

  // Expose globally (per-page scripts call these by name).
  window.renderLineChart = renderLineChart;
  window.renderTwoLineChart = renderTwoLineChart;
  window.scCssColor = cssColor;
  window.scVGradient = vGradient;
  window.SC_AXIS_BASE = AXIS_BASE;
  window.SC_TOOLTIP = TOOLTIP;
  window.SC_ANIMATION = ANIMATION;
})();
