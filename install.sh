#!/usr/bin/env bash
# MountBridge v1.1 — installer for Debian / XFCE
set -euo pipefail

APP="MountBridge"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}→${NC}  $*"; }
ok()     { echo -e "${GREEN}✓${NC}  $*"; }
warn()   { echo -e "${YELLOW}⚠${NC}  $*"; }
err()    { echo -e "${RED}✗${NC}  $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

header "=== $APP Installer ==="
[[ $EUID -eq 0 ]] && { err "Do not run as root."; exit 1; }

# 1. System packages
header "1. System packages"
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-notify-0.7 \
    python3-keyring python3-secretstorage \
    sshfs cifs-utils nfs-common sshpass \
    avahi-utils samba-common-bin
ok "Core packages installed"

if sudo apt-get install -y libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1 2>/dev/null; then
    ok "Ayatana AppIndicator installed"
elif sudo apt-get install -y libappindicator3-1 gir1.2-appindicator3-0.1 2>/dev/null; then
    ok "AppIndicator3 installed"
else
    warn "AppIndicator unavailable — tray will use StatusIcon fallback"
fi

# 2. Python package
header "2. Python package"
pip install --user --break-system-packages "${REPO_DIR}"
export PATH="$HOME/.local/bin:$PATH"
ok "MountBridge installed"

# 3. Directories
header "3. Directories"
mkdir -p "$HOME/.mounts" "$HOME/.config/mountbridge"
ok "~/.mounts and ~/.config/mountbridge ready"

# 4. Desktop integration
header "4. Desktop integration"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPS_DIR" "$ICON_DIR"
install -m 644 "$REPO_DIR/data/mountbridge.desktop" "$APPS_DIR/mountbridge.desktop"
install -m 644 "$REPO_DIR/data/icons/mountbridge.svg" "$ICON_DIR/mountbridge.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
xdg-desktop-menu forceupdate 2>/dev/null || true
ok "Desktop entry and icon installed"

# 5. Autostart
header "5. Autostart"
read -rp "Start MountBridge automatically on login? [y/N] " ans_auto
if [[ "$ans_auto" =~ ^[Yy]$ ]]; then
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/mountbridge.desktop" << EOF
[Desktop Entry]
Type=Application
Name=MountBridge
Exec=$HOME/.local/bin/mountbridge
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Network Mount Manager
EOF
    ok "Autostart entry created"
else
    info "Skipping autostart"
fi

# 6. Sudoers
header "6. Sudoers (NFS/SMB passwordless mount)"
SUDOERS_DST="/etc/sudoers.d/mountbridge"
SUDOERS_TMP="$(mktemp)"
sed "s/%USER%/$USER/g" "$REPO_DIR/data/mountbridge.sudoers" > "$SUDOERS_TMP"
echo ""; cat "$SUDOERS_TMP"; echo ""
read -rp "Install this sudoers rule? [y/N] " ans_sudo
if [[ "$ans_sudo" =~ ^[Yy]$ ]]; then
    sudo install -m 440 "$SUDOERS_TMP" "$SUDOERS_DST"
    if sudo visudo -cf "$SUDOERS_DST" &>/dev/null; then
        ok "Sudoers rule installed at $SUDOERS_DST"
    else
        err "Validation failed — removing"
        sudo rm -f "$SUDOERS_DST"
    fi
else
    warn "Skipped — NFS/SMB will prompt for sudo password"
fi
rm -f "$SUDOERS_TMP"

# 7. FUSE
header "7. FUSE (SSHFS)"
FUSE_CONF="/etc/fuse.conf"
if [[ -f "$FUSE_CONF" ]] && grep -q "^#user_allow_other" "$FUSE_CONF"; then
    read -rp "Enable user_allow_other in $FUSE_CONF? [y/N] " ans_fuse
    [[ "$ans_fuse" =~ ^[Yy]$ ]] && sudo sed -i 's/^#user_allow_other/user_allow_other/' "$FUSE_CONF" && ok "Enabled"
fi
if getent group fuse &>/dev/null && ! id -nG "$USER" | grep -qw fuse; then
    sudo usermod -aG fuse "$USER"
    warn "Added $USER to fuse group — re-login required"
fi

# 8. Keyring check
header "8. Keyring"
if pgrep -x gnome-keyring-daemon &>/dev/null || pgrep -x kwalletd5 &>/dev/null || pgrep -x kwalletd6 &>/dev/null; then
    ok "Keyring daemon running"
else
    warn "No keyring daemon detected. Install: apt install gnome-keyring"
fi

# Done
header "══════════════════════════════════════════════════════"
echo -e "${GREEN}${BOLD}  $APP installed!${NC}"
echo -e "  Run:     ${CYAN}mountbridge${NC}"
echo -e "  Config:  ${CYAN}~/.config/mountbridge/mounts.json${NC}"
echo -e "  Mounts:  ${CYAN}~/.mounts/${NC}"
header "══════════════════════════════════════════════════════"
