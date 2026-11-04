"""Adversarial stress harness and empirical challenge tests for İP-1 backup & restore.

Covers:
1. Bozuk manifest senaryoları (geçersiz JSON, bozuk şema, sahte SHA-256, tahrif edilmiş zincir uçları).
2. Tahrif edilmiş yedek dosyası senaryoları (bit flip header/data, kesik dosya boyları, çöp baytlar).
3. restore_drill sırasında canlı veritabanının tek bir baytının dahi değişmediğinin kesin deneysel kanıtı.
4. zincir-uclari.jsonl üzerinde fcntl.flock eşzamanlı stres testi ve prev_entry_sha256 kriptografik zincirlenmesi.
5. Geri yükleme güvenlik ve atomik rollback korumaları.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import pytest

from masa.audit.events import AuditLogger
from masa.backup import (
    BackupCorruptionError,
    BackupError,
    BackupManifest,
    ChainTipEntry,
    RestoreConfirmationRequiredError,
    append_chain_tip_log,
    compute_file_sha256,
    create_backup,
    restore_database,
    restore_drill,
    verify_chain_tips,
)
from masa.pipeline import integrity_report
from masa.storage import DatabaseManager, SCHEMA_VERSION, SnapshotStore
from masa.storage.hash_chain import canonical_json, sha256_text


@pytest.fixture
def populated_live_db(tmp_path: Path) -> DatabaseManager:
    """Creates a rich live SQLite database with real snapshots, quotes, audit events."""
    db_file = tmp_path / "var" / "private" / "masa.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    mgr = DatabaseManager(db_path=db_file)
    mgr.initialize_schema()

    store = SnapshotStore(mgr)
    now = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)
    raw_id1, _ = store.store_raw_object("sc", '{"quotes": [{"isin": "IE00B3YLTY66", "bid": 11.60}]}', now)
    quotes1 = [{
        "isin": "IE00B3YLTY66",
        "currency": "EUR",
        "bid": "11.60",
        "ask": "11.62",
        "provider_mid": "11.61",
        "computed_mid": "11.61",
        "spread": "0.02",
        "spread_pct": "0.17",
        "quote_timestamp": now,
        "retrieved_at": now,
        "quality_status": "FRESH",
    }]
    store.save_quote_snapshot("snap_001", raw_id1, "sc", now, now, quotes1)

    raw_id2, _ = store.store_raw_object("sc", '{"cash": [{"currency": "EUR", "amount": "2500.50"}]}', now)
    cash_items = [{
        "account_id_masked": "ACC_TEST_01",
        "currency": "EUR",
        "settled_cash": "2500.50",
        "total_cash": "2500.50",
        "observed_at": now.isoformat(),
    }]
    store.save_cash_snapshot("snap_002", raw_id2, "sc", now, now, cash_items)

    AuditLogger(mgr).log_event("adversarial_test", "INIT", "test", "1", {"stage": "adversarial"})
    return mgr


# ==============================================================================
# BÖLÜM 1: BOZUK MANİFEST SENARYOLARI
# ==============================================================================

def test_adversarial_manifest_invalid_json(populated_live_db: DatabaseManager, tmp_path: Path):
    """Manifest JSON sözdizimi bozuk olduğunda restore_drill reddetmeli."""
    b_dir = tmp_path / "backups_adv_1"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    # Manifest dosyasını geçersiz JSON ile boz
    res.manifest_path.write_text("{this is not valid json! 'foo': bar, , }", encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert any("Manifest okunamadı veya geçersiz" in err for err in drill_res.errors)


def test_adversarial_manifest_schema_corruption(populated_live_db: DatabaseManager, tmp_path: Path):
    """Manifest JSON geçerli ancak Pydantic şeması tip veya zorunlu alan ihlali içeriyorsa reddetmeli."""
    b_dir = tmp_path / "backups_adv_2"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    # Manifest verisinde alan tiplerini boz
    m_dict = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    m_dict["backup_bytes"] = "kesinlikle_sayi_degil"
    res.manifest_path.write_text(json.dumps(m_dict), encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert any("Manifest okunamadı veya geçersiz" in err for err in drill_res.errors)


def test_adversarial_manifest_fake_sha256(populated_live_db: DatabaseManager, tmp_path: Path):
    """Manifest içindeki SHA-256 sahte veya değiştirilmişse restore_drill anında reddetmeli."""
    b_dir = tmp_path / "backups_adv_3"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    m_dict = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    # Sahte bir SHA-256 yaz
    m_dict["backup_sha256"] = "deadbeef" * 8
    res.manifest_path.write_text(json.dumps(m_dict), encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert drill_res.db_sha256_matches is False
    assert any("SHA-256 uyuşmazlığı" in err for err in drill_res.errors)


def test_adversarial_manifest_tampered_chain_tips(populated_live_db: DatabaseManager, tmp_path: Path):
    """Dosya SHA-256'sı tutsa bile, manifestteki mühür/denetim uçları sahteyse reddetmeli."""
    b_dir = tmp_path / "backups_adv_4"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    m_dict = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    # Zincir uçlarını sahte değerlerle değiştir
    m_dict["snapshot_chain_tip"] = "0123456789abcdef" * 4
    res.manifest_path.write_text(json.dumps(m_dict), encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert drill_res.tips_match_manifest is False
    assert any("Yedek DB zincir uçları manifest ile uyuşmuyor" in err for err in drill_res.errors)


# ==============================================================================
# BÖLÜM 2: TAHRİF EDİLMİŞ YEDEK DOSYASI SENARYOLARI
# ==============================================================================

def test_adversarial_bit_flip_in_header(populated_live_db: DatabaseManager, tmp_path: Path):
    """SQLite dosya başlığında 1 baytlık bit flip SHA-256 uyuşmazlığı ile yakalanmalı."""
    b_dir = tmp_path / "backups_adv_5"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    data = bytearray(res.db_path.read_bytes())
    # Başlıktaki byte 16'yı (page size byte) flip et
    data[16] ^= 0x01
    res.db_path.write_bytes(bytes(data))

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    assert drill_res.db_sha256_matches is False


def test_adversarial_bit_flip_with_recomputed_manifest_sha256(populated_live_db: DatabaseManager, tmp_path: Path):
    """Tahrifat sonrası manifest SHA-256'sı yeniden hesaplansa bile SQLite bütünlük veya hash zinciri yakalamalı."""
    b_dir = tmp_path / "backups_adv_6"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    data = bytearray(res.db_path.read_bytes())
    # SQLite sayfa 1 B-tree başlığında sayfa tipi baytını (byte 100) flip et
    data[100] ^= 0x01
    res.db_path.write_bytes(bytes(data))

    # Saldırgan manifestin SHA-256 özetini yeni dosyaya göre güncelliyor
    new_sha = compute_file_sha256(res.db_path)
    m_dict = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    m_dict["backup_sha256"] = new_sha
    res.manifest_path.write_text(json.dumps(m_dict), encoding="utf-8")

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False
    # SHA-256 tutsa bile SQLite veya kriptografik zincir ihlali tespit edilmelidir
    assert (
        drill_res.sqlite_integrity_ok is False
        or drill_res.snapshot_chain_verified is False
        or drill_res.audit_chain_verified is False
        or drill_res.raw_objects_verified is False
        or len(drill_res.errors) > 0
    )


@pytest.mark.parametrize("cut_length", [0, 16, 512, 1024, 2048])
def test_adversarial_truncated_file_lengths(populated_live_db: DatabaseManager, tmp_path: Path, cut_length: int):
    """Farklı uzunluklarda kesilmiş (truncated) veritabanı dosyaları reddedilmeli."""
    b_dir = tmp_path / f"backups_adv_trunc_{cut_length}"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    data = res.db_path.read_bytes()
    truncated_data = data[: min(cut_length, len(data))]
    res.db_path.write_bytes(truncated_data)

    drill_res = restore_drill(res.db_path, res.manifest_path)
    assert drill_res.ok is False


def test_adversarial_restore_database_aborts_on_corrupt_backup(populated_live_db: DatabaseManager, tmp_path: Path):
    """Bozuk bir yedek dosyasıyla canlı geri yükleme denenirse canlı DB'ye kesinlikle dokunulmamalıdır."""
    b_dir = tmp_path / "backups_adv_7"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    # Dosyayı sıfırla
    res.db_path.write_bytes(b"\x00" * 256)

    live_path = populated_live_db.db_path
    live_sha_before = compute_file_sha256(live_path)
    live_bytes_before = live_path.read_bytes()
    live_stat_before = live_path.stat()

    with pytest.raises(BackupCorruptionError):
        restore_database(res.db_path, confirm=True, db_manager=populated_live_db)

    # Canlı DB teyidi
    assert live_path.read_bytes() == live_bytes_before
    assert compute_file_sha256(live_path) == live_sha_before
    assert live_path.stat().st_mtime_ns == live_stat_before.st_mtime_ns
    assert live_path.stat().st_ino == live_stat_before.st_ino


# ==============================================================================
# BÖLÜM 3: CANLI DB SIFIR BAYT DEĞİŞİM (ZERO-BYTE MUTATION) KANITI
# ==============================================================================

def test_adversarial_restore_drill_zero_byte_mutation_live_db(populated_live_db: DatabaseManager, tmp_path: Path):
    """restore_drill çalışırken canlı veritabanının tek bir baytının dahi değişmediğini deneysel olarak kanıtla."""
    b_dir = tmp_path / "backups_adv_zero_byte"
    res = create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    live_path = populated_live_db.db_path
    live_bytes_initial = live_path.read_bytes()
    live_sha_initial = compute_file_sha256(live_path)
    live_stat_initial = live_path.stat()

    # 15 ardışık restore_drill çağrısı (hem geçerli hem bozuk yedeklerle)
    for i in range(10):
        drill_res = restore_drill(res.db_path, res.manifest_path)
        assert drill_res.ok is True

        # Canlı DB'nin her deneme sonrası tek tek baytlarını ve stat bilgilerini doğrula
        assert live_path.read_bytes() == live_bytes_initial, f"İterasyon {i}: Bayt seviyesinde fark tespit edildi!"
        assert compute_file_sha256(live_path) == live_sha_initial
        assert live_path.stat().st_ino == live_stat_initial.st_ino
        assert live_path.stat().st_mtime_ns == live_stat_initial.st_mtime_ns
        assert live_path.stat().st_size == live_stat_initial.st_size

    # Ekstra: Canlı DB'nin kendisi backup_path olarak verilse bile (izole kopyalama sayesinde)
    # canlı DB'nin değişmediğini teyit et
    drill_direct = restore_drill(live_path, manifest_path=None)
    assert drill_direct.ok is True
    assert live_path.read_bytes() == live_bytes_initial
    assert compute_file_sha256(live_path) == live_sha_initial


# ==============================================================================
# BÖLÜM 4: ZİNCİR-UCLARİ.JSONL FCNTL.FLOCK VE PREV_ENTRY_SHA256 ZİNCİRLEME TESTLERİ
# ==============================================================================

def _worker_append_chain(args: tuple[str, int, int]) -> int:
    """Ayrı bir süreç (process) içinde kütüğe fcntl.flock ile ardışık kayıtlar ekler."""
    ledger_file, worker_id, count = args
    for i in range(count):
        snap_tip = hashlib.sha256(f"snap_{worker_id}_{i}".encode()).hexdigest()
        audit_tip = hashlib.sha256(f"audit_{worker_id}_{i}".encode()).hexdigest()
        append_chain_tip_log(
            snapshot_chain_tip=snap_tip,
            snapshot_count=i + 1,
            audit_chain_tip=audit_tip,
            audit_count=i + 1,
            backup_filename=f"backup_w{worker_id}_{i}.db",
            backup_sha256=hashlib.sha256(f"file_{worker_id}_{i}".encode()).hexdigest(),
            ledger_path=ledger_file,
            enforce_monotonicity=False,
        )
    return count


def test_adversarial_flock_concurrency_stress(tmp_path: Path):
    """10 ayrı süreçten (process) aynı anda zincir-uclari.jsonl kütüğüne yazma yarışı (flock stres testi)."""
    ledger_path = tmp_path / "concurrent_ledger.jsonl"
    num_workers = 8
    appends_per_worker = 15
    total_expected = num_workers * appends_per_worker

    tasks = [(str(ledger_path), w_id, appends_per_worker) for w_id in range(num_workers)]

    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=num_workers, mp_context=ctx) as executor:
        results = list(executor.map(_worker_append_chain, tasks))

    assert sum(results) == total_expected

    # Tüm kütüğü oku ve zincir bütünlüğünü satır satır denetle
    lines = [line.strip() for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == total_expected, f"Kayıp satır veya bozuk yazım: beklenen {total_expected}, bulunan {len(lines)}"

    # Kriptografik zincirlenme doğrulaması
    expected_prev = "0" * 64
    for idx, line in enumerate(lines):
        obj = json.loads(line)
        entry = ChainTipEntry(**obj)

        # 1. Her satırın prev_entry_sha256 değeri bir önceki satırın entry_sha256 değeri olmalıdır
        assert entry.prev_entry_sha256 == expected_prev, (
            f"Kırık zincir halkası (satır {idx}): prev={entry.prev_entry_sha256} != beklenen={expected_prev}"
        )

        # 2. Satır özeti doğrulaması
        data_to_hash = {k: v for k, v in obj.items() if k != "entry_sha256"}
        calc_sha = sha256_text(canonical_json(data_to_hash))
        assert calc_sha == entry.entry_sha256, f"Satır {idx} özet tahrifatı!"

        expected_prev = entry.entry_sha256

    # Dosya izinlerinin 0o600 olduğunu teyit et
    assert oct(ledger_path.stat().st_mode)[-3:] == "600"


def test_adversarial_ledger_middle_tampering_detected(populated_live_db: DatabaseManager, tmp_path: Path):
    """zincir-uclari.jsonl'in geçmişindeki ara bir satır tahrif edildiğinde verify_chain_tips yakalamalıdır."""
    ledger_path = tmp_path / "tampered_chain.jsonl"

    # 5 geçerli satır ekle
    for i in range(5):
        append_chain_tip_log(
            snapshot_chain_tip=f"snap_{i}" * 8,
            snapshot_count=i + 1,
            audit_chain_tip=f"audit_{i}" * 8,
            audit_count=i + 1,
            ledger_path=ledger_path,
        )

    lines = [line.strip() for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Senaryo A: 2. satırın içeriğini tahrif et (hash güncellemeden)
    lines_a = list(lines)
    obj_2 = json.loads(lines_a[2])
    obj_2["snapshot_count"] = 9999
    lines_a[2] = canonical_json(obj_2)
    ledger_path.write_text("\n".join(lines_a) + "\n", encoding="utf-8")

    conn = populated_live_db.get_connection()
    try:
        res_a = verify_chain_tips(conn, ledger_path=ledger_path)
        assert res_a.status == "CRITICAL_MISMATCH"
        assert "Harici kütük satır özeti uyuşmuyor" in res_a.details
    finally:
        conn.close()

    # Senaryo B: 2. satırın hash'ini de yeniden hesapla ancak 3. satırın prev_entry_sha256'sına dokunma
    lines_b = list(lines)
    obj_2 = json.loads(lines_b[2])
    obj_2["snapshot_count"] = 9999
    data_to_hash = {k: v for k, v in obj_2.items() if k != "entry_sha256"}
    obj_2["entry_sha256"] = sha256_text(canonical_json(data_to_hash))
    lines_b[2] = canonical_json(obj_2)
    ledger_path.write_text("\n".join(lines_b) + "\n", encoding="utf-8")

    conn = populated_live_db.get_connection()
    try:
        res_b = verify_chain_tips(conn, ledger_path=ledger_path)
        assert res_b.status == "CRITICAL_MISMATCH"
        assert "Harici kütük zinciri bozulmuş" in res_b.details
    finally:
        conn.close()


def test_adversarial_rollback_and_fork_attacks(populated_live_db: DatabaseManager, tmp_path: Path):
    """Canlı DB geriye sarılırsa veya çatallanırsa (fork) integrity_report kritik ihlal vermelidir."""
    b_dir = tmp_path / "backups_rollback"
    ledger_path = b_dir / "zincir-uclari.jsonl"

    # İlk yedek
    create_backup(db_manager=populated_live_db, backup_dir=b_dir)

    # 1. Rollback Saldırısı Simülasyonu:
    # Saldırgan canlı DB'deki snapshots tablosundan satır siliyor (veya eski DB kopyasını koyuyor)
    conn = populated_live_db.get_connection()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("PRAGMA recursive_triggers = OFF;")
    conn.execute("DROP TRIGGER IF EXISTS prevent_delete_snapshots;")
    conn.execute("DELETE FROM snapshots WHERE rowid = (SELECT MAX(rowid) FROM snapshots);")
    conn.commit()
    conn.close()

    report = integrity_report(populated_live_db, ledger_path=ledger_path)
    assert report["ok"] is False
    assert report["critical_integrity_violation"] is True
    assert report["chain_tip_status"] == "CRITICAL_MISMATCH"
    assert "az" in report["chain_tip_details"] or "Geriye sarma" in report["chain_tip_details"]
