import subprocess
import sys


def run(*args):
    code = ("import sys; from mountbridge.cli import main; sys.argv = ['mountbridge', *sys.argv[1:]];"
            "rc = main(); print('GTK_LOADED' if 'gi.repository.Gtk' in sys.modules else 'NO_GTK');"
            "sys.exit(rc)")
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True)


def test_version_without_gtk():
    r = run("--version")
    assert r.returncode == 0
    assert r.stdout.startswith("MountBridge ") and "NO_GTK" in r.stdout


def test_help_without_gtk():
    r = run("--help")
    assert r.returncode == 0 and "--hidden" in r.stdout and "NO_GTK" in r.stdout
