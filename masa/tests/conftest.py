"""Pytest configuration and fixtures for Masa test suite.

Includes Step 1 production file isolation barrier:
- Automatically sets MASA_DB_PATH and MASA_BACKUP_DIR to an isolated sandbox.
- Intercepts and strictly forbids any test from connecting to or modifying:
  1. masa/var/private/masa.db
  2. masa/var/backups/
  3. masa/var/backups/zincir-uclari.jsonl
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Callable, Dict, List, Optional, Tuple
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MASA_ROOT = Path(__file__).resolve().parent.parent
PROD_VAR = (MASA_ROOT / "var").resolve()
PROD_DB = (PROD_VAR / "private" / "masa.db").resolve()
PROD_BACKUPS = (PROD_VAR / "backups").resolve()
PROD_LEDGER = (PROD_BACKUPS / "zincir-uclari.jsonl").resolve()

_TEST_SANDBOX_DIR: Optional[tempfile.TemporaryDirectory] = None
_REAL_CONNECT = sqlite3.connect
_REAL_OPEN = builtins.open
_REAL_REMOVE = os.remove
_REAL_UNLINK = os.unlink
_REAL_REPLACE = os.replace


def _is_prod_target(path_like) -> bool:
    """Check if path targets production DB, backups directory, or ledger."""
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
    return False


def pytest_configure(config):
    """Set up isolated test sandbox before any tests run."""
    global _TEST_SANDBOX_DIR
    _TEST_SANDBOX_DIR = tempfile.TemporaryDirectory(prefix="masa_test_sandbox_")
    sb_path = Path(_TEST_SANDBOX_DIR.name)
    sb_db = sb_path / "test_sandbox.db"
    sb_backups = sb_path / "backups"
    sb_backups.mkdir(parents=True, exist_ok=True)

    # Initialize sandbox schema so default DB callers have required tables
    from masa.storage.db import DatabaseManager
    from masa.identity.registry import IdentityRegistry
    mgr = DatabaseManager(sb_db)
    mgr.initialize_schema()
    try:
        IdentityRegistry(db=mgr).seed_from_configs(verify=True)
    except Exception:
        pass

    os.environ["MASA_DB_PATH"] = str(sb_db)
    os.environ["MASA_BACKUP_DIR"] = str(sb_backups)


def pytest_unconfigure(config):
    """Clean up test sandbox."""
    global _TEST_SANDBOX_DIR
    if _TEST_SANDBOX_DIR:
        try:
            _TEST_SANDBOX_DIR.cleanup()
        except Exception:
            pass


@pytest.fixture(autouse=True, scope="session")
def protect_live_production_data_session():
    """Session-level barrier preventing any access to live DB or backups."""

    def guarded_connect(*args, **kwargs):
        if args:
            target = args[0]
            if _is_prod_target(target):
                raise RuntimeError(
                    f"CRITICAL: Test ortamında canlı veritabanı veya yedekleme dosyasına SQLite bağlantısı YASAKTIR! (Hedef: {target})"
                )
        if "database" in kwargs:
            target = kwargs["database"]
            if _is_prod_target(target):
                raise RuntimeError(
                    f"CRITICAL: Test ortamında canlı veritabanı veya yedekleme dosyasına SQLite bağlantısı YASAKTIR! (Hedef: {target})"
                )
        return _REAL_CONNECT(*args, **kwargs)

    def guarded_open(*args, **kwargs):
        if args:
            target = args[0]
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            is_write = any(m in mode for m in ("w", "a", "+", "x"))
            if _is_prod_target(target):
                if is_write:
                    raise RuntimeError(
                        f"CRITICAL: Test ortamında canlı üretim dosyasına YAZMA/DEĞİŞTİRME YASAKTIR! (Hedef: {target}, Mod: {mode})"
                    )
                if Path(target).resolve() == PROD_DB:
                    raise RuntimeError(
                        f"CRITICAL: Test ortamında canlı veritabanı dosyasına doğrudan okuma YASAKTIR! (Hedef: {target})"
                    )
        return _REAL_OPEN(*args, **kwargs)

    def guarded_remove(path, *args, **kwargs):
        if _is_prod_target(path):
            raise RuntimeError(f"CRITICAL: Test ortamında canlı üretim dosyasını silme YASAKTIR! (Hedef: {path})")
        return _REAL_REMOVE(path, *args, **kwargs)

    def guarded_unlink(path, *args, **kwargs):
        if _is_prod_target(path):
            raise RuntimeError(f"CRITICAL: Test ortamında canlı üretim dosyasını silme YASAKTIR! (Hedef: {path})")
        return _REAL_UNLINK(path, *args, **kwargs)

    def guarded_replace(src, dst, *args, **kwargs):
        if _is_prod_target(dst):
            raise RuntimeError(f"CRITICAL: Test ortamında canlı üretim dosyasının üzerine yazma YASAKTIR! (Hedef: {dst})")
        return _REAL_REPLACE(src, dst, *args, **kwargs)

    sqlite3.connect = guarded_connect
    builtins.open = guarded_open
    os.remove = guarded_remove
    os.unlink = guarded_unlink
    os.replace = guarded_replace

    yield

    sqlite3.connect = _REAL_CONNECT
    builtins.open = _REAL_OPEN
    os.remove = _REAL_REMOVE
    os.unlink = _REAL_UNLINK
    os.replace = _REAL_REPLACE


@pytest.fixture
def mock_fixture_loader():
    """Load JSON fixture file text."""
    def _loader(filename: str) -> str:
        path = FIXTURES_DIR / filename
        return path.read_text(encoding="utf-8")
    return _loader


@pytest.fixture
def mock_runner_factory(mock_fixture_loader):
    """Create a mock runner callable returning specific fixture outputs based on command."""
    def _factory(overrides: Optional[Dict[str, Tuple[int, str, str]]] = None) -> Callable[[List[str], float], Tuple[int, str, str]]:
        mapping = {
            "broker quote": (0, mock_fixture_loader("sample_quote_apple.json"), ""),
            "broker holdings": (0, mock_fixture_loader("sample_holdings.json"), ""),
            "broker cash-breakdown": (0, mock_fixture_loader("sample_cash_breakdown.json"), ""),
            "broker transactions": (0, mock_fixture_loader("sample_transactions.json"), ""),
        }
        if overrides:
            mapping.update(overrides)

        def _runner(cmd: List[str], timeout: float) -> Tuple[int, str, str]:
            cmd_str = " ".join(cmd)
            for key, val in mapping.items():
                if key in cmd_str:
                    return val
            return 1, "", f"Unrecognized mock command: {cmd_str}"

        return _runner
    return _factory
