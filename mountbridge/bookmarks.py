"""GTK file-chooser / file-manager bookmarks (~/.config/gtk-3.0/bookmarks).

Thunar, Nautilus, Nemo, Caja and GTK file dialogs all read this file, so a
bookmark here puts a mount in the file manager's side pane. That matters for
NFS/SMB: the real mountpoints live under /mnt/mountbridge/, which GIO does
not list in side panes on its own.

Format: one entry per line, "<file URI>[ <label>]". Lines we don't own are
preserved byte-for-byte. No GTK import, so this is testable without a display.
"""
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def bookmarks_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "gtk-3.0" / "bookmarks"


def _uri(path: str) -> str:
    return Path(os.path.abspath(os.path.expanduser(path))).as_uri()


def _path_of(line: str) -> Optional[str]:
    """Local path a bookmark line points at, or None for remote/blank lines."""
    uri = line.split(" ", 1)[0].strip()
    p = urlparse(uri)
    if p.scheme != "file":
        return None
    return os.path.normpath(unquote(p.path))


def _read(f: Path) -> List[str]:
    try:
        return f.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _write(f: Path, lines: List[str]) -> None:
    # Follow a symlinked bookmarks file (dotfile managers) instead of
    # replacing the link with a regular file.
    target = Path(os.path.realpath(f))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".bookmarks.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in lines))
        try:
            os.chmod(tmp, os.stat(target).st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def has(path: str, f: Optional[Path] = None) -> bool:
    want = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    return any(_path_of(line) == want for line in _read(f or bookmarks_file()))


def add(path: str, label: str, f: Optional[Path] = None) -> bool:
    """Append a bookmark unless one for path exists. Returns True if written."""
    f = f or bookmarks_file()
    if has(path, f):
        return False
    label = _CTRL.sub("", label).strip()
    lines = _read(f)
    lines.append(f"{_uri(path)} {label}" if label else _uri(path))
    _write(f, lines)
    return True


def remove(path: str, f: Optional[Path] = None) -> bool:
    """Drop every bookmark for path. Returns True if anything was removed."""
    f = f or bookmarks_file()
    want = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    lines = _read(f)
    kept = [line for line in lines if _path_of(line) != want]
    if len(kept) == len(lines):
        return False
    _write(f, kept)
    return True
