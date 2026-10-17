import os
import time

import pytest


def test_names(helper):
    assert helper.check_name("media") == "media"
    for bad in ("", "../etc", "a/b", ".hidden", "-x", "x" * 65):
        with pytest.raises(helper.Refused):
            helper.check_name(bad)


def test_sources(helper):
    helper.check_source("nfs", "nas:/export/data")
    helper.check_source("nfs4", "[fe80::1]:/x")
    helper.check_source("cifs", "//fileserver/Media Files/sub")
    for fs, bad in (("nfs", "-oProxy:/x"), ("nfs", "nas:relative"), ("nfs", "nas:/x\n"),
                    ("cifs", "//-x/share"), ("cifs", "\\\\host\\share"), ("cifs", "//host")):
        with pytest.raises(helper.Refused):
            helper.check_source(fs, bad)


def test_options_enforce_nosuid_nodev(helper):
    assert helper.check_options("nfs", "rw,hard,vers=4.2", 1000, 1000) == \
        ["rw", "hard", "vers=4.2", "nosuid", "nodev"]
    assert helper.check_options("cifs", "file_mode=0644,uid=1000", 1000, 1000) == \
        ["file_mode=0644", "uid=1000", "gid=1000", "nosuid", "nodev"]


@pytest.mark.parametrize("opts", [
    "suid", "dev", "bind", "rbind", "remount", "move", "user", "helper=/tmp/x",
    "X-mount.mkdir", "x-systemd.automount", "credentials=/etc/shadow", "username=root",
    "password=x", "context=system_u", "vers=4.2;id", "port=abc", "unknownopt",
])
def test_options_rejected(helper, opts):
    with pytest.raises(helper.Refused):
        helper.check_options("nfs" if "cifs" not in opts else "cifs", opts, 1000, 1000)


def test_cifs_uid_must_be_caller(helper):
    with pytest.raises(helper.Refused):
        helper.check_options("cifs", "uid=0", 1000, 1000)


def test_creds(helper):
    assert helper.parse_creds("username=bob\npassword=p;a ss=\n") == \
        "username=bob\npassword=p;a ss=\n"
    with pytest.raises(helper.Refused):
        helper.parse_creds("credentials=/etc/shadow\n")


def test_caller_requires_sudo(helper, monkeypatch):
    monkeypatch.delenv("SUDO_UID", raising=False)
    with pytest.raises(helper.Refused):
        helper.caller()
    monkeypatch.setenv("SUDO_UID", "0")
    monkeypatch.setenv("SUDO_GID", "0")
    with pytest.raises(helper.Refused):
        helper.caller()


def test_umount_modes(helper, monkeypatch):
    assert helper.UMOUNT_FLAGS["--force"] == ["-f", "-l"]
    with pytest.raises(helper.Refused, match="usage"):
        helper.do_umount("media", "--bogus")


def test_umount_force_runs_and_removes_mountpoint(helper, monkeypatch):
    runs, removed = [], []
    monkeypatch.setattr(helper, "caller", lambda: (1000, 1000, "ben"))
    monkeypatch.setattr(helper, "mounted_at", lambda p: "nfs4")
    monkeypatch.setattr(helper, "run", lambda cmd, stdin=None: runs.append(cmd) or 0)
    monkeypatch.setattr(helper, "remove_mountpoint", removed.append)
    assert helper.do_umount("media", "--force") == 0
    assert runs == [["umount", "-f", "-l", "--", "/mnt/mountbridge/ben/media"]]
    assert removed == ["/mnt/mountbridge/ben/media"]


def test_main_parses_force_and_tidy(helper, monkeypatch):
    seen = []
    monkeypatch.setattr(helper, "do_umount", lambda n, mode=None: seen.append((n, mode)) or 0)
    monkeypatch.setattr(helper, "do_tidy", lambda: seen.append("tidy") or 0)
    assert helper.main(["umount", "media", "--force"]) == 0
    assert helper.main(["umount", "media"]) == 0
    assert helper.main(["tidy"]) == 0
    assert helper.main(["tidy", "x"]) == 2
    assert seen == [("media", "--force"), ("media", None), "tidy"]


def test_remove_mountpoint_leaves_data_and_mounts(helper, monkeypatch, tmp_path):
    empty, full = tmp_path / "empty", tmp_path / "full"
    empty.mkdir()
    full.mkdir()
    (full / "f").write_text("x")
    monkeypatch.setattr(helper, "mounted_at", lambda p: None)
    helper.remove_mountpoint(str(empty))
    helper.remove_mountpoint(str(full))
    assert not empty.exists() and (full / "f").exists()
    again = tmp_path / "mounted"
    again.mkdir()
    monkeypatch.setattr(helper, "mounted_at", lambda p: "cifs")
    helper.remove_mountpoint(str(again))
    assert again.exists()


def test_sweep_creds_removes_only_old_cred_files(helper, tmp_path):
    for name in ("cred-old", "cred-new", "other"):
        (tmp_path / name).write_text("x")
    old = time.time() - 1000
    os.utime(tmp_path / "cred-old", (old, old))
    os.utime(tmp_path / "other", (old, old))
    helper.sweep_creds(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cred-new", "other"]


def test_tidy_dir(helper, tmp_path):
    old = time.time() - 3600
    for name in ("stale", "recent", "mounted", "full", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "full" / "f").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "stale")
    for name in ("stale", "mounted", "full", ".hidden"):
        os.utime(tmp_path / name, (old, old))
    removed = helper.tidy_dir(str(tmp_path), {str(tmp_path / "mounted")})
    assert removed == ["stale"]
    assert sorted(p.name for p in tmp_path.iterdir()) == \
        [".hidden", "full", "link", "mounted", "recent"]
