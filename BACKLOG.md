# Scalable Capital Dashboard — Backlog

> Cross-repo context: [`../TR-GBM-Project/BACKLOG.md`](../TR-GBM-Project/BACKLOG.md)
> Hard rules: see [CLAUDE.md](CLAUDE.md) "⚠️ HARD RULES" section.

## ✅ Done (2026-06-07/08, Wealth + per-page CSV + Apollo cache discovery)

- **Wealth detail page** — `app/wealth.html` with picker between portfolios,
  4 KPIs (current value / TWR since inception / contributions / fees),
  asset-class allocation ring chart, TWR-over-time line chart, valuation
  history line chart, ETFs table, recent transactions table.
- New `sc_api/wealth.py` + `WEALTH_PORTFOLIO_DETAIL` query (discovered via
  Apollo cache inspection on live cockpit, not from HAR). Fields:
  `valuationHistory`, `timeWeightedReturnHistory`, `latestAllocation`
  (with `eftAllocations` — note Scalable's typo), `transactions`.
  Confirmed against Carlos's account: "Avoid poverty" TWR +24.96% since
  2025-06-29 inception, 344 daily valuations, 90.26% EQUITIES / 9.49%
  COMMODITIES / 0.25% CASH.
- Tab order matches TR pattern: Portfolio · Analytics · 📋 Orders ·
  💰 Dividends · 📒 Ledger · 🏦 Wealth · 📖 Glossary · ⚙ Settings.
- Per-page CSV exports (`/export/orders.csv` / `ledger.csv` / `dividends.csv`
  / `holdings.csv` / `wealth.csv`). Idea proposed back to TR + GBM backlogs.
- Full-pagination transactions (100 → 284 items in current dataset).
- Forward dividend forecast on Dividends page (heuristic: last-12-months × 1.0).
- Temporary `/ingest_wealth_detail` endpoint added to server.py for the
  MCP-Chrome→localhost side-channel pattern; works but turned out unnecessary
  (sc-api auth import picks up fresh cookies from Chrome SQLite). Keep as
  defensive fallback for headless scenarios.

## ✅ Done (2026-06-06)

- sc-api programmatic Auth0 + push 2FA login (no Chrome)
- Discovery: Broker + Wealth in one batched call
- Cookie dedupe defensive against `.scalable.capital` vs `de.scalable.capital` duplication
- **Portfolio page** — KPIs (Total / Cash / Securities / Wealth) + Wealth table + Broker Holdings
  - search box, click-to-sort columns, position detail modal on row click,
    concentration warnings (top-1 ≥50%, top-5 ≥70%)
- **Orders page** — security transactions with side/status/type filters + search + 4 KPIs
- **Ledger page** — cash movements with type filter + 5 KPIs (in/out/distributions/net/count)
- **Dividends page** — distributions filtered, by-year SVG bar chart, by-security totals
- **Analytics page** — XIRR (Newton-Raphson), TWR table by timeframe, ring chart allocation,
  dividends bar by year, net capital committed line chart over time
- **Glossary page** — Scalable-specific terms (WORLD_GOLD, FRANZ, riskLevel, order lifecycle,
  cash transaction types, performance metrics, identifiers)
- **Settings page** — Account / Session / Data / About (English UI)
- Full 7-tab navigation across all pages, dashboard.sh hardened (no `set -e` silent aborts)

## 🚧 Next steps

All 6 main pages exist. Refinements that came out of the build:

- [ ] **Full-pagination transactions** — `sc_fetch.py` only pulls the first
      page (100 items). With more history, XIRR + Analytics need a full
      load. Add cursor pagination in sc_fetch.
- [ ] **Forward dividend forecast** — based on holdings' historical
      distribution frequency. Best-effort projection on Dividends page.
- [ ] **Benchmark replay** on Analytics — pick MSCI World (Scalable's
      defaultish) and replay user's deposits against it for comparison.
- [ ] **Wealth detail page** — currently we just show top-level Wealth
      KPIs. To drill into a Wealth portfolio's composition, we'd need a
      new HAR capture from clicking into a Wealth portfolio in the
      cockpit, then add the relevant GraphQL operation.
- [ ] **CSV export** — already in BACKLOG; one button per page.
- [ ] **`personOverview` query fix** — current short version 400s. Use
      the full 1042-char version from `discovery/operations.json` to get
      countries + locale + personalDetails properly.

## 🛠 Infrastructure

- [ ] Auto-refresh of sc-api session (keepalive every N seconds against `/cockpit/graphql`)
  to keep cookies alive indefinitely without re-login
- [ ] Background daemon mode for sc_fetch (run every X minutes)
- [ ] Full-pagination support in transactions fetch (current: only first page)
- [ ] Holdings refresh via WebSocket realtime quotes (`realTimeQuoteTicks`)

## 📋 Deferred / open questions

- [ ] Detailed Wealth holdings — composition of the fund inside each Wealth portfolio.
      Need a fresh HAR with navigation into a Wealth portfolio detail page.
- [ ] PDF documents download — `documents[]` field exists on transaction details;
      need to map `/broker/api/download/<slug>` actually delivers PDFs.
- [ ] Real `personOverview` query — current one is simplified and 400s. Use the
      full ~1042-char version from `discovery/operations.json` if needed.
- [ ] Savings (Tagesgeld) discovery — `OvernightOverview` query exists in
      `_queries.py` but we don't auto-discover savings IDs yet.

## ⚙️ Workflow per page

1. Update this BACKLOG with detailed sub-items
2. Build the HTML page (English UI strings per HARD RULES)
3. Add nav tab to top-bar in ALL existing pages (index, settings, plus the new one)
4. Update `app/sc_fetch.py` if the page needs new data files
5. Test against live data with `./dashboard.sh restart` + Cmd+Shift+R
6. Move item to "Done" section above with date
