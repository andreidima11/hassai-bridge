#!/usr/bin/env bash
# HASSAI Bridge — Uninstaller
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}HASSAI Bridge — Uninstaller${NC}"
echo ""

# ── Stop server ──
PID=$(lsof -ti:8899 2>/dev/null || true)
if [[ -n "$PID" ]]; then
    echo -e "${CYAN}[INFO]${NC}  Stopping server (PID $PID)..."
    kill -9 $PID 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC}    Server stopped"
fi

# ── Remove systemd service (Linux) ──
SERVICE_FILE="/etc/systemd/system/hassai-bridge.service"
if [[ -f "$SERVICE_FILE" ]]; then
    echo -e "${CYAN}[INFO]${NC}  Removing systemd service..."
    sudo systemctl stop hassai-bridge 2>/dev/null || true
    sudo systemctl disable hassai-bridge 2>/dev/null || true
    sudo rm -f "$SERVICE_FILE"
    sudo systemctl daemon-reload
    echo -e "${GREEN}[OK]${NC}    Systemd service removed"
fi

# ── Remove launchd plist (macOS) ──
PLIST_FILE="$HOME/Library/LaunchAgents/com.hassai.bridge.plist"
if [[ -f "$PLIST_FILE" ]]; then
    echo -e "${CYAN}[INFO]${NC}  Removing launchd service..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    rm -f "$PLIST_FILE"
    echo -e "${GREEN}[OK]${NC}    LaunchAgent removed"
fi

# ── Ask about data ──
echo ""
echo -e "${YELLOW}Do you want to keep your data (memories, conversations, config)?${NC}"
read -r -p "Keep data? [Y/n]: " KEEP_DATA
KEEP_DATA="${KEEP_DATA:-y}"

if [[ "$(echo "$KEEP_DATA" | tr '[:upper:]' '[:lower:]')" == "n" ]]; then
    echo -e "${RED}WARNING: This will delete ALL memories, conversations, and settings!${NC}"
    read -r -p "Are you sure? Type 'DELETE' to confirm: " CONFIRM
    if [[ "$CONFIRM" == "DELETE" ]]; then
        rm -rf "$INSTALL_DIR/data"
        echo -e "${GREEN}[OK]${NC}    Data deleted"
    else
        echo -e "${CYAN}[INFO]${NC}  Data preserved"
    fi
else
    echo -e "${CYAN}[INFO]${NC}  Data preserved in $INSTALL_DIR/data/"
    echo -e "         To reuse it, keep the data/ folder before deleting."
fi

# ── Remove venv ──
if [[ -d "$INSTALL_DIR/venv" ]]; then
    echo -e "${CYAN}[INFO]${NC}  Removing virtual environment..."
    rm -rf "$INSTALL_DIR/venv"
    echo -e "${GREEN}[OK]${NC}    Virtual environment removed"
fi

echo ""
echo -e "${GREEN}[OK]${NC}    Uninstall complete."
if [[ "$(echo "$KEEP_DATA" | tr '[:upper:]' '[:lower:]')" != "n" ]]; then
    echo -e "         Your data is still in: $INSTALL_DIR/data/"
fi
echo -e "         To fully remove, delete: rm -rf $INSTALL_DIR"
echo ""
