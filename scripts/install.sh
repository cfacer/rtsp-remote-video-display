#!/usr/bin/env bash
# ==============================================================
#  RTSP Remote Video Display — Ubuntu installation script
#  Run from the project root directory:
#
#      bash scripts/install.sh
#
#  What it does:
#    1. Installs system packages (ffmpeg, python3-tk, etc.)
#    2. Forces X11 mode so ffplay can embed into tkinter frames
#    3. Installs Python dependencies
#    4. Copies config.yaml.example → config.yaml (if absent)
#    5. Installs a systemd service that starts the app on login
# ==============================================================
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="$INSTALL_DIR/scripts/rtsp-display.service"
SERVICE_DST="/etc/systemd/system/rtsp-display.service"

# Detect the logged-in user (works even when run via sudo)
INSTALL_USER="${SUDO_USER:-$USER}"
INSTALL_HOME=$(eval echo "~$INSTALL_USER")

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     RTSP Remote Video Display — Ubuntu installer     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Install directory : $INSTALL_DIR"
echo "  Running as user   : $INSTALL_USER"
echo ""

# ── 1. System packages ─────────────────────────────────────────
echo "▶ Installing system packages…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-tk \
    ffmpeg \
    git

# ── 2. Force X11 (disable Wayland) ────────────────────────────
# ffplay's -wid embedding requires X11.  If GDM3 is present we
# disable Wayland there; the systemd unit also sets GDK_BACKEND=x11.
GDMCONF="/etc/gdm3/custom.conf"
if [ -f "$GDMCONF" ]; then
    echo "▶ Disabling Wayland in GDM3 (required for ffplay embedding)…"
    sudo sed -i 's/^#*\s*WaylandEnable=.*/WaylandEnable=false/' "$GDMCONF"
    # Make sure the line exists even if it was fully absent
    if ! grep -q "^WaylandEnable=false" "$GDMCONF"; then
        sudo sed -i '/^\[daemon\]/a WaylandEnable=false' "$GDMCONF"
    fi
else
    echo "  ℹ  GDM3 not found — skipping Wayland disable."
    echo "     If using LightDM or XFCE you are likely already on X11."
fi

# ── 3. Python dependencies ─────────────────────────────────────
echo "▶ Installing Python dependencies…"
pip3 install --break-system-packages -r "$INSTALL_DIR/requirements.txt"

# ── 4. Config file ─────────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    cp "$INSTALL_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml"
    echo "▶ Created config.yaml from example — PLEASE EDIT IT before starting."
else
    echo "  ℹ  config.yaml already exists — skipping."
fi

# ── 5. systemd service ────────────────────────────────────────
echo "▶ Installing systemd service…"

# Substitute placeholders in the template
sudo bash -c "sed \
    -e 's|{{INSTALL_DIR}}|$INSTALL_DIR|g' \
    -e 's|{{USER}}|$INSTALL_USER|g' \
    -e 's|{{HOME}}|$INSTALL_HOME|g' \
    '$SERVICE_SRC' > '$SERVICE_DST'"

sudo systemctl daemon-reload
sudo systemctl enable rtsp-display.service

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║               Installation complete!                 ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                       ║"
echo "║  1. Edit config.yaml and set your MQTT broker IP.    ║"
echo "║  2. Add your camera presets.                          ║"
echo "║  3. Reboot (or start the service manually):           ║"
echo "║       sudo systemctl start rtsp-display               ║"
echo "║                                                       ║"
echo "║  Logs:  sudo journalctl -u rtsp-display -f            ║"
echo "║  Test:  python3 -m rtsp_display.main --debug          ║"
echo "║                                                       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
