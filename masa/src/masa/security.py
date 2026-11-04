"""Security hardening and filesystem permission enforcement (İP-10).

Design Invariants:
1. Directory permissions: all folders under var/ must be 0700 (drwx------).
2. Sensitive file permissions: *.db, *.lock, *.jsonl, .env must be 0600 (-rw-------).
3. Fail-closed: if permissions cannot be set or verified, raise PermissionError.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import stat
from typing import List, Optional

logger = logging.getLogger(__name__)

SENSITIVE_EXTENSIONS = {".db", ".lock", ".jsonl", ".env"}
SENSITIVE_FILENAMES = {".env", "masa.db", "sc.lock", "zincir-uclari.jsonl"}


def ensure_secure_permissions(base_dir: Optional[Path] = None) -> List[str]:
    """Audit and enforce strict POSIX permissions on private directories and files.

    - Directories: 0700 (Owner rwx only)
    - Sensitive files: 0600 (Owner rw only)
    Returns list of modified or verified paths.
    """
    if base_dir is None:
        # Default to masa/var directory
        base_dir = Path(__file__).resolve().parent.parent.parent / "var"

    if not base_dir.exists():
        return []

    changes: List[str] = []

    # Enforce base directory permissions
    try:
        base_stat = base_dir.stat()
        base_mode = stat.S_IMODE(base_stat.st_mode)
        if base_mode != 0o700:
            os.chmod(base_dir, 0o700)
            changes.append(f"DIR {base_dir} -> 0700 (was {oct(base_mode)})")
    except Exception as exc:
        raise PermissionError(f"Dizin izinleri düzeltilemedi ({base_dir}): {exc}") from exc

    # Recursively check subdirectories and files
    for root, dirs, files in os.walk(base_dir):
        root_path = Path(root)

        # Enforce directory permissions
        for d in dirs:
            d_path = root_path / d
            try:
                d_mode = stat.S_IMODE(d_path.stat().st_mode)
                if d_mode != 0o700:
                    os.chmod(d_path, 0o700)
                    changes.append(f"DIR {d_path} -> 0700 (was {oct(d_mode)})")
            except Exception as exc:
                raise PermissionError(f"Alt dizin izinleri düzeltilemedi ({d_path}): {exc}") from exc

        # Enforce file permissions
        for f in files:
            f_path = root_path / f
            try:
                is_sensitive = (
                    f_path.suffix.lower() in SENSITIVE_EXTENSIONS
                    or f_path.name in SENSITIVE_FILENAMES
                    or "private" in str(f_path)
                    or "backup" in str(f_path)
                )
                desired_mode = 0o600 if is_sensitive else 0o644
                f_mode = stat.S_IMODE(f_path.stat().st_mode)

                # If file is more permissive than desired, restrict it
                if f_mode != desired_mode:
                    os.chmod(f_path, desired_mode)
                    changes.append(f"FILE {f_path} -> {oct(desired_mode)} (was {oct(f_mode)})")
            except Exception as exc:
                raise PermissionError(f"Dosya izinleri düzeltilemedi ({f_path}): {exc}") from exc

    if changes:
        logger.info(f"Güvenlik izinleri sıkılaştırıldı ({len(changes)} değişiklik)")
    return changes
