"""Cryptographic audit logger (AuditLogger)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, Generator, Optional, Tuple, Union
import uuid

from masa.storage.db import DatabaseManager
from masa.storage.hash_chain import GENESIS_HASH, HashChainEngine, canonical_json, sha256_text


class AuditLogger:
    """Logs system events and state transitions into an append-only, SHA-256 hash-chained ledger."""

    def __init__(self, db: Union[DatabaseManager, sqlite3.Connection]) -> None:
        self.db = db

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        if hasattr(self.db, "transaction"):
            with self.db.transaction() as conn:
                yield conn
        else:
            already_in_tx = getattr(self.db, "in_transaction", False)
            try:
                yield self.db
                if not already_in_tx and self.db.in_transaction:
                    self.db.commit()
            except Exception:
                if not already_in_tx and self.db.in_transaction:
                    self.db.rollback()
                raise

    def log_event(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: Dict[str, Any],
        event_time: Optional[datetime] = None,
    ) -> str:
        """Atomically append a new event to the audit ledger."""
        t = event_time or datetime.now(timezone.utc)
        event_time_iso = t.astimezone(timezone.utc).isoformat()
        event_uuid = str(uuid.uuid4())

        canon_payload = canonical_json(payload)
        payload_sha256 = sha256_text(canon_payload)

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1")
            row = cursor.fetchone()
            prev_hash = row["curr_hash"] if row else GENESIS_HASH

            curr_hash = HashChainEngine.compute_audit_event_hash(
                prev_hash=prev_hash,
                event_uuid=event_uuid,
                event_time=event_time_iso,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload_sha256=payload_sha256,
            )

            cursor.execute(
                """INSERT INTO audit_events
                   (event_uuid, event_time, actor, action, entity_type, entity_id,
                    payload_json, payload_sha256, prev_hash, curr_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_uuid,
                    event_time_iso,
                    actor,
                    action,
                    entity_type,
                    entity_id,
                    canon_payload,
                    payload_sha256,
                    prev_hash,
                    curr_hash,
                ),
            )
            return curr_hash

    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        """Verify the cryptographic hash chain of the entire audit ledger."""
        with self._transaction() as conn:
            return HashChainEngine.verify_audit_chain(conn)
