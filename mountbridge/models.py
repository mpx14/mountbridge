"""Data model classes."""
import dataclasses
from enum import Enum
from typing import Optional


class MountType(str, Enum):
    NFS   = "nfs"
    SMB   = "smb"
    SSHFS = "sshfs"


class MountStatus(str, Enum):
    MOUNTED   = "on"
    UNMOUNTED = "off"
    BUSY      = "busy"
    ERROR     = "err"


@dataclasses.dataclass
class MountConfig:
    id:          str
    name:        str
    mount_type:  str
    host:        str
    remote_path: str
    local_path:  str
    username:    Optional[str] = None
    domain:      Optional[str] = None
    port:        Optional[int] = None
    ssh_key:     Optional[str] = None
    options:     str           = ""
    auto_mount:  bool          = False
    created_at:  str           = ""

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


class LiveMount:
    """A network mount active in /proc/mounts but not tracked in config."""

    def __init__(self, mount_type: str, device: str, local_path: str,
                 host: str, remote_path: str, options: str,
                 username: Optional[str] = None, port: Optional[int] = None):
        self.mount_type  = mount_type
        self.device      = device
        self.local_path  = local_path
        self.host        = host
        self.remote_path = remote_path
        self.options     = options
        self.username    = username
        self.port        = port
