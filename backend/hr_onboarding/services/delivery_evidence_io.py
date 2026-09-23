"""Bounded, private, fail-closed file I/O for offline delivery evidence."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile


def validate_new_json_path(path):
    path = Path(path).expanduser().absolute()
    if path.suffix.lower() != ".json" or ".." in path.parts:
        raise ValueError("Evidence output must be a new .json path")
    if any(p.is_symlink() for p in (path, *path.parents)) or path.exists():
        raise ValueError("Evidence cannot overwrite a file or follow a symbolic path")
    return path


def read_private_key(path):
    path = Path(path).expanduser().absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Verification key must not use symbolic paths or parent traversal")
    flags = os.O_RDONLY | getattr(os,"O_NOFOLLOW",0) | getattr(os,"O_NONBLOCK",0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 32 <= info.st_size <= 4096:
            raise ValueError("Use a regular random 32..4096 byte verification key")
        if os.name != "nt" and info.st_mode & 0o077:
            raise ValueError("Verification key must be private to its owner")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            key = stream.read(4097)
        if len(key) != info.st_size or not 32 <= len(key) <= 4096:
            raise ValueError("Verification key changed while being read")
        return key
    finally:
        os.close(fd)


def write_new_private_json(path, payload):
    """Publish a complete file without replacing an existing destination.

    Hard-link publication is atomic and fails if another process wins the name.
    No partial destination is exposed; private temp is removed on all failures.
    """
    path = validate_new_json_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".hr-proof-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary,0o600)
        os.link(temporary,path)  # exclusive publication; never os.replace()
    finally:
        temporary.unlink(missing_ok=True)
    return path
