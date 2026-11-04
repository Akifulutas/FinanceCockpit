"""Comprehensive test suite for Investment Thesis Manager and contracts (IP-5)."""

from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
import pytest

from masa.cli import main
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.thesis.manager import ThesisManager
from masa.thesis.models import (
    ThesisCategory,
    ThesisHorizon,
    ThesisRecord,
    ThesisStatus,
)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Create an isolated test database initialized with Schema v3."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASA_BACKUP_DIR", str(backup_dir))

    db_path = tmp_path / "test_masa.db"
    db = DatabaseManager(db_path=db_path)
    db.initialize_schema()
    registry = IdentityRegistry(db=db)
    registry.seed_from_configs()
    return db


class TestThesisModels:
    def test_invalid_isin_rejected(self):
        with pytest.raises(ValueError, match="ISO 6166"):
            ThesisRecord(
                isin="INVALID_ISIN",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Geçersiz ISIN Tezi",
                one_line_summary="Bu bir test özetidir en az 10 karakter.",
                economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
            )

    def test_less_than_two_falsification_triggers_rejected(self):
        with pytest.raises(ValueError, match="en az 2 somut çürütme koşulu"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Yetersiz Tetikleyici",
                one_line_summary="Bu bir test özetidir en az 10 karakter.",
                economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
                falsification_triggers=["Yalnızca bir tetikleyici"],
            )

    def test_falsification_triggers_deduplication(self):
        record = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Deduplication Test",
            one_line_summary="Bu bir test özetidir en az 10 karakter.",
            economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
            falsification_triggers=["Tetikleyici 1", "Tetikleyici 2", "Tetikleyici 1"],
        )
        assert record.falsification_triggers == ["Tetikleyici 1", "Tetikleyici 2"]

    def test_version_one_cannot_have_supersedes_id(self):
        with pytest.raises(ValueError, match="İlk sürümde"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Hatalı V1",
                one_line_summary="Bu bir test özetidir en az 10 karakter.",
                economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
                supersedes_id="thv_someoldversion",
                version_number=1,
            )

    def test_version_two_requires_supersedes_and_rationale(self):
        with pytest.raises(ValueError, match="supersedes_id zorunludur"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Hatalı V2",
                one_line_summary="Bu bir test özetidir en az 10 karakter.",
                economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
                version_number=2,
            )

        with pytest.raises(ValueError, match="açıklayıcı gerekçe"):
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Hatalı V2 Gerekçesiz",
                one_line_summary="Bu bir test özetidir en az 10 karakter.",
                economic_rationale="Gerekçe metni de en az 10 karakter olmalıdır.",
                falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
                supersedes_id="thv_123456789012",
                version_number=2,
                revision_rationale="kısa",
            )


