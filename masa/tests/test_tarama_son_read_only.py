"""test_tarama_son_read_only.py — Tests for İP-4 [O2] Tarama read/write separation and zero audit events on read."""

import json
import io
from pathlib import Path
import sys
import pytest
import jsonschema

from masa.cli import build_parser, cmd_tarama
from masa.storage.db import DatabaseManager

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


def test_tarama_son_schema_and_zero_audit_events():
    db = DatabaseManager()
    db.initialize_schema()
    conn = db.get_connection()
    try:
        initial_events = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    finally:
        conn.close()

    schema_path = CONTRACTS_DIR / "tarama.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    parser = build_parser()
    args = parser.parse_args(["tarama", "--son", "--json"])

    for _ in range(5):
        captured_out = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_out
        try:
            exit_code, _ = cmd_tarama(args)
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        raw_out = captured_out.getvalue()
        data = json.loads(raw_out)
        jsonschema.validate(instance=data, schema=schema)

    conn = db.get_connection()
    try:
        final_events = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    finally:
        conn.close()

    assert final_events == initial_events, f"Expected 0 new audit events, but events increased from {initial_events} to {final_events}"
