#!/bin/bash
# =============================================================================
# Scalable Capital Dashboard — Single orchestrator
# =============================================================================
# USO:
#   ./dashboard.sh              Arranca server + abre browser
#   ./dashboard.sh start        Igual que el default
#   ./dashboard.sh stop         Detiene el server
#   ./dashboard.sh restart      stop + start (con sleep para liberar puerto)
#   ./dashboard.sh status       Inventario, fechas, estado del server
#
# Para login/setup: abre el dashboard y usa la UI (email + password + push approval).
# Scalable usa push-only para 2FA — apruebas con biometric en el teléfono.
# =============================================================================
#
# NOTE: NO `set -e` aquí. Versiones recientes de bash abortan silenciosamente
# en algunos contextos (negations, $(...) ) y dejaba restart sin output.
# En vez de eso checamos el código de retorno explícitamente donde importa.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$PROJECT_DIR/app"
DATA_DIR="$PROJECT_DIR/DATA"
PORT="${SC_DASHBOARD_PORT:-8087}"

SC_API_PATH="${SC_API_PATH:-$PROJECT_DIR/../sc-api}"

VENV_DIR="$PROJECT_DIR/.venv"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

LAST_UPDATE_FILE="$DATA_DIR/last_update.date"
SERVER_LOG="$DATA_DIR/server.log"
SERVER_PID="$DATA_DIR/server.pid"

mkdir -p "$DATA_DIR"
cd "$PROJECT_DIR"

# ----------------------------------------------------------------------- python env
ensure_python_env() {
    if [ ! -x "$PY" ]; then
        echo "🐍 Creating Python venv at $VENV_DIR …"
        if command -v python3.11 >/dev/null 2>&1; then
            python3.11 -m venv "$VENV_DIR"
        else
            echo "  ⚠️  python3.11 not found — using system python3"
            echo "     (server runs 3.11; consider: brew install python@3.11)"
            python3 -m venv "$VENV_DIR"
        fi
        if [ ! -x "$PY" ]; then
            echo "❌ venv creation failed at $VENV_DIR"
            return 1
        fi
        "$PIP" install --quiet --upgrade pip >/dev/null 2>&1
    fi
    if ! "$PY" -c "import sc_api" 2>/dev/null; then
        echo "📦 Installing sc-api into the dashboard venv …"
        if [ -d "$SC_API_PATH" ]; then
            "$PIP" install --quiet -e "$SC_API_PATH"
        else
            "$PIP" install --quiet "sc-api"
        fi
        if ! "$PY" -c "import sc_api" 2>/dev/null; then
            echo "❌ sc-api still not importable after install"
            return 1
        fi
    fi
    return 0
}

# ----------------------------------------------------------------------- server
start_server() {
    if ! ensure_python_env; then
        echo "❌ Aborting: Python env not ready"
        return 1
    fi
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "🌐 Server already running at http://localhost:$PORT/app/index.html"
        open "http://localhost:$PORT/app/index.html" 2>/dev/null
        return 0
    fi
    echo "🚀 Starting local server on port $PORT..."
    "$PY" "$APP_DIR/server.py" > "$SERVER_LOG" 2>&1 &
    echo $! > "$SERVER_PID"

    # Wait up to 5s for the port to actually bind. If it doesn't, surface logs.
    local i=0
    while [ $i -lt 10 ]; do
        if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo "🌐 Server ready at http://localhost:$PORT/app/index.html"
            open "http://localhost:$PORT/app/index.html" 2>/dev/null
            return 0
        fi
        sleep 0.5
        i=$((i + 1))
    done

    echo "❌ Server didn't bind to port $PORT within 5s. Last log lines:"
    tail -20 "$SERVER_LOG" 2>/dev/null
    return 1
}

stop_server() {
    local killed=0
    if [ -f "$SERVER_PID" ]; then
        local pid
        pid=$(cat "$SERVER_PID")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "🛑 Server stopped (PID $pid)."
            killed=1
        fi
        rm -f "$SERVER_PID"
    fi
    # Belt + suspenders: kill anything still on the port.
    local lsof_pid
    lsof_pid=$(lsof -ti:$PORT 2>/dev/null)
    if [ -n "$lsof_pid" ]; then
        kill -9 $lsof_pid 2>/dev/null
        echo "  (also killed lingering process(es) $lsof_pid on port $PORT)"
        killed=1
    fi
    if [ $killed -eq 0 ]; then
        echo "  (nothing running on port $PORT)"
    fi
}

# ----------------------------------------------------------------------- status
do_status() {
    echo "📊 SCALABLE CAPITAL DASHBOARD — STATUS"
    echo "======================================"
    echo "Project:     $PROJECT_DIR"
    echo "Total size:  $(du -sh "$PROJECT_DIR" 2>/dev/null | cut -f1)"
    echo ""
    if [ -f "$LAST_UPDATE_FILE" ]; then
        echo "Last update: $(cat "$LAST_UPDATE_FILE")"
    else
        echo "Last update: never (open the dashboard and click ⟳ Actualizar)"
    fi
    echo ""
    echo "Data files:"
    for f in "$DATA_DIR/inventory.json" "$DATA_DIR/cash.json" \
             "$DATA_DIR/wealth.json" "$DATA_DIR/broker_overview.json" \
             "$DATA_DIR/transactions.json" "$DATA_DIR/watchlist.json"; do
        if [ -f "$f" ]; then
            local mtime size
            mtime=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f")
            size=$(du -h "$f" | cut -f1)
            printf "  %-30s  %6s  %s\n" "$(basename "$f")" "$size" "$mtime"
        else
            printf "  %-30s  (missing)\n" "$(basename "$f")"
        fi
    done
    echo ""
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "Server:      🟢 RUNNING  (http://localhost:$PORT/app/index.html)"
    else
        echo "Server:      ⚪ stopped  (start with: ./dashboard.sh)"
    fi
}

case "${1:-}" in
    ""|start)  start_server ;;
    stop)      stop_server ;;
    restart)   stop_server; sleep 1; start_server ;;
    status)    do_status ;;
    *)
        echo "Usage: $0 [start|stop|restart|status]"
        exit 1
        ;;
esac
