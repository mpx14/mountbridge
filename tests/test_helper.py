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
