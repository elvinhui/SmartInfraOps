#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════
# SmartInfraOps — Termux Phone Proxy Setup (One-Click)
# 
# Turns your Android phone into a SOCKS5 proxy endpoint
# accessible via Tailscale mesh VPN.
#
# Usage:
#   curl -fsSL <raw-url> | bash
#   OR
#   bash termux-setup.sh
#
# Prerequisites:
#   - Termux installed from F-Droid (NOT Google Play)
#   - Termux:Boot installed from F-Droid (for auto-start)
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

GOST_VERSION="2.12.0"
SOCKS_PORT="${SOCKS_PORT:-1080}"

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Step 0: Validate environment ─────────────────────────────
if [ ! -d "/data/data/com.termux" ]; then
    err "This script must be run inside Termux on Android."
    exit 1
fi

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║  SmartInfraOps — Phone Proxy Setup            ║"
echo "║  Tailscale + gost SOCKS5                      ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# ── Step 1: Install packages ─────────────────────────────────
info "Installing required packages..."
pkg update -y
pkg install -y wget openssl termux-services cronie

# ── Step 2: Install Tailscale ─────────────────────────────────
info "Installing Tailscale..."
if command -v tailscale &> /dev/null; then
    ok "Tailscale already installed: $(tailscale version)"
else
    pkg install -y tailscale
    ok "Tailscale installed."
fi

# ── Step 3: Download gost ────────────────────────────────────
info "Detecting CPU architecture..."
ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64) GOST_ARCH="arm64" ;;
    armv7l|armhf)  GOST_ARCH="armv7" ;;
    x86_64|amd64)  GOST_ARCH="amd64" ;;
    *)
        err "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac
ok "Architecture: $ARCH → gost-${GOST_ARCH}"

if command -v gost &> /dev/null; then
    ok "gost already installed."
else
    info "Downloading gost v${GOST_VERSION} (${GOST_ARCH})..."
    GOST_URL="https://github.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/gost-linux-${GOST_ARCH}-${GOST_VERSION}.gz"
    wget -q --show-progress -O /tmp/gost.gz "$GOST_URL"
    gzip -d /tmp/gost.gz
    chmod +x /tmp/gost
    mv /tmp/gost "$PREFIX/bin/gost"
    ok "gost installed to $PREFIX/bin/gost"
fi

# ── Step 4: Generate SOCKS5 credentials ──────────────────────
CRED_FILE="$HOME/.gost_credentials"
if [ -f "$CRED_FILE" ]; then
    source "$CRED_FILE"
    ok "Loaded existing credentials from $CRED_FILE"
else
    SOCKS_USER="gha_$(openssl rand -hex 4)"
    SOCKS_PASS="$(openssl rand -hex 16)"
    echo "SOCKS_USER=\"$SOCKS_USER\"" > "$CRED_FILE"
    echo "SOCKS_PASS=\"$SOCKS_PASS\"" >> "$CRED_FILE"
    chmod 600 "$CRED_FILE"
    ok "Generated new credentials → $CRED_FILE"
fi

# ── Step 5: Start Tailscale ──────────────────────────────────
info "Starting Tailscale daemon..."
tailscaled &> /tmp/tailscaled.log &
sleep 2

if tailscale status &> /dev/null; then
    ok "Tailscale already connected."
else
    info "Tailscale login required. Opening browser..."
    tailscale up --hostname=smartinfra-phone
    echo ""
    warn "Please complete Tailscale login in your browser."
    echo "   After login, re-run this script to continue."
    echo ""
fi

TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
if [ -z "$TAILSCALE_IP" ]; then
    err "Could not get Tailscale IP. Make sure Tailscale is connected."
    exit 1
fi
ok "Tailscale IP: $TAILSCALE_IP"

# ── Step 6: Start gost SOCKS5 proxy ─────────────────────────
info "Starting gost SOCKS5 proxy on ${TAILSCALE_IP}:${SOCKS_PORT}..."

# Kill existing gost if running
pkill gost 2>/dev/null || true
sleep 1

nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:${SOCKS_PORT}" \
    > /tmp/gost.log 2>&1 &

