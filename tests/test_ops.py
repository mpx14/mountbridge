from mountbridge import ops
from mountbridge.models import MountConfig
from mountbridge.parsing import parse_mountinfo
from tests.test_parsing import MOUNTINFO


def cfg(**kw):
    base = dict(id="abcd1234", name="n", mount_type="nfs", host="h", remote_path="/x",
                local_path="/home/ben/.mounts/media")
    return MountConfig(**{**base, **kw})


def test_nfs_smb_mountpoint_is_root_owned_tree(monkeypatch):
    monkeypatch.setattr(ops, "SYS_MOUNT_BASE", ops.Path("/mnt/mountbridge/ben"))
    o = ops.MountOps(creds=None)
    assert o.mountpoint(cfg()) == "/mnt/mountbridge/ben/media"
    assert o.mountpoint(cfg(local_path="/home/ben/.mounts/My NAS!")) == "/mnt/mountbridge/ben/my-nas"
    assert o.mountpoint(cfg(mount_type="sshfs", local_path="/home/ben/.mounts/x/../y")) == \
        "/home/ben/.mounts/y"


def test_is_mounted_uses_mount_table_only(monkeypatch):
    monkeypatch.setattr(ops, "SYS_MOUNT_BASE", ops.Path("/mnt/mountbridge/ben"))
    o = ops.MountOps(creds=None)
    mounted = ops.mounted_paths(parse_mountinfo(MOUNTINFO))
    assert o.is_mounted(cfg(), mounted)
    assert o.is_mounted(cfg(mount_type="sshfs", local_path="/home/ben/.mounts/my nas"), mounted)
    assert not o.is_mounted(cfg(local_path="/home/ben/.mounts/other"), mounted)


def test_scanner_parses_and_filters():
    entries = parse_mountinfo(MOUNTINFO)
    live = ops.LiveMountScanner().scan({"/mnt/mountbridge/ben/media"}, entries)
    got = {(lm.mount_type, lm.host, lm.remote_path, lm.local_path, lm.username) for lm in live}
    assert got == {
        ("sshfs", "nas", "/srv", "/home/ben/.mounts/my nas", "ben"),
        ("smb", "fileserver", "docs", "/mnt/mountbridge/ben/docs", "ben"),
        ("nfs", "fe80::1", "/x", "/mnt/a\\b", None),
    }


def test_sshfs_password_never_in_argv(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ops.subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, kw)) or
                        type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    class Creds:
        def get(self, _):
            return "hunter2"

    o = ops.MountOps(Creds())
    ok, _ = o.mount(cfg(mount_type="sshfs", local_path=str(tmp_path / "m"), username="u"))
    cmd, kw = calls[0]
    assert ok and "hunter2" not in " ".join(cmd)
    assert kw["input"] == "hunter2\n" and "password_stdin" in cmd and "sshpass" not in cmd
    assert cmd[-3] == "--"


def test_smb_creds_go_to_helper_stdin(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ops, "HELPER", "/bin/true")
    monkeypatch.setattr(ops, "SYS_MOUNT_BASE", tmp_path / "sys")
    monkeypatch.setattr(ops.subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, kw)) or
                        type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    class Creds:
        def get(self, _):
            return "p@ss"

    o = ops.MountOps(Creds())
    o.mount(cfg(mount_type="smb", remote_path="docs", username="ben", domain="CORP",
                local_path=str(tmp_path / "link")))
    cmd, kw = calls[0]
    assert cmd[:3] == ["sudo", "-n", "/bin/true"]
    assert cmd[3:7] == ["mount", "cifs", "//h/docs", "link"]
    assert "p@ss" not in " ".join(cmd)
    assert kw["input"] == "username=ben\npassword=p@ss\ndomain=CORP\n"
    assert (tmp_path / "link").is_symlink()


def test_keyring_failure_is_reported(monkeypatch, tmp_path):
    from mountbridge.store import CredentialError

    class Broken:
        def get(self, _):
            raise CredentialError("Keyring unavailable or locked: boom")

    ok, msg = ops.MountOps(Broken()).mount(cfg(mount_type="smb", username="u",
                                               local_path=str(tmp_path / "l")))
    assert not ok and "Keyring" in msg
