"""Small file helpers shared by the registry and the console: atomic replace with a Windows retry."""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path


def replace_retry(src: Path, dst: Path, attempts: int = 20) -> None:
    """``os.replace``, retried briefly while another process holds ``dst`` open on Windows."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == attempts - 1:
                raise
            time.sleep(0.05)


def temp_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write ``data`` to a fresh temporary sibling (created exclusively), then replace ``path``."""
    tmp = temp_sibling(path)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        replace_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
