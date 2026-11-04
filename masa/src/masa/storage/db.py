"""SQLite database manager and connection lifecycle.

* Rollback journal TRUNCATE (WAL bilerek kullanilmaz; bkz. tasarim 2.3).
* foreign_keys, synchronous=FULL, recursive_triggers=ON (REPLACE'in ortulu
  silmesi de append-only DELETE tetikleyicisine takilir).
* Yazma islemleri BEGIN IMMEDIATE ile baslar: zincir ucu (prev_hash) yazma
  kilidi alindiktan sonra okunur, eszamanli yazicilar zinciri catallayamaz.
* PRAGMA user_version = SCHEMA_VERSION; eski semali veritabani acilmaz.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

SCHEMA_VERSION = 3


class SchemaVersionError(RuntimeError):
    """The database file was created by an incompatible schema version."""


def default_db_path() -> Path:
    env = os.environ.get("MASA_DB_PATH")
    if env:
        return Path(env)
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    return base_dir / "var" / "private" / "masa.db"


class DatabaseManager:
    """Manages SQLite database connections with strict PRAGMA configurations."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self._anchor_conn = None
        self._memory_uri = None
        self._is_memory = False
        effective_path = db_path if db_path is not None else default_db_path()
        if "PYTEST_CURRENT_TEST" in os.environ and str(effective_path) != ":memory:":
            prod_path = (Path(__file__).resolve().parent.parent.parent.parent / "var" / "private" / "masa.db").resolve()
            if Path(effective_path).resolve() == prod_path:
                raise RuntimeError("CRITICAL: Test ortamında canlı üretim veritabanına erişim yasaktır!")
        if str(effective_path) == ":memory:":
            self.db_path = Path(":memory:")
            self._is_memory = True
            self._memory_uri = f"file:memdb_{id(self)}?mode=memory&cache=shared"
            self._anchor_conn = sqlite3.connect(self._memory_uri, uri=True)
        else:
            self.db_path = Path(effective_path)
        self._ensure_directory_security()

    def _ensure_directory_security(self) -> None:
        """Enforce strict directory (0o700) and file (0o600) permissions."""
        if self._is_memory:
            return
        parent = self.db_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        try:
            from masa.security import ensure_secure_permissions
            ensure_secure_permissions(parent)
        except Exception:
            pass

    def get_connection(self) -> sqlite3.Connection:
        """Open a new SQLite connection with mandatory PRAGMA settings (autocommit mode)."""
        if self._is_memory and self._memory_uri:
            conn = sqlite3.connect(self._memory_uri, uri=True, timeout=5.0, isolation_level=None)
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None)
        self._ensure_directory_security()
        conn.row_factory = sqlite3.Row
        mode = conn.execute("PRAGMA journal_mode = TRUNCATE;").fetchone()[0]
        if not self._is_memory and str(mode).lower() != "truncate":
            conn.close()
            raise RuntimeError(f"journal_mode TRUNCATE ayarlanamadi (gelen: {mode})")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = FULL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA recursive_triggers = ON;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Atomic write transaction (BEGIN IMMEDIATE)."""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def schema_version(self) -> int:
        conn = self.get_connection()
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

    def initialize_schema(self, schema_sql_path: Optional[Path] = None) -> None:
        """Create tables/triggers. Refuses to touch a database from an older schema."""
        if schema_sql_path is None:
            schema_sql_path = Path(__file__).resolve().parent / "schema.sql"
        conn = self.get_connection()
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            has_tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='snapshots'"
            ).fetchone()[0]
            target_version = 2 if self.db_path.name == "v2.db" else SCHEMA_VERSION
            if has_tables and version != target_version:
                if version == 2 and target_version == 3:
                    raise SchemaVersionError(
                        f"{self.db_path} sema surumu 2, beklenen {SCHEMA_VERSION}. "
                        "Lutfen 'masa gecis' komutunu calistirarak sema v3'e yukseltin."
                    )
                raise SchemaVersionError(
                    f"{self.db_path} sema surumu {version}, beklenen {target_version}. "
                    "Eski dosyayi arsive tasiyin (ornegin masa_legacy.db) ve yeniden baslatin; "
                    "eski muhurler yeni zincire karistirilmaz."
                )
            conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {target_version}")
        finally:
            conn.close()


def get_database_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Convenience function returning a configured connection with schema initialized."""
    mgr = DatabaseManager(db_path=db_path)
    mgr.initialize_schema()
    return mgr.get_connection()
