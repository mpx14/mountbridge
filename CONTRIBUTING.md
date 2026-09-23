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

# 3. Create a dev venv that can see apt's python3-gi, with ruff/mypy/pytest
make install-dev

# 4. Run from source
.venv/bin/mountbridge

# 5. Before committing
make check        # ruff + pytest — the same as CI
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
| `parsing.py` | Pure parsers/validators — mountinfo, discovery output, hostnames |
| `discovery.py` | Avahi / smbclient / showmount — all async via threads |
| `widgets.py` | All GTK widget subclasses |
| `window.py` | `MainWindow`, `MountBridgeApp`, tray, `main()` entry point |

Keep GTK imports out of `models.py`, `parsing.py`, `store.py` and `ops.py` —
those modules must remain importable without a display server for unit testing.

`data/mountbridge-helper` runs as root and is the security boundary for NFS/SMB.
Changes to it need a test in `tests/test_helper.py`, and any new mount option
must be added to its allow-list deliberately.

---

## Pull requests

1. Branch from `main`: `git checkout -b feature/my-thing`
2. Keep commits focused — one logical change per commit
3. Run `make check` — lint and tests must pass
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
