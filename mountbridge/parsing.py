"""Pure parsing and validation helpers — no GTK, no I/O side effects.

Everything here is covered by tests/ and must stay importable without gi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── /proc/self/mountinfo ─────────────────────────────────────────────────────

_OCTAL = re.compile(r"\\([0-7]{3})")


def unescape(s: str) -> str:
    r"""Decode the kernel's octal escapes (\040 space, \011 tab, \012 newline, \134 backslash)."""
    return _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), s)


@dataclass(frozen=True)
class MountEntry:
    mountpoint: str
    fstype: str
    source: str
    options: str  # per-mount options + superblock options, comma-joined


def parse_mountinfo(text: str) -> list[MountEntry]:
    """Parse /proc/self/mountinfo. See proc(5).

    Format: id parent maj:min root mountpoint mount_opts [optional...] - fstype source super_opts
    """
    out: list[MountEntry] = []
    for line in text.splitlines():
        pre, sep, post = line.partition(" - ")
        if not sep:
            continue
        left, right = pre.split(), post.split()
        if len(left) < 6 or len(right) < 2:
            continue
        super_opts = right[2] if len(right) > 2 else ""
        out.append(MountEntry(
            mountpoint=unescape(left[4]),
            fstype=right[0],
            source=unescape(right[1]),
            options=",".join(o for o in (left[5], super_opts) if o),
        ))
    return out


def read_mounts(path: str = "/proc/self/mountinfo") -> list[MountEntry]:
    """Read the mount table. Never stats any mountpoint, so a hung NFS server cannot block it."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            return parse_mountinfo(f.read())
    except OSError:
        return []


# ── Names and hosts ──────────────────────────────────────────────────────────

_SLUG_BAD = re.compile(r"[^a-z0-9._-]+")


def slugify(name: str, fallback: str = "mount") -> str:
    """Turn a display name into a safe single path component: [a-z0-9._-], max 64 chars."""
    s = _SLUG_BAD.sub("-", name.lower()).strip("-._")[:64].strip("-._")
    return s or fallback


_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
_HOST = re.compile(rf"^(?:{_LABEL}(?:\.{_LABEL})*\.?|\[[0-9A-Fa-f:.]+\])$")


def valid_host(host: str) -> bool:
    """Hostname, IPv4 address or bracketed IPv6 address. Rejects leading '-' (option injection)."""
    return bool(host) and len(host) <= 253 and bool(_HOST.match(host))


# ── Discovery tool output ────────────────────────────────────────────────────

def parse_avahi(stdout: str) -> list[dict]:
    """Parse `avahi-browse -t -r -p _smb._tcp` output into unique hosts."""
    seen: dict[str, dict] = {}
    for line in stdout.splitlines():
        if not line.startswith("="):
            continue
        cols = line.split(";")
        if len(cols) < 9:
            continue
        host, addr = cols[6].strip(), cols[7].strip()
        if not valid_host(host) or host in seen:
            continue
        seen[host] = {"host": host, "share": None, "type": "smb", "detail": addr or "avahi"}
    return list(seen.values())


def parse_smbclient(stdout: str) -> list[str]:
    """Parse `smbclient -g -L host` (grepable) output: lines like `Disk|name|comment`."""
    shares = []
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and parts[0] == "Disk" and parts[1] and not parts[1].endswith("$"):
            shares.append(parts[1])
    return shares


def parse_showmount(stdout: str) -> list[str]:
    """Parse `showmount -e --no-headers host` output. Export paths may contain spaces."""
    exports = []
    for line in stdout.splitlines():
        line = line.rstrip()
        if not line.startswith("/"):
            continue
        # The client list is the last whitespace-separated field.
        path = line.rsplit(None, 1)[0] if " " in line or "\t" in line else line
        exports.append(path.rstrip())
    return exports
