"""Fetch Scalable Capital portfolio data via sc-api and write DATA/*.json.

Invoked by `server.py` on POST /update. Mirrors the role of
`Trade-Republic-Dashboard/app/tr_fetch.py` but talks to Scalable.

Exit codes (canonical, mirrored across the trio + GBM trio):
   0  EXIT_OK           — success, data written
  10  EXIT_MFA_REQUIRED — cookies dead, user must re-import from Chrome
                          (Scalable's 2FA is push-only; we can't drive it)
  12  EXIT_AUTH_FAILED  — explicit auth refusal (rare; usually surfaces as 10)
  20  EXIT_API_ERROR    — Scalable returned 5xx / unexpected payload
  30  EXIT_CONFIG_ERROR — sc-api not installed, profile missing, etc.

Usage:
    python sc_fetch.py [--email <addr>] [--portfolio-id <id>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_MFA_REQUIRED = 10
EXIT_MFA_INVALID = 11
EXIT_AUTH_FAILED = 12
EXIT_API_ERROR = 20
EXIT_TIMEOUT = 21
EXIT_CONFIG_ERROR = 30

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "DATA"
LAST_UPDATE_FILE = DATA_DIR / "last_update.date"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=None,
                        help="Profile email (default: active profile)")
    parser.add_argument("--portfolio-id", default=None,
                        help="Override portfolio_id (default: first one on profile)")
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="Where to write *.json files")
    args = parser.parse_args(argv)

    try:
        import sc_api
        from sc_api import ScalableClient, profiles
        from sc_api import identity
        from sc_api.exceptions import (
            SessionExpired, MissingSessionCookies, NoActiveProfile,
            ProfileNotFound, ApiError,
        )
    except ImportError as e:
        _log(f"sc-api not installed: {e}")
        return EXIT_CONFIG_ERROR

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # ---- profile + identity ----
    try:
        prof = profiles.load(args.email) if args.email else profiles.get_active()
    except (NoActiveProfile, ProfileNotFound) as e:
        _log(str(e))
        return EXIT_CONFIG_ERROR

    # Auto-relogin helper. Catches SessionExpired anywhere downstream and
    # retries the operation after a fresh login (push approval on user's
    # phone). Mirrors what tr-api / gbm-mx-api do: stored creds + one tap
    # on phone = full auto-refresh, no manual return-to-Settings.
    def _auto_relogin() -> bool:
        creds = profiles.load_credentials(prof)
        if not creds:
            _log("No stored credentials — can't auto-relogin. "
                 "Go to Settings → log in again.")
            return False
        _log("📱 Cookies expired — triggering push approval, please approve on your phone...")
        try:
            from sc_api import auth as _auth, cookies as _cookies_mod
            result = _auth.login_flow(
                email=creds["email"],
                password=creds["password"],
                device_type="Mac OS", device_name="Chrome",
            )
            cookies_dict = {c.name: c.value for c in result.cookies
                            if c.domain and "scalable.capital" in c.domain}
            _cookies_mod.save_to_file(cookies_dict, prof.cookies_file)
            _log(f"Relogin OK — {len(cookies_dict)} cookies refreshed.")
            return True
        except Exception as e:
            _log(f"Auto-relogin failed: {type(e).__name__}: {e}")
            return False

    try:
        client = ScalableClient.from_profile(prof)
    except MissingSessionCookies as e:
        _log(str(e))
        # Try auto-relogin even if cookies are completely gone
        if _auto_relogin():
            try:
                client = ScalableClient.from_profile(prof)
            except MissingSessionCookies as e2:
                _log(str(e2))
                return EXIT_MFA_REQUIRED
        else:
            return EXIT_MFA_REQUIRED

    # Discover portfolioId on first run.
    if not prof.portfolio_ids:
        try:
            ident = identity.discover_and_persist(client)
            _log(f"discovered portfolios: {ident.portfolio_ids}, savings: {ident.savings_ids}")
            prof = profiles.load(prof.email)  # reload with persisted IDs
            client = ScalableClient.from_profile(prof)
        except SessionExpired as e:
            _log(str(e))
            return EXIT_MFA_REQUIRED
        except ApiError as e:
            _log(f"discovery failed: {e}")
            return EXIT_API_ERROR

    portfolio_id = args.portfolio_id or prof.default_portfolio_id
    if not portfolio_id:
        _log("No portfolio_id available — discovery returned empty.")
        return EXIT_API_ERROR

    # ---- fetch + write ----
    try:
        _log(f"fetching broker snapshot for portfolio_id={portfolio_id[:12]}...")
        snap = sc_api.portfolio.snapshot(client, portfolio_id=portfolio_id)
        _write_json(data_dir / "inventory.json", snap["inventory"])
        _write_json(data_dir / "cash.json", snap["cash"])
        _write_json(data_dir / "interest.json", snap["interest"])
        _write_json(data_dir / "crypto.json", snap["crypto"])
        _write_json(data_dir / "pending_orders.json", {"count": snap["pending_orders"]})

        _log("fetching watchlist...")
        wl = sc_api.portfolio.watchlist(client, portfolio_id=portfolio_id)
        _write_json(data_dir / "watchlist.json", wl)

        _log("fetching ALL transactions (paginated)...")
        all_tx = sc_api.transactions.fetch_all(
            client, portfolio_id=portfolio_id, page_size=100,
            max_pages=100,  # safety cap — 10,000 tx max
        )
        # Shape matches what the old fetch_page() returned (cursor/total + items)
        # so the dashboard JS doesn't need to change.
        _write_json(data_dir / "transactions.json", {
            "cursor": None, "total": len(all_tx), "transactions": all_tx,
        })

        # Wealth portfolios — re-discover so we get fresh valuations every fetch.
        _log("fetching wealth portfolios + broker overview (discovery)...")
        ident = identity.discover(client)
        wealth_payload = [
            {
                "id": p.id, "name": p.name,
                "custodian": p.custodian, "portfolio_type": p.portfolio_type,
                "funded": p.funded, "invested": p.invested,
                "valuation": p.valuation,
                "risk_category": p.risk_category, "risk_level": p.risk_level,
            }
            for p in ident.wealth_portfolios
        ]
        _write_json(data_dir / "wealth.json", wealth_payload)

        # Wealth detail — composition + history per Wealth portfolio.
        # Cheap: one batched GraphQL call for ALL wealth portfolios at once.
        if ident.wealth_portfolios:
            _log("fetching wealth detail (history + allocation per portfolio)...")
            try:
                wealth_details = sc_api.wealth.fetch_all_detail(client)
                _write_json(data_dir / "wealth_detail.json", wealth_details)
            except ApiError as e:
                _log(f"wealth detail fetch failed (non-fatal): {e}")
        broker_overview = [
            {
                "id": p.id, "name": p.name,
                "custodian_bank": p.custodian_bank,
                "valuation": p.valuation,
                "crypto_valuation": p.crypto_valuation,
                "pending_orders": p.pending_orders,
            }
            for p in ident.broker_portfolios
        ]
        _write_json(data_dir / "broker_overview.json", broker_overview)

        # Savings — best-effort, may not exist.
        if prof.savings_ids:
            try:
                _log("fetching Tagesgeld overview...")
                _write_json(
                    data_dir / "savings.json",
                    sc_api.savings.overview(client),
                )
                _write_json(
                    data_dir / "savings_transactions.json",
                    sc_api.savings.transactions(client),
                )
            except ApiError as e:
                _log(f"savings fetch failed (non-fatal): {e}")

        LAST_UPDATE_FILE.write_text(
            time.strftime("%Y-%m-%d %H:%M:%S\n"),
            encoding="utf-8",
        )
        _log("OK")
        return EXIT_OK

    except SessionExpired as e:
        _log(f"Mid-fetch SessionExpired: {e}")
        # Auto-relogin and retry the whole fetch ONCE
        if not _auto_relogin():
            return EXIT_MFA_REQUIRED
        _log("Retrying fetch after auto-relogin...")
        try:
            client = ScalableClient.from_profile(prof)
        except MissingSessionCookies:
            return EXIT_MFA_REQUIRED
        try:
            snap = sc_api.portfolio.snapshot(client, portfolio_id=portfolio_id)
            _write_json(data_dir / "inventory.json", snap["inventory"])
            _write_json(data_dir / "cash.json", snap["cash"])
            _write_json(data_dir / "interest.json", snap["interest"])
            _write_json(data_dir / "crypto.json", snap["crypto"])
            _write_json(data_dir / "pending_orders.json", {"count": snap["pending_orders"]})
            _write_json(data_dir / "watchlist.json",
                        sc_api.portfolio.watchlist(client, portfolio_id=portfolio_id))
            tx_all = sc_api.transactions.fetch_all(
                client, portfolio_id=portfolio_id, page_size=100, max_pages=100,
            )
            _write_json(data_dir / "transactions.json",
                        {"cursor": None, "total": len(tx_all), "transactions": tx_all})
            ident = identity.discover(client)
            _write_json(data_dir / "wealth.json", [
                {"id": p.id, "name": p.name, "custodian": p.custodian,
                 "portfolio_type": p.portfolio_type, "funded": p.funded,
                 "invested": p.invested, "valuation": p.valuation,
                 "risk_category": p.risk_category, "risk_level": p.risk_level}
                for p in ident.wealth_portfolios
            ])
            _write_json(data_dir / "broker_overview.json", [
                {"id": p.id, "name": p.name, "custodian_bank": p.custodian_bank,
                 "valuation": p.valuation, "crypto_valuation": p.crypto_valuation,
                 "pending_orders": p.pending_orders}
                for p in ident.broker_portfolios
            ])
            if ident.wealth_portfolios:
                _write_json(data_dir / "wealth_detail.json",
                            sc_api.wealth.fetch_all_detail(client))
            LAST_UPDATE_FILE.write_text(
                time.strftime("%Y-%m-%d %H:%M:%S\n"), encoding="utf-8",
            )
            _log("OK (after auto-relogin)")
            return EXIT_OK
        except SessionExpired:
            _log("SessionExpired even after relogin — giving up")
            return EXIT_MFA_REQUIRED
        except ApiError as e:
            _log(f"api error after relogin: {e}")
            return EXIT_API_ERROR
    except ApiError as e:
        _log(f"api error: {e}")
        return EXIT_API_ERROR


def _write_json(path: Path, data: object) -> None:
    """Atomic write: tmp → fsync → rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


def _log(msg: str) -> None:
    print(f"[sc_fetch] {msg}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
