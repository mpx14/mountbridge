from mountbridge.parsing import (
    parse_avahi,
    parse_mountinfo,
    parse_showmount,
    parse_smbclient,
    slugify,
    unescape,
    valid_host,
)

MOUNTINFO = r"""22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw
40 22 0:50 / /home/ben/.mounts/my\040nas rw,nosuid,nodev,relatime shared:30 - fuse.sshfs ben@nas:/srv rw,user_id=1000,group_id=1000
41 22 0:51 / /mnt/mountbridge/ben/media rw,nosuid,nodev,relatime shared:31 - nfs4 192.168.1.10:/export/media rw,vers=4.2,hard
42 22 0:52 / /mnt/mountbridge/ben/docs rw,nosuid,nodev - cifs //fileserver/docs rw,vers=3.1.1,username=ben,uid=1000
43 22 0:53 / /mnt/a\134b rw - nfs [fe80::1]:/x rw
"""


def test_unescape_all_kernel_escapes():
    assert unescape(r"/a\040b\011c\012d\134e") == "/a b\tc\nd\\e"


def test_parse_mountinfo_fields_and_escapes():
    e = parse_mountinfo(MOUNTINFO)
    assert [x.mountpoint for x in e] == [
        "/", "/home/ben/.mounts/my nas", "/mnt/mountbridge/ben/media",
        "/mnt/mountbridge/ben/docs", "/mnt/a\\b"]
    assert e[1].fstype == "fuse.sshfs" and e[1].source == "ben@nas:/srv"
    assert "username=ben" in e[3].options and "nosuid" in e[3].options


def test_parse_mountinfo_skips_garbage():
    assert parse_mountinfo("garbage\n\n1 2 3\n") == []


def test_slugify():
    assert slugify("nas — /export/data") == "nas-export-data"   # was 'nas__/export/data'
    assert slugify("/etc") == "etc"                            # was an absolute path
    assert slugify("../..") == "mount"
    assert slugify("Home NAS") == "home-nas"
    assert len(slugify("x" * 200)) == 64


def test_valid_host():
    for ok in ("nas", "nas.local", "192.168.1.10", "[fe80::1]", "my_server", "a-b.example.com."):
        assert valid_host(ok), ok
    for bad in ("", "-oProxyCommand=x", "a b", "a,b", "a;b", "nas/x", "x" * 300, "-nas"):
        assert not valid_host(bad), bad


def test_parse_avahi_dedupes_and_validates():
    out = "\n".join([
        "+;eth0;IPv4;NAS;_smb._tcp;local",
        "=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.5;445;",
        "=;eth0;IPv6;NAS;_smb._tcp;local;nas.local;fe80::1;445;",
        "=;eth0;IPv4;Evil;_smb._tcp;local;-oProxyCommand=x;10.0.0.1;445;",
    ])
    assert parse_avahi(out) == [
        {"host": "nas.local", "share": None, "type": "smb", "detail": "192.168.1.5"}]


def test_parse_smbclient_grepable():
    out = "Disk|Media Files|Films\nDisk|backup|\nIPC|IPC$|IPC Service\nDisk|print$|Drivers\n"
    assert parse_smbclient(out) == ["Media Files", "backup"]


def test_parse_showmount():
    out = "/export/data 192.168.1.0/24\n/export/with space *\n/bare\nclnt_create: RPC error\n"
    assert parse_showmount(out) == ["/export/data", "/export/with space", "/bare"]
