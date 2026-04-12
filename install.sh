#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════╗
# ║        HASSAI Bridge — Installer                 ║
# ║  AI Bridge for Home Assistant                    ║
# ║  https://github.com/andreidima11/hassai-bridge   ║
# ╚══════════════════════════════════════════════════╝
set -euo pipefail

# ── Colors ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

INSTALL_DIR="${HASSAI_DIR:-$HOME/hassai-bridge}"
REPO_URL="https://github.com/andreidima11/hassai-bridge.git"
PORT=8899
MIN_PYTHON="3.10"

# Cross-platform local IP detection
get_local_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' \
    || ipconfig getifaddr en0 2>/dev/null \
    || echo "localhost"
}

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       HASSAI Bridge — Installer              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── 1) Check Python ──
info "Checking Python version..."
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    fail "Python 3.10+ is required but not found. Install it first:
       macOS:   brew install python3
       Ubuntu:  sudo apt install python3 python3-venv python3-pip
       Fedora:  sudo dnf install python3"
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10 ]]; then
    fail "Python $MIN_PYTHON+ required, found $PY_VERSION"
fi
ok "Python $PY_VERSION"

# ── 2) Check venv module ──
if ! $PYTHON -c "import venv" 2>/dev/null; then
    warn "Python venv module not found. Attempting to install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y python3-venv || fail "Could not install python3-venv"
    else
        fail "Python venv module not available. Install python3-venv manually."
    fi
fi

# ── 3) Clone or update repo ──
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation in $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull --ff-only || warn "Git pull failed — continuing with existing code"
    ok "Repository updated"
elif [[ -d "$INSTALL_DIR" ]]; then
    # Directory exists but is not a git repo (manual install)
    info "Directory $INSTALL_DIR exists (non-git). Using as-is."
    cd "$INSTALL_DIR"
else
    info "Cloning HASSAI Bridge to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    ok "Repository cloned"
fi

# ── 4) Create virtual environment ──
if [[ ! -d "venv" ]]; then
    info "Creating Python virtual environment..."
    $PYTHON -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

# ── 5) Install dependencies ──
info "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip -q 2>/dev/null || true
pip install -r requirements.txt -q
ok "Dependencies installed"

# ── 6) Create data directory and default config ──
mkdir -p data
if [[ ! -f "data/config.json" ]]; then
    info "Creating default configuration..."
    cat > data/config.json << 'DEFAULTCFG'
{
    "system_prompt": "You are a helpful AI assistant integrated with Home Assistant. Answer questions clearly and concisely in the user's language. When you have memory context about the user, use it to personalize your responses.",
    "api_key": "",
    "active_provider": "",
    "providers": [],
    "searxng": {
        "enabled": false,
        "base_url": ""
    },
    "knowledge_cutoff": "2024-01",
    "users": {
        "default_user": "default",
        "api_keys": {}
    },
    "performance": {
        "history_limit": 10
    }
}
DEFAULTCFG
    ok "Default config created (data/config.json)"
    echo ""
    warn "You need to configure at least one AI provider."
    warn "Open http://$(get_local_ip):$PORT after starting."
else
    ok "Configuration exists (data/config.json)"
fi

# ── 7) Create launcher script ──
cat > hassai-bridge << 'LAUNCHER'
#!/usr/bin/env bash
# HASSAI Bridge — launcher script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

get_local_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' \
    || ipconfig getifaddr en0 2>/dev/null \
    || echo "localhost"
}

usage() {
    echo -e "${BOLD}HASSAI Bridge${NC} — AI Bridge for Home Assistant"
    echo ""
    echo "Usage: $0 {start|stop|restart|status|logs|update}"
    echo ""
    echo "  start    Start the server (background)"
    echo "  stop     Stop the server"
    echo "  restart  Restart the server"
    echo "  status   Check if the server is running"
    echo "  logs     Show recent server logs"
    echo "  update   Pull latest code and restart"
    echo ""
}

get_pid() {
    lsof -ti:8899 2>/dev/null | head -1 || true
}

cmd_start() {
    local pid
    pid=$(get_pid)
    if [[ -n "$pid" ]]; then
        echo -e "${CYAN}[INFO]${NC}  Server already running (PID $pid)"
        return 0
    fi
    echo -e "${CYAN}[INFO]${NC}  Starting HASSAI Bridge..."
    source venv/bin/activate
    nohup python main.py > data/hassai.log 2>&1 &
    local new_pid=$!
    # Wait for server to be ready
    for i in {1..15}; do
        if curl -sf http://localhost:8899/api/settings/health >/dev/null 2>&1; then
            echo -e "${GREEN}[OK]${NC}    Server started (PID $new_pid)"
            echo -e "${GREEN}[OK]${NC}    Web UI: http://$(get_local_ip):8899"
            return 0
        fi
        sleep 1
    done
    echo -e "${GREEN}[OK]${NC}    Server starting (PID $new_pid) — may take a few seconds"
}

