"""Network discovery: SMB broadcast via Avahi, SMB shares, NFS exports."""
import subprocess
import threading

from gi.repository import GLib


class Discovery:
    """Fire-and-forget network scan methods; results delivered via GLib.idle_add callback."""

    def smb_broadcast(self, cb):
        """Discover SMB/CIFS hosts on the local network via Avahi mDNS."""
        def _work():
            results = []
            try:
                r = subprocess.run(
                    ["avahi-browse", "-t", "-r", "-p", "_smb._tcp", "--no-db-lookup"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in r.stdout.splitlines():
                    if line.startswith("=") and ";IPv4;" in line:
                        cols = line.split(";")
                        if len(cols) >= 7:
                            host = cols[6].strip()
                            if host:
                                results.append(
                                    {"host": host, "share": None,
                                     "type": "smb", "detail": "avahi"}
                                )
            except Exception:
                pass
            GLib.idle_add(cb, results)

        threading.Thread(target=_work, daemon=True).start()

    def smb_shares(self, host: str, user: str, pw: str, cb):
        """List shares on a specific SMB host using smbclient."""
        def _work():
            shares = []
            try:
                u = f"{user}%{pw}" if user and pw else (user or "guest")
                r = subprocess.run(
                    ["smbclient", "-L", host, "-U", u],
                    capture_output=True, text=True, timeout=10,
                )
                for line in r.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] in ("Disk", "disk"):
                        shares.append(parts[0])
            except Exception:
                pass
            GLib.idle_add(cb, host, shares)

        threading.Thread(target=_work, daemon=True).start()

    def nfs_exports(self, host: str, cb):
        """List NFS exports on a specific host using showmount."""
        def _work():
            exports = []
            try:
                r = subprocess.run(
                    ["showmount", "-e", "--no-headers", host],
                    capture_output=True, text=True, timeout=10,
                )
                for line in r.stdout.splitlines():
                    p = line.split()
                    if p:
                        exports.append(p[0])
            except Exception:
                pass
            GLib.idle_add(cb, host, exports)

        threading.Thread(target=_work, daemon=True).start()
