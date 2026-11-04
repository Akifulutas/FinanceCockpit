"""Contract verification tests for CLI JSON outputs and Cockpit command whitelist (İ1)."""

import json
from pathlib import Path
import pytest
import jsonschema

from masa.cli import build_parser

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


def test_cockpit_command_whitelist_parseable():
    """All argv patterns invoked by ETFCockpit must parse cleanly without unrecognized arguments."""
    whitelist_file = CONTRACTS_DIR / "cockpit_commands.json"
    assert whitelist_file.exists(), f"Missing {whitelist_file}"

    items = json.loads(whitelist_file.read_text(encoding="utf-8"))
    assert len(items) >= 20

    parser = build_parser()
    for item in items:
        argv = item["argv"] if isinstance(item, dict) else item
        try:
            parsed = parser.parse_args(argv)
            assert parsed.command is not None
        except SystemExit as exc:
            pytest.fail(f"Cockpit command failed argparse: {argv} -> SystemExit {exc}")


def _load_schema(name: str) -> dict:
    path = CONTRACTS_DIR / f"{name}.schema.json"
    assert path.exists(), f"Schema file not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_durum_schema_contract():
    schema = _load_schema("durum")
    sample = {
        "schema_version": "1.0.0",
        "ok": True,
        "database_path": "/path/to/masa.db",
        "integrity": {
            "schema_version": 3,
            "trigger_count": 78,
            "snapshots": 30,
            "audit_events": 105,
            "chain_tip_status": "MATCH_SEALED",
            "ok": True,
        },
        "capabilities": {
            "version": "1.0.0",
            "command_count": 38,
            "drift_level": "CLEAN",
            "critical_issues": [],
            "warnings": [],
        },
        "queue": {
            "pending_count": 0,
            "recent_jobs": [],
        },
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_portfoy_schema_contract():
    schema = _load_schema("portfoy")
    sample = {
        "schema_version": "1.0.0",
        "run_id": "run_01",
        "completed_at": "2026-10-31T12:00:00Z",
        "positions_count": 1,
        "cash_eur": 100.0,
        "total_eur": 1100.0,
        "positions": [
            {
                "isin": "IE00B3YLTY66",
                "name": "SPDR ACWI",
                "role": "Core",
                "quantity": 10.0,
                "mid_eur": 100.0,
                "value_eur": 1000.0,
                "weight_pct": 90.9,
                "quality": "FRESH",
                "fifo_price_eur": 95.0,
            }
        ],
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_degerlendir_schema_contract():
    schema = _load_schema("degerlendir")
    sample = {
        "schema_version": "1.0.0",
        "run_id": "run_01",
        "assessments": [
            {
                "isin": "IE00B3YLTY66",
                "name": "SPDR ACWI",
                "label": "TUT",
                "reasons": ["Risk metrikleri normal"],
                "notes": ["Teilfreistellung %30"],
            }
        ],
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_tarama_schema_contract():
    schema = _load_schema("tarama")
    sample = {
        "schema_version": "1.0.0",
        "pool_count": 10,
        "candidates": [
            {
                "isin": "IE00B3YLTY66",
                "name": "SPDR ACWI",
                "label": "ARAŞTIRMAYA DEĞER",
                "score": 1.25,
                "reasons": ["Yüksek Sharpe"],
            }
        ],
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_tahmin_karne_schema_contract():
    schema = _load_schema("tahmin_karne")
    sample = {
        "schema_version": "1.0.0",
        "total_forecasts": 35,
        "settled_count": 32,
        "pending_count": 3,
        "hit_rate_pct": "62.50",
        "is_small_sample": False,
        "mape_pct": "1.20",
        "mae_eur": "0.1500",
        "mpe_pct": "-0.05",
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_zamanla_durum_schema_contract():
    schema = _load_schema("zamanla_durum")
    sample = {
        "schema_version": "1.0.0",
        "agents": [
            {
                "label": "com.etf.masa.sabah",
                "description": "Sabah 09:30 CET",
                "schedule": "Pzt-Cum 09:30 CET",
                "installed": True,
                "loaded": True,
                "last_exit_code": 0,
                "plist_path": "/Library/LaunchAgents/com.etf.masa.sabah.plist",
                "log_lines": ["ok"],
            }
        ],
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_ayar_goster_schema_contract():
    schema = _load_schema("ayar_goster")
    sample = {
        "schema_version": "1.0.0",
        "portfoy": {
            "araclar": {},
            "cekirdek_isin": "IE00B3YLTY66",
            "hedef_agirliklar": {},
        },
        "politika": {
            "durum": "TASLAK",
            "tolerans_mutlak": 0.05,
            "tolerans_goreli": 0.25,
            "min_emir_eur": 25,
            "nakit_hedefi": 0.0,
            "ucits_kontrolu": False,
        },
        "modeller": {},
        "model_erisim": {
            "providers": ["chatgpt", "google"],
            "chatgpt_auth_exists": True,
        },
        "broker": {
            "cli_path": "/opt/homebrew/bin/sc",
            "cli_exists": True,
        },
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_tez_ekle_schema_contract():
    schema = _load_schema("tez_ekle")
    sample = {
        "isin": "IE00B3YLTY66",
        "baslik": "Dunya Portfoy Tezi",
        "ozet": "Gelismiş ve gelismekte olan piyasalari dengeli kapsar",
        "gerekce": "Ekonomik buyumeden uzun vadeli pay alma stratejisi",
        "kategori": "CORE",
        "vade": "LONG_TERM",
        "tetikleyiciler": ["Faizler %15'in ustune cikarsa", "Kuresel buyume durursa"],
        "kanitlar": ["Kanit 1", "Kanit 2"],
        "karsi_gorus": "Kisa vadeli volatilite riski",
        "hedef_agirlik": 0.40,
        "sonraki_kontrol": "2026-12-01",
        "yazar": "user",
    }
    jsonschema.validate(instance=sample, schema=schema)


def test_additional_properties_rejected():
    schemas_to_test = [
        "giris",
        "durum",
        "portfoy",
        "degerlendir",
        "tarama",
        "tahmin_karne",
        "zamanla_durum",
        "ayar_goster",
        "tez_ekle",
    ]
    for schema_name in schemas_to_test:
        schema = _load_schema(schema_name)
        assert schema.get("additionalProperties") is False, f"Schema {schema_name} missing additionalProperties: false"
        bad_sample = {"unexpected_property_123": "injected_value"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_sample, schema=schema)
