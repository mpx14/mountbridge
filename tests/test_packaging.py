"""Packaging consistency. Skipped where the source tree isn't available
(e.g. inside the Debian build, which only copies tests/ and data/)."""
import re

import pytest

from tests.conftest import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "debian" / "changelog").exists(),
                                reason="needs the full source tree")


def pyproject_version():
    return re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)[1]


def test_debian_changelog_matches_pyproject():
    top = (ROOT / "debian" / "changelog").read_text().splitlines()[0]
    deb_version = re.match(r"mountbridge \(([^)]+)\)", top)[1]
    upstream = deb_version.split("-")[0].split("+")[0]
    assert upstream == pyproject_version(), (
        f"debian/changelog has {deb_version}, pyproject.toml has {pyproject_version()}: "
        "bump both (dch -v <version>)")


def test_changelog_md_has_entry_for_version():
    assert f"## [{pyproject_version()}]" in (ROOT / "CHANGELOG.md").read_text()


def test_sudoers_template_is_group_based():
    rule = [ln for ln in (ROOT / "data" / "mountbridge.sudoers").read_text().splitlines()
            if ln and not ln.startswith("#")]
    assert rule == ["%mountbridge ALL=(root) NOPASSWD: @HELPER@"]
