"""Adversarial Challenger Test Suite for Phase 1 - Instance 1.

Empirical verification of H1, H2, H3:
1. `masa ayar yaz` with bad payloads, invalid ISINs, weight sums > 1.0, unconfirmed policy approvals.
2. Parameter boundary violations in `politika.json`.
3. Backup archiving integrity, atomic writes, and audit trail generation.
4. Comprehensive ISO 6166 Luhn check digit validation & oracle testing.
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import pytest

from masa import config
from masa.cli import cmd_ayar
from masa.identity.isin import calculate_isin_check_digit, is_valid_isin, validate_isin
from masa.storage.db import DatabaseManager


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Provides isolated config and db directories for clean testing."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)

    db_path = tmp_path / "test_masa_challenger1.db"
    db = DatabaseManager(db_path)
    db.initialize_schema()

    portfoy = {
        "cekirdek_isin": "IE00B3YLTY66",
        "araclar": {
            "IE00B3YLTY66": {"rol": "ACWI Core", "tur": "ETF"},
            "IE00BKM4GZ66": {"rol": "EM IMI", "tur": "ETF"},
        },
        "hedef_agirliklar": {},
        "hedef_durumu": "ONAYLANMADI",
    }
    politika = {
        "durum": "TASLAK",
        "tolerans_mutlak": 0.05,
        "tolerans_goreli": 0.25,
        "trend_uyari": -0.05,
        "dusus_inceleme": -0.20,
        "min_emir_eur": 25.0,
        "nakit_hedefi": 0.0,
        "ucits_kontrolu": False,
    }
    havuz = {
        "etf": {"IE00B4L5Y983": {"rol": "World", "tur": "ETF"}},
        "hisse": {"US0378331005": {"rol": "Apple", "tur": "STOCK"}},
    }

    (cfg_dir / "portfoy.json").write_text(json.dumps(portfoy, indent=2), encoding="utf-8")
    (cfg_dir / "politika.json").write_text(json.dumps(politika, indent=2), encoding="utf-8")
    (cfg_dir / "havuz.json").write_text(json.dumps(havuz, indent=2), encoding="utf-8")

    return cfg_dir, db


# =====================================================================
# Track 1: masa ayar yaz Malformed Payloads & Negative Inputs
# =====================================================================

def test_write_config_rejects_invalid_dosya():
    with pytest.raises(ValueError, match="Geçersiz yapılandırma dosyası"):
        config.write_config("invalid_target", {"foo": "bar"})


def test_write_config_rejects_non_dict_payload(isolated_env):
    cfg_dir, db = isolated_env
    with pytest.raises(AttributeError):
        config.write_config("portfoy", ["not", "a", "dict"], db=db)


@pytest.mark.parametrize("invalid_isin", [
    "",
    "IE00B3YLTY6",        # 11 chars
    "IE00B3YLTY660",      # 13 chars
    "1E00B3YLTY66",       # Numbers in country code
    "ie00b3ylty66",       # Lowercase
    "IE00B3YLTY6@",       # Special char
    "IE00B3YLTY65",       # Wrong check digit (expected 6)
    "US0378331000",       # Wrong check digit (expected 5)
    "DE000BAY0019",       # Wrong check digit (expected 7)
    "   ",                # Whitespace only
])
def test_write_config_portfoy_invalid_isins(isolated_env, invalid_isin):
    cfg_dir, db = isolated_env
    payload = {
        "hedef_agirliklar": {
            invalid_isin: 0.50
        }
    }
    with pytest.raises(ValueError):
        config.write_config("portfoy", payload, db=db)


@pytest.mark.parametrize("invalid_weight", [
    -0.0001,
    -1.0,
    -50.0,
])
def test_write_config_portfoy_negative_weights(isolated_env, invalid_weight):
    cfg_dir, db = isolated_env
    payload = {
        "hedef_agirliklar": {
            "IE00B3YLTY66": invalid_weight
        }
    }
    with pytest.raises(ValueError, match="Negatif ağırlık geçersiz"):
        config.write_config("portfoy", payload, db=db)


@pytest.mark.parametrize("w1,w2", [
    (0.60, 0.4002),       # Sum = 1.0002 > 1.0001
    (0.80, 0.30),         # Sum = 1.10
    (50.0, 50.0),         # Sum = 100.0 (user passed % instead of decimal)
    (1.0002, 0.0),        # Single weight > 1.0001
])
def test_write_config_portfoy_sum_exceeded_adversarial(isolated_env, w1, w2):
    cfg_dir, db = isolated_env
    payload = {
        "hedef_agirliklar": {
            "IE00B3YLTY66": w1,
            "IE00BKM4GZ66": w2,
        }
    }
    with pytest.raises(ValueError, match="hedef_agirliklar toplamı 1'i aşıyor"):
        config.write_config("portfoy", payload, db=db)


def test_write_config_portfoy_boundary_sums(isolated_env):
    cfg_dir, db = isolated_env
    # Exact 1.0
    payload_1 = {
        "hedef_agirliklar": {
            "IE00B3YLTY66": 0.60,
            "IE00BKM4GZ66": 0.40,
        }
    }
    ok, msg, arc = config.write_config("portfoy", payload_1, db=db)
    assert ok is True

    # 1.0001 tolerance boundary (floating point rounding cushion)
    payload_tol = {
        "hedef_agirliklar": {
            "IE00B3YLTY66": 0.70005,
            "IE00BKM4GZ66": 0.30005,
        }
    }
    ok2, msg2, arc2 = config.write_config("portfoy", payload_tol, db=db)
    assert ok2 is True


def test_write_config_portfoy_empty_targets(isolated_env):
    cfg_dir, db = isolated_env
    payload = {
        "hedef_agirliklar": {}
    }
    ok, msg, arc = config.write_config("portfoy", payload, db=db)
    assert ok is True
    data = json.loads((cfg_dir / "portfoy.json").read_text(encoding="utf-8"))
    assert data["hedef_durumu"].startswith("ONAYLANMADI")
    assert data["hedef_agirliklar"] == {}


def test_write_config_portfoy_araclar_isin_validation(isolated_env):
    cfg_dir, db = isolated_env
    payload = {
        "araclar": {
            "INVALID_ISIN": {"rol": "Bad"}
        }
    }
    with pytest.raises(ValueError):
        config.write_config("portfoy", payload, db=db)


# =====================================================================
# Track 2: Investment Policy Boundary Checks & Unconfirmed Approvals
# =====================================================================

@pytest.mark.parametrize("durum_input", ["ONAYLANDI", "onaylandi", "Onaylandi"])
def test_write_config_politika_approval_requires_confirmation(isolated_env, durum_input):
    cfg_dir, db = isolated_env
    payload = {"durum": durum_input}
    with pytest.raises(ValueError, match="--onayla-politika parametresi gereklidir"):
        config.write_config("politika", payload, confirm_policy=False, db=db)

    # When confirmed, succeeds
    ok, msg, arc = config.write_config("politika", payload, confirm_policy=True, db=db)
    assert ok is True
    data = json.loads((cfg_dir / "politika.json").read_text(encoding="utf-8"))
    assert data["durum"] == "ONAYLANDI"


@pytest.mark.parametrize("field,bad_val", [
    ("tolerans_mutlak", 0.0),
    ("tolerans_mutlak", -0.01),
    ("tolerans_mutlak", 0.5001),
    ("tolerans_goreli", 0.0),
    ("tolerans_goreli", -0.1),
    ("tolerans_goreli", 1.0001),
    ("trend_uyari", 0.0001),
    ("trend_uyari", -0.5001),
    ("dusus_inceleme", 0.0001),
    ("dusus_inceleme", -0.9001),
    ("min_emir_eur", -0.01),
    ("nakit_hedefi", -0.01),
    ("nakit_hedefi", 1.0001),
])
def test_write_config_politika_boundary_violations(isolated_env, field, bad_val):
    cfg_dir, db = isolated_env
    payload = {"durum": "TASLAK", field: bad_val}
    with pytest.raises(ValueError):
        config.write_config("politika", payload, confirm_policy=False, db=db)


# =====================================================================
# Track 3: Backup Archiving, Atomic Writes & Audit Logging
# =====================================================================

def test_backup_archiving_and_audit_logging(isolated_env):
    cfg_dir, db = isolated_env
    original_content = (cfg_dir / "portfoy.json").read_text(encoding="utf-8")

    payload = {
        "cekirdek_isin": "IE00B3YLTY66",
        "hedef_agirliklar": {"IE00B3YLTY66": 0.50, "IE00BKM4GZ66": 0.50}
    }
    ok, msg, arc = config.write_config("portfoy", payload, db=db)
    assert ok is True
    assert arc is not None
    assert arc.exists()
    assert arc.read_text(encoding="utf-8") == original_content

    # Verify audit log in SQLite
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT action, entity_type, entity_id, payload_json FROM audit_events WHERE action = 'CONFIG_UPDATED'")
        row = cur.fetchone()
        assert row is not None
        assert row["action"] == "CONFIG_UPDATED"
        assert row["entity_type"] == "config"
        assert row["entity_id"] == "portfoy"
        audit_payload = json.loads(row["payload_json"])
        assert audit_payload["file"] == "portfoy.json"
        assert audit_payload["archived_to"] == str(arc)
    finally:
        conn.close()


# =====================================================================
# Track 4: ISO 6166 ISIN Luhn Oracle & Generator
# =====================================================================

KNOWN_VALID_ISINS = [
    "US0378331005",  # Apple
    "US5949181045",  # Microsoft
    "US88160R1014",  # Tesla
    "IE00B3YLTY66",  # SPDR ACWI IMI
    "IE00BKM4GZ66",  # Emerging Markets IMI
    "IE00B4L5Y983",  # iShares Core MSCI World
    "DE000BAY0017",  # Bayer AG
    "DE0007164600",  # SAP SE
    "FR0000120271",  # TotalEnergies
    "GB0002374006",  # Diageo
    "NL0010273215",  # ASML
    "CH0012005267",  # Novartis
    "JP3435000009",  # Sony
    "AU000000BHP4",  # BHP Group
    "CA0679011084",  # Barrick Gold
]


def test_known_valid_isins():
    for isin in KNOWN_VALID_ISINS:
        assert is_valid_isin(isin) is True
        assert validate_isin(isin) == isin


def test_isin_check_digit_oracle():
    for isin in KNOWN_VALID_ISINS:
        prefix11 = isin[:11]
        expected_digit = int(isin[11])
        calculated = calculate_isin_check_digit(prefix11)
        assert calculated == expected_digit


def test_isin_check_digit_mutation_100_percent_detected():
    """Mutating the check digit itself must ALWAYS be detected (100% rejection rate)."""
    for isin in KNOWN_VALID_ISINS:
        expected_check = int(isin[11])
        for other_digit in range(10):
            if other_digit != expected_check:
                mutated = isin[:11] + str(other_digit)
                assert is_valid_isin(mutated) is False


def test_isin_adjacent_transpositions_empirical_bound():
    """Adjacent transpositions in alphanumeric ISINs have >70% detection under ISO 6166 Luhn."""
    detected = 0
    total = 0
    for isin in KNOWN_VALID_ISINS:
        for i in range(10):
            if isin[i] != isin[i+1]:
                transposed = isin[:i] + isin[i+1] + isin[i] + isin[i+2:]
                total += 1
                if not is_valid_isin(transposed):
                    detected += 1
    detection_rate = detected / total
    assert detection_rate > 0.70
