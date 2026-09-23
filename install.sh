#!/usr/bin/env bash
# MountBridge — installer for Debian / XFCE
set -euo pipefail

APP="MountBridge"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER_DST="/usr/local/libexec/mountbridge-helper"
SUDOERS_DST="/etc/sudoers.d/mountbridge"
GROUP="mountbridge"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}→${NC}  $*"; }
ok()     { echo -e "${GREEN}✓${NC}  $*"; }
warn()   { echo -e "${YELLOW}⚠${NC}  $*"; }
err()    { echo -e "${RED}✗${NC}  $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

header "=== $APP Installer ==="
[[ $EUID -eq 0 ]] && { err "Do not run as root."; exit 1; }
if dpkg-query -W -f='${Status}' mountbridge 2>/dev/null | grep -q "install ok installed"; then
    err "MountBridge is installed as a Debian package. Update it with apt, or remove it"
    err "(sudo apt remove mountbridge) before using install.sh."
    exit 1
fi

# 1. System packages
header "1. System packages"
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-notify-0.7 \
    python3-keyring python3-secretstorage \
    sshfs cifs-utils nfs-common \
    avahi-utils smbclient pipx
ok "Core packages installed"

if sudo apt-get install -y gir1.2-ayatanaappindicator3-0.1 2>/dev/null; then
    ok "Ayatana AppIndicator installed"
elif sudo apt-get install -y gir1.2-appindicator3-0.1 2>/dev/null; then
    ok "AppIndicator3 installed"
else
    warn "AppIndicator unavailable — tray will use StatusIcon fallback"
fi

# 2. Python package (pipx venv that can still see apt's python3-gi)
header "2. Python package"
if python3 -m pip show --quiet mountbridge 2>/dev/null; then
    info "Removing previous pip --user install"
    python3 -m pip uninstall -y --break-system-packages mountbridge || true
fi
# Uninstall first rather than `pipx install --force`: with a uv backend (Debian's
# pipx when uv is on PATH), --force fails because the venv already exists.
if pipx list --short 2>/dev/null | grep -q '^mountbridge '; then
    info "Removing previous pipx install"
    pipx uninstall mountbridge >/dev/null
fi
pipx install --system-site-packages "${REPO_DIR}"
pipx ensurepath >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"
ok "MountBridge installed ($(command -v mountbridge))"

# 3. Directories
header "3. Directories"
mkdir -p "$HOME/.mounts" "$HOME/.config/mountbridge"
chmod 700 "$HOME/.config/mountbridge"
ok "$HOME/.mounts and $HOME/.config/mountbridge ready"

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
read -rp "Start MountBridge in the tray automatically on login? [y/N] " ans_auto
if [[ "$ans_auto" =~ ^[Yy]$ ]]; then
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/mountbridge.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=MountBridge
Exec=$HOME/.local/bin/mountbridge --hidden
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Network Mount Manager
DESKTOP
    ok "Autostart entry created"
else
    info "Skipping autostart"
fi

# 6. Root helper + sudoers (NFS/SMB)
header "6. NFS/SMB root helper"
echo "NFS and SMB mounts need root. MountBridge installs a small validating helper"
echo "at $HELPER_DST, and a sudoers rule that lets members of the '$GROUP' group"
echo "run only that helper. You ($USER) will be added to the group."
SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT
sed "s|@HELPER@|$HELPER_DST|g" "$REPO_DIR/data/mountbridge.sudoers" > "$SUDOERS_TMP"
echo ""; grep -v '^#' "$SUDOERS_TMP" | sed '/^$/d'; echo ""
if [[ -f "$SUDOERS_DST" ]] && sudo grep -q "/bin/mount" "$SUDOERS_DST"; then
    warn "An older MountBridge sudoers rule granting mount/umount is installed."
    warn "It allows root access — replacing it is strongly recommended."
fi
read -rp "Install the helper and this sudoers rule? [y/N] " ans_sudo
if [[ "$ans_sudo" =~ ^[Yy]$ ]]; then
    if ! sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
        err "Generated sudoers rule failed validation — nothing installed"
        exit 1
    fi
    getent group "$GROUP" >/dev/null || sudo groupadd --system "$GROUP"
    sudo install -D -o root -g root -m 755 "$REPO_DIR/data/mountbridge-helper" "$HELPER_DST"
    sudo install -o root -g root -m 440 "$SUDOERS_TMP" "$SUDOERS_DST"
    ok "Helper installed at $HELPER_DST; sudoers rule at $SUDOERS_DST"
    if id -nG "$USER" | tr ' ' '\n' | grep -qx "$GROUP"; then
        ok "$USER is in the '$GROUP' group"
    else
        sudo usermod -aG "$GROUP" "$USER"
        warn "Added $USER to the '$GROUP' group — log out and back in before mounting NFS/SMB"
    fi
    info "Other users get NFS/SMB access with: sudo adduser <user> $GROUP"
else
    if [[ -f "$SUDOERS_DST" ]] && sudo grep -q "/bin/mount" "$SUDOERS_DST"; then
        read -rp "Remove the old (unsafe) rule anyway? [Y/n] " ans_rm
        [[ "$ans_rm" =~ ^[Nn]$ ]] || { sudo rm -f "$SUDOERS_DST"; ok "Old rule removed"; }
    fi
    warn "Skipped — NFS/SMB mounting will not work until the helper is installed"
fi

# 7. Keyring check
header "7. Keyring"
if pgrep -x gnome-keyring-daemon &>/dev/null || pgrep -x kwalletd5 &>/dev/null || pgrep -x kwalletd6 &>/dev/null; then
    ok "Keyring daemon running"
else
    warn "No keyring daemon detected. Install: sudo apt install gnome-keyring"
fi

# Done
header "══════════════════════════════════════════════════════"
echo -e "${GREEN}${BOLD}  $APP installed!${NC}"
echo -e "  Run:        ${CYAN}mountbridge${NC}"
echo -e "  Config:     ${CYAN}~/.config/mountbridge/mounts.json${NC}"
echo -e "  NFS/SMB:    ${CYAN}/mnt/mountbridge/$USER/<name>${NC} (linked from ~/.mounts/)"
echo -e "  SSHFS:      ${CYAN}~/.mounts/<name>${NC}"
header "══════════════════════════════════════════════════════"
