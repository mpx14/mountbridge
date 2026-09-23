"""Mount and unmount operations, plus the live-mount scanner.

NFS/SMB go through the root helper (data/mountbridge-helper) via `sudo -n`;
SSHFS runs entirely as the user. Nothing here stats a mountpoint to decide
whether it is mounted: status comes from /proc/self/mountinfo only, so a hung
server can't block the caller.
"""
import grp
import os
import pwd
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from .constants import HELPER, HELPER_GROUP, SYS_MOUNT_BASE
from .models import LiveMount, MountConfig, MountType
from .parsing import MountEntry, read_mounts, slugify
from .store import CredentialError, CredentialStore

Result = Tuple[bool, str]

NET_FSTYPES = {"nfs", "nfs4", "cifs", "fuse.sshfs"}
NFS_DEFAULT_OPTS = "rw,hard"
SMB_DEFAULT_OPTS = "file_mode=0644,dir_mode=0755"


def _norm(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path))


def helper_access_problem() -> Optional[str]:
    """Explain why this user can't use the NFS/SMB helper yet, or None if they can.

    Membership is checked in both the group database and the current session:
    after `adduser`, the new group only applies from the next login.
    """
    user = pwd.getpwuid(os.getuid()).pw_name
    try:
        group = grp.getgrnam(HELPER_GROUP)
    except KeyError:
        return None  # no group: an older per-user sudoers rule may apply; let sudo decide
    if group.gr_gid in os.getgroups() or os.getgid() == group.gr_gid:
        return None
    if user in group.gr_mem:
        return (f"You were added to the '{HELPER_GROUP}' group, but that only takes effect "
                "after you log out and back in.")
    return (f"Your account isn't allowed to mount NFS/SMB shares yet. An administrator "
            f"needs to run:\n\n    sudo adduser {user} {HELPER_GROUP}\n\n"
            "and then you need to log out and back in. (SSHFS mounts don't need this.)")


def mounted_paths(entries: Optional[Iterable[MountEntry]] = None) -> Set[str]:
    return {e.mountpoint for e in (read_mounts() if entries is None else entries)}


