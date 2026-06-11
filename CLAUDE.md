# CLAUDE.md — Scalable-Capital-Dashboard

> Context for AI assistants. Humans: see [README.md](README.md).
> **Read [`../TR-GBM-Project/`](../TR-GBM-Project/) docs before doing anything.**
> This dashboard inherits every convention from `gbm-dashboard` and
> `Trade-Republic-Dashboard`.

## ⚠️ HARD RULES — re-read before EVERY UI change

1. **ALL UI strings MUST be in English.** Labels, buttons, headers, toasts,
   alerts, error messages, help text, table column headers, tab names,
   page titles — everything user-facing. No Spanish. Spanish is ONLY for
   GBM (different audience). Scalable matches TR (English).
   - Carlos called this out twice in 2026-06-06 ("desde un principio
     dije que la página tenía que ser en inglés"). Don't be the third
     time.
   - If you find yourself typing "Configuración"/"Aprueba"/"Actualizar",
     stop. Use Settings/Approve/Update Now.
   - See `feedback_sc_ui_english.md` in user memory.

2. **NO `backdrop-filter: blur()` on modal scrims.** Plain darkened
   rgba only. Inherited rule. See `feedback_no_backdrop_blur` in memory.

3. **NO light theme.** Dark by default, period.

4. **P&L only green/red.** No other status colors compete with profit/loss.

(End of hard rules — everything below is context, not law.)

## What this is

Local, single-user dashboard for a Scalable Capital portfolio (Broker +
Wealth roboadvisor in one view). Plays the same role as
`Trade-Republic-Dashboard` and `gbm-dashboard` in their respective trios.

**Upstream library:** [`sc-api`](../sc-api/) (Python). All data fetching
goes through it. Don't talk to Scalable directly from this repo.

## Position in the family

Third trio alongside [[project-tr-trio]] and the GBM trio:

```
sc-api  (Python lib, upstream)
   ↓
Scalable-Capital-Dashboard (this repo, single-user)
   ↓ port verbatim + minimal patches (see TR-GBM-Project/OWNCLOUD-PATCHES.md)
Scalable-Capital-owncloud (multi-user ownCloud 10 port)
```

## Unification policy

Carlos has ONE brain operating THREE dashboards (TR, GBM, SC). Asymmetric
chrome forces context-switch tax every time he switches. Per
[`../TR-GBM-Project/UNIFICATION.md`](../TR-GBM-Project/UNIFICATION.md),
where the underlying data allows, the three apps should feel like **the
same app dressed for three markets**.

Specifically:

| Surface | Rule |
|---|---|
| Cockpit / KPI cards | Same shape, same order, same metrics where the data exists. |
| Top-bar chrome | Brand left · tabs centered · Update right. Same `_shared.js`-injected pattern. |
| Staleness chip | Same colors (fresh/warn/stale), same thresholds (15 min / 24 h), same tooltip behavior. |
| Concentration warnings | Same thresholds (30% / 70% top-5 → amber; 50% / 85% → red). |
| Modal patterns | MFA, config, progress overlay — same DOM shape, same UX flow. |
| Glossary terms | Shared concepts (XIRR, cost basis, dividend forecast, concentration) phrased the same way. |
| **No `backdrop-filter: blur(…)` on scrims** | Solid `rgba(15, 20, 25, 0.92)` only. Top-bar header blur OK. |

Where SC genuinely differs (and divergence IS justified):

- **One account model, two products.** Like TR, Scalable is one login —
  but with two product surfaces (Broker self-directed + Wealth roboadvisor).
  Cockpit should show both with a per-product badge/filter, not as two
  separate accounts like GBM.
- **Push 2FA, no TOTP.** The MFA modal is "Approve in your phone" with a
  poll for confirmation, not "Type your 6-digit code." See "MFA flow" below.
- **No CSV-export round-trip.** Scalable has a native CSV export which we
  use as ground-truth during development. The dashboard exposes its own
  CSV export anyway for consistency with TR/GBM.

## Page plan (mirrors TR + GBM — tab order matches TR exactly)

1. **Portfolio** — holdings, allocation, totals (Broker + Wealth combined,
   per-product badge so user can distinguish)
2. **Analytics** — XIRR, time-weighted return, concentration warnings, net
   worth line, ring chart, dividends bar
3. **📋 Orders** — order history, status, venue
4. **💰 Dividends** — dividend events, forward dividends, bars by year
5. **📒 Ledger** — full cash ledger (deposits, withdrawals, interest)
6. **🏦 Wealth** — roboadvisor portfolio detail: TWR over time + Portfolio
   value vs capital invested (deposit-step overlay), asset class breakdown,
   ETF allocations, wealth-only transactions
7. **📖 Glossary** — term reference (port verbatim from GBM/TR glossary
   where concepts overlap)
8. **⚙ Settings** — credentials save (no auth call), data wipe, session
   reset, version info

## Design system

Follow [`../TR-GBM-Project/DESIGN-SYSTEM.md`](../TR-GBM-Project/DESIGN-SYSTEM.md)
exactly. Base palette is shared:

```css
:root {
  --bg:     #0f1419;   /* fondo principal */
  --card:   #1a1f2e;   /* cards / panels */
  --border: #2a3142;   /* separadores */
  --text:   #e8eef5;   /* texto principal */
  --muted:  #7a8599;   /* texto secundario / labels */
  --green:  #4ade80;   /* P&L positivo */
  --red:    #f87171;   /* P&L negativo */
  --amber:  #fbbf24;   /* warning */
}
```

**Scalable brand-adjacent accent (TBD)** — Scalable corporate identity is
white + dark green. Likely `--blue` replaced by a Scalable-green:

```css
:root {
  --blue: #00373d;    /* Scalable dark green (placeholder — verify against brand) */
  /* Or a teal in the same family: #00b8a9 (already used as GBM accent-teal) */
}
```

Hard rules (inherited, non-negotiable):
1. **NO `backdrop-filter: blur()`** on modal/overlay scrims.
2. **NO light theme.**
3. **P&L only green/red.**
4. **Tabs activas con accent del broker.**
5. **System fonts only**, tabular numbers in numeric columns.

## MFA flow (push approval, not TOTP)

Pattern adapted from
[`../TR-GBM-Project/TECHNICAL-PATTERNS.md#1`](../TR-GBM-Project/TECHNICAL-PATTERNS.md).
For Scalable the modal asks the user to **approve a push notification**
on their phone, then we poll for state. No 6-digit input.

```
1. Client → POST /update (no MFA payload)        ─►  Backend probe
2. Backend: cookies fresh?         yes → 200 OK
                                   no  → exit 10 mfa_required
3. Client opens modal: "Approve in your Scalable app"
4. Client → POST /update {await_push: true}
5. Backend triggers push, polls Scalable for confirmation
6. Backend: confirmed?   yes → exit 0
                         no  → exit 11 mfa_invalid (timed out / declined)
```

Toast UI pattern #6 + null-safe `on()` helper #10 from the technical
patterns doc are mandatory. The 200 ms defensive poll (pattern #7) is
not needed since there's no input field.

## Endpoint surface (server.py — mirrors gbm-dashboard)

```
GET  /                  → 302 to /app/index.html
GET  /app/*             → static files
GET  /DATA/*            → JSON / CSV outputs
404 on any directory listing

GET  /config            → returns email (no password)
POST /config            → save email + password (mode 0600)
GET  /settings          → days-back ranges + version info
POST /settings          → save ranges
POST /update            → fetch + write DATA/*.json (push approval optional)
POST /reset             → full session wipe (cookie jar + push session)
GET  /export/transactions.csv  → consistent CSV format
GET  /progress          → SSE / poll endpoint for update progress
```

Same CSRF Origin check on POSTs as TR/GBM. `BIND_HOST=127.0.0.1` by
default (Carlos can flip to LAN if he wants phone access — same trade-off
as TR).

## Storage

```
PROJECT_DIR/
├── app/                      ← HTML + JS + CSS
│   └── .env                  ← creds (gitignored, mode 0600)
├── DATA/                     ← gitignored
│   ├── portfolio.json
│   ├── transactions.json
│   ├── dividends.json
│   └── analytics.json
└── scripts/
    └── deploy.sh             ← 3-pillar deploy (only used when porting to ownCloud)

~/.sc-api/
└── session.json              ← cookies, mode 0600
```

## Settings page — credentials, not auth

UNLIKE the first scaffold draft: Settings has a **"Save credentials"**
button that just persists email+password to `~/.sc-api/profiles/<email>/
credentials.json` (mode 0600). It does NOT trigger login.

Push approval happens **lazily on Update Now**: when fetch detects stale
cookies, it reads stored credentials and triggers Scalable's push 2FA.
User approves on phone, fetch continues. This matches TR/GBM.

Four sections on Settings: 👤 Account · 🔐 Session · 💾 Data · ℹ️ About.

## Status (2026-06-11) — shipped

✅ **All 8 pages live with real data.** Working against Carlos's account
(€2,360.82 Broker + €5,674.80 Wealth "Avoid poverty" + €0 cancelled
"For The Beach" = €8,035.62 total). Implemented:

- Programmatic Auth0 login + push 2FA approval (no Chrome required)
- 22+ verbatim GraphQL operations against `/cockpit/graphql`
- Auto-relogin on stale cookies via stored credentials
- Wealth detail: TWR + value-vs-capital with deposit overlay + range pills
- CSV export endpoints for orders/ledger/dividends/holdings/wealth
- UTC timestamps everywhere (no more "120m ago" CEST drift bug)
- Canonical Update Now (toast + try/catch/finally) on every page

Still pending (BACKLOG): WebSocket realtime quotes, scheduled
auto-update daemon, benchmark replay in Analytics.
