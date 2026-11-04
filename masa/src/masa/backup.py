"""ETF Yatırım Masası — SQLite Online Yedekleme, Doğrulama ve Zincir Ucu Modülü.

İP-1 Güvenlik ve Mimari Prensipleri:
1. Online Yedekleme: Python 3.13 sqlite3.Connection.backup(pages=250, sleep=0.01)
   ile canlı DB'deki yazıcıları (BEGIN IMMEDIATE) engellemeyecek şekilde chunked kopyalama.
2. Manifest ve Bütünlük: Her yedek için SHA-256 özeti, mühür/denetim zincir uçları ve
   tablo sayılarını içeren backup-<YYYYMMDD_HHMMSS>.json manifesti üretilir.
3. Bağımsız Kütük: masa/var/backups/zincir-uclari.jsonl dosyasına her yedekleme anında
   append-only, kriptografik olarak birbirine bağlı (prev_entry_sha256) satırlar eklenir.
4. restore_drill: Canlı veritabanına ASLA dokunmadan tempfile.TemporaryDirectory içinde
   manifest SHA-256 kontrolü, SQLite PRAGMA quick_check ve HashChainEngine alan düzeyinde
   tam yeniden doğrulama.
5. restore_database: Canlı veritabanı geri yükleme. --onayla (confirm=True) zorunludur.
   Canlı DB ezilmeden hemen önce masa.db.pre-restore-<ts>.bak olarak arşivlenir.
   Atomik dosya geçişi (os.replace) ve hata durumunda otomatik geri alma (rollback).
6. FileVault ve İzinler: Yedek dizini 0o700, dosyalar 0o600 izinleriyle korunur.
"""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

from masa.audit.events import AuditLogger
from masa.config import MASA_DIR
from masa.storage.db import DatabaseManager, SCHEMA_VERSION, default_db_path
from masa.storage.hash_chain import GENESIS_HASH, HashChainEngine, canonical_json, sha256_text


# ---------------------------------------------------------------- Exceptions
class BackupError(Exception):
    """Yedekleme veya geri yükleme işleminde temel hata."""


class BackupCorruptionError(BackupError):
    """Yedek dosyası bozuk, SHA-256 uyuşmuyor veya hash zinciri geçersiz."""


class RestoreConfirmationRequiredError(BackupError):
    """Canlı DB geri yükleme işlemi için onay bayrağı eksik."""


class RestoreExecutionError(BackupError):
    """Geri yükleme veya sahneleme aşamasında çalışma zamanı hatası."""


class ChainDivergenceError(BackupError):
    """Canlı veritabanı ile harici zincir ucu kütüğü arasında ayrışma tespit edildi."""


# ---------------------------------------------------------------- Pydantic v2 Modelleri
class BackupManifest(BaseModel):
    manifest_version: int = 1
    backup_timestamp: str
    backup_filename: str
    backup_sha256: str
    backup_bytes: int
    source_db_path: str
    schema_version: int
    snapshot_chain_tip: str
    snapshot_count: int
    audit_chain_tip: str
    audit_count: int
    raw_object_count: int
    table_counts: Dict[str, int] = Field(default_factory=dict)
    integrity_status: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ChainTipEntry(BaseModel):
    timestamp: str
    event: str = "BACKUP"
    backup_filename: Optional[str] = None
    backup_sha256: Optional[str] = None
    snapshot_chain_tip: str
    snapshot_count: int
    audit_chain_tip: str
    audit_count: int
    prev_entry_sha256: str = "0" * 64
    entry_sha256: str
    pruned_files: Optional[List[str]] = None


class RestoreDrillResult(BaseModel):
    ok: bool
    backup_path: str
    manifest_path: Optional[str] = None
    db_sha256_matches: bool = False
    sqlite_integrity_ok: bool = False
    schema_version: int = 0
    trigger_count: int = 0
    raw_objects_verified: bool = False
    snapshot_chain_verified: bool = False
    audit_chain_verified: bool = False
    tips_match_manifest: bool = False
    errors: List[str] = Field(default_factory=list)


class RestoreResult(BaseModel):
    success: bool
    restored_from: str
    archived_live_db: Optional[str] = None
    drill_result: Optional[RestoreDrillResult] = None
    error_message: Optional[str] = None


class BackupResult(BaseModel):
    success: bool
    db_path: Path
    manifest_path: Path
    manifest: BackupManifest
    chain_tip_recorded: bool
    drill_result: Optional[RestoreDrillResult] = None
    skipped: bool = False
    message: Optional[str] = None


class PruneResult(BaseModel):
    dry_run: bool
    total_backups: int
    kept_count: int
    pruned_count: int
    kept_files: List[str] = Field(default_factory=list)
    pruned_files: List[str] = Field(default_factory=list)
    protected_latest: Optional[str] = None
    protected_drill: Optional[str] = None
    ledger_updated: bool = False
    message: str = ""


class ChainVerificationResult(BaseModel):
    status: str  # "MATCH_SEALED", "AHEAD_OF_SEALED", "NO_EXTERNAL_LEDGER", "CRITICAL_MISMATCH"
    details: str
    live_snapshot_tip: Optional[str] = None
    sealed_snapshot_tip: Optional[str] = None
    live_audit_tip: Optional[str] = None
    sealed_audit_tip: Optional[str] = None
    live_snapshot_count: int = 0
    sealed_snapshot_count: int = 0


# ---------------------------------------------------------------- Yardımcı Fonksiyonlar
def default_backup_dir() -> Path:
    """Yedekleme dizinini döner (MASA_BACKUP_DIR çevre değişkeni veya varsayılan)."""
    env = os.environ.get("MASA_BACKUP_DIR")
    if env:
        return Path(env)
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("CRITICAL: Test ortamında MASA_BACKUP_DIR ayarlanmadan canlı yedekleme dizinine erişim yasaktır!")
    return MASA_DIR / "var" / "backups"


