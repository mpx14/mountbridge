# Changelog

All notable changes to MountBridge are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.1.0] — 2024-11-xx

### Added
- **Live mount detection** — scans `/proc/mounts` on startup and every 12 s;
  unmanaged NFS, SMB/CIFS and SSHFS mounts appear in a separate "Unmanaged Live
  Mounts" section with amber highlight border and LIVE badge
- **Import to Config** — pre-fills the add dialog from a live unmanaged mount
  (host, remote path, local path, username, port all populated automatically)
- **Unmount unmanaged** — unmount a live mount directly without importing it
- **Section divider rows** — visual separator between managed and unmanaged
  sections in the mount list
- **`LiveMountScanner`** class parsing nfs4, cifs and fuse.sshfs entries from
  `/proc/mounts` including kernel octal-escape decoding for paths with spaces
- Status bar now shows `• N unmanaged` when unmanaged mounts are present
- Sidebar type-filter badges count unmanaged mounts alongside managed ones
- Modular package structure: `constants`, `models`, `store`, `ops`, `discovery`,
  `widgets`, `window` modules

### Fixed
- **Window decorations missing on XFCE** — replaced `Gtk.HeaderBar` +
  `set_titlebar()` (GTK CSD) with a plain toolbar `Gtk.Box`; xfwm4 now renders
  the native title bar with min/max/close buttons correctly
- **`AttributeError: 'MainWindow' has no attribute 'lb'`** on startup —
  `select_row()` was called inside `_build_sidebar()` before `self.lb` was
  created; moved to end of `_build()` with a `hasattr` guard
- `CssProvider.load_from_data()` now receives bytes (`CSS.encode("utf-8")`)
  instead of a plain string

---

## [1.0.0] — 2024-10-xx

### Added
- Initial release
- Native GTK3 UI with XFCE-compatible styling
- NFS, SMB/CIFS and SSHFS mount management
- System keyring credential storage via `python3-keyring` / SecretService
- Network discovery: SMB broadcast (Avahi), SMB shares (`smbclient`),
  NFS exports (`showmount`)
- Per-mount auto-mount on login
- Ayatana AppIndicator3 system tray with Open/Quit menu
- libnotify desktop notifications on mount/unmount
- Sidebar navigation with per-type filters and count badges
- Search bar
- Ctrl+N keyboard shortcut to add a mount
- `install.sh` with interactive sudoers and FUSE configuration