class MountOps:
    """Executes mount and unmount commands for all supported filesystem types."""

    def __init__(self, creds: CredentialStore):
        self.creds = creds

    # ── Paths / status ───────────────────────────────────────────────────────

    @staticmethod
    def helper_name(m: MountConfig) -> str:
        """Name of the root-owned mountpoint for an NFS/SMB mount."""
        return slugify(Path(m.local_path).name, fallback=m.id)

    def mountpoint(self, m: MountConfig) -> str:
        """Where the filesystem is actually mounted."""
        if m.mount_type == MountType.SSHFS:
            return _norm(m.local_path)
        return str(SYS_MOUNT_BASE / self.helper_name(m))

    def is_mounted(self, m: MountConfig, mounted: Optional[Set[str]] = None) -> bool:
        return self.mountpoint(m) in (mounted_paths() if mounted is None else mounted)

    # ── Mount ────────────────────────────────────────────────────────────────

    def mount(self, m: MountConfig) -> Result:
        if self.is_mounted(m):
            return True, "Already mounted"
        try:
            t = MountType(m.mount_type)
        except ValueError:
            return False, f"Unknown mount type: {m.mount_type}"
        try:
            if t == MountType.SSHFS:
                return self._sshfs(m)
            ok, msg = self._smb(m) if t == MountType.SMB else self._nfs(m)
        except CredentialError as e:
            return False, str(e)
        if ok:
            self._link(m)
        return ok, msg

    def _sshfs(self, m: MountConfig) -> Result:
        pw = None if m.ssh_key else self.creds.get(m.id)
        user = m.username or os.environ.get("USER", "")
        remote = f"{user}@{m.host}:{m.remote_path}" if user else f"{m.host}:{m.remote_path}"
        local = _norm(m.local_path)
        Path(local).mkdir(parents=True, exist_ok=True)

        cmd = ["sshfs", "-p", str(m.port or 22),
               "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=3"]
        if m.ssh_key:
            cmd += ["-o", f"IdentityFile={os.path.expanduser(m.ssh_key)}",
                    "-o", "BatchMode=yes", "-o", "reconnect"]
        elif pw:
            # Password goes over stdin, never argv. (reconnect can't re-send it.)
            cmd += ["-o", "password_stdin"]
        else:
            cmd += ["-o", "BatchMode=yes", "-o", "reconnect"]
        for opt in (m.options or "").split(","):
            if opt.strip():
                cmd += ["-o", opt.strip()]
        cmd += ["--", remote, local]
        return self._run(cmd, 30, "sshfs not found — install: apt install sshfs",
                         stdin=(pw + "\n") if pw and not m.ssh_key else None)

    def _smb(self, m: MountConfig) -> Result:
        pw = self.creds.get(m.id) or ""
        creds = ""
        if m.username:
            creds = f"username={m.username}\npassword={pw}\n"
            if m.domain:
                creds += f"domain={m.domain}\n"
        src = f"//{m.host}/{m.remote_path.strip('/')}"
        opts = ",".join(o for o in (SMB_DEFAULT_OPTS, m.options) if o)
        return self._helper(["mount", "cifs", src, self.helper_name(m), opts], stdin=creds)

    def _nfs(self, m: MountConfig) -> Result:
        src = f"{m.host}:{m.remote_path}"
        return self._helper(["mount", "nfs", src, self.helper_name(m),
                             m.options or NFS_DEFAULT_OPTS])

    def _link(self, m: MountConfig):
        """Point ~/.mounts/<name> (the configured local path) at the real mountpoint."""
        link, target = Path(_norm(m.local_path)), self.mountpoint(m)
        try:
            if link.is_symlink():
                if os.readlink(link) != target:
                    link.unlink()
                else:
                    return
            elif link.exists():
                if str(link) in mounted_paths():
                    return  # something is mounted there; leave it alone
                if link.is_dir() and not any(link.iterdir()):
                    link.rmdir()  # empty dir from an older version
                else:
                    return  # user data; never touch it
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
        except OSError as e:
            print(f"[ops] could not create link {link}: {e}")

    # ── Unmount ──────────────────────────────────────────────────────────────

    def unmount(self, m: MountConfig, lazy: bool = False) -> Result:
        if not self.is_mounted(m):
            return True, "Not mounted"
        if m.mount_type == MountType.SSHFS:
            return self._fuse_unmount(self.mountpoint(m), lazy)
        return self._helper(["umount", self.helper_name(m)] + (["--lazy"] if lazy else []))

    def unmount_live(self, lm: LiveMount, lazy: bool = False) -> Result:
        """Unmount a mount MountBridge didn't create."""
        if lm.mount_type == "sshfs":
            return self._fuse_unmount(lm.local_path, lazy)
        if Path(lm.local_path).parent == SYS_MOUNT_BASE:
            name = Path(lm.local_path).name
            return self._helper(["umount", name] + (["--lazy"] if lazy else []))
        # Works for fstab `user`/`users` mounts; anything else needs root.
        ok, msg = self._run(["umount"] + (["-l"] if lazy else []) + ["--", lm.local_path], 15)
        if not ok:
            msg += f"\n\nThis mount wasn't created by MountBridge. Unmount it with:\nsudo umount {lm.local_path}"
        return ok, msg

    def _fuse_unmount(self, path: str, lazy: bool) -> Result:
        return self._run(["fusermount", "-uz" if lazy else "-u", "--", path], 15)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _helper(self, args: List[str], stdin: Optional[str] = "") -> Result:
        if not os.path.exists(HELPER):
            return False, ("The MountBridge NFS/SMB helper is not installed. Install the "
                           "mountbridge package, or re-run install.sh.")
        problem = helper_access_problem()
        if problem:
            return False, problem
        ok, msg = self._run(["sudo", "-n", HELPER] + args, 60, stdin=stdin)
        if not ok and "sudo" in msg and ("password" in msg or "not allowed" in msg):
            msg = (f"Not authorised to run {HELPER}. Check that /etc/sudoers.d/mountbridge "
                   f"exists and that you're in the '{HELPER_GROUP}' group.\n\n" + msg)
        return ok, msg

    def _run(self, cmd, timeout, not_found_msg=None, stdin: Optional[str] = None) -> Result:
        try:
            r = subprocess.run(cmd, input=stdin if stdin is not None else "",
                               capture_output=True, text=True, timeout=timeout)
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
    """Returns network mounts from the mount table that aren't tracked in config."""

    def scan(self, known_paths: Set[str],
             entries: Optional[Iterable[MountEntry]] = None) -> List[LiveMount]:
        results = []
        for e in (read_mounts() if entries is None else entries):
            if e.fstype not in NET_FSTYPES or e.mountpoint in known_paths:
                continue
            lm = self._parse(e)
            if lm:
                results.append(lm)
        return results

    @staticmethod
    def _parse(e: MountEntry) -> Optional[LiveMount]:
        opts = e.options.split(",")

        def opt(name):
            return next((o.split("=", 1)[1] for o in opts if o.startswith(name + "=")), None)

        if e.fstype in ("nfs", "nfs4"):
            src = e.source
            if src.startswith("["):  # [v6addr]:/path
                host, sep, remote = src[1:].partition("]:")
            else:
                host, sep, remote = src.partition(":")
            if not sep or not host:
                return None
            return LiveMount("nfs", e.source, e.mountpoint, host, remote or "/", e.options)

        if e.fstype == "cifs":
            d = e.source.lstrip("/")
            if "/" not in d:
                return None
            host, share = d.split("/", 1)
            return LiveMount("smb", e.source, e.mountpoint, host, share, e.options,
                             username=opt("username"))

        if e.fstype == "fuse.sshfs":
            username, host_part = None, e.source
            if "@" in host_part:
                username, host_part = host_part.split("@", 1)
            if ":" not in host_part:
                return None
            host, remote = host_part.split(":", 1)
            port = opt("port")
            return LiveMount("sshfs", e.source, e.mountpoint, host, remote or "/",
                             e.options, username=username,
                             port=int(port) if port and port.isdigit() else None)
        return None