cmd_stop() {
    local pid
    pid=$(get_pid)
    if [[ -z "$pid" ]]; then
        echo -e "${CYAN}[INFO]${NC}  Server is not running"
        return 0
    fi
    echo -e "${CYAN}[INFO]${NC}  Stopping server (PID $pid)..."
    kill $pid 2>/dev/null || true
    sleep 1
    # Force kill if still running
    pid=$(get_pid)
    if [[ -n "$pid" ]]; then
        kill -9 $pid 2>/dev/null || true
    fi
    echo -e "${GREEN}[OK]${NC}    Server stopped"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    local pid
    pid=$(get_pid)
    if [[ -n "$pid" ]]; then
        echo -e "${GREEN}[OK]${NC}    Server is running (PID $pid)"
        if curl -sf http://localhost:8899/api/settings/health >/dev/null 2>&1; then
            local info
            info=$(curl -sf http://localhost:8899/api/settings/info 2>/dev/null)
            if [[ -n "$info" ]]; then
                local version uptime
                version=$(echo "$info" | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
                uptime_s=$(echo "$info" | python3 -c "import json,sys; print(json.load(sys.stdin).get('uptime_seconds',0))" 2>/dev/null || echo "0")
                if [[ "$uptime_s" =~ ^[0-9]+$ ]] && (( uptime_s > 0 )); then
                    local h=$((uptime_s / 3600)) m=$(( (uptime_s % 3600) / 60 )) s=$((uptime_s % 60))
                    uptime="${h}h ${m}m ${s}s"
                else
                    uptime="just started"
                fi
                echo -e "         Version: $version"
                echo -e "         Uptime:  $uptime"
            fi
        fi
    else
        echo -e "${RED}[--]${NC}    Server is not running"
    fi
}

cmd_logs() {
    if [[ -f "data/hassai.log" ]]; then
        tail -50 data/hassai.log
    else
        echo "No log file found. Start the server first."
    fi
}

cmd_update() {
    echo -e "${CYAN}[INFO]${NC}  Updating HASSAI Bridge..."
    cmd_stop
    if [[ -d ".git" ]]; then
        git pull --ff-only || { echo -e "${RED}[ERROR]${NC} Git pull failed"; return 1; }
    else
        echo -e "${RED}[ERROR]${NC} Not a git repository — update manually"
        return 1
    fi
    source venv/bin/activate
    pip install -r requirements.txt -q
    echo -e "${GREEN}[OK]${NC}    Updated. Starting server..."
    cmd_start
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    logs)    cmd_logs ;;
    update)  cmd_update ;;
    *)       usage ;;
esac
LAUNCHER
chmod +x hassai-bridge
ok "Launcher script created: ./hassai-bridge"

# ── 8) Offer systemd service (Linux only) ──
if [[ "$(uname)" == "Linux" ]] && command -v systemctl &>/dev/null; then
    echo ""
    echo -e "${BOLD}Optional: Install as a system service (auto-start on boot)?${NC}"
    read -r -p "Install systemd service? [y/N]: " INSTALL_SERVICE
    if [[ "$(echo "$INSTALL_SERVICE" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
        SERVICE_FILE="/etc/systemd/system/hassai-bridge.service"
        sudo tee "$SERVICE_FILE" > /dev/null << SYSTEMD
[Unit]
Description=HASSAI Bridge — AI Bridge for Home Assistant
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=on-failure
RestartSec=5
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
SYSTEMD
        sudo systemctl daemon-reload
        sudo systemctl enable hassai-bridge
        sudo systemctl start hassai-bridge
        ok "Systemd service installed and started"
        info "Commands: sudo systemctl {start|stop|restart|status} hassai-bridge"
    fi
fi

# ── 9) Offer launchd plist (macOS only) ──
if [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    echo -e "${BOLD}Optional: Auto-start on boot (macOS)?${NC}"
    read -r -p "Install launchd service? [y/N]: " INSTALL_LAUNCH
    if [[ "$(echo "$INSTALL_LAUNCH" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
        PLIST_FILE="$HOME/Library/LaunchAgents/com.hassai.bridge.plist"
        cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hassai.bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/data/hassai.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/data/hassai.log</string>
</dict>
</plist>
PLIST
        launchctl load "$PLIST_FILE" 2>/dev/null || true
        ok "LaunchAgent installed — HASSAI Bridge will auto-start on login"
        info "To remove: launchctl unload $PLIST_FILE && rm $PLIST_FILE"
    fi
fi

# ── Done ──
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       ✅ Installation complete!               ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Quick start:${NC}"
echo -e "    cd $INSTALL_DIR"
echo -e "    ./hassai-bridge start"
echo ""
echo -e "  ${BOLD}Management:${NC}"
echo -e "    ./hassai-bridge status    — check server status"
echo -e "    ./hassai-bridge stop      — stop server"
echo -e "    ./hassai-bridge restart   — restart server"
echo -e "    ./hassai-bridge update    — update & restart"
echo -e "    ./hassai-bridge logs      — view server logs"
echo ""
LOCAL_IP=$(get_local_ip)
[[ -z "$LOCAL_IP" ]] && LOCAL_IP="localhost"
echo -e "  ${BOLD}Web UI:${NC}  http://$LOCAL_IP:$PORT"
echo -e "  ${BOLD}API:${NC}     http://$LOCAL_IP:$PORT/v1/"
echo ""
echo -e "  ${YELLOW}Next step:${NC} Open the Web UI and add an AI provider (LM Studio, OpenAI, etc.)"
echo ""
