"""Local HTTP server for the Scalable Capital Dashboard.

Mirrors `Trade-Republic-Dashboard/app/server.py` shape: stdlib http.server
binding to localhost:8087 by default (TR=8085, GBM=8086, SC=8087 → so all
three trios can run in parallel during development).

Endpoints:
    GET  /, /app                  → 302 to /app/index.html
    GET  /app/*, /DATA/*          → static files (404 on directory listing)
    GET  /setup_status            → { configured, email }
    POST /setup                   → save { email } and run cookie import
    POST /update                  → run sc_fetch.py, return { status, ... }
    POST /reset                   → clear DATA/ and active profile
    GET  /progress                → server-sent progress

CSRF: Origin header check on every POST (must be http://localhost:<PORT>
or http://127.0.0.1:<PORT>). Other origins get 403.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_DIR / "app"
DATA_DIR = PROJECT_DIR / "DATA"
SC_FETCH = APP_DIR / "sc_fetch.py"

BIND_HOST = os.environ.get("SC_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("SC_DASHBOARD_PORT", "8087"))

# Exit codes mirrored from sc_fetch.py — keep in sync.
EXIT_OK = 0
EXIT_MFA_REQUIRED = 10
EXIT_MFA_INVALID = 11
EXIT_AUTH_FAILED = 12
EXIT_API_ERROR = 20
EXIT_TIMEOUT = 21
EXIT_CONFIG_ERROR = 30

EXIT_TO_STATUS = {
    EXIT_OK: "ok",
    EXIT_MFA_REQUIRED: "auth_required",
    EXIT_MFA_INVALID: "mfa_invalid",
    EXIT_AUTH_FAILED: "auth_failed",
    EXIT_API_ERROR: "api_error",
    EXIT_TIMEOUT: "timeout",
    EXIT_CONFIG_ERROR: "config_error",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ScalableDashboard/0.0.1"

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path

        if path in ("/", "/app", "/app/"):
            return self._redirect("/app/index.html")
        if path == "/setup_status":
            return self._handle_setup_status()
        if path == "/progress":
            return self._handle_progress()
        if path == "/version":
            return self._handle_version()

        if path.startswith("/app/"):
            return self._serve_static(APP_DIR, path[len("/app/"):])
        if path.startswith("/DATA/"):
            return self._serve_static(DATA_DIR, path[len("/DATA/"):])
        if path.startswith("/export/"):
            kind = path[len("/export/"):]
            return self._handle_export(kind)

        self._json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        if not self._csrf_ok():
            self._json(403, {"error": "bad origin"})
            return

        url = urlparse(self.path)
        path = url.path
        body = self._read_body()

        if path == "/setup":
            return self._handle_setup(body)
        if path == "/update":
            return self._handle_update(body)
        if path == "/reset":
            return self._handle_reset()
        if path == "/logout":
            return self._handle_logout()
        if path == "/check_session":
            return self._handle_check_session()
        if path == "/ingest_wealth_detail":
            # TEMPORARY ingest endpoint — used when Chrome MCP has live cookies
            # but sc-api's cookies on disk are stale. Receives the wealth_detail
            # JSON directly and writes it to DATA/. CORS-open to any origin.
            return self._handle_ingest(body)

        self._json(404, {"error": "not found", "path": path})

    def do_OPTIONS(self) -> None:  # noqa: N802
        # CORS preflight for the /ingest endpoint.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "3600")
        self.end_headers()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _handle_setup_status(self) -> None:
        try:
            from sc_api import profiles
            email = profiles.get_active_email()
            if not email:
                self._json(200, {"configured": False, "email": None})
                return
            prof = profiles.load(email)
            # "configured" also requires cookies on disk — otherwise we can't talk to Scalable
            has_cookies = prof.cookies_file.is_file()
            self._json(200, {
                "configured": has_cookies,
                "email": email,
                "user_id": prof.person_id,
                "portfolio_ids": prof.portfolio_ids,
                "savings_ids": prof.savings_ids,
            })
        except ImportError:
            self._json(200, {"configured": False, "email": None,
                             "warning": "sc-api not installed in venv"})
        except Exception as e:
            self._json(200, {"configured": False, "email": None,
                             "warning": f"{type(e).__name__}: {e}"})

    def _handle_version(self) -> None:
        try:
            import sc_api
            self._json(200, {"sc_api": sc_api.__version__})
        except Exception as e:
            self._json(200, {"sc_api": "unknown", "error": str(e)})

    def _handle_logout(self) -> None:
        """Wipe DATA/ + cookies + credentials + profile dir.

        After logout the auto-relogin mechanism is disabled (credentials gone),
        so user must go to Settings → enter email + password again.
        """
        try:
            from sc_api import profiles
            email = profiles.get_active_email()
        except Exception:
            email = None

        if DATA_DIR.is_dir():
            for f in DATA_DIR.iterdir():
                if f.is_file():
                    f.unlink()

        if email:
            try:
                from sc_api import profiles
                profiles.remove(email)  # removes cookies + credentials + meta
            except Exception:
                pass

        self._json(200, {"status": "ok", "removed_email": email})

    def _handle_ingest(self, body: dict | list) -> None:
        """Accept a JSON array of wealth portfolios and write to DATA/wealth_detail.json.

        Used as a side channel when MCP Chrome has live cookies but the
        sc-api Python cookies are stale. CORS-open so it works cross-origin.
        """
        import os
        import json as _json
        try:
            payload = body if isinstance(body, list) else body.get("data") if isinstance(body, dict) else None
            if not isinstance(payload, list):
                self._json(400, {"error": "expected JSON array of wealth portfolios"})
                return
            target = DATA_DIR / "wealth_detail.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(_json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
            os.replace(tmp, target)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(_json.dumps({
                "status": "ok",
                "items": len(payload),
                "path": str(target),
            }).encode("utf-8"))
        except Exception as e:
            self._json(500, {"error": f"ingest failed: {type(e).__name__}: {e}"})

    def _handle_export(self, kind: str) -> None:
        """Stream a CSV view of one of the JSON files in DATA/.

        Supported:
            orders.csv      — security transactions
            ledger.csv      — cash transactions
            dividends.csv   — distributions (filtered cash transactions)
            holdings.csv    — current broker inventory (flattened)
            wealth.csv      — wealth portfolios summary
        """
        import csv
        import io
        import json as _json

        tx_path = DATA_DIR / "transactions.json"
        inv_path = DATA_DIR / "inventory.json"
        wealth_path = DATA_DIR / "wealth.json"
        cash_path = DATA_DIR / "cash.json"

        buf = io.StringIO()
        writer = csv.writer(buf)
        filename = "export.csv"

        try:
            if kind == "orders.csv":
                tx = _json.loads(tx_path.read_text("utf-8")) if tx_path.is_file() else {}
                items = [t for t in (tx.get("transactions") or [])
                         if t.get("type") == "SECURITY_TRANSACTION"]
                writer.writerow(["date", "side", "type", "isin", "security",
                                 "quantity", "amount_eur", "status"])
                for t in items:
                    writer.writerow([
                        t.get("lastEventDateTime", ""),
                        t.get("side", ""),
                        t.get("securityTransactionType", ""),
                        t.get("isin", ""),
                        t.get("description", ""),
                        t.get("quantity", ""),
                        t.get("amount", ""),
                        t.get("status", ""),
                    ])
                filename = "scalable-orders.csv"

            elif kind == "ledger.csv":
                tx = _json.loads(tx_path.read_text("utf-8")) if tx_path.is_file() else {}
                items = [t for t in (tx.get("transactions") or [])
                         if t.get("type") == "CASH_TRANSACTION"]
                writer.writerow(["date", "type", "description", "related_isin",
                                 "amount_eur", "currency", "status"])
                for t in items:
                    writer.writerow([
                        t.get("lastEventDateTime", ""),
                        t.get("cashTransactionType", ""),
                        t.get("description", ""),
                        t.get("relatedIsin", "") or "",
                        t.get("amount", ""),
                        t.get("currency", "EUR"),
                        t.get("status", ""),
                    ])
                filename = "scalable-ledger.csv"

            elif kind == "dividends.csv":
                tx = _json.loads(tx_path.read_text("utf-8")) if tx_path.is_file() else {}
                items = [t for t in (tx.get("transactions") or [])
                         if t.get("type") == "CASH_TRANSACTION"
                         and t.get("cashTransactionType") == "DISTRIBUTION"]
                writer.writerow(["date", "security", "isin", "amount_eur",
                                 "currency", "status"])
                for t in items:
                    writer.writerow([
                        t.get("lastEventDateTime", ""),
                        t.get("description", ""),
                        t.get("relatedIsin", "") or "",
                        t.get("amount", ""),
                        t.get("currency", "EUR"),
                        t.get("status", ""),
                    ])
                filename = "scalable-dividends.csv"

            elif kind == "holdings.csv":
                inv = _json.loads(inv_path.read_text("utf-8")) if inv_path.is_file() else {}
                grouped = ((inv.get("portfolioGroups") or {}).get("items") or [])
                rows = []
                for g in grouped:
                    group_name = (g.get("details") or {}).get("name") or "—"
                    for sec in (g.get("items") or []):
                        rows.append((group_name, sec))
                for sec in ((inv.get("ungroupedInventoryItems") or {}).get("items") or []):
                    rows.append(("Ungrouped", sec))
                writer.writerow(["group", "name", "isin", "wkn", "type",
                                 "quantity_filled", "quantity_pending", "quantity_blocked",
                                 "fifo_price", "current_price", "value_eur",
                                 "currency", "is_outdated"])
                for group_name, sec in rows:
                    pos = (sec.get("inventory") or {}).get("position") or {}
                    tick = sec.get("quoteTick") or {}
                    qty = (pos.get("filled") or 0) + (pos.get("pending") or 0) + (pos.get("blocked") or 0)
                    val = (tick.get("midPrice") or 0) * qty if tick.get("midPrice") else ""
                    writer.writerow([
                        group_name,
                        sec.get("name", ""),
                        sec.get("isin", ""),
                        sec.get("wkn", "") or "",
                        sec.get("type", ""),
                        pos.get("filled", 0),
                        pos.get("pending", 0),
                        pos.get("blocked", 0),
                        pos.get("fifoPrice", "") or "",
                        tick.get("midPrice", "") or "",
                        val,
                        tick.get("currency", "EUR"),
                        tick.get("isOutdated", ""),
                    ])
                filename = "scalable-holdings.csv"

            elif kind == "wealth.csv":
                wealth = _json.loads(wealth_path.read_text("utf-8")) if wealth_path.is_file() else []
                writer.writerow(["name", "id", "custodian", "portfolio_type",
                                 "funded", "invested", "valuation_eur",
                                 "recurring_sum", "risk_category", "risk_level"])
                for w in wealth:
                    writer.writerow([
                        w.get("name", ""),
                        w.get("id", ""),
                        w.get("custodian", ""),
                        w.get("portfolio_type", ""),
                        w.get("funded", ""),
                        w.get("invested", ""),
                        w.get("valuation", ""),
                        "",  # recurring_sum not in our summary; need re-fetch
                        w.get("risk_category", ""),
                        w.get("risk_level", ""),
                    ])
                filename = "scalable-wealth.csv"

            else:
                self._json(404, {"error": f"unknown export type: {kind!r}"})
                return

        except Exception as e:
            self._json(500, {"error": f"export failed: {type(e).__name__}: {e}"})
            return

        body = buf.getvalue().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _handle_check_session(self) -> None:
        """Make ONE cheap GraphQL call to confirm cookies still authenticate."""
        try:
            from sc_api import ScalableClient
            from sc_api import _queries
            from sc_api.exceptions import SessionExpired, ScApiError
            c = ScalableClient.from_active()
            data = c.graphql(
                operation_name="custodianBanks",
                query=_queries.CUSTODIAN_BANKS,
                variables={"personId": c.profile.person_id},
            )
            banks = (data.get("personOverview") or {}).get("custodianBanks") or []
            self._json(200, {"status": "ok",
                             "detail": f"custodians: {banks}"})
        except SessionExpired:
            self._json(200, {"status": "expired",
                             "detail": "cookies dead — re-login arriba"})
        except ScApiError as e:
            self._json(200, {"status": "error", "detail": str(e)[:200]})
        except Exception as e:
            self._json(200, {"status": "error",
                             "detail": f"{type(e).__name__}: {e}"[:200]})

    def _handle_setup(self, body: dict) -> None:
        """Programmatic login from the browser — same flow as
        `sc-api auth login`. Blocks for up to 2 min while the user
        approves the push notification on their phone.
        """
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        if not email or not password:
            self._json(400, {"error": "email and password required"})
            return

        # Run the login subprocess — it'll trigger the push and poll until
        # SUCCESS or timeout. ~30-120 seconds typical.
        proc = subprocess.run(
            [sys.executable, "-m", "sc_api.cli", "auth", "login",
             "--email", email, "--password", password, "--set-active"],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            # Map common failures to user-friendly statuses
            stderr = (proc.stderr or "").lower()
            status = "auth_failed"
            if "denied" in stderr or "push was denied" in stderr:
                status = "push_denied"
            elif "timeout" in stderr or "didn't approve" in stderr:
                status = "push_timeout"
            elif "rejected the email" in stderr or "invalidcredentials" in stderr:
                status = "bad_credentials"
            self._json(500, {
                "status": status,
                "stderr": proc.stderr[-2000:],
                "stdout": proc.stdout[:2000],
            })
            return

        # Auth success — also run discovery so portfolioIds are persisted.
        disc = subprocess.run(
            [sys.executable, "-m", "sc_api.cli", "auth", "discover"],
            capture_output=True, text=True, timeout=30,
        )
        self._json(200 if disc.returncode == 0 else 500, {
            "status": "ok" if disc.returncode == 0 else "discovery_failed",
            "login_stdout": proc.stdout[:2000],
            "discovery_stdout": disc.stdout[:2000],
            "stderr": (proc.stderr + disc.stderr)[-2000:],
        })

    def _handle_update(self, body: dict) -> None:
        if not SC_FETCH.is_file():
            self._json(500, {"status": "config_error",
                             "error": f"sc_fetch.py missing at {SC_FETCH}"})
            return

        cmd = [sys.executable, str(SC_FETCH)]
        if body.get("portfolio_id"):
            cmd += ["--portfolio-id", body["portfolio_id"]]
        if body.get("email"):
            cmd += ["--email", body["email"]]

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            self._json(504, {"status": "timeout"})
            return

        status = EXIT_TO_STATUS.get(proc.returncode, "unknown_error")
        self._json(200 if proc.returncode == EXIT_OK else 500, {
            "status": status,
            "exit_code": proc.returncode,
            "log": proc.stderr[-4000:],
        })

    def _handle_reset(self) -> None:
        # Wipe DATA/ (keeps the profile + cookies — only data).
        if DATA_DIR.is_dir():
            for f in DATA_DIR.iterdir():
                if f.is_file():
                    f.unlink()
        self._json(200, {"status": "ok"})

    def _handle_progress(self) -> None:
        # Phase 0: just echo last_update.date timestamp.
        last = DATA_DIR / "last_update.date"
        ts = last.read_text(encoding="utf-8").strip() if last.is_file() else None
        self._json(200, {"last_update": ts})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _serve_static(self, base: Path, rel: str) -> None:
        if rel.endswith("/") or ".." in rel.split("/"):
            self._json(404, {"error": "no directory listing"})
            return
        target = base / rel
        if not target.is_file():
            self._json(404, {"error": "not found", "path": rel})
            return
        ctype = _guess_content_type(target.suffix)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def _csrf_ok(self) -> bool:
        origin = self.headers.get("Origin", "")
        # /ingest_wealth_detail is intentionally CORS-open for the
        # MCP-Chrome→localhost side-channel.
        if self.path == "/ingest_wealth_detail":
            return True
        ok = (
            origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")
            or not origin  # CLI clients without Origin (curl) are OK for local dev
        )
        return ok

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[server {time.strftime('%H:%M:%S')}] {fmt % args}",
              file=sys.stderr, flush=True)


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _guess_content_type(suffix: str) -> str:
    return CONTENT_TYPES.get(suffix.lower(), "application/octet-stream")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND_HOST, PORT), Handler)
    print(f"[server] Scalable Dashboard on http://{BIND_HOST}:{PORT}/app/index.html",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
