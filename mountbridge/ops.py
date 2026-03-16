"""Mount and unmount operations, plus /proc/mounts live scanner."""
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from .constants import CONFIG_DIR
from .models import MountConfig, MountType, LiveMount
from .store import CredentialStore


class MountOps:
    """Executes mount and unmount commands for all supported filesystem types."""

    def __init__(self, creds: CredentialStore):
        self.creds = creds

    # ── Status ────────────────────────────────────────────────────────────────

    def is_mounted(self, m: MountConfig) -> bool:
        target = os.path.realpath(m.local_path)
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and os.path.realpath(parts[1]) == target:
                        return True
        except Exception:
            pass
        return False

    # ── Mount ─────────────────────────────────────────────────────────────────

    def mount(self, m: MountConfig) -> tuple:
        Path(m.local_path).mkdir(parents=True, exist_ok=True)
        if self.is_mounted(m):
            return True, "Already mounted"
        t = MountType(m.mount_type)
        if t == MountType.SSHFS:
            return self._sshfs(m)
        if t == MountType.SMB:
            return self._smb(m)
        if t == MountType.NFS:
            return self._nfs(m)
        return False, "Unknown type"

    def _sshfs(self, m: MountConfig) -> tuple:
        pw     = self.creds.get(m.id)
        port   = m.port or 22
        user   = m.username or os.environ.get("USER", "")
        remote = (f"{user}@{m.host}:{m.remote_path}" if user
                  else f"{m.host}:{m.remote_path}")

        cmd = []
        if pw and not m.ssh_key:
            cmd += ["sshpass", "-p", pw]
        cmd += ["sshfs"]
        if m.ssh_key:
            cmd += ["-o", f"IdentityFile={m.ssh_key}"]
        cmd += [
            "-p", str(port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "reconnect",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
        ]
        for opt in (m.options or "").split(","):
            opt = opt.strip()
            if opt:
                cmd += ["-o", opt]
        cmd += [remote, m.local_path]
        return self._run(cmd, 30, "sshfs not found — install: apt install sshfs")

    def _smb(self, m: MountConfig) -> tuple:
        pw       = self.creds.get(m.id) or ""
        user     = m.username or "guest"
        uid, gid = os.getuid(), os.getgid()

        cf = CONFIG_DIR / f".creds_{m.id}"
        cf.write_text(f"username={user}\npassword={pw}\n")
        cf.chmod(0o600)

        src  = f"//{m.host}/{m.remote_path.lstrip('/')}"
        opts = f"credentials={cf},uid={uid},gid={gid},file_mode=0644,dir_mode=0755"
        if m.domain:
            opts += f",domain={m.domain}"
        if m.options:
            opts += f",{m.options}"

        cmd     = ["sudo", "mount", "-t", "cifs", src, m.local_path, "-o", opts]
        ok, msg = self._run(cmd, 30, "mount.cifs not found — install: apt install cifs-utils")
        cf.unlink(missing_ok=True)
        return ok, msg

    def _nfs(self, m: MountConfig) -> tuple:
        src  = f"{m.host}:{m.remote_path}"
        opts = m.options or "rw,soft,timeo=30"
        cmd  = ["sudo", "mount", "-t", "nfs", src, m.local_path, "-o", opts]
        return self._run(cmd, 30, "mount.nfs not found — install: apt install nfs-common")

    # ── Unmount ───────────────────────────────────────────────────────────────

    def unmount(self, m: MountConfig) -> tuple:
        if not self.is_mounted(m):
            return True, "Not mounted"
        if MountType(m.mount_type) == MountType.SSHFS:
            cmd = ["fusermount", "-u", m.local_path]
        else:
            cmd = ["sudo", "umount", m.local_path]
        return self._run(cmd, 15)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, cmd, timeout, not_found_msg=None) -> tuple:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return True, "OK"
            return False, (r.stderr.strip() or r.stdout.strip() or "Command failed")
        except subprocess.TimeoutExpired:
            return False, "Timed out"
        except FileNotFoundError:
            return False, (not_found_msg or f"{cmd[0]} not found")
        except Exception as e:
            return False, str(e)


class LiveMountScanner:
    """Parses /proc/mounts and returns network mounts not tracked in config."""

    NET_FSTYPES = {"nfs", "nfs4", "cifs", "fuse.sshfs"}

    def scan(self, known_paths: set) -> List[LiveMount]:
        results = []
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    device, mountpoint, fstype, options = (
                        parts[0], parts[1], parts[2], parts[3]
                    )
                    if fstype not in self.NET_FSTYPES:
                        continue
                    mountpoint = self._unescape(mountpoint)
                    if mountpoint in known_paths:
                        continue
                    lm = self._parse(device, mountpoint, fstype, options)
                    if lm:
                        results.append(lm)
        except Exception as e:
            print(f"[scanner] {e}")
        return results

    def _unescape(self, s: str) -> str:
        return re.sub(r"\\0([0-7]{2})", lambda m: chr(int(m.group(1), 8)), s)

    def _parse(self, device: str, mountpoint: str,
               fstype: str, options: str) -> Optional[LiveMount]:
        try:
            if fstype in ("nfs", "nfs4"):
                if ":" not in device:
                    return None
                host, remote = device.split(":", 1)
                return LiveMount("nfs", device, mountpoint,
                                 host.strip(), remote or "/", options)

            elif fstype == "cifs":
                d = device.lstrip("/")
                if "/" not in d:
                    return None
                host, share = d.split("/", 1)
                username = next(
                    (o.split("=", 1)[1] for o in options.split(",")
                     if o.startswith("username=")), None
                )
                return LiveMount("smb", device, mountpoint,
                                 host, share, options, username=username)

            elif fstype == "fuse.sshfs":
                username, host_part = None, device
                if "@" in device:
                    username, host_part = device.split("@", 1)
                if ":" not in host_part:
                    return None
                host, remote = host_part.split(":", 1)
                port = None
                for opt in options.split(","):
                    if opt.startswith("port="):
                        try:
                            port = int(opt.split("=", 1)[1])
                        except ValueError:
                            pass
                return LiveMount("sshfs", device, mountpoint, host,
                                 remote or "/", options,
                                 username=username, port=port)
        except Exception as e:
            print(f"[scanner] parse error for {device}: {e}")
        return None
