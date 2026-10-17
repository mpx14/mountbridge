"""Mount and unmount operations, plus the live-mount scanner.

NFS/SMB go through the root helper (data/mountbridge-helper) via `sudo -n`;
SSHFS runs entirely as the user. Nothing here stats a mountpoint to decide
whether it is mounted: status comes from /proc/self/mountinfo only, so a hung
server can't block the caller.
"""
import grp
import os
import pwd
import socket
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from .constants import HELPER, HELPER_GROUP, MOUNTS_DIR, SYS_MOUNT_BASE
from .models import LiveMount, MountConfig, MountType
from .parsing import MountEntry, read_mounts, slugify
from .store import CredentialError, CredentialStore

Result = Tuple[bool, str]

NET_FSTYPES = {"nfs", "nfs4", "cifs", "fuse.sshfs"}
NFS_DEFAULT_OPTS = "rw,hard"
SMB_DEFAULT_OPTS = "file_mode=0644,dir_mode=0755"

# "Roaming" mounts (laptops hopping between networks) fail fast instead of hanging
# every process that touches them, and MountBridge reconnects them afterwards.
# softerr returns ETIMEDOUT after timeo*retrans (5 s x 2); a program that ignores
# write errors can lose data if the server vanishes mid-write — that's the trade.
NFS_ROAMING_OPTS = "softerr,timeo=50,retrans=2"
SMB_ROAMING_OPTS = "echo_interval=10"   # cifs is soft by default; notice a dead server in ~20 s

SERVER_UNREACHABLE = ("Detached. The server isn't reachable from this network yet; "
                      "it will be remounted when it is.")

# Probe command for a mountpoint. Run as a child process so a hung NFS server
# blocks (and gets killed in) the child, never MountBridge itself.
PROBE_CMD = ("stat", "-t", "--")


def _norm(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path))


_HARDNESS = {"hard", "soft", "softerr"}


def _opt_key(opt: str) -> str:
    key = opt.split("=", 1)[0]
    return "hard/soft" if key in _HARDNESS else key


def merge_options(*layers: Optional[str]) -> str:
    """Comma-join option strings. An option in a later layer replaces an earlier one
    with the same key; hard, soft and softerr count as the same key."""
    merged: dict = {}
    for layer in layers:
        for opt in (layer or "").split(","):
            opt = opt.strip()
            if opt:
                key = _opt_key(opt)
                merged.pop(key, None)
                merged[key] = opt
    return ",".join(merged.values())


def _opt_value(options: Optional[str], key: str) -> Optional[str]:
    for opt in (options or "").split(","):
        k, eq, v = opt.strip().partition("=")
        if eq and k == key:
            return v
    return None


_DEAD_MARKERS = ("timed out", "stale file handle", "transport endpoint is not connected",
                 "not responding", "host is down", "no route to host",
                 "network is unreachable")


def is_dead_error(msg: Optional[str]) -> bool:
    """Does an error message mean the server is gone (as opposed to busy/denied)?"""
    low = (msg or "").lower()
    return any(s in low for s in _DEAD_MARKERS)


