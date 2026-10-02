import os

from mountbridge import bookmarks


def test_add_has_remove_roundtrip(tmp_path):
    f = tmp_path / "bookmarks"
    p = str(tmp_path / "mnt" / "home nas")
    assert not bookmarks.has(p, f)
    assert bookmarks.add(p, "Home NAS", f)
    assert bookmarks.has(p, f)
    assert "home%20nas Home NAS" in f.read_text()
    assert not bookmarks.add(p, "Home NAS", f)  # no duplicate
    assert f.read_text().count("home%20nas") == 1
    assert bookmarks.remove(p, f)
    assert not bookmarks.has(p, f)
    assert not bookmarks.remove(p, f)


def test_foreign_lines_preserved(tmp_path):
    f = tmp_path / "bookmarks"
    foreign = ["file:///home/ben/Documents", "sftp://darkstar/srv Darkstar", "",
               "file:///home/ben/Caf%C3%A9 Café"]
    f.write_text("\n".join(foreign) + "\n")
    p = str(tmp_path / "share")
    bookmarks.add(p, "Share", f)
    bookmarks.remove(p, f)
    assert f.read_text().splitlines() == foreign


def test_matches_entries_written_by_others(tmp_path):
    # Thunar may encode differently or add a trailing slash; match on path.
    f = tmp_path / "bookmarks"
    p = tmp_path / "mnt" / "x y"
    f.write_text(f"file://{tmp_path}/mnt/x%20y/ Thunar label\n")
    assert bookmarks.has(str(p), f)
    assert bookmarks.remove(str(p), f)
    assert f.read_text() == ""


def test_label_control_chars_stripped(tmp_path):
    f = tmp_path / "bookmarks"
    bookmarks.add(str(tmp_path / "a"), "evil\nfile:///etc", f)
    assert len(f.read_text().splitlines()) == 1


def test_creates_missing_dir_and_follows_symlink(tmp_path):
    real = tmp_path / "dotfiles" / "bookmarks"
    real.parent.mkdir()
    real.write_text("file:///keep\n")
    os.chmod(real, 0o600)
    link_dir = tmp_path / "cfg" / "gtk-3.0"
    link_dir.mkdir(parents=True)
    link = link_dir / "bookmarks"
    link.symlink_to(real)
    bookmarks.add(str(tmp_path / "m"), "M", link)
    assert link.is_symlink()
    assert "file:///keep" in real.read_text() and "M" in real.read_text()
    assert real.stat().st_mode & 0o777 == 0o600
    assert not list(real.parent.glob(".bookmarks.*.tmp"))

    fresh = tmp_path / "new" / "gtk-3.0" / "bookmarks"
    bookmarks.add(str(tmp_path / "m"), "M", fresh)
    assert fresh.exists()


def test_default_location_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert bookmarks.bookmarks_file() == tmp_path / "gtk-3.0" / "bookmarks"
