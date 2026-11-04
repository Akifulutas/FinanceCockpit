"""File lock mechanism ensuring single-flight execution for Scalable Capital CLI (sc.lock)."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import logging
from pathlib import Path
import time
from typing import Generator, Optional

from masa.config import MASA_DIR

logger = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = MASA_DIR / "var" / "private" / "sc.lock"


class ScalableLockTimeoutError(RuntimeError):
    """Raised when acquiring the single-flight sc.lock exceeds timeout."""
    pass


@contextmanager
def sc_file_lock(
    lock_path: Optional[Path] = None,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.05,
) -> Generator[Path, None, None]:
    """Ensure strictly single-flight (one-at-a-time) execution for sc commands."""
    path = lock_path or DEFAULT_LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    f = open(path, "a+")
    start_time = time.monotonic()
    acquired = False

    try:
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout_seconds:
                    raise ScalableLockTimeoutError(
                        f"Tek uçuş kuralı ihlali: sc.lock kilidi {timeout_seconds} saniyede alınamadı "
                        f"(başka bir sc işlemi çalışıyor olabilir: {path})."
                    )
                time.sleep(poll_interval)

        yield path
    finally:
        if acquired:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception as exc:
                logger.debug(f"sc.lock serbest bırakılırken hata: {exc}")
        f.close()