class TestThesisLifecycleAndImmutability:
    def test_unseeded_isin_rejected(self, test_db):
        mgr = ThesisManager(test_db)
        # Random valid Luhn ISIN not in instruments table
        rec = ThesisRecord(
            isin="DE000BAY0017",
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.MEDIUM_TERM,
            title="Kayıtsız Varlık",
            one_line_summary="Instruments tablosunda bulunmayan bir menkul kıymet.",
            economic_rationale="Bu varlık tohumlanmadı ve instruments tablosunda yoktur.",
            falsification_triggers=["Tetikleyici 1", "Tetikleyici 2"],
        )
        with pytest.raises(ValueError, match="instruments tablosunda bulunamadı"):
            mgr.create_thesis(rec)

    def test_create_thesis_lifecycle_and_verification(self, test_db):
        mgr = ThesisManager(test_db)
        rec = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Küresel Geniş Piyasa Çekirdek Maruziyeti",
            one_line_summary="SPDR MSCI ACWI IMI düşük maliyetli küresel hisse ortaklığı.",
            economic_rationale="Dünya sermaye piyasalarının uzun vadeli büyümesine pasif iştirak.",
            falsification_triggers=["TER > %0.25 olması", "Takip hatası > %0.50"],
            evidence_pillars=["9000+ hisse", "TER %0.17", "Fiziksel örnekleme"],
            target_allocation_pct=Decimal("0.45"),
            next_review_date="2026-11-30",
        )
        created = mgr.create_thesis(rec)
        assert created.version_number == 1
        assert created.supersedes_id is None
        assert created.record_hash is not None
        assert len(created.record_hash) == 64

        # Verify query from current head view
        head = mgr.get_thesis(created.thesis_id)
        assert head is not None
        assert head.version_id == created.version_id
        assert head.title == "Küresel Geniş Piyasa Çekirdek Maruziyeti"

        # Verify duplicate active thesis on same ISIN is prevented
        with pytest.raises(ValueError, match="zaten aktif bir tez mevcut"):
            mgr.create_thesis(rec)

    def test_revise_thesis_creates_linear_version_chain(self, test_db):
        mgr = ThesisManager(test_db)
        rec = ThesisRecord(
            isin="IE00BP3QZ825",
            category=ThesisCategory.FACTOR,
            horizon=ThesisHorizon.MEDIUM_TERM,
            title="Momentum Faktör Eğilimi",
            one_line_summary="World Momentum faktör primi ve trend takibi stratejisi.",
            economic_rationale="Fiyat momentumu anomalisinden sistematik getiri sağlama.",
            falsification_triggers=["Faktör yayılımı çöküşü", "İşlem maliyeti > getiri"],
        )
        v1 = mgr.create_thesis(rec)
        assert v1.version_number == 1

        # Revise with valid rationale
        v2 = mgr.revise_thesis(
            thesis_id=v1.thesis_id,
            rationale="Piyasa rejimi değişikliği nedeniyle hedef ağırlık azaltıldı.",
            updates={"target_allocation_pct": Decimal("0.15")},
        )
        assert v2.version_number == 2
        assert v2.supersedes_id == v1.version_id
        assert v2.target_allocation_pct == Decimal("0.15")

        # Head should now point to v2
        head = mgr.get_thesis(v1.thesis_id)
        assert head is not None
        assert head.version_id == v2.version_id
        assert head.version_number == 2

        # Full history returns both versions
        history = mgr.get_thesis_history(v1.thesis_id)
        assert len(history) == 2
        assert history[0].version_id == v1.version_id
        assert history[1].version_id == v2.version_id

    def test_dag_branching_prevention(self, test_db):
        mgr = ThesisManager(test_db)
        rec = ThesisRecord(
            isin="US0378331005",
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.MEDIUM_TERM,
            title="Apple Donanım ve Hizmetler",
            one_line_summary="Yüksek serbest nakit akımı ve ekosistem bağlılığı.",
            economic_rationale="Hizmet gelirleri marj genişlemesi sağlamaktadır.",
            falsification_triggers=["Çin pazar payı kaybı > %20", "Hizmet büyümesi < %5"],
        )
        v1 = mgr.create_thesis(rec)

        # First revision succeeds
        mgr.revise_thesis(v1.thesis_id, rationale="İlk geçerli revizyon gerekçesi burada.")

        # Attempting second direct child branching from v1 MUST fail with IntegrityError
        conn = test_db.get_connection()
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO thesis_versions (
                        version_id, thesis_id, supersedes_id, version_number,
                        isin, category, horizon, status, title, one_line_summary,
                        economic_rationale, evidence_pillars_json, counter_arguments,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        target_allocation_pct, next_review_date, revision_rationale,
                        author, created_at, record_hash
                    ) VALUES (
                        'thv_forkattempt', ?, ?, 2, 'US0378331005', 'STOCK', 'MEDIUM_TERM',
                        'ACTIVE', 'Çatallanma Denemesi', 'Geçersiz fork.', 'Açıklama',
                        '[]', NULL, '[\"t1\",\"t2\"]', 'ref', '[]', NULL, NULL,
                        'İkinci çatallanma gerekçesi', 'attacker', '2026-10-31T10:00:00Z',
                        'fakehashfork0000000000000000000000000000000000000000000000000000'
                    )
                    """,
                    (v1.thesis_id, v1.version_id),
                )
        finally:
            conn.close()

    def test_invalidation_lifecycle(self, test_db):
        mgr = ThesisManager(test_db)
        rec = ThesisRecord(
            isin="US5949181045",
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.LONG_TERM,
            title="Microsoft Bulut ve Yapay Zeka",
            one_line_summary="Azure ve kurumsal yazılım tekeli nakit üretimi.",
            economic_rationale="Kurumsal bulut göçü ve yapay zeka entegrasyonu.",
            falsification_triggers=["Azure büyümesi < %15", "Antitröst cezaları"],
        )
        v1 = mgr.create_thesis(rec)

        # Invalidate
        inv = mgr.invalidate_thesis(
            v1.thesis_id,
            rationale="Temel tezin çürütme koşulu gerçekleşti; tez sonlandırıldı.",
        )
        assert inv.status == ThesisStatus.INVALIDATED
        assert inv.version_number == 2

        # Head is now INVALIDATED
        head = mgr.get_thesis(v1.thesis_id)
        assert head.status == ThesisStatus.INVALIDATED

        # Trying to revise invalidated thesis fails
        with pytest.raises(ValueError, match="Geçersiz kılınmış bir tez revize edilemez"):
            mgr.revise_thesis(v1.thesis_id, rationale="Geçersiz tezi güncelleme denemesi.")

    def test_append_only_immutability_triggers(self, test_db):
        mgr = ThesisManager(test_db)
        rec = ThesisRecord(
            isin="DE0007164600",
            category=ThesisCategory.STOCK,
            horizon=ThesisHorizon.LONG_TERM,
            title="SAP Bulut Dönüşümü",
            one_line_summary="S/4HANA Cloud geçişi tekrarlayan gelirleri artırıyor.",
            economic_rationale="ERP geçişleri yüksek geçiş maliyetleri yaratır.",
            falsification_triggers=["Bulut büyümesi < %10", "Marj daralması"],
        )
        created = mgr.create_thesis(rec)

        conn = test_db.get_connection()
        try:
            # 1. UPDATE attempt must fail
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions degistirilemez"):
                conn.execute("UPDATE thesis_versions SET title = 'Değiştirilmiş Başlık' WHERE version_id = ?", (created.version_id,))

            # 2. DELETE attempt must fail
            with pytest.raises(sqlite3.IntegrityError, match="thesis_versions kaydi silinemez"):
                conn.execute("DELETE FROM thesis_versions WHERE version_id = ?", (created.version_id,))

            # 3. INSERT OR REPLACE attempt must fail
            with pytest.raises(sqlite3.IntegrityError, match="mevcut kaydin uzerine yazma"):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO thesis_versions (
                        version_id, thesis_id, isin, category, horizon, status,
                        title, one_line_summary, economic_rationale, evidence_pillars_json,
                        falsification_triggers_json, benchmark_reference, sources_json,
                        created_at, record_hash
                    ) VALUES (
                        ?, ?, 'DE0007164600', 'STOCK', 'LONG_TERM', 'ACTIVE',
                        'Yeniden Yazılmış', 'Özet', 'Gerekçe', '[]', '[\"t1\",\"t2\"]',
                        'ref', '[]', '2026-10-31T10:00:00Z', ?
                    )
                    """,
                    (created.version_id, created.thesis_id, created.record_hash),
                )
        finally:
            conn.close()

    def test_audit_theses_health_and_review_dates(self, test_db):
        mgr = ThesisManager(test_db)
        # Create one with future date
        mgr.create_thesis(
            ThesisRecord(
                isin="IE00B3YLTY66",
                category=ThesisCategory.CORE,
                horizon=ThesisHorizon.LONG_TERM,
                title="Sağlıklı Tez",
                one_line_summary="Gelecek inceleme tarihli sağlıklı tez.",
                economic_rationale="Ekonomik gerekçe metni açıklaması.",
                falsification_triggers=["T1", "T2"],
                next_review_date="2099-12-31",
            )
        )
        # Create one with overdue date
        mgr.create_thesis(
            ThesisRecord(
                isin="IE00BKM4GZ66",
                category=ThesisCategory.SATELLITE,
                horizon=ThesisHorizon.MEDIUM_TERM,
                title="Günü Geçmiş Tez",
                one_line_summary="İnceleme günü geçmiş tez örneği.",
                economic_rationale="Gerekçe açıklaması en az 10 karakter.",
                falsification_triggers=["T1", "T2"],
                next_review_date="2020-01-01",
            )
        )

        health = mgr.audit_theses_health()
        assert health["total_active_theses"] == 2
        assert health["due_for_review_count"] == 1
        assert health["up_to_date_count"] == 1
        assert health["is_all_healthy"] is False


