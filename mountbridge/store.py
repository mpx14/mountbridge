"""Persistent storage: JSON config and keyring credentials."""
import json
import os
import sys
import tempfile
import time
from typing import List, Optional

from .constants import CONFIG_DIR, CONFIG_FILE, KEYRING_SVC
from .models import MountConfig


class CredentialError(Exception):
    """The keyring backend is unavailable or locked."""


class CredentialStore:
    """Stores passwords in the system keyring (SecretService / KWallet)."""

    def _kr(self):
        import keyring
        return keyring

    def store(self, mount_id: str, password: str) -> bool:
        try:
            self._kr().set_password(KEYRING_SVC, mount_id, password)
            return True
        except Exception as e:
            print(f"[creds] store error: {e}", file=sys.stderr)
            return False

    def get(self, mount_id: str) -> Optional[str]:
        """Return the stored password, or None if there is none.

        Raises CredentialError if the keyring itself fails, so callers don't
        silently fall back to an empty password / guest login.
        """
        try:
            return self._kr().get_password(KEYRING_SVC, mount_id)
        except Exception as e:
            raise CredentialError(f"Keyring unavailable or locked: {e}") from e

    def delete(self, mount_id: str):
        try:
            self._kr().delete_password(KEYRING_SVC, mount_id)
        except Exception:
            pass  # nothing stored, or backend unavailable: nothing to clean up


class ConfigStore:
    """Reads and writes mount configurations to ~/.config/mountbridge/mounts.json."""

    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONFIG_DIR, 0o700)
        self.mounts: List[MountConfig] = []
        self.load_warning: Optional[str] = None
        self._load()

    def _load(self):
        if not CONFIG_FILE.exists():
            return
        try:
            raw = json.loads(CONFIG_FILE.read_text())
            self.mounts = [MountConfig.from_dict(m) for m in raw.get("mounts", [])]
        except Exception as e:
            # Keep the unreadable file rather than overwriting it on the next save.
            backup = CONFIG_FILE.with_name(f"mounts.json.bad-{time.strftime('%Y%m%d-%H%M%S')}")
            CONFIG_FILE.rename(backup)
            self.mounts = []
            self.load_warning = f"Config could not be read ({e}); moved to {backup}"
            print(f"[config] {self.load_warning}", file=sys.stderr)

    def save(self):
        """Atomic write: temp file in the same directory, fsync, rename."""
        data = json.dumps({"mounts": [m.to_dict() for m in self.mounts]}, indent=2)
        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".mounts.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_FILE)
        except BaseException:
            os.unlink(tmp)
            raise

    def get(self, mid: str) -> Optional[MountConfig]:
        return next((m for m in self.mounts if m.id == mid), None)

    def add(self, m: MountConfig):
        self.mounts.append(m)
        self.save()

    def update(self, m: MountConfig):
        for i, x in enumerate(self.mounts):
            if x.id == m.id:
                self.mounts[i] = m
                break
        self.save()

    def delete(self, mid: str):
        self.mounts = [m for m in self.mounts if m.id != mid]
        self.save()
