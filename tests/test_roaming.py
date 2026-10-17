"""Dead-mount detection, recovery and cleanup (no GTK, no root)."""
import os
import socket
import time

import pytest

from mountbridge import ops
from mountbridge.models import MountConfig


def cfg(**kw):
    base = dict(id="abcd1234", name="n", mount_type="nfs", host="h", remote_path="/x",
                local_path="/home/ben/mnt/media")
    return MountConfig(**{**base, **kw})


# ── Options ──────────────────────────────────────────────────────────────────

def test_merge_options_later_layer_wins_and_hardness_is_one_key():
    assert ops.merge_options("rw,hard,timeo=600", "softerr,timeo=50") == \
        "rw,softerr,timeo=50"
    assert ops.merge_options("a", None, "", "b") == "a,b"


def test_nfs_roaming_overrides_hard():
    assert ops.MountOps.nfs_options(cfg()) == "rw,hard"
    assert ops.MountOps.nfs_options(cfg(roaming=True)) == "rw,softerr,timeo=50,retrans=2"
    assert ops.MountOps.nfs_options(cfg(options="ro,vers=4.2,hard", roaming=True)) == \
        "ro,vers=4.2,softerr,timeo=50,retrans=2"


def test_smb_options_merge_without_duplicates():
    assert ops.MountOps.smb_options(cfg(mount_type="smb", options="file_mode=0600")) == \
        "dir_mode=0755,file_mode=0600"
    assert ops.MountOps.smb_options(cfg(mount_type="smb", roaming=True)).endswith(
        "echo_interval=10")


def test_roaming_options_pass_the_helper_allow_list(helper):
    nfs = ops.MountOps.nfs_options(cfg(roaming=True))
    smb = ops.MountOps.smb_options(cfg(mount_type="smb", roaming=True))
    helper.check_options("nfs", nfs, 1000, 1000)
    helper.check_options("cifs", smb, 1000, 1000)


def test_old_config_without_roaming_loads():
    old = {k: v for k, v in cfg().to_dict().items() if k != "roaming"}
    assert MountConfig.from_dict(old).roaming is False


def test_sshfs_has_connect_timeout(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ops.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or
                        type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    ops.MountOps(creds=None).mount(cfg(mount_type="sshfs", ssh_key="~/.ssh/id",
                                       local_path=str(tmp_path / "m")))
    assert "ConnectTimeout=10" in calls[0]


# ── Health ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg,dead", [
    ("Timed out", True),
    ("umount.nfs4: /mnt/x: Stale file handle", True),
    ("fusermount: failed to unmount: Transport endpoint is not connected", True),
    ("mount error(112): Host is down", True),
    ("umount: /mnt/x: target is busy.", False),
    ("Not authorised to run helper", False),
    ("", False),
])
def test_is_dead_error(msg, dead):
    assert ops.is_dead_error(msg) is dead


def test_probe_path(tmp_path):
    assert ops.probe_path(str(tmp_path))
    assert not ops.probe_path(str(tmp_path / "missing"))


def test_probe_path_kills_a_hung_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "PROBE_CMD", ("sh", "-c", "sleep 30", "probe"))
    t = time.monotonic()
    assert not ops.probe_path(str(tmp_path), timeout=0.3)
    assert time.monotonic() - t < 3


def test_host_reachable():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert ops.host_reachable("127.0.0.1", port)
    finally:
        srv.close()
    assert not ops.host_reachable("127.0.0.1", port)  # closed now: refused
    assert ops.host_reachable("no-such-host.invalid", 22, unresolvable=True)
    assert not ops.host_reachable("no-such-host.invalid", 22)


def test_service_port():
    assert ops.service_port(cfg()) == 2049
    assert ops.service_port(cfg(mount_type="smb")) == 445
    assert ops.service_port(cfg(mount_type="smb", options="vers=3,port=1445")) == 1445
    assert ops.service_port(cfg(mount_type="sshfs")) == 22
    assert ops.service_port(cfg(mount_type="sshfs", port=2222)) == 2222


# ── Recovery ─────────────────────────────────────────────────────────────────

def _recording_helper(monkeypatch, replies):
    calls = []

    def fake(self, args, stdin=""):
        calls.append(args)
        return replies.pop(0) if replies else (True, "OK")

    monkeypatch.setattr(ops.MountOps, "_helper", fake)
    monkeypatch.setattr(ops.MountOps, "is_mounted", lambda self, m, mounted=None: True)
    return calls


def test_force_unmount_uses_helper_force(monkeypatch):
    calls = _recording_helper(monkeypatch, [])
    assert ops.MountOps(None).unmount(cfg(), force=True)[0]
    assert calls == [["umount", "media", "--force"]]


def test_force_falls_back_to_lazy_on_an_old_helper(monkeypatch):
    calls = _recording_helper(monkeypatch, [
        (False, "mountbridge-helper: usage: umount NAME [--lazy]")])
    assert ops.MountOps(None).unmount(cfg(), force=True)[0]
    assert calls == [["umount", "media", "--force"], ["umount", "media", "--lazy"]]


def test_force_sshfs_is_lazy_fusermount(monkeypatch):
    calls = []
    monkeypatch.setattr(ops.MountOps, "is_mounted", lambda self, m, mounted=None: True)
    monkeypatch.setattr(ops.MountOps, "_run", lambda self, cmd, *a, **k: calls.append(cmd)
                        or (True, "OK"))
    ops.MountOps(None).unmount(cfg(mount_type="sshfs"), force=True)
    assert calls[0][:2] == ["fusermount", "-uz"]


