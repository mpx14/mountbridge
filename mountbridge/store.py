"""Persistent storage: JSON config and keyring credentials."""
import json
from typing import List, Optional

from .constants import CONFIG_DIR, CONFIG_FILE, KEYRING_SVC
from .models import MountConfig


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
            print(f"[creds] store error: {e}")
            return False

    def get(self, mount_id: str) -> Optional[str]:
        try:
            return self._kr().get_password(KEYRING_SVC, mount_id)
        except Exception:
            return None

    def delete(self, mount_id: str):
        try:
            self._kr().delete_password(KEYRING_SVC, mount_id)
        except Exception:
            pass


class ConfigStore:
    """Reads and writes mount configurations to ~/.config/mountbridge/mounts.json."""

    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.mounts: List[MountConfig] = []
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                raw = json.loads(CONFIG_FILE.read_text())
                self.mounts = [MountConfig.from_dict(m) for m in raw.get("mounts", [])]
            except Exception as e:
                print(f"[config] load error: {e}")

    def save(self):
        CONFIG_FILE.write_text(
            json.dumps({"mounts": [m.to_dict() for m in self.mounts]}, indent=2)
        )

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
