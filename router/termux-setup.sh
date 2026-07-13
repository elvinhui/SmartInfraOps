#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

GOST_VERSION="2.12.0"
SOCKS_PORT="${SOCKS_PORT:-1080}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

if [ ! -d "/data/data/com.termux" ]; then
    err "This script must be run inside Termux on Android."
    exit 1
fi

echo ""
echo "SmartInfraOps - Phone Proxy Setup"
echo "Tailscale + gost SOCKS5"
echo "================================="
echo ""

info "Step 1: Installing required packages..."
pkg update -y
pkg install -y wget openssl openssl-tool termux-services cronie

info "Step 2: Detecting CPU architecture..."
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
ok "Architecture: $ARCH -> ${GOST_ARCH}"

info "Step 3: Installing Tailscale..."
if command -v tailscale &> /dev/null; then
    ok "Tailscale already installed: $(tailscale version | head -n1)"
else
    TS_VERSION="1.68.2"
    TS_URL="https://pkgs.tailscale.com/stable/tailscale_${TS_VERSION}_${GOST_ARCH}.tgz"
    info "Downloading Tailscale v${TS_VERSION}..."
    mkdir -p $PREFIX/tmp
    wget --tries=3 --timeout=30 --show-progress -O $PREFIX/tmp/tailscale.tgz "$TS_URL"
    tar xzf $PREFIX/tmp/tailscale.tgz -C $PREFIX/tmp
    mv $PREFIX/tmp/tailscale_${TS_VERSION}_${GOST_ARCH}/tailscale "$PREFIX/bin/"
    mv $PREFIX/tmp/tailscale_${TS_VERSION}_${GOST_ARCH}/tailscaled "$PREFIX/bin/"
    rm -rf $PREFIX/tmp/tailscale*
    ok "Tailscale installed to $PREFIX/bin/"
fi

info "Step 4: Installing gost..."
if command -v gost &> /dev/null; then
    ok "gost already installed."
else
    info "Downloading gost v${GOST_VERSION} (${GOST_ARCH})..."
    GOST_FILE="gost_${GOST_VERSION}_linux_${GOST_ARCH}.tar.gz"
    mkdir -p $PREFIX/tmp

    DOWNLOADED=0
    for MIRROR in "https://kkgithub.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/${GOST_FILE}" "https://ghproxy.net/https://github.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/${GOST_FILE}" "https://github.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/${GOST_FILE}"; do
        info "Trying: $MIRROR"
        if wget --tries=2 --timeout=30 --show-progress -O $PREFIX/tmp/gost.tar.gz "$MIRROR"; then
            if tar -tzf $PREFIX/tmp/gost.tar.gz &>/dev/null; then
                DOWNLOADED=1
                ok "Downloaded and verified OK"
                break
            else
                warn "File corrupted, trying next mirror..."
                rm -f $PREFIX/tmp/gost.tar.gz
            fi
        else
            warn "Mirror failed, trying next..."
        fi
    done

    if [ "$DOWNLOADED" -eq 0 ]; then
        err "All mirrors failed. Check your network."
        exit 1
    fi

    tar xzf $PREFIX/tmp/gost.tar.gz -C $PREFIX/tmp
    chmod +x $PREFIX/tmp/gost
    mv $PREFIX/tmp/gost "$PREFIX/bin/gost"
    rm -f $PREFIX/tmp/gost.tar.gz $PREFIX/tmp/LICENSE $PREFIX/tmp/README*
    ok "gost installed to $PREFIX/bin/gost"
fi

info "Step 5: Generating SOCKS5 credentials..."
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
    ok "Generated new credentials -> $CRED_FILE"
fi

info "Step 6: Starting Tailscale daemon (userspace networking)..."
tailscaled --tun=userspace-networking &> $PREFIX/tmp/tailscaled.log &
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

info "Step 7: Starting gost SOCKS5 proxy on ${TAILSCALE_IP}:${SOCKS_PORT}..."
pkill gost 2>/dev/null || true
sleep 1

nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:${SOCKS_PORT}" > $PREFIX/tmp/gost.log 2>&1 &

sleep 2

if pgrep gost > /dev/null; then
    ok "gost is running! (PID: $(pgrep gost))"
else
    err "gost failed to start. Check $PREFIX/tmp/gost.log"
    cat $PREFIX/tmp/gost.log
    exit 1
fi

info "Step 8: Creating Termux:Boot auto-start script..."
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
BOOT_SCRIPT="$BOOT_DIR/start-proxy.sh"
echo '#!/data/data/com.termux/files/usr/bin/bash' > "$BOOT_SCRIPT"
echo 'termux-wake-lock' >> "$BOOT_SCRIPT"
echo 'tailscaled --tun=userspace-networking &> $PREFIX/tmp/tailscaled.log &' >> "$BOOT_SCRIPT"
echo 'sleep 5' >> "$BOOT_SCRIPT"
echo 'tailscale up --hostname=smartinfra-phone' >> "$BOOT_SCRIPT"
echo 'for i in $(seq 1 30); do' >> "$BOOT_SCRIPT"
echo '    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")' >> "$BOOT_SCRIPT"
echo '    if [ -n "$TAILSCALE_IP" ]; then break; fi' >> "$BOOT_SCRIPT"
echo '    sleep 2' >> "$BOOT_SCRIPT"
echo 'done' >> "$BOOT_SCRIPT"
echo 'if [ -z "$TAILSCALE_IP" ]; then exit 1; fi' >> "$BOOT_SCRIPT"
echo 'source "$HOME/.gost_credentials"' >> "$BOOT_SCRIPT"
echo 'nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:1080" > $PREFIX/tmp/gost.log 2>&1 &' >> "$BOOT_SCRIPT"
chmod +x "$BOOT_SCRIPT"
ok "Boot script created: $BOOT_SCRIPT"

info "Step 9: Creating watchdog cron script..."
WATCHDOG_SCRIPT="$HOME/gost-watchdog.sh"
echo '#!/data/data/com.termux/files/usr/bin/bash' > "$WATCHDOG_SCRIPT"
echo 'if ! pgrep gost > /dev/null; then' >> "$WATCHDOG_SCRIPT"
echo '    source "$HOME/.gost_credentials"' >> "$WATCHDOG_SCRIPT"
echo '    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")' >> "$WATCHDOG_SCRIPT"
echo '    if [ -n "$TAILSCALE_IP" ]; then' >> "$WATCHDOG_SCRIPT"
echo '        nohup gost -L "socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:1080" > $PREFIX/tmp/gost.log 2>&1 &' >> "$WATCHDOG_SCRIPT"
echo '    fi' >> "$WATCHDOG_SCRIPT"
echo 'fi' >> "$WATCHDOG_SCRIPT"
chmod +x "$WATCHDOG_SCRIPT"

(crontab -l 2>/dev/null | grep -v gost-watchdog; echo "*/5 * * * * $WATCHDOG_SCRIPT") | crontab -
sv-enable crond 2>/dev/null || true
ok "Watchdog cron installed (every 5 min)."

info "Step 10: Acquiring wake lock..."
termux-wake-lock 2>/dev/null || warn "termux-wake-lock not available. Install Termux:API from F-Droid."

echo ""
echo "================================="
echo "  Setup Complete!"
echo "================================="
echo ""
echo "  Proxy: socks5://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:${SOCKS_PORT}"
echo ""
echo "  Add these to GitHub Secrets:"
echo "    PROXY_TAILSCALE_IP = ${TAILSCALE_IP}"
echo "    SOCKS_USER         = ${SOCKS_USER}"
echo "    SOCKS_PASS         = ${SOCKS_PASS}"
echo ""
echo "  Android Settings (IMPORTANT):"
echo "    1. Settings > Battery > Termux > Unrestricted"
echo "    2. Settings > Battery > Tailscale > Unrestricted"
echo "    3. Recent apps > Lock Termux (tap lock icon)"
echo ""
