# Contributing to MountBridge

Thank you for considering a contribution. This document covers the workflow for
bug reports, feature requests and pull requests.

---

## Reporting bugs

Use the **Bug report** issue template. Please include:

- Output of `mountbridge` run from a terminal (captures tracebacks)
- Debian/Ubuntu version: `lsb_release -a`
- Python version: `python3 --version`
- GTK version: `python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print(Gtk.get_major_version(), Gtk.get_minor_version())"`
- Whether the issue is specific to NFS, SMB or SSHFS
- Steps to reproduce

---

## Requesting features

Use the **Feature request** issue template. Describe the use case and the
expected behaviour — a mockup or description of the UI change is helpful.

---

## Development setup

```bash
# 1. Fork and clone
git clone https://github.com/yourusername/mountbridge.git
cd mountbridge

# 2. Install system deps (GTK3 bindings are not pip-installable)
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
                 gir1.2-notify-0.7 python3-keyring

# 3. Install in editable mode
pip install --user --break-system-packages -e .

# 4. Install dev tools
pip install --user --break-system-packages ruff mypy

# 5. Run from source
mountbridge
```

---

## Code style

- **Formatter / linter:** `ruff` — run `make fmt` before committing
- **Line length:** 100
- **Imports:** `isort`-compatible (ruff handles this)
- All public functions and classes should have a one-line docstring

```bash
make lint    # check
make fmt     # auto-fix
```

---

## Module layout

| Module | Responsibility |
|---|---|
| `constants.py` | App ID, paths, GTK CSS string |
| `models.py` | `MountConfig`, `LiveMount`, enums — no GTK imports |
| `store.py` | JSON config on disk + keyring credential store |
| `ops.py` | `MountOps` (mount/unmount) + `LiveMountScanner` |
| `discovery.py` | Avahi / smbclient / showmount — all async via threads |
| `widgets.py` | All GTK widget subclasses |
| `window.py` | `MainWindow`, `MountBridgeApp`, tray, `main()` entry point |

Keep GTK imports out of `models.py`, `store.py` and `ops.py` — those modules
must remain importable without a display server for unit testing.

---

## Pull requests

1. Branch from `main`: `git checkout -b feature/my-thing`
2. Keep commits focused — one logical change per commit
3. Run `make lint` — no new lint errors
4. Update `CHANGELOG.md` under `[Unreleased]`
5. Open the PR against `main`; fill in the PR template

---

## Commit message format

```
type(scope): short description

Longer explanation if needed.
```

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `style`

Examples:
```
feat(ops): add NFSv4 mount support
fix(window): guard _nav_selected against early lb access
docs(readme): add keyring setup section
```
