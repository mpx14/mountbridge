---
name: Bug report
about: Something isn't working
title: "[BUG] "
labels: bug
assignees: ''
---

## Describe the bug

A clear description of what the bug is.

## Steps to reproduce

1. Open MountBridge
2. Click '...'
3. See error

## Expected behaviour

What you expected to happen.

## Actual behaviour

What actually happened. If there is a traceback, paste the full output of running `mountbridge` from a terminal.

```
paste traceback here
```

## Environment

- **Debian/Ubuntu version:** (`lsb_release -a`)
- **Python version:** (`python3 --version`)
- **GTK version:** (`python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print(Gtk.get_major_version(), Gtk.get_minor_version())"`)
- **Desktop environment:** XFCE / other
- **MountBridge version:** (`mountbridge --version` or from `pyproject.toml`)

## Mount type affected

- [ ] NFS
- [ ] SMB / CIFS
- [ ] SSHFS
- [ ] Not mount-type specific

## Additional context

Any other relevant context, config excerpts (redact passwords/hostnames as needed), or screenshots.
