"""Pytest configuration for root tests suite with live file protection."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
import sqlite3
import tempfile
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
PROD_VAR = (ROOT_DIR / "masa" / "var").resolve()
PROD_DB = (PROD_VAR / "private" / "masa.db").resolve()
PROD_BACKUPS = (PROD_VAR / "backups").resolve()
PROD_LEDGER = (PROD_BACKUPS / "zincir-uclari.jsonl").resolve()

_REAL_CONNECT = sqlite3.connect
_REAL_OPEN = builtins.open


def _is_prod_target(path_like) -> bool:
    try:
        p = Path(path_like).resolve()
    except Exception:
        return False
    if p == PROD_DB or p == PROD_LEDGER:
        return True
    try:
        if p.is_relative_to(PROD_BACKUPS):
            return True
    except AttributeError:
        if str(p).startswith(str(PROD_BACKUPS)):
            return True
    if p.name == "masa.db" and "var/private" in str(p):
        return True
    return False


@pytest.fixture(autouse=True, scope="session")
def protect_live_production_data_root():
    """Barrier preventing tests in root tests/ from modifying live files."""

    def guarded_connect(*args, **kwargs):
        if args and _is_prod_target(args[0]):
            raise RuntimeError(f"CRITICAL: Test ortamında canlı veritabanına erişim yasaktır! (Hedef: {args[0]})")
        if "database" in kwargs and _is_prod_target(kwargs["database"]):
            raise RuntimeError(f"CRITICAL: Test ortamında canlı veritabanına erişim yasaktır! (Hedef: {kwargs['database']})")
        return _REAL_CONNECT(*args, **kwargs)

    def guarded_open(*args, **kwargs):
        if args:
            target = args[0]
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if _is_prod_target(target):
                if any(m in mode for m in ("w", "a", "+", "x")):
                    raise RuntimeError(f"CRITICAL: Test ortamında canlı üretim dosyasına yazma yasaktır! (Hedef: {target})")
                if Path(target).resolve() == PROD_DB:
                    raise RuntimeError(f"CRITICAL: Test ortamında canlı veritabanı dosyasına doğrudan okuma yasaktır! (Hedef: {target})")
        return _REAL_OPEN(*args, **kwargs)

    sqlite3.connect = guarded_connect
    builtins.open = guarded_open

    yield

    sqlite3.connect = _REAL_CONNECT
    builtins.open = _REAL_OPEN