def probe_path(path: str, timeout: float = 3.0) -> bool:
    """True if `path` answers a stat within `timeout` seconds.

    Hard NFS mounts wait in a killable sleep, so the child can be killed on
    timeout. Must still be called from a worker thread: a non-killable hang
    would otherwise stall the caller for up to a second while reaping.
    """
    try:
        p = subprocess.Popen(list(PROBE_CMD) + [path], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return True  # can't probe: don't declare a mount dead on our own failure
    try:
        return p.wait(timeout=timeout) == 0
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass  # stuck uninterruptibly; subprocess reaps it later
        return False


def host_reachable(host: str, port: int, timeout: float = 2.0,
                   unresolvable: bool = False) -> bool:
    """TCP-connect to host:port. Touches no filesystem, so it can't hang on a dead
    mount. Name resolution has no timeout of its own: call from a worker thread.
    `unresolvable` is returned when the name doesn't resolve (an ssh_config alias
    for SSHFS resolves only inside ssh)."""
    try:
        with socket.create_connection((host.strip("[]"), port), timeout=timeout):
            return True
    except socket.gaierror:
        return unresolvable
    except OSError:
        return False


def service_port(m: MountConfig) -> int:
    """TCP port the server must answer on for this mount to work."""
    if m.mount_type == MountType.SSHFS:
        return int(m.port or 22)
    port = _opt_value(m.options, "port")
    if port and port.isdigit():
        return int(port)
    return 445 if m.mount_type == MountType.SMB else 2049


ACCESS_OK, ACCESS_RELOGIN, ACCESS_NOT_MEMBER = "ok", "relogin", "not-member"
PKEXEC = "/usr/bin/pkexec"
ADDUSER = "/usr/sbin/adduser"


def current_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def helper_access_state() -> str:
    """ok / relogin (in the group database, not yet in this session) / not-member.

    sudo checks the running session's groups, and a new group membership only
    reaches a session at login — hence the separate 'relogin' state.
    """
    try:
        group = grp.getgrnam(HELPER_GROUP)
    except KeyError:
        return ACCESS_OK  # no group: an older per-user sudoers rule may apply; let sudo decide
    if group.gr_gid in os.getgroups() or os.getgid() == group.gr_gid:
        return ACCESS_OK
    if current_user() in group.gr_mem:
        return ACCESS_RELOGIN
    return ACCESS_NOT_MEMBER


def manual_grant_command(user: str) -> str:
    return f"sudo adduser {user} {HELPER_GROUP}"


def helper_access_problem() -> Optional[str]:
    """Explain why this user can't use the NFS/SMB helper yet, or None if they can."""
    state = helper_access_state()
    if state == ACCESS_RELOGIN:
        return (f"You were added to the '{HELPER_GROUP}' group, but that only takes effect "
                "after you log out and back in.")
    if state == ACCESS_NOT_MEMBER:
        return (f"Your account isn't allowed to mount NFS/SMB shares yet. An administrator "
                f"needs to run:\n\n    {manual_grant_command(current_user())}\n\n"
                "and then you need to log out and back in. (SSHFS mounts don't need this.)")
    return None


def grant_helper_access(user: str) -> Result:
    """Add `user` to the helper group via pkexec; polkit asks for an administrator's
    password in the desktop's usual dialog. Blocks until the dialog is answered."""
    manual = f"\n\nAn administrator can instead run:\n\n    {manual_grant_command(user)}"
    if not os.path.exists(PKEXEC):
        return False, "pkexec is not installed." + manual
    try:
        r = subprocess.run([PKEXEC, ADDUSER, user, HELPER_GROUP], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for authentication." + manual
    except OSError as e:
        return False, f"Could not run pkexec: {e}" + manual
    if r.returncode == 0:
        return True, f"{user} can now mount NFS/SMB shares after logging out and back in."
    if r.returncode == 126:
        return False, "Cancelled."
    if r.returncode == 127:
        return False, ("Not authorised, or no authentication agent is running "
                       "(the desktop's password dialog)." + manual)
    return False, (r.stderr.strip() or f"adduser failed (exit {r.returncode})") + manual


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
        except OSError as e:  # e.g. mkdir on a path under a dead mount
            return False, e.strerror or str(e)
        if ok:
            self._link(m)
        return ok, msg

    def reconnect(self, m: MountConfig) -> Result:
        """Force-detach a dead mount, then mount it again if the server answers.
        Returns (False, SERVER_UNREACHABLE) when detached but not yet remountable."""
        ok, msg = self.unmount(m, force=True)
        if not ok:
            return False, msg
        if not self.server_reachable(m):
            return False, SERVER_UNREACHABLE
        return self.mount(m)

    # ── Health ───────────────────────────────────────────────────────────────

    def probe(self, m: MountConfig) -> bool:
        """Is the mounted filesystem answering? Blocks up to ~4 s: worker threads only."""
        return probe_path(self.mountpoint(m))

    def server_reachable(self, m: MountConfig) -> bool:
        """Can we reach the server's service port from the current network?"""
        return host_reachable(m.host, service_port(m),
                              unresolvable=m.mount_type == MountType.SSHFS)

    def _sshfs(self, m: MountConfig) -> Result:
        pw = None if m.ssh_key else self.creds.get(m.id)
        user = m.username or os.environ.get("USER", "")
        remote = f"{user}@{m.host}:{m.remote_path}" if user else f"{m.host}:{m.remote_path}"
        local = _norm(m.local_path)
        Path(local).mkdir(parents=True, exist_ok=True)

        cmd = ["sshfs", "-p", str(m.port or 22),
               "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ConnectTimeout=10",
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
        return self._helper(["mount", "cifs", src, self.helper_name(m), self.smb_options(m)],
                            stdin=creds)

    def _nfs(self, m: MountConfig) -> Result:
        src = f"{m.host}:{m.remote_path}"
        return self._helper(["mount", "nfs", src, self.helper_name(m), self.nfs_options(m)])

    @staticmethod
    def nfs_options(m: MountConfig) -> str:
        """User options replace the defaults; the roaming switch wins over both."""
        base = m.options or NFS_DEFAULT_OPTS
        return merge_options(base, NFS_ROAMING_OPTS) if m.roaming else base

    @staticmethod
    def smb_options(m: MountConfig) -> str:
        return merge_options(SMB_DEFAULT_OPTS, m.options,
                             SMB_ROAMING_OPTS if m.roaming else "")

    def _link(self, m: MountConfig):
        """Point ~/mnt/<name> (the configured local path) at the real mountpoint."""
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

    def ensure_link(self, m: MountConfig):
        """Recreate a missing ~/mnt/<name> shortcut for a mounted NFS/SMB share
        (e.g. the mount finished after the client had already timed out)."""
        if m.mount_type != MountType.SSHFS and not os.path.islink(_norm(m.local_path)):
            self._link(m)

    @staticmethod
    def remove_link(path: str) -> bool:
        """Remove a shortcut MountBridge made: a symlink into SYS_MOUNT_BASE.
        Uses readlink only, so a dead mount behind it can't block."""
        p = _norm(path)
        try:
            target = os.readlink(p)
        except OSError:
            return False  # not a symlink (SSHFS dir, user data) or missing
        if Path(target).parent != SYS_MOUNT_BASE:
            return False
        try:
            os.unlink(p)
            return True
        except OSError:
            return False

    def sweep_links(self, keep: Set[str], directory: Optional[Path] = None) -> List[str]:
        """Remove shortcuts in ~/mnt pointing at a MountBridge mountpoint that no
        configured mount uses and nothing is mounted on (left by renames, deletes
        or older versions). Returns the removed paths."""
        removed: List[str] = []
        try:
            entries = list(os.scandir(directory or MOUNTS_DIR))
        except OSError:
            return removed
        mounted = mounted_paths()
        for e in entries:
            if not e.is_symlink():
                continue
            try:
                target = os.readlink(e.path)
            except OSError:
                continue
            if target in keep or target in mounted:
                continue
            if self.remove_link(e.path):
                removed.append(e.path)
        return removed

    def tidy(self) -> Result:
        """Ask the helper to remove empty, unused mountpoint dirs (best effort)."""
        if not os.path.exists(HELPER) or helper_access_problem():
            return False, "helper unavailable"
        return self._helper(["tidy"])

    # ── Unmount ──────────────────────────────────────────────────────────────

    def unmount(self, m: MountConfig, lazy: bool = False, force: bool = False) -> Result:
        """force: the server is gone — abort pending I/O and detach (may lose unwritten data)."""
        if not self.is_mounted(m):
            return True, "Not mounted"
        if m.mount_type == MountType.SSHFS:
            return self._fuse_unmount(self.mountpoint(m), lazy or force)
        return self._helper_umount(self.helper_name(m), lazy, force)

    def unmount_live(self, lm: LiveMount, lazy: bool = False, force: bool = False) -> Result:
        """Unmount a mount MountBridge didn't create."""
        if lm.mount_type == "sshfs":
            return self._fuse_unmount(lm.local_path, lazy or force)
        if Path(lm.local_path).parent == SYS_MOUNT_BASE:
            return self._helper_umount(Path(lm.local_path).name, lazy, force)
        # Works for fstab `user`/`users` mounts; anything else needs root.
        detach = lazy or force
        ok, msg = self._run(["umount"] + (["-l"] if detach else []) + ["--", lm.local_path], 15)
        if not ok:
            msg += f"\n\nThis mount wasn't created by MountBridge. Unmount it with:\nsudo umount {lm.local_path}"
        return ok, msg

    def _helper_umount(self, name: str, lazy: bool, force: bool) -> Result:
        flag = ["--force"] if force else (["--lazy"] if lazy else [])
        ok, msg = self._helper(["umount", name] + flag)
        if not ok and force and "usage:" in msg:
            # Helper from an older package without --force: a lazy detach still
            # frees the mountpoint (pending I/O is left to time out on its own).
            ok, msg = self._helper(["umount", name, "--lazy"])
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
        # 60 s > the helper's own 45 s limit on mount/umount, so the helper always
        # reports first and we never call a mount "timed out" that then succeeds.
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
