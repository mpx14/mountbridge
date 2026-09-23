import json

from mountbridge import store
from mountbridge.models import MountConfig


def make(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "mounts.json")
    return store.ConfigStore()


def m(i):
    return MountConfig(id=i, name=i, mount_type="nfs", host="h", remote_path="/x", local_path="/l")


def test_roundtrip_and_permissions(monkeypatch, tmp_path):
    s = make(monkeypatch, tmp_path)
    s.add(m("a"))
    s.add(m("b"))
    assert [x.id for x in make(monkeypatch, tmp_path).mounts] == ["a", "b"]
    assert (tmp_path / "mounts.json").stat().st_mode & 0o077 == 0
    assert not list(tmp_path.glob(".mounts.*.tmp"))


def test_corrupt_config_is_preserved_not_overwritten(monkeypatch, tmp_path):
    (tmp_path / "mounts.json").write_text('{"mounts": [ truncated')
    s = make(monkeypatch, tmp_path)
    assert s.mounts == [] and s.load_warning
    backups = list(tmp_path.glob("mounts.json.bad-*"))
    assert len(backups) == 1 and "truncated" in backups[0].read_text()
    s.add(m("new"))
    assert json.loads((tmp_path / "mounts.json").read_text())["mounts"][0]["id"] == "new"