sleep 2

if pgrep gost > /dev/null; then
    ok "gost is running! (PID: $(pgrep gost))"
else
    err "gost failed to start. Check /tmp/gost.log"
    cat /tmp/gost.log
    exit 1
fi

# ── Step 7: Setup Termux:Boot auto-start ─────────────────────
info "Configuring Termux:Boot auto-start..."
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"

cat > "$BOOT_DIR/start-proxy.sh" << 'BOOTEOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start script for Termux:Boot
# Starts Tailscale + gost on phone boot

termux-wake-lock

# Start Tailscale
tailscaled &> /tmp/tailscaled.log &
sleep 5
tailscale up --hostname=smartinfra-phone

# Wait for Tailscale IP
for i in $(seq 1 30); do
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [ -n "$TAILSCALE_IP" ]; then
        break
    fi
    sleep 2
done

if [ -z "$TAILSCALE_IP" ]; then
    echo "$(date) - Failed to get Tailscale IP" >> /tmp/gost_watchdog.log
    exit 1
fi

# Load credentials
source "$HOME/.gost_credentials"

# Start gost
nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:1080" \
    > /tmp/gost.log 2>&1 &

echo "$(date) - Proxy started on ${TAILSCALE_IP}:1080" >> /tmp/gost_watchdog.log
BOOTEOF

chmod +x "$BOOT_DIR/start-proxy.sh"
ok "Boot script created: $BOOT_DIR/start-proxy.sh"

# ── Step 8: Setup watchdog cron ──────────────────────────────
info "Setting up watchdog cron (every 5 minutes)..."

WATCHDOG_SCRIPT="$HOME/gost-watchdog.sh"
cat > "$WATCHDOG_SCRIPT" << 'WDEOF'
#!/data/data/com.termux/files/usr/bin/bash
# Watchdog: restart gost if it's dead
if ! pgrep gost > /dev/null; then
    echo "$(date) - gost DOWN, restarting..." >> /tmp/gost_watchdog.log
    source "$HOME/.gost_credentials"
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [ -n "$TAILSCALE_IP" ]; then
        nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:1080" \
            > /tmp/gost.log 2>&1 &
        echo "$(date) - gost restarted on ${TAILSCALE_IP}:1080" >> /tmp/gost_watchdog.log
    else
        echo "$(date) - No Tailscale IP, cannot restart gost" >> /tmp/gost_watchdog.log
    fi
fi
WDEOF
chmod +x "$WATCHDOG_SCRIPT"

# Add to crontab
(crontab -l 2>/dev/null | grep -v gost-watchdog; echo "*/5 * * * * $WATCHDOG_SCRIPT") | crontab -
sv-enable crond 2>/dev/null || true
ok "Watchdog cron installed (every 5 min)."

# ── Step 9: Enable wake lock ─────────────────────────────────
info "Acquiring Termux wake lock (prevents background kill)..."
termux-wake-lock 2>/dev/null || warn "termux-wake-lock not available. Install Termux:API from F-Droid."

# ── Done! ─────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  ✅ Setup Complete!                                       ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║                                                           ║"
echo "║  Proxy endpoint:                                          ║"
echo "║  socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:${SOCKS_PORT}"
echo "║                                                           ║"
echo "║  ┌─────────────────────────────────────────────┐          ║"
echo "║  │ Add these to GitHub Secrets:                 │          ║"
echo "║  │                                              │          ║"
echo "║  │  PROXY_TAILSCALE_IP = ${TAILSCALE_IP}        │          ║"
echo "║  │  SOCKS_USER         = ${SOCKS_USER}          │          ║"
echo "║  │  SOCKS_PASS         = ${SOCKS_PASS}          │          ║"
echo "║  └─────────────────────────────────────────────┘          ║"
echo "║                                                           ║"
echo "║  ⚠️  Android Settings (IMPORTANT):                        ║"
echo "║  1. Settings → Battery → Termux → Unrestricted            ║"
echo "║  2. Settings → Battery → Tailscale → Unrestricted         ║"
echo "║  3. Recent apps → Lock Termux (tap 🔒)                   ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
