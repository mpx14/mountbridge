"""Network discovery: SMB hosts via Avahi, SMB shares, NFS exports.

Discovered hostnames come from the network, so they are validated before use
and every subprocess gets stdin=/dev/null (nothing may block on a prompt).
"""
import os
import subprocess
import tempfile
import threading

from gi.repository import GLib

from .parsing import parse_avahi, parse_showmount, parse_smb_error, parse_smbclient, valid_host


def _run_full(cmd, timeout=10) -> tuple[str, str]:
    """Run cmd; return (stdout, stderr). Never raises; a missing binary is reported in stderr."""
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout, r.stderr
    except FileNotFoundError:
        return "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return "", "NT_STATUS_IO_TIMEOUT"
    except (OSError, subprocess.SubprocessError) as e:
        return "", str(e)


def _run(cmd, timeout=10) -> str:
    return _run_full(cmd, timeout)[0]


def _thread(fn):
    threading.Thread(target=fn, daemon=True).start()


class Discovery:
    """Fire-and-forget network scans; results delivered on the main loop via GLib.idle_add."""

    def smb_broadcast(self, cb):
        """Discover SMB/CIFS hosts on the local network via Avahi mDNS."""
        def _work():
            out = _run(["avahi-browse", "-t", "-r", "-p", "--no-db-lookup", "_smb._tcp"])
            GLib.idle_add(cb, parse_avahi(out))
        _thread(_work)

    def smb_shares(self, host: str, user: str, pw: str, cb, domain: str = ""):
        """List shares on an SMB host. Anonymous unless user is given.

        cb(host, shares, error) — error is a user-facing message or None.
        """
        def _work():
            if not valid_host(host):
                GLib.idle_add(cb, host, [], "Invalid hostname.")
                return
            authfile = None
            try:
                if user:
                    # Credentials via a 0600 auth file, never argv (`-U user%pw` shows in ps).
                    rundir = os.environ.get("XDG_RUNTIME_DIR") or None
                    fd, authfile = tempfile.mkstemp(dir=rundir, prefix="mountbridge-smb-")
                    with os.fdopen(fd, "w") as f:
                        f.write(f"username={user}\npassword={pw or ''}\n")
                        if domain:
                            f.write(f"domain={domain}\n")
                    auth = ["-A", authfile]
                else:
                    auth = ["-N"]
                out, err = _run_full(["smbclient", "-g", "-L", host] + auth, timeout=15)
            finally:
                if authfile:
                    os.unlink(authfile)
            shares = parse_smbclient(out)
            error = None if shares else (parse_smb_error(err + out)
                                         or (err.strip().splitlines() or [None])[-1])
            GLib.idle_add(cb, host, shares, error)
        _thread(_work)

    def nfs_exports(self, host: str, cb):
        """List NFS exports on a host using showmount (NFSv3 mountd; NFSv4-only servers won't answer)."""
        def _work():
            out = _run(["showmount", "-e", "--no-headers", host]) if valid_host(host) else ""
            GLib.idle_add(cb, host, parse_showmount(out))
        _thread(_work)