class TestThesisCLI:
    def test_cli_tez_commands_e2e(self, tmp_path, monkeypatch, capsys):
        db_file = tmp_path / "test_cli.db"
        test_db = DatabaseManager(db_file)
        test_db.initialize_schema()
        IdentityRegistry(db=test_db).seed_from_configs()
        monkeypatch.setenv("MASA_DB_PATH", str(db_file))

        # 1. ekle
        with pytest.raises(SystemExit) as exc:
            main([
                "tez", "ekle",
                "--isin", "IE00B3YLTY66",
                "--baslik", "SPDR ACWI Çekirdek",
                "--kategori", "CORE",
                "--vade", "LONG_TERM",
                "--ozet", "Küresel geniş piyasaya düşük maliyetli ortaklık.",
                "--gerekce", "Dünya ekonomik büyümesine ve sermaye birikimine yatırım.",
                "--tetikleyiciler", "TER > %0.25", "Takip hatası > %0.50",
                "--hedef-agirlik", "0.40",
                "--sonraki-kontrol", "2026-12-31",
            ])
        assert exc.value.code == 0
        out1 = capsys.readouterr().out
        assert "Yatırım tezi başarıyla mühürlendi" in out1

        # 2. listele
        with pytest.raises(SystemExit) as exc:
            main(["tez", "listele"])
        assert exc.value.code == 0
        out2 = capsys.readouterr().out
        assert "SPDR ACWI Çekirdek" in out2

        # 3. kontrol
        with pytest.raises(SystemExit) as exc:
            main(["tez", "kontrol"])
        assert exc.value.code == 0
        out3 = capsys.readouterr().out
        assert "AYLIK TEZ SAĞLIK VE İNCELEME DENETİMİ" in out3
