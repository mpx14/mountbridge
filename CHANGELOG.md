# Changelog

All notable changes to MountBridge are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.2.0] — Unreleased

### Security
- **Replaced the sudoers rule.** The 1.1 rule granted `mount`/`umount` with
  wildcard arguments, which let any process running as the user gain root
  (e.g. `sudo mount -t nfs --bind /tmp/x /etc`) and unmount arbitrary paths.
  NFS/SMB now go through `mountbridge-helper`, which allow-lists filesystem
  types and options, always adds `nosuid,nodev`, mounts only in a root-owned
  tree (`/mnt/mountbridge/<user>/`) and is the only command the new rule allows.
  `install.sh` detects and replaces the old rule.
- SSHFS passwords are passed with `-o password_stdin` instead of `sshpass -p`.
  sshpass overwrites its argv shortly after starting, so exposure was a brief
  race window, but it is now gone entirely; `sshpass` is no longer a dependency.
- SMB credentials are passed to the helper on stdin and written to a root-only
  file in `/run/mountbridge`; previously a user file was created world-readable
  and then `chmod`ed.
- Discovered hostnames are validated before use; `smbclient` credentials use
  an auth file instead of `-U user%pass`.
- `install.sh` no longer enables `user_allow_other` or adds the user to the
  obsolete `fuse` group.

### Fixed
- `pip install .` failed: invalid build backend `setuptools.backends.legacy`.
- UI could freeze on a hung NFS server: mount status called `realpath()` (stat)
  on every mountpoint in the system from the GTK main thread. Status now comes
  from `/proc/self/mountinfo` string comparison only.
- Mounts whose path contained a space never showed as mounted; `\134` escapes
  weren't decoded.
- The list was rebuilt every 12 s, resetting scroll position and dropping the
  "Working…" state mid-operation (allowing double mounts). Cards now update in
  place, driven by GIO's mount monitor; rebuilds happen only when needed.
- Closing the window quit the app (so the tray did nothing); tray icon objects
  could be garbage-collected.
- A corrupt `mounts.json` was silently replaced by an empty config on the next
  save. Writes are now atomic, and unreadable files are kept as
  `mounts.json.bad-<timestamp>`.
- Generated mount paths from display names could contain `/` or be absolute
  (`nas — /export` → `~/.mounts/nas__/export`); names are now slugified.
- `smbclient -L` could block on a password prompt; now uses `-N`/`-A` and
  grepable output (share names with spaces work).
- A locked keyring silently mounted SMB as guest; it now reports the error.
- Add/Edit dialog discarded invalid input on Save; it now validates in place.
- Removing a mounted entry deleted it even if unmount failed.
- "Open Folder" on an unreachable mount failed silently (the file manager's
  error was discarded); it now reports e.g. "Connection refused".
- A failure to save a password to the keyring was only printed to stderr; it
  is now shown in a dialog.
- `mountbridge --version`, referenced by the bug report template, didn't exist.
- Re-running `install.sh` failed with pipx's uv backend (`--force` can't
  replace an existing venv); it now uninstalls the old copy first.
- CI failed on its own lint config; `py.typed` was missing; `.[dev]` extra was
  undefined; sidebar layout gap; `Gdk` imported without a version.

### Added
- **Debian package** (`make deb`; built and install-tested in CI on Debian
  12/13/testing and Ubuntu 22.04/24.04). Installs the helper to
  `/usr/libexec/mountbridge/` and grants it to the `mountbridge` group.
- `mountbridge --help`; `--version`/`--help` work without a display.

### Changed
- NFS/SMB access is granted per **group** (`mountbridge`) instead of a sudoers
  rule naming one user, for both the package and `install.sh`. Users outside
  the group are told exactly what to ask their administrator.
- NFS default options are now `rw,hard` (was `rw,soft,timeo=30`, which risks
  silent data loss on writes; see nfs(5)).
- Busy unmounts offer a lazy unmount.
- Edit is disabled while a mount is active.
- Autostart launches minimised to the tray (`mountbridge --hidden`).
- Auto-mount waits for the network and reports failures.
- Installed with `pipx --system-site-packages` instead of
  `pip --break-system-packages`.
- Added a pytest suite (parsers, ops, store, root helper) and CI runs it on
  Python 3.11–3.14 along with shellcheck and a package build.
- Removed redundant `bin/mountbridge`.
- The version is defined once, in `pyproject.toml`; the app reads it from the
  installed package metadata and shows it in the window.

---

## [1.1.0] — 2026-03-16

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

[1.2.0]: https://github.com/mpx14/mountbridge/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mpx14/mountbridge/releases/tag/v1.1.0