def default_ledger_path(backup_dir: Optional[Path | str] = None) -> Path:
    """Bağımsız zincir ucu kütüğü yolunu döner."""
    b_dir = Path(backup_dir) if backup_dir else default_backup_dir()
    return b_dir / "zincir-uclari.jsonl"


def compute_file_sha256(file_path: Path | str) -> str:
    """Dosyanın SHA-256 özetini bellek dostu (64KB bloklar) hesaplar."""
    p = Path(file_path)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_filevault_status() -> str:
    """macOS fdesetup status komutunu çalıştırarak FileVault şifreleme durumunu döner."""
    if sys.platform != "darwin":
        return "macOS değil (FileVault uygulanamaz)"
    try:
        res = subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=3.0)
        out = res.stdout.strip()
        if "FileVault is On" in out:
            return "FileVault Açık (Disk Şifreli - APFS XTS-AES)"
        elif "FileVault is Off" in out:
            return "FileVault Kapalı (UYARI: Disk şifrelenmemiş)"
        return out or "Bilinmiyor"
    except Exception as exc:
        return f"Kontrol edilemedi ({exc})"


def find_latest_backup(backup_dir: Optional[Path | str] = None) -> Optional[Path]:
    """En son alınan yedek .db dosyasını bulur."""
    b_dir = Path(backup_dir) if backup_dir else default_backup_dir()
    if not b_dir.exists():
        return None
    db_files = sorted(b_dir.glob("backup-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return db_files[0] if db_files else None


# ---------------------------------------------------------------- Zincir Ucu Kütüğü (zincir-uclari.jsonl)
def append_chain_tip_log(
    snapshot_chain_tip: str,
    snapshot_count: int,
    audit_chain_tip: str,
    audit_count: int,
    backup_filename: Optional[str] = None,
    backup_sha256: Optional[str] = None,
    event: str = "BACKUP",
    ledger_path: Optional[Path | str] = None,
    enforce_monotonicity: bool = True,
    pruned_files: Optional[List[str]] = None,
) -> ChainTipEntry:
    """Bağımsız append-only zincir ucu kütüğüne fcntl dosya kilidiyle kriptografik satır ekler."""
    path = Path(ledger_path) if ledger_path else default_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            lines = [line.strip() for line in f if line.strip()]
            prev_entry_sha256 = "0" * 64
            if lines:
                try:
                    last_obj = json.loads(lines[-1])
                    prev_entry_sha256 = last_obj.get("entry_sha256", "0" * 64)
                    if event == "BACKUP" and enforce_monotonicity:
                        last_snap_cnt = int(last_obj.get("snapshot_count", 0))
                        last_audit_cnt = int(last_obj.get("audit_count", 0))
                        if snapshot_count < last_snap_cnt or audit_count < last_audit_cnt:
                            raise RuntimeError(
                                f"CRITICAL: Onaysız geriye sarma (unapproved rewind) engellendi! "
                                f"Yedeklenecek DB mühür/denetim sayısı ({snapshot_count}/{audit_count}), "
                                f"kütükteki son onaylı durumdan ({last_snap_cnt}/{last_audit_cnt}) az. "
                                "Geri yükleme işlemi yalnız onaylı 'masa geri-yukle --onayla' ile yetkilendirilebilir."
                            )
                except RuntimeError:
                    raise
                except Exception:
                    pass

            ts = datetime.now(timezone.utc).isoformat()
            data_to_hash = {
                "timestamp": ts,
                "event": event,
                "backup_filename": backup_filename,
                "backup_sha256": backup_sha256,
                "snapshot_chain_tip": snapshot_chain_tip,
                "snapshot_count": snapshot_count,
                "audit_chain_tip": audit_chain_tip,
                "audit_count": audit_count,
                "prev_entry_sha256": prev_entry_sha256,
            }
            if pruned_files is not None:
                data_to_hash["pruned_files"] = sorted(pruned_files)
            entry_sha256 = sha256_text(canonical_json(data_to_hash))
            entry_data = {**data_to_hash, "entry_sha256": entry_sha256}

            f.seek(0, os.SEEK_END)
            f.write(canonical_json(entry_data) + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return ChainTipEntry(**entry_data)


def verify_chain_tips(
    conn: sqlite3.Connection,
    ledger_path: Optional[Path | str] = None,
) -> ChainVerificationResult:
    """Canlı veritabanındaki zincir uçlarını bağımsız zincir-uclari.jsonl kütüğü ile çapraz denetler."""
    path = Path(ledger_path) if ledger_path else default_ledger_path()

    live_snap_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    live_audit_count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    live_snap_row = conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
    live_snap_tip = live_snap_row[0] if live_snap_row else GENESIS_HASH
    live_audit_row = conn.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
    live_audit_tip = live_audit_row[0] if live_audit_row else GENESIS_HASH

    if not path.exists() or path.stat().st_size == 0:
        if live_snap_count == 0 and live_audit_count == 0:
            return ChainVerificationResult(
                status="NO_EXTERNAL_LEDGER",
                details="Veritabanı ve harici zincir ucu kütüğü henüz boş (genesis durumu).",
                live_snapshot_tip=live_snap_tip,
                live_audit_tip=live_audit_tip,
                live_snapshot_count=live_snap_count,
                sealed_snapshot_count=0,
            )
        return ChainVerificationResult(
            status="NO_EXTERNAL_LEDGER",
            details="Harici zincir ucu kütüğü (zincir-uclari.jsonl) bulunamadı. İlk yedeği almak için: masa yedek",
            live_snapshot_tip=live_snap_tip,
            live_audit_tip=live_audit_tip,
            live_snapshot_count=live_snap_count,
            sealed_snapshot_count=0,
        )

    # Read ledger lines
    with open(path, "r", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            lines = [line.strip() for line in f if line.strip()]
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    if not lines:
        return ChainVerificationResult(
            status="NO_EXTERNAL_LEDGER",
            details="Harici zincir ucu kütüğü boş.",
            live_snapshot_tip=live_snap_tip,
            live_audit_tip=live_audit_tip,
            live_snapshot_count=live_snap_count,
            sealed_snapshot_count=0,
        )

    # Verify ledger's internal hash chain and collect entries
    expected_prev = "0" * 64
    parsed_entries: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except Exception as e:
            return ChainVerificationResult(
                status="CRITICAL_MISMATCH",
                details=f"Harici kütük {idx+1}. satır JSON hatası: {e}",
                live_snapshot_tip=live_snap_tip,
                live_audit_tip=live_audit_tip,
                live_snapshot_count=live_snap_count,
            )
        if idx == 0 and obj.get("event") == "RESTORE":
            expected_prev = obj.get("prev_entry_sha256", "0" * 64)
        if obj.get("prev_entry_sha256") != expected_prev:
            return ChainVerificationResult(
                status="CRITICAL_MISMATCH",
                details=(
                    f"Harici kütük zinciri bozulmuş (satır {idx+1}): "
                    f"prev_entry_sha256={obj.get('prev_entry_sha256')} != beklenen {expected_prev}"
                ),
                live_snapshot_tip=live_snap_tip,
                live_audit_tip=live_audit_tip,
                live_snapshot_count=live_snap_count,
            )
        data_to_hash = {k: v for k, v in obj.items() if k != "entry_sha256"}
        calc_hash = sha256_text(canonical_json(data_to_hash))
        if calc_hash != obj.get("entry_sha256"):
            return ChainVerificationResult(
                status="CRITICAL_MISMATCH",
                details=f"Harici kütük satır özeti uyuşmuyor (satır {idx+1})",
                live_snapshot_tip=live_snap_tip,
                live_audit_tip=live_audit_tip,
                live_snapshot_count=live_snap_count,
            )
        expected_prev = obj["entry_sha256"]
        parsed_entries.append(obj)

    latest_entry = parsed_entries[-1]
    sealed_snap_tip = latest_entry["snapshot_chain_tip"]
    sealed_snap_count = int(latest_entry["snapshot_count"])
    sealed_audit_tip = latest_entry["audit_chain_tip"]
    sealed_audit_count = int(latest_entry["audit_count"])

    # Check 1: Unapproved rewind in ledger history (monotonicity violation in ledger)
    for idx in range(1, len(parsed_entries)):
        prev_e = parsed_entries[idx - 1]
        curr_e = parsed_entries[idx]
        if curr_e.get("event") != "RESTORE":
            if (int(curr_e.get("snapshot_count", 0)) < int(prev_e.get("snapshot_count", 0)) or
                int(curr_e.get("audit_count", 0)) < int(prev_e.get("audit_count", 0))):
                return ChainVerificationResult(
                    status="CRITICAL_CHAIN_REWIND_DETECTED",
                    details=(
                        f"CRITICAL: Harici kütükte onaysız geriye sarma (unapproved rewind) tespit edildi! "
                        f"Satır {idx+1} ({curr_e.get('event', 'BACKUP')}) mühür/denetim sayısı ({curr_e.get('snapshot_count')}/{curr_e.get('audit_count')}), "
                        f"önceki satırdan ({prev_e.get('snapshot_count')}/{prev_e.get('audit_count')}) az ve 'RESTORE' onayı içermiyor."
                    ),
                    live_snapshot_tip=live_snap_tip,
                    sealed_snapshot_tip=sealed_snap_tip,
                    live_audit_tip=live_audit_tip,
                    sealed_audit_tip=sealed_audit_tip,
                    live_snapshot_count=live_snap_count,
                    sealed_snapshot_count=sealed_snap_count,
                )

    # Check 2: Truncation/Rollback attack on live database (live count strictly less than sealed count)
    if live_snap_count < sealed_snap_count or live_audit_count < sealed_audit_count:
        return ChainVerificationResult(
            status="CRITICAL_MISMATCH",
            details=(
                f"CRITICAL: Canlı veritabanındaki kayıt sayısı dış kütükteki mühürlü sayıdan az! "
                f"Mühür: {live_snap_count} < {sealed_snap_count}, Denetim: {live_audit_count} < {sealed_audit_count}. "
                "Geriye sarma (rollback) veya veri silinmesi tespit edildi."
            ),
            live_snapshot_tip=live_snap_tip,
            sealed_snapshot_tip=sealed_snap_tip,
            live_audit_tip=live_audit_tip,
            sealed_audit_tip=sealed_audit_tip,
            live_snapshot_count=live_snap_count,
            sealed_snapshot_count=sealed_snap_count,
        )

    # Check 3: Monotonicity - Containment of ALL historical tips in the active chain
    active_start_idx = 0
    for idx in range(len(parsed_entries) - 1, -1, -1):
        if parsed_entries[idx].get("event") == "RESTORE":
            active_start_idx = idx
            break

    for idx in range(active_start_idx, len(parsed_entries)):
        ent = parsed_entries[idx]
        e_snap_tip = ent.get("snapshot_chain_tip")
        e_snap_cnt = int(ent.get("snapshot_count", 0))
        if e_snap_cnt > 0 and e_snap_tip and e_snap_tip != ("0" * 64):
            found_snap = conn.execute("SELECT 1 FROM snapshots WHERE curr_hash = ?", (e_snap_tip,)).fetchone()
            if not found_snap:
                return ChainVerificationResult(
                    status="CRITICAL_MISMATCH",
                    details=(
                        f"CRITICAL: Kütükteki önceki mühür ucu ({e_snap_tip[:12]}…, count={e_snap_cnt}, satır={idx+1}) "
                        f"canlı veritabanında bulunamadı! Zincir çatallanması, manipülasyon veya farklı veritabanı tespit edildi."
                    ),
                    live_snapshot_tip=live_snap_tip,
                    sealed_snapshot_tip=e_snap_tip,
                    live_audit_tip=live_audit_tip,
                    sealed_audit_tip=sealed_audit_tip,
                    live_snapshot_count=live_snap_count,
                    sealed_snapshot_count=sealed_snap_count,
                )
        e_audit_tip = ent.get("audit_chain_tip")
        e_audit_cnt = int(ent.get("audit_count", 0))
        if e_audit_cnt > 0 and e_audit_tip and e_audit_tip != ("0" * 64):
            found_audit = conn.execute("SELECT 1 FROM audit_events WHERE curr_hash = ?", (e_audit_tip,)).fetchone()
            if not found_audit:
                return ChainVerificationResult(
                    status="CRITICAL_MISMATCH",
                    details=(
                        f"CRITICAL: Kütükteki önceki denetim ucu ({e_audit_tip[:12]}…, count={e_audit_cnt}, satır={idx+1}) "
                        f"canlı veritabanında bulunamadı!"
                    ),
                    live_snapshot_tip=live_snap_tip,
                    sealed_snapshot_tip=sealed_snap_tip,
                    live_audit_tip=live_audit_tip,
                    sealed_audit_tip=e_audit_tip,
                    live_snapshot_count=live_snap_count,
                    sealed_snapshot_count=sealed_snap_count,
                )

    # Check 4: Exact tip match
    if live_snap_tip == sealed_snap_tip and live_audit_tip == sealed_audit_tip:
        return ChainVerificationResult(
            status="MATCH_SEALED",
            details="Canlı veritabanı uçları harici kütükteki son mühürlü uçlarla birebir eşleşiyor.",
            live_snapshot_tip=live_snap_tip,
            sealed_snapshot_tip=sealed_snap_tip,
            live_audit_tip=live_audit_tip,
            sealed_audit_tip=sealed_audit_tip,
            live_snapshot_count=live_snap_count,
            sealed_snapshot_count=sealed_snap_count,
        )

    # Check 5: Live DB is ahead of sealed backup (and passed all historical containment checks above)
    return ChainVerificationResult(
        status="AHEAD_OF_SEALED",
        details=(
            f"Canlı veritabanı mühürlü yedekten ileride (tüm mühürlü uçlar canlı DB geçmişinde doğrulandı; "
            f"son yedekten sonra {live_snap_count - sealed_snap_count} yeni mühür, "
            f"{live_audit_count - sealed_audit_count} yeni denetim olayı)."
        ),
        live_snapshot_tip=live_snap_tip,
        sealed_snapshot_tip=sealed_snap_tip,
        live_audit_tip=live_audit_tip,
        sealed_audit_tip=sealed_audit_tip,
        live_snapshot_count=live_snap_count,
        sealed_snapshot_count=sealed_snap_count,
    )


# ---------------------------------------------------------------- restore_drill
def restore_drill(
    backup_db_path: Path | str,
    manifest_path: Optional[Path | str] = None,
) -> RestoreDrillResult:
    """Canlı DB'ye ASLA dokunmadan tempfile içinde yedeği tam kriptografik olarak doğrular."""
    backup_path = Path(backup_db_path).resolve()
    errors: List[str] = []

    if not backup_path.exists():
        return RestoreDrillResult(
            ok=False,
            backup_path=str(backup_path),
            errors=[f"Yedek dosyası mevcut değil: {backup_path}"],
        )

    # 1. Manifest çözümleme
    manifest: Optional[BackupManifest] = None
    m_path = Path(manifest_path).resolve() if manifest_path else backup_path.with_suffix(".json")
    if m_path.exists():
        try:
            m_data = json.loads(m_path.read_text(encoding="utf-8"))
            manifest = BackupManifest(**m_data)
        except Exception as exc:
            errors.append(f"Manifest okunamadı veya geçersiz: {exc}")

    # 2. SHA-256 doğrulama
    computed_sha256 = compute_file_sha256(backup_path)
    sha_match = True
    if manifest:
        sha_match = (computed_sha256 == manifest.backup_sha256)
        if not sha_match:
            errors.append(
                f"SHA-256 uyuşmazlığı: manifest={manifest.backup_sha256}, hesaplanan={computed_sha256}"
            )
            return RestoreDrillResult(
                ok=False,
                backup_path=str(backup_path),
                manifest_path=str(m_path) if m_path.exists() else None,
                db_sha256_matches=False,
                errors=errors,
            )

    # 3. İzole geçici dizinde prova (Canlı DB yoluyla çakışmadığı zorunlu assert ile denetlenir)
    sqlite_integrity_ok = False
    schema_version = 0
    trigger_count = 0
    raw_objects_ok = False
    snapshot_chain_ok = False
    audit_chain_ok = False
    tips_match = False

    with tempfile.TemporaryDirectory(prefix="masa_restore_drill_") as tmp_dir:
        try:
            os.chmod(tmp_dir, 0o700)
        except OSError:
            pass

        drill_db_path = Path(tmp_dir) / "drill.db"
        assert drill_db_path.resolve() != default_db_path().resolve(), "CRITICAL: Prova canlı veritabanına işaret edemez!"

        try:
            shutil.copy2(backup_path, drill_db_path)
            os.chmod(drill_db_path, 0o600)
        except Exception as exc:
            errors.append(f"Yedek geçici alana kopyalanamadı: {exc}")
            return RestoreDrillResult(
                ok=False,
                backup_path=str(backup_path),
                manifest_path=str(m_path) if m_path.exists() else None,
                db_sha256_matches=sha_match,
                errors=errors,
            )

        try:
            conn = sqlite3.connect(str(drill_db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA recursive_triggers = ON;")

            # PRAGMA quick_check ve integrity_check
            try:
                q_res = conn.execute("PRAGMA quick_check;").fetchall()
                i_res = conn.execute("PRAGMA integrity_check;").fetchall()
                q_ok = len(q_res) == 1 and q_res[0][0] == "ok"
                i_ok = len(i_res) == 1 and i_res[0][0] == "ok"
                sqlite_integrity_ok = q_ok and i_ok
                if not sqlite_integrity_ok:
                    errors.append(f"SQLite PRAGMA bütünlük hatası: quick={q_res}, integrity={i_res}")
            except Exception as e:
                errors.append(f"SQLite PRAGMA kontrolü çalıştırılamadı: {e}")

            # Şema sürümü ve tetikleyici sayısı
            try:
                schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                expected_version = manifest.schema_version if manifest else SCHEMA_VERSION
                if schema_version != expected_version:
                    errors.append(f"Şema sürümü uyuşmazlığı: beklenen {expected_version}, bulunan {schema_version}")
                trigger_count = int(
                    conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
                )
                if trigger_count < 24:
                    errors.append(f"Tetikleyici sayısı yetersiz: beklenen >=24, bulunan {trigger_count}")
            except Exception as e:
                errors.append(f"Şema meta verisi okunamadı: {e}")

            # Hash zinciri alan düzeyinde yeniden hesaplama
            try:
                raw_ok, raw_err = HashChainEngine.verify_raw_objects(conn)
                raw_objects_ok = raw_ok
                if not raw_ok:
                    errors.append(f"raw_objects doğrulaması başarısız: {raw_err}")

                snap_ok, snap_err = HashChainEngine.verify_snapshot_chain(conn)
                snapshot_chain_ok = snap_ok
                if not snap_ok:
                    errors.append(f"snapshots zincir doğrulaması başarısız: {snap_err}")

                aud_ok, aud_err = HashChainEngine.verify_audit_chain(conn)
                audit_chain_ok = aud_ok
                if not aud_ok:
                    errors.append(f"audit_events zincir doğrulaması başarısız: {aud_err}")
            except Exception as e:
                errors.append(f"Kriptografik zincir doğrulaması sırasında hata: {e}")

            # Manifest zincir uçları ile karşılaştırma
            if manifest:
                live_snap_row = conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
                drill_snap_tip = live_snap_row[0] if live_snap_row else GENESIS_HASH
                live_audit_row = conn.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
                drill_audit_tip = live_audit_row[0] if live_audit_row else GENESIS_HASH

                tips_match = (
                    drill_snap_tip == manifest.snapshot_chain_tip
                    and drill_audit_tip == manifest.audit_chain_tip
                )
                if not tips_match:
                    errors.append(
                        f"Yedek DB zincir uçları manifest ile uyuşmuyor: "
                        f"snap({drill_snap_tip} != {manifest.snapshot_chain_tip}), "
                        f"audit({drill_audit_tip} != {manifest.audit_chain_tip})"
                    )
            else:
                tips_match = True
        except Exception as exc:
            errors.append(f"Prova bağlantısında hata: {exc}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    overall_ok = (
        len(errors) == 0
        and sha_match
        and sqlite_integrity_ok
        and raw_objects_ok
        and snapshot_chain_ok
        and audit_chain_ok
        and tips_match
    )
    return RestoreDrillResult(
        ok=overall_ok,
        backup_path=str(backup_path),
        manifest_path=str(m_path) if m_path.exists() else None,
        db_sha256_matches=sha_match,
        sqlite_integrity_ok=sqlite_integrity_ok,
        schema_version=schema_version,
        trigger_count=trigger_count,
        raw_objects_verified=raw_objects_ok,
        snapshot_chain_verified=snapshot_chain_ok,
        audit_chain_verified=audit_chain_ok,
        tips_match_manifest=tips_match,
        errors=errors,
    )


# ---------------------------------------------------------------- create_backup
def create_backup(
    db_manager: Optional[DatabaseManager] = None,
    backup_dir: Optional[Path | str] = None,
    pages_per_step: int = 250,
    sleep_between_steps: float = 0.01,
    run_drill: bool = False,
    force: bool = False,
) -> BackupResult:
    """Canlı SQLite veritabanından non-blocking online yedek alır, manifest üretir ve kütüğe ekler."""
    mgr = db_manager or DatabaseManager()
    source_db_path = mgr.db_path
    if not source_db_path.exists():
        raise BackupError(f"Canlı veritabanı bulunamadı: {source_db_path}")

    canonical_live_path = MASA_DIR / "var" / "private" / "masa.db"
    env_db_path = Path(os.environ["MASA_DB_PATH"]).resolve() if "MASA_DB_PATH" in os.environ else None
    try:
        source_resolved = source_db_path.resolve()
        is_live = (source_resolved == canonical_live_path.resolve()) or (env_db_path and source_resolved == env_db_path)
    except Exception:
        is_live = False

    if backup_dir:
        b_dir = Path(backup_dir)
    elif is_live and os.environ.get("MASA_BACKUP_DIR"):
        b_dir = Path(os.environ["MASA_BACKUP_DIR"])
    elif is_live:
        b_dir = default_backup_dir()
    else:
        b_dir = source_db_path.parent / "backups"
    b_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(b_dir, 0o700)
    except OSError:
        pass

    # Deduplication check: İşlem/denetim ve mühür uçları değişmemişse gereksiz yedek alma
    ledger_path = default_ledger_path(b_dir)
    if ledger_path.exists() and not force:
        source_conn = mgr.get_connection()
        try:
            tip_verif = verify_chain_tips(source_conn, ledger_path=ledger_path)
            if tip_verif.status == "MATCH_SEALED":
                latest_backup = None
                with open(ledger_path, "r", encoding="utf-8") as lf:
                    for line in lf:
                        if line.strip():
                            try:
                                ent = json.loads(line)
                                if ent.get("event") == "BACKUP" and ent.get("backup_filename"):
                                    latest_backup = ent
                            except Exception:
                                pass
                if latest_backup:
                    b_file = b_dir / latest_backup["backup_filename"]
                    m_file = b_dir / Path(latest_backup["backup_filename"]).with_suffix(".json")
                    if b_file.exists() and m_file.exists():
                        m_obj = BackupManifest(**json.loads(m_file.read_text(encoding="utf-8")))
                        drill_res = None
                        if run_drill:
                            drill_res = restore_drill(b_file, m_file)
                            if not drill_res.ok:
                                raise BackupCorruptionError(f"Yedekleme provası başarısız oldu: {drill_res.errors}")
                            if not m_obj.integrity_status.get("drill_verified"):
                                m_obj.integrity_status["drill_verified"] = True
                                m_file.write_text(canonical_json(m_obj.model_dump()), encoding="utf-8")
                        return BackupResult(
                            success=True,
                            db_path=b_file,
                            manifest_path=m_file,
                            manifest=m_obj,
                            chain_tip_recorded=True,
                            drill_result=drill_res,
                            skipped=True,
                            message=f"Değişiklik yok, son yedek {latest_backup['backup_filename']} ({latest_backup.get('timestamp')}) geçerli, yeni yedek atlandı.",
                        )
        finally:
            source_conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = f"backup-{ts}"
    if (b_dir / f"{base_name}.db").exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"backup-{ts}"

    tmp_db_path = b_dir / f"{base_name}.db.tmp"
    final_db_path = b_dir / f"{base_name}.db"
    manifest_path = b_dir / f"{base_name}.json"

    # Adım 1: Canlı DB'ye yedekleme denetim olayı işleme (yedeğe dahil olması için)
    try:
        AuditLogger(mgr).log_event(
            actor="masa.backup",
            action="CREATE_BACKUP",
            entity_type="backup",
            entity_id=final_db_path.name,
            payload={
                "backup_filename": final_db_path.name,
                "target_dir": str(b_dir),
                "timestamp": ts,
            },
        )
    except Exception:
        pass


    # Adım 2: Geçici dosyaya online chunked kopyalama
    source_conn = mgr.get_connection()
    try:
        tmp_conn = sqlite3.connect(str(tmp_db_path), timeout=5.0)
        try:
            os.chmod(tmp_db_path, 0o600)
        except OSError:
            pass
        try:
            source_conn.backup(tmp_conn, pages=pages_per_step, sleep=sleep_between_steps)
        finally:
            tmp_conn.close()
    finally:
        source_conn.close()


    # Adım 2: Geçici dosyanın doğrulanması
    try:
        check_conn = sqlite3.connect(str(tmp_db_path), timeout=5.0)
        check_conn.row_factory = sqlite3.Row
        try:
            q_check = check_conn.execute("PRAGMA quick_check;").fetchone()[0]
            if q_check != "ok":
                raise BackupCorruptionError(f"Geçici yedek dosyasında SQLite quick_check hatası: {q_check}")

            raw_ok, raw_err = HashChainEngine.verify_raw_objects(check_conn)
            snap_ok, snap_err = HashChainEngine.verify_snapshot_chain(check_conn)
            aud_ok, aud_err = HashChainEngine.verify_audit_chain(check_conn)
            if not (raw_ok and snap_ok and aud_ok):
                raise BackupCorruptionError(
                    f"Geçici yedek hash zinciri doğrulaması başarısız: raw={raw_err}, snap={snap_err}, audit={aud_err}"
                )

            schema_version = int(check_conn.execute("PRAGMA user_version").fetchone()[0])
            snap_count = int(check_conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            audit_count = int(check_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            raw_count = int(check_conn.execute("SELECT COUNT(*) FROM raw_objects").fetchone()[0])

            snap_tip_row = check_conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
            snap_tip = snap_tip_row[0] if snap_tip_row else GENESIS_HASH

            audit_tip_row = check_conn.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
            audit_tip = audit_tip_row[0] if audit_tip_row else GENESIS_HASH

            table_counts: Dict[str, int] = {}
            for tbl in ["quotes", "position_observations", "cash_observations", "transaction_observations", "series_points", "jobs"]:
                try:
                    table_counts[tbl] = int(check_conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
                except Exception:
                    pass
        finally:
            check_conn.close()
    except Exception as exc:
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass
        raise BackupError(f"Yedekleme doğrulaması başarısız oldu, geçici dosya silindi: {exc}") from exc

    # Adım 3: Atomik dosya terfisi
    os.replace(tmp_db_path, final_db_path)
    try:
        os.chmod(final_db_path, 0o600)
    except OSError:
        pass

    # Adım 4: SHA-256 ve manifest üretimi
    backup_sha256 = compute_file_sha256(final_db_path)
    backup_bytes = final_db_path.stat().st_size

    manifest = BackupManifest(
        manifest_version=1,
        backup_timestamp=ts,
        backup_filename=final_db_path.name,
        backup_sha256=backup_sha256,
        backup_bytes=backup_bytes,
        source_db_path=str(source_db_path),
        schema_version=schema_version,
        snapshot_chain_tip=snap_tip,
        snapshot_count=snap_count,
        audit_chain_tip=audit_tip,
        audit_count=audit_count,
        raw_object_count=raw_count,
        table_counts=table_counts,
        integrity_status={
            "sqlite_integrity_check": "ok",
            "snapshot_chain_ok": True,
            "audit_chain_ok": True,
            "raw_objects_ok": True,
        },
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    manifest_path.write_text(canonical_json(manifest.model_dump()), encoding="utf-8")
    try:
        os.chmod(manifest_path, 0o600)
    except OSError:
        pass

    # Adım 5: Bağımsız kütüğe ekleme
    ledger_path = default_ledger_path(b_dir)
    append_chain_tip_log(
        snapshot_chain_tip=snap_tip,
        snapshot_count=snap_count,
        audit_chain_tip=audit_tip,
        audit_count=audit_count,
        backup_filename=final_db_path.name,
        backup_sha256=backup_sha256,
        event="BACKUP",
        ledger_path=ledger_path,
    )

    # Adım 6: İsteğe bağlı prova
    drill_res: Optional[RestoreDrillResult] = None
    if run_drill:
        drill_res = restore_drill(final_db_path, manifest_path)
        if not drill_res.ok:
            raise BackupCorruptionError(f"Yedekleme provası başarısız oldu: {drill_res.errors}")
        manifest.integrity_status["drill_verified"] = True
        manifest_path.write_text(canonical_json(manifest.model_dump()), encoding="utf-8")

    return BackupResult(
        success=True,
        db_path=final_db_path,
        manifest_path=manifest_path,
        manifest=manifest,
        chain_tip_recorded=True,
        drill_result=drill_res,
    )


# ---------------------------------------------------------------- restore_database
def restore_database(
    backup_db_path: Path | str,
    manifest_path: Optional[Path | str] = None,
    confirm: bool = False,
    db_manager: Optional[DatabaseManager] = None,
) -> RestoreResult:
    """Canlı DB'yi arşivleyerek yedeği atomik ve güvenli şekilde geri yükler."""
    if not confirm:
        raise RestoreConfirmationRequiredError(
            "Canlı veritabanı geri yükleme işlemi için 'confirm=True' (--onayla) zorunludur."
        )

    b_path = Path(backup_db_path).resolve()
    if not b_path.exists():
        raise BackupError(f"Geri yüklenecek yedek dosyası bulunamadı: {b_path}")

    # Adım 1: Ön prova (restore_drill) — canlı veritabanına dokunulmaz
    drill_res = restore_drill(b_path, manifest_path)
    if not drill_res.ok:
        raise BackupCorruptionError(
            f"Geri yükleme provası başarısız oldu, canlı DB'ye dokunulmadı: {drill_res.errors}"
        )

    mgr = db_manager or DatabaseManager()
    live_db_path = mgr.db_path
    live_parent = live_db_path.parent
    live_parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(live_parent, 0o700)
    except OSError:
        pass

    # Adım 2: Canlı veritabanının otomatik arşivlenmesi (.bak)
    archived_live_path: Optional[Path] = None
    if live_db_path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archived_live_path = live_parent / f"masa.db.pre-restore-{ts}.bak"
        if archived_live_path.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            archived_live_path = live_parent / f"masa.db.pre-restore-{ts}.bak"
        shutil.copy2(live_db_path, archived_live_path)
        try:
            os.chmod(archived_live_path, 0o600)
        except OSError:
            pass

    # Adım 3: Aynı dizinde sahneleme ve atomik os.replace
    staging_path = live_parent / f".masa.db.restoring-{uuid.uuid4().hex[:8]}.tmp"
    try:
        shutil.copy2(b_path, staging_path)
        try:
            os.chmod(staging_path, 0o600)
        except OSError:
            pass

        # Sahnelenen dosyada hızlı SQLite testi
        test_conn = sqlite3.connect(str(staging_path), timeout=5.0)
        try:
            q_res = test_conn.execute("PRAGMA quick_check;").fetchone()[0]
            if q_res != "ok":
                raise RestoreExecutionError(f"Sahnelenen kopya bozuk: {q_res}")
        finally:
            test_conn.close()

        # Atomik geçiş
        os.replace(staging_path, live_db_path)
        try:
            os.chmod(live_db_path, 0o600)
        except OSError:
            pass

        # Eski journal dosyasını temizle
        journal_path = Path(str(live_db_path) + "-journal")
        if journal_path.exists():
            try:
                journal_path.unlink()
            except OSError:
                pass
    except Exception as exc:
        # Otomatik geri alma (Rollback)
        if archived_live_path and archived_live_path.exists():
            try:
                os.replace(archived_live_path, live_db_path)
            except Exception:
                pass
        if staging_path.exists():
            try:
                staging_path.unlink()
            except OSError:
                pass
        raise RestoreExecutionError(f"Geri yükleme sırasında hata oluştu, geri alındı: {exc}") from exc

    # Adım 4: Geri yükleme sonrası denetim olayı ve bağımsız kütüğe RESTORE kaydı işleme
    try:
        AuditLogger(mgr).log_event(
            actor="masa.restore",
            action="RESTORE_DATABASE",
            entity_type="database",
            entity_id=live_db_path.name,
            payload={
                "restored_from": str(b_path),
                "manifest_path": str(manifest_path) if manifest_path else None,
                "archived_live_db": str(archived_live_path) if archived_live_path else None,
                "restored_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        pass

    try:
        res_conn = sqlite3.connect(str(live_db_path), timeout=5.0)
        try:
            s_row = res_conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
            r_snap_tip = s_row[0] if s_row else ("0" * 64)
            r_snap_count = int(res_conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            a_row = res_conn.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
            r_audit_tip = a_row[0] if a_row else ("0" * 64)
            r_audit_count = int(res_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
        finally:
            res_conn.close()

        cand_ledger = default_ledger_path()
        if hasattr(mgr, "db_path"):
            cand_backups = mgr.db_path.parent / "backups"
            if cand_backups.exists():
                cand_ledger = cand_backups / "zincir-uclari.jsonl"
            elif (mgr.db_path.parent.parent / "backups").exists():
                cand_ledger = mgr.db_path.parent.parent / "backups" / "zincir-uclari.jsonl"

        append_chain_tip_log(
            snapshot_chain_tip=r_snap_tip,
            snapshot_count=r_snap_count,
            audit_chain_tip=r_audit_tip,
            audit_count=r_audit_count,
            backup_filename=b_path.name,
            backup_sha256=compute_file_sha256(b_path),
            event="RESTORE",
            ledger_path=cand_ledger,
        )
    except Exception as log_err:
        logger.warning(f"RESTORE kütük kaydı eklenemedi: {log_err}")

    return RestoreResult(
        success=True,
        restored_from=str(b_path),
        archived_live_db=str(archived_live_path) if archived_live_path else None,
        drill_result=drill_res,
    )


# ---------------------------------------------------------------- prune_backups
def prune_backups(
    backup_dir: Optional[Path | str] = None,
    dry_run: bool = True,
    confirmed: bool = False,
    retention_daily: int = 7,
    retention_weekly: int = 4,
    retention_monthly: int = 12,
    db_manager: Optional[DatabaseManager] = None,
) -> PruneResult:
    """GFS (Grandfather-Father-Son) saklama politikasına göre eski yedekleri budar.

    Değişmez Kurallar:
    1. En son yedek ve en son restore_drill ile doğrulanmış yedek ASLA silinmez.
    2. Günlük (son 7 gün, günde 1), Haftalık (son 4 hafta, haftada 1), Aylık (son 12 ay, ayda 1) saklanır.
    3. Budanan dosyaların .db ve .json manifestleri kaldırılır.
    4. Harici kütüğe (zincir-uclari.jsonl) append-only PRUNE olayı eklenir (kütükten satır silinmez).
    """
    if backup_dir:
        b_dir = Path(backup_dir)
    else:
        b_dir = default_backup_dir()

    if not b_dir.exists():
        return PruneResult(
            dry_run=dry_run,
            total_backups=0,
            kept_count=0,
            pruned_count=0,
            message=f"Yedek dizini bulunamadı: {b_dir}",
        )

    # 1. Config'ten politikayı oku (varsayılanları ez)
    try:
        from masa.config import _load
        pol = _load("politika")
        ret_cfg = pol.get("yedek_saklama", {})
        retention_daily = ret_cfg.get("gunluk", retention_daily)
        retention_weekly = ret_cfg.get("haftalik", retention_weekly)
        retention_monthly = ret_cfg.get("aylik", retention_monthly)
    except Exception:
        pass

    # 2. Mevcut tüm backup-*.db dosyalarını topla ve zamana göre sırala
    db_files = sorted(b_dir.glob("backup-*.db"))
    if not db_files:
        return PruneResult(
            dry_run=dry_run,
            total_backups=0,
            kept_count=0,
            pruned_count=0,
            message="Budanacak yedek bulunamadı.",
        )

    class BackupItem:
        def __init__(self, path: Path):
            self.path = path
            self.name = path.name
            self.manifest_path = path.with_suffix(".json")
            self.manifest: Optional[Dict[str, Any]] = None
            self.is_drill_verified = False
            self.dt: datetime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

            if self.manifest_path.exists():
                try:
                    self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    if self.manifest.get("integrity_status", {}).get("drill_verified"):
                        self.is_drill_verified = True
                except Exception:
                    pass

            import re
            m = re.match(r"^backup-(\d{8})_(\d{6})", self.name)
            if m:
                try:
                    self.dt = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                except Exception:
                    pass

    items = [BackupItem(p) for p in db_files]
    items.sort(key=lambda x: x.dt)
    total_backups = len(items)

    # 3. Korumalar: En son yedek ve en son prova edilmiş yedek
    protected_latest = items[-1].name
    protected_drill = None
    for item in reversed(items):
        if item.is_drill_verified:
            protected_drill = item.name
            break

    # 4. GFS Seçimi
    kept_items = set()
    kept_items.add(items[-1].name)
    if protected_drill:
        kept_items.add(protected_drill)

    daily_slots: Dict[str, str] = {}
    weekly_slots: Dict[str, str] = {}
    monthly_slots: Dict[str, str] = {}

    for item in reversed(items):
        day_key = item.dt.strftime("%Y-%m-%d")
        week_key = f"{item.dt.isocalendar()[0]}-W{item.dt.isocalendar()[1]:02d}"
        month_key = item.dt.strftime("%Y-%m")

        qualifies = False
        if len(daily_slots) < retention_daily and day_key not in daily_slots:
            daily_slots[day_key] = item.name
            qualifies = True

        if len(weekly_slots) < retention_weekly and week_key not in weekly_slots:
            weekly_slots[week_key] = item.name
            qualifies = True

        if len(monthly_slots) < retention_monthly and month_key not in monthly_slots:
            monthly_slots[month_key] = item.name
            qualifies = True

        if qualifies:
            kept_items.add(item.name)

    kept_files = [it.name for it in items if it.name in kept_items]
    pruned_files = [it.name for it in items if it.name not in kept_items]

    # 5. Silme ve Kütük Güncelleme
    ledger_updated = False
    if not dry_run and confirmed:
        for p_name in pruned_files:
            p_db = b_dir / p_name
            p_json = b_dir / Path(p_name).with_suffix(".json")
            try:
                if p_db.exists():
                    p_db.unlink()
                if p_json.exists():
                    p_json.unlink()
            except OSError:
                pass

        if pruned_files:
            ledger_path = default_ledger_path(b_dir)
            mgr = db_manager or DatabaseManager()
            snap_tip = GENESIS_HASH
            snap_cnt = 0
            aud_tip = GENESIS_HASH
            aud_cnt = 0
            try:
                conn = mgr.get_connection()
                try:
                    s_row = conn.execute("SELECT curr_hash FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone()
                    snap_tip = s_row[0] if s_row else GENESIS_HASH
                    snap_cnt = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
                    a_row = conn.execute("SELECT curr_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
                    aud_tip = a_row[0] if a_row else GENESIS_HASH
                    aud_cnt = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
                finally:
                    conn.close()
            except Exception:
                if ledger_path.exists():
                    try:
                        lines = [l.strip() for l in ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
                        if lines:
                            last_e = json.loads(lines[-1])
                            snap_tip = last_e.get("snapshot_chain_tip", GENESIS_HASH)
                            snap_cnt = int(last_e.get("snapshot_count", 0))
                            aud_tip = last_e.get("audit_chain_tip", GENESIS_HASH)
                            aud_cnt = int(last_e.get("audit_count", 0))
                    except Exception:
                        pass

            append_chain_tip_log(
                snapshot_chain_tip=snap_tip,
                snapshot_count=snap_cnt,
                audit_chain_tip=aud_tip,
                audit_count=aud_cnt,
                backup_filename=None,
                backup_sha256=None,
                event="PRUNE",
                ledger_path=ledger_path,
                enforce_monotonicity=False,
                pruned_files=pruned_files,
            )
            ledger_updated = True

    return PruneResult(
        dry_run=dry_run,
        total_backups=total_backups,
        kept_count=len(kept_files),
        pruned_count=len(pruned_files),
        kept_files=kept_files,
        pruned_files=pruned_files,
        protected_latest=protected_latest,
        protected_drill=protected_drill,
        ledger_updated=ledger_updated,
        message=f"{len(pruned_files)} yedek elendi, {len(kept_files)} yedek saklandı.",
    )