def test_reconnect_waits_when_server_unreachable(monkeypatch):
    calls = _recording_helper(monkeypatch, [])
    monkeypatch.setattr(ops.MountOps, "server_reachable", lambda self, m: False)
    ok, msg = ops.MountOps(None).reconnect(cfg())
    assert (ok, msg) == (False, ops.SERVER_UNREACHABLE)
    assert calls == [["umount", "media", "--force"]]


def test_reconnect_remounts_when_reachable(monkeypatch):
    _recording_helper(monkeypatch, [])
    monkeypatch.setattr(ops.MountOps, "server_reachable", lambda self, m: True)
    mounted = []
    monkeypatch.setattr(ops.MountOps, "mount", lambda self, m: mounted.append(m) or (True, "OK"))
    assert ops.MountOps(None).reconnect(cfg()) == (True, "OK")
    assert mounted


def test_mount_reports_oserror_instead_of_raising(monkeypatch):
    monkeypatch.setattr(ops.MountOps, "is_mounted", lambda self, m, mounted=None: False)

    def boom(self, m):
        raise OSError(107, "Transport endpoint is not connected")

    monkeypatch.setattr(ops.MountOps, "_sshfs", boom)
    assert ops.MountOps(None).mount(cfg(mount_type="sshfs")) == \
        (False, "Transport endpoint is not connected")


# ── Shortcut cleanup ─────────────────────────────────────────────────────────

@pytest.fixture
def sysbase(monkeypatch, tmp_path):
    base = tmp_path / "sys"
    base.mkdir()
    monkeypatch.setattr(ops, "SYS_MOUNT_BASE", base)
    monkeypatch.setattr(ops, "mounted_paths", lambda entries=None: set())
    return base


def test_remove_link_only_removes_our_symlinks(sysbase, tmp_path):
    ours, foreign, data = tmp_path / "ours", tmp_path / "foreign", tmp_path / "data"
    ours.symlink_to(sysbase / "media")
    foreign.symlink_to("/srv/elsewhere")
    data.mkdir()
    assert ops.MountOps.remove_link(str(ours)) and not os.path.lexists(ours)
    assert not ops.MountOps.remove_link(str(foreign)) and foreign.is_symlink()
    assert not ops.MountOps.remove_link(str(data)) and data.is_dir()
    assert not ops.MountOps.remove_link(str(tmp_path / "missing"))


def test_sweep_links_keeps_configured_and_mounted(sysbase, tmp_path, monkeypatch):
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    (mnt / "keep").symlink_to(sysbase / "keep")
    (mnt / "old").symlink_to(sysbase / "old")
    (mnt / "live").symlink_to(sysbase / "live")
    (mnt / "other").symlink_to("/srv/x")
    (mnt / "dir").mkdir()
    monkeypatch.setattr(ops, "mounted_paths", lambda entries=None: {str(sysbase / "live")})
    removed = ops.MountOps(None).sweep_links({str(sysbase / "keep")}, mnt)
    assert removed == [str(mnt / "old")]
    assert sorted(p.name for p in mnt.iterdir()) == ["dir", "keep", "live", "other"]


def test_ensure_link_recreates_missing_shortcut(sysbase, tmp_path):
    m = cfg(local_path=str(tmp_path / "mnt" / "media"))
    o = ops.MountOps(None)
    o.ensure_link(m)
    assert os.readlink(tmp_path / "mnt" / "media") == str(sysbase / "media")
    o.ensure_link(cfg(mount_type="sshfs", local_path=str(tmp_path / "s")))
    assert not os.path.lexists(tmp_path / "s")


# ── Laptop detection (default for the Roaming switch) ────────────────────────

def _sys(tmp_path, chassis=None, supplies=()):
    if chassis is not None:
        d = tmp_path / "class/dmi/id"
        d.mkdir(parents=True)
        (d / "chassis_type").write_text(f"{chassis}\n")
    for name, typ, scope in supplies:
        d = tmp_path / "class/power_supply" / name
        d.mkdir(parents=True)
        (d / "type").write_text(typ + "\n")
        if scope:
            (d / "scope").write_text(scope + "\n")
    return str(tmp_path)


@pytest.mark.parametrize("chassis,supplies,laptop", [
    (10, (), True),                                      # Notebook (e.g. Framework 13)
    (9, (), True),                                       # Laptop
    (31, (), True),                                      # Convertible
    (3, (("BAT0", "Battery", ""),), False),              # Desktop with a UPS battery
    (2, (("BAT0", "Battery", ""),), True),               # Unknown chassis: battery decides
    (None, (("BAT0", "Battery", "System"),), True),      # no DMI (e.g. ARM)
    (None, (("hidpp_battery_0", "Battery", "Device"),    # wireless mouse only
            ("AC", "Mains", "")), False),
    (None, (), False),
])
def test_is_laptop(tmp_path, chassis, supplies, laptop):
    assert ops.is_laptop(_sys(tmp_path, chassis, supplies)) is laptop


def test_is_laptop_ignores_garbage_chassis(tmp_path):
    root = _sys(tmp_path, "n/a", (("BAT1", "Battery", ""),))
    assert ops.is_laptop(root) is True
