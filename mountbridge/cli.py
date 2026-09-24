"""Command-line entry point. Handles --version/--help without importing GTK,
so they work on headless systems (package install checks, bug reports)."""
import sys

from .constants import APP_NAME, APP_VERSION

USAGE = f"""Usage: mountbridge [--hidden] [--version] [--help]

{APP_NAME} — network mount manager (NFS, SMB/CIFS, SSHFS).

  --hidden    start minimised to the tray (used by the autostart entry)
  --version   print the version and exit
  --help      show this help and exit
"""


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0
    from .window import main as gui_main  # imports GTK
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
