# MountBridge

> A network mount manager for **XFCE / Debian** — NFS, SMB/CIFS and SSHFS with system keyring credential storage, live mount discovery and a clean native GTK3 UI.

![License](https://img.shields.io/badge/license-GPLv3-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![GTK](https://img.shields.io/badge/GTK-3.0-green)
![Platform](https://img.shields.io/badge/platform-Debian%20%2F%20XFCE-orange)

---

## Features

| Feature | Detail |
|---|---|
| **Mount types** | NFS, SMB/CIFS, SSHFS |
| **Credentials** | Stored in the system keyring (gnome-keyring / KWallet via SecretService — never written to disk in plaintext) |
| **Live mount detection** | Scans `/proc/mounts` on startup and every 12 s — unmanaged NFS/SMB/SSHFS mounts appear automatically with an **Import** button |
| **Network discovery** | SMB broadcast via Avahi mDNS · SMB share listing via `smbclient` · NFS export listing via `showmount` |
| **Auto-mount** | Per-mount toggle, fires in a background thread at login |
| **XFCE native** | Uses xfwm4 server-side decorations (no GTK CSD) — title bar, min/max/close behave normally |
| **System tray** | Ayatana AppIndicator3 with Open/Quit menu; falls back to `Gtk.StatusIcon` |
| **Notifications** | libnotify desktop notification on mount/unmount success or failure |
| **Keyboard shortcut** | Ctrl+N — add a new mount from anywhere |

---

## Requirements

### Debian / Ubuntu packages

```bash
sudo apt install \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-notify-0.7 \
    python3-keyring python3-secretstorage \
    sshfs cifs-utils nfs-common sshpass \
    avahi-utils samba-common-bin \
    gnome-keyring
```

### Optional (system tray icon)

```bash
# Prefer Ayatana (modern):
sudo apt install libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1
# Or legacy:
sudo apt install libappindicator3-1 gir1.2-appindicator3-0.1
```

---

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/yourusername/mountbridge.git
cd mountbridge
bash install.sh
```

The installer will:

1. Install all `apt` and `pip` dependencies
2. Install the `mountbridge` package into `~/.local`
3. Create `~/.mounts/` and `~/.config/mountbridge/`
4. Install the `.desktop` entry and SVG icon
5. Optionally create an XFCE autostart entry
6. Optionally install a scoped `sudoers` rule for passwordless NFS/SMB mounting
7. Optionally enable `user_allow_other` in `/etc/fuse.conf` for SSHFS

### Manual install

```bash
pip install --user --break-system-packages .
mountbridge
```

---

## Sudoers (NFS / SMB)

SSHFS is fully userspace — no `sudo` is ever needed. NFS and SMB/CIFS mounts call `sudo mount`, which requires either your password each time or a scoped sudoers rule.

The installer offers to install `/etc/sudoers.d/mountbridge` automatically. To do it manually:

```bash
sudo install -m 440 data/mountbridge.sudoers /etc/sudoers.d/mountbridge
sudo vim /etc/sudoers.d/mountbridge   # replace %USER% with your username
sudo visudo -cf /etc/sudoers.d/mountbridge
```

---

## Keyring setup (XFCE)

MountBridge uses the SecretService API. On a fresh XFCE install:

1. `sudo apt install gnome-keyring`
2. **Session and Startup → Application Autostart** → Add:
   - Command: `/usr/bin/gnome-keyring-daemon --start`
3. Log out and back in

---

## Configuration

Config lives in `~/.config/mountbridge/mounts.json`. Passwords are **not** stored there — they live exclusively in the system keyring under service name `mountbridge`.

### Example entry

```json
{
  "id": "a1b2c3d4",
  "name": "Home NAS",
  "mount_type": "nfs",
  "host": "192.168.1.10",
  "remote_path": "/export/media",
  "local_path": "/home/ben/.mounts/home-nas",
  "options": "rw,soft,timeo=30",
  "auto_mount": true,
  "created_at": "2024-11-01T09:00:00"
}
```

---

## Project structure

```
mountbridge/
├── mountbridge/           # Python package
│   ├── __init__.py
│   ├── constants.py       # APP_ID, paths, GTK CSS
│   ├── models.py          # MountConfig, LiveMount, enums
│   ├── store.py           # ConfigStore (JSON) + CredentialStore (keyring)
│   ├── ops.py             # MountOps + LiveMountScanner
│   ├── discovery.py       # Avahi/smbclient/showmount discovery
│   ├── widgets.py         # GTK widget classes
│   └── window.py          # MainWindow + MountBridgeApp
├── bin/
│   └── mountbridge        # CLI entry point
├── data/
│   ├── mountbridge.desktop
│   ├── mountbridge.sudoers
│   └── icons/mountbridge.svg
├── install.sh
├── Makefile
├── pyproject.toml
└── README.md
```

---

## Uninstalling

```bash
pip uninstall mountbridge
rm -f ~/.local/share/applications/mountbridge.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/mountbridge.svg
rm -f ~/.config/autostart/mountbridge.desktop
sudo rm -f /etc/sudoers.d/mountbridge
# Optionally remove config:
rm -rf ~/.config/mountbridge
rmdir --ignore-fail-on-non-empty ~/.mounts
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[GNU General Public License v3.0](LICENSE)
