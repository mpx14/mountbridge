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
| **Live mount detection** | Watches the kernel mount table (`/proc/self/mountinfo`) and updates instantly — unmanaged NFS/SMB/SSHFS mounts appear automatically with an **Import** button. Never stats a mountpoint, so a hung server can't freeze the UI |
| **Network discovery** | SMB broadcast via Avahi mDNS · SMB share listing via `smbclient` · NFS export listing via `showmount` |
| **Auto-mount** | Per-mount toggle; runs when MountBridge starts, waiting for the network if needed |
| **XFCE native** | Uses xfwm4 server-side decorations (no GTK CSD) — title bar, min/max/close behave normally |
| **System tray** | Ayatana AppIndicator3 with Open/Quit menu; falls back to `Gtk.StatusIcon`. Closing the window keeps MountBridge running in the tray |
| **Notifications** | libnotify desktop notification on mount/unmount success or failure |
| **Keyboard shortcuts** | Ctrl+N — add a mount · Ctrl+Q — quit |
| **Least privilege** | NFS/SMB go through a small validating root helper; SSHFS never uses root |

---

## Requirements

### Debian / Ubuntu packages

```bash
sudo apt install \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-notify-0.7 \
    python3-keyring python3-secretstorage \
    sshfs cifs-utils nfs-common \
    avahi-utils smbclient pipx \
    gnome-keyring
```

### Optional (system tray icon)

```bash
# Prefer Ayatana (modern):
sudo apt install gir1.2-ayatanaappindicator3-0.1
# Or legacy:
sudo apt install gir1.2-appindicator3-0.1
```

---

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/mpx14/mountbridge.git
cd mountbridge
bash install.sh
```

The installer will:

1. Install the `apt` dependencies
2. Install the `mountbridge` package with `pipx` (its venv can see apt's `python3-gi`)
3. Create `~/.mounts/` and `~/.config/mountbridge/`
4. Install the `.desktop` entry and SVG icon
5. Optionally create an XFCE autostart entry (starts minimised to the tray)
6. Optionally install the NFS/SMB root helper and its sudoers rule (and replace the unsafe rule from v1.1 if present)

### Manual install

```bash
pipx install --system-site-packages .
mountbridge
```

NFS/SMB additionally need the helper and sudoers rule — see below.

---

## NFS / SMB and root

SSHFS is fully userspace — no root is ever involved. Mounting NFS and SMB/CIFS
requires root, so MountBridge uses a small root helper,
`/usr/local/libexec/mountbridge-helper`, and a sudoers rule that allows **only
that helper**:

```
ben ALL=(root) NOPASSWD: /usr/local/libexec/mountbridge-helper
```

The helper is the security boundary. It:

- mounts only `nfs`, `nfs4` and `cifs`, only at `/mnt/mountbridge/<user>/<name>`
  (a root-owned tree the user can't tamper with);
- accepts only allow-listed mount options, and always adds `nosuid,nodev`;
- forces `uid`/`gid` on CIFS mounts to the calling user;
- reads SMB credentials from stdin and never from the command line;
- unmounts only nfs/cifs mounts in the caller's own directory.

`~/.mounts/<name>` is created as a shortcut (symlink) to the real mountpoint.

> **Upgrading from 1.1:** the old rule granted `mount`/`umount` with wildcard
> arguments, which is equivalent to full root (for example `mount --bind` over
> `/etc`). `install.sh` detects and replaces it. If you're not re-running the
> installer, remove it now: `sudo rm /etc/sudoers.d/mountbridge`.

Manual install:

```bash
sudo install -D -o root -g root -m 755 data/mountbridge-helper /usr/local/libexec/mountbridge-helper
sed "s/%USER%/$USER/g" data/mountbridge.sudoers > /tmp/mb.sudoers
sudo visudo -cf /tmp/mb.sudoers && sudo install -o root -g root -m 440 /tmp/mb.sudoers /etc/sudoers.d/mountbridge
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
  "options": "rw,hard",
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
│   ├── parsing.py         # Pure parsers/validators (mountinfo, discovery output)
│   ├── discovery.py       # Avahi/smbclient/showmount discovery
│   ├── widgets.py         # GTK widget classes
│   └── window.py          # MainWindow + MountBridgeApp
├── data/
│   ├── mountbridge-helper # Root helper for NFS/SMB (installed to /usr/local/libexec)
│   ├── mountbridge.desktop
│   ├── mountbridge.sudoers
│   └── icons/mountbridge.svg
├── tests/                 # pytest suite (no display needed)
├── install.sh
├── Makefile
├── pyproject.toml
└── README.md
```

---

## Uninstalling

```bash
pipx uninstall mountbridge
rm -f ~/.local/share/applications/mountbridge.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/mountbridge.svg
rm -f ~/.config/autostart/mountbridge.desktop
sudo rm -f /etc/sudoers.d/mountbridge /usr/local/libexec/mountbridge-helper
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
