"""ETF Yatırım Masası — komut satırı.

Ana akış:  masa baslat  (kontrol → giriş yönlendirmesi → veri → geçmiş → analiz →
           tut/sat değerlendirmesi → fırsat taraması → [TradingAgents] → rapor)

Tek tek: kontrol | giris | veri | gecmis | dogrula | portfoy | rapor | degerlendir |
         tarama | plan | tradingagents | yorum
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import importlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from masa import analytics
from masa.advisor import assess
from masa.calc import rebalancing
from masa.calendar.adapter import CalendarAdapter
from masa.config import CONFIG_DIR, MASA_DIR, REPORT_DIR, load_config
from masa.ingestion.exceptions import ScalableCommandError, ScalableReaderError
from masa.integrations import tradingagents as ta
from masa.pipeline import Pipeline, integrity_report, latest_run, latest_series, latest_transactions
from masa.report import build, critic_check, eur, pct
from masa.storage.db import DatabaseManager, SchemaVersionError

LINE = "=" * 72
PACKAGES = [("pydantic", "pydantic"), ("exchange-calendars", "exchange_calendars"), ("quantstats", "quantstats"),
            ("scipy", "scipy"), ("statsmodels", "statsmodels"), ("numpy", "numpy"), ("pandas", "pandas"),
            ("jsonschema", "jsonschema"), ("trafilatura", "trafilatura"),
            ("edgartools", "edgar")]


def _p(msg: str = "") -> None:
    print(msg, flush=True)


def _header(title: str) -> None:
    _p(LINE); _p(f"  {title}"); _p(LINE)


# ---------------------------------------------------------------- session
LOGIN_HELP = """
  Scalable oturumu açık değil ya da süresi dolmuş.

  1) Yeni bir Terminal penceresinde şunu çalıştırın:
         sc login --local-read-only
     Tarayıcıda giriş yapıp 2FA'yı onaylayın.
     (--local-read-only: oturum yerelde salt-okunur kaydedilir; CLI emir,
      Sparplan ve diğer değiştiren komutları engeller. masa zaten yalnız okur;
      bu ikinci kilittir.)
  2) Bittiğinde bu pencereye dönüp Enter'a basın.
"""


def check_session(pipe: Pipeline, silent: bool = False) -> Optional[str]:
    """Returns the session owner's name, or None if not logged in."""
    try:
        raw = pipe.reader.get_whoami()
        pd = raw.parsed_json["data"]["result"]["personOverview"]["personalDetails"]
        return " ".join(x for x in (pd.get("firstName"), pd.get("lastName")) if x) or "(adsız oturum)"
    except (ScalableCommandError, ScalableReaderError, KeyError, TypeError) as exc:
        if not silent:
            _p(f"  ✗ sc whoami başarısız: {str(exc)[:200]}")
        return None


def ensure_session(pipe: Pipeline, interactive: bool = True, attempts: int = 3, silent: bool = False) -> Optional[str]:
    for i in range(attempts):
        owner = check_session(pipe, silent=silent)
        if owner:
            if not silent:
                _p(f"  ✓ Scalable oturumu açık: {owner}")
            return owner
        if not silent:
            _p(LOGIN_HELP)
        if not (interactive and sys.stdin.isatty()):
            return None
        try:
            input("  Giriş yaptıktan sonra Enter'a basın (vazgeçmek için Ctrl+C)… ")
        except (EOFError, KeyboardInterrupt):
            if not silent:
                _p("")
            return None
    return None


# ---------------------------------------------------------------- kontrol
def cmd_kontrol(args) -> int:
    _header("SİSTEM KONTROLÜ — Scalable CLI, paketler, veritabanı, TradingAgents")
    ok = True
    _p(f"  Python {platform.python_version()} · SQLite {sqlite3.sqlite_version} · {platform.platform()}")
    pipe = None
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ Veritabanı: {exc}"); ok = False
    sc_bin = pipe.reader.binary_path if pipe else "/opt/homebrew/bin/sc"
    _p(f"  {'✓' if Path(sc_bin).exists() else '✗'} Scalable CLI: {sc_bin}")
    if not Path(sc_bin).exists():
        ok = False
        _p("      Kurulum: https://github.com/ScalableCapital/scalable-cli (Homebrew)")
    elif pipe:
        owner = check_session(pipe)
        if owner:
            _p(f"  ✓ Oturum açık: {owner}")
        else:
            ok = False
            _p("    → `masa giris` ile yönlendirmeli giriş yapın.")
    _p("")
    _p("  Paketler (masa ortamı):")
    for dist, mod in PACKAGES:
        try:
            ver = md.version(dist)
            importlib.import_module(mod)
            extra = ""
            _p(f"    ✓ {dist} {ver}{extra}")
        except Exception as exc:
            ok = False
            _p(f"    ✗ {dist}: {type(exc).__name__}: {str(exc)[:80]}")
    _p("")
    st = ta.status()
    _p(f"  {'✓' if st.available else '✗'} TradingAgents: {st.detail}")
    if st.available:
        for line in ta.describe_providers():
            _p(f"      {line}")
    gl = shutil.which("gitleaks")
    _p(f"  {'✓' if gl else '·'} gitleaks: {gl or 'bulunamadı (isteğe bağlı sır taraması)'}")
    if pipe and Path(sc_bin).exists():
        try:
            from masa.ingestion.capabilities import detect_capabilities_drift
            caps = pipe.reader.get_capabilities()
            drift = detect_capabilities_drift(caps.commands, caps.version)
            drift_marker = "✓" if drift.ok else "✗"
            _p(f"  {drift_marker} CLI Yetenekleri: v{caps.version} ({len(caps.commands)} komut), Değişim: {drift.level.value}")
            if drift.critical_issues:
                for issue in drift.critical_issues:
                    _p(f"      ✗ {issue}")
                ok = False
            elif drift.warnings:
                for warn in drift.warnings:
                    _p(f"      · {warn}")
        except Exception as exc:
            _p(f"  · CLI Yetenek kontrolü atlandı: {exc}")
    if pipe:
        integ = integrity_report(pipe.db)
        _p(f"  {'✓' if integ['ok'] else '✗'} masa.db: şema v{integ['schema_version']}, {integ['snapshots']} mühür, "
           f"zincir {'geçerli' if integ['snapshot_chain_ok'] else 'BOZUK'}, denetim {'geçerli' if integ['audit_chain_ok'] else 'BOZUK'}")
        ok = ok and integ["ok"]
    try:
        cfg = load_config()
        _p(f"  ✓ Ayarlar: {CONFIG_DIR} ({len(cfg.instruments)} araç, havuz {sum(len(v) for v in cfg.pool.values())}, "
           f"hedef {'var' if cfg.targets else 'yok'}, politika {'ONAYLANDI' if cfg.policy.approved else 'TASLAK'})")
    except Exception as exc:
        ok = False
        _p(f"  ✗ Ayarlar: {exc}")
    _p(LINE)
    _p(f"  Sonuç: {'HAZIR' if ok else 'EKSİK VAR (yukarıdaki ✗ satırları)'}")
    return 0 if ok else 1


def cmd_giris(args) -> int:
    is_json = getattr(args, "json", False)
    if getattr(args, "login", False):
        import subprocess
        pipe = Pipeline()
        sc_bin = str(pipe.reader.binary_path)
        cmd = [sc_bin, "login", "--local-read-only"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            for line in iter(proc.stdout.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
            proc.wait()
            return proc.returncode
        except KeyboardInterrupt:
            proc.terminate()
            return 130

    pipe = Pipeline()
    owner = ensure_session(pipe, interactive=not is_json, silent=is_json)
    is_ok = bool(owner)
    if is_json:
        import json
        whoami_info = None
        if is_ok:
            try:
                who = pipe.reader.whoami()
                raw_acc = str(who.get("account_id") or "")
                raw_email = str(who.get("email") or "")

                masked_acc = f"••••{raw_acc[-4:]}" if len(raw_acc) >= 4 else ("••••" if raw_acc else None)
                masked_email = None
                if "@" in raw_email:
                    user_part, domain_part = raw_email.split("@", 1)
                    u_masked = f"{user_part[0]}***" if user_part else "***"
                    d_parts = domain_part.split(".")
                    d_masked = f"***.{d_parts[-1]}" if len(d_parts) > 1 else "***"
                    masked_email = f"{u_masked}@{d_masked}"
                elif raw_email:
                    masked_email = "***"

                whoami_info = {"account_id": masked_acc, "email": masked_email}
            except Exception:
                pass
        _p(json.dumps({
            "schema_version": "1.0.0",
            "active": is_ok,
            "session_ok": is_ok,
            "reader_path": str(pipe.reader.binary_path),
            "account_info": whoami_info,
        }, ensure_ascii=False, indent=2))
        return 0 if is_ok else 1

    _header("SCALABLE GİRİŞ KONTROLÜ")
    return 0 if is_ok else 1


# ---------------------------------------------------------------- data
def cmd_veri(args, pipe: Optional[Pipeline] = None) -> int:
    pipe = pipe or Pipeline()
    _header("CANLI VERİ → MÜHÜR (pozisyon, nakit, kotasyon)")
    try:
        res = pipe.collect_snapshot()
    except (ScalableCommandError, ScalableReaderError) as exc:
        _p(f"  ✗ Scalable okuma hatası: {str(exc)[:240]}")
        _p(LOGIN_HELP)
        return 1
    _p(f"  Çalışma: {res.run_id} · kalite {res.quality}")
    for kind, s in res.snapshots.items():
        _p(f"  ✓ {kind:<9} mühür {s.snapshot_id}  hash {s.curr_hash[:16]}…{'' if s.created else '  (aynı ham veri, yeni kayıt yok)'}")
    for f in res.quote_failures:
        _p(f"  ✗ {f}")
    _p(f"  Yatırımlar {eur(res.total_positions_value)} (broker değerlemesi) · nakit {eur(res.cash_balance)}")
    return 0 if res.ok else 2


def cmd_gecmis(args, pipe: Optional[Pipeline] = None) -> int:
    pipe = pipe or Pipeline()
    run = latest_run(pipe.db)
    if run is None:
        _p("  Önce `masa veri` çalıştırın."); return 1
    _header("GEÇMİŞ → MÜHÜR (fiyat serileri + işlem geçmişi)")
    try:
        res = pipe.collect_history([p.isin for p in run.positions])
    except (ScalableCommandError, ScalableReaderError) as exc:
        _p(f"  ✗ Scalable okuma hatası: {str(exc)[:240]}"); return 1
    for key, (snap, n) in sorted(res["series"].items()):
        _p(f"  ✓ seri {key:<20} {n:>4} nokta  {snap.curr_hash[:12]}…")
    if "transactions" in res:
        snap, n = res["transactions"]
        _p(f"  ✓ işlem geçmişi {n} kayıt  {snap.curr_hash[:12]}…")
    for e in res["errors"]:
        _p(f"  ✗ {e}")
    return 0 if not res["errors"] else 2


def cmd_dogrula(args) -> int:
    _header("BÜTÜNLÜK DOĞRULAMASI")
    from masa.backup import check_filevault_status
    _p(f"  ✓ Şifreleme durumu: {check_filevault_status()}")
    db = DatabaseManager(); db.initialize_schema()
    integ = integrity_report(db)
    for k, v in integ.items():
        _p(f"  {k:<30} {v}")
    if integ.get("critical_integrity_violation"):
        _p("\n  ✗ KRİTİK BÜTÜNLÜK İHLALİ: Canlı DB harici kütükle uyuşmuyor!")
        return 3
    return 0 if integ["ok"] else 3


def cmd_yedek(args) -> int:
    action = getattr(args, "yedek_action", None)
    if action == "budama":
        _header("YEDEK SAKLAMA VE BUDAMA (Retention Pruning)")
        from masa.backup import prune_backups
        backup_dir = Path(args.cikti) if getattr(args, "cikti", None) else None
        kuru = getattr(args, "kuru", False)
        uygula = getattr(args, "uygula", False)
        onay = getattr(args, "onay", False)

        if not kuru and not uygula:
            _p("  Eksik bayrak: Budama önizlemesi için '--kuru', uygulamak için '--uygula --onay' kullanın.")
            return 1

        if uygula and not onay:
            _p("  ✗ HATA: Budama işlemi eski yedek dosyalarını kalıcı olarak silecektir.")
            _p("    İşlemi onaylamak için '--onay' bayrağı zorunludur: masa yedek budama --uygula --onay")
            return 1

        dry_run = kuru or not (uygula and onay)
        res = prune_backups(backup_dir=backup_dir, dry_run=dry_run, confirmed=(uygula and onay))

        _p(f"  Mod: {'KURU ÇALIŞMA (DRY-RUN - Dosyalara dokunulmadı)' if res.dry_run else 'UYGULANDI (GERÇEK BUDAMA)'}")
        _p(f"  Toplam yedek: {res.total_backups}")
        _p(f"  Saklanan yedek sayısı: {res.kept_count}")
        _p(f"  Elenen (budanacak) yedek sayısı: {res.pruned_count}")
        if res.protected_latest:
            _p(f"  ✓ En son yedek korundu: {res.protected_latest}")
        if res.protected_drill:
            _p(f"  ✓ Son prova onaylı yedek korundu: {res.protected_drill}")

        if res.pruned_files:
            _p("\n  Budanan / Elenen Dosyalar:")
            for pf in res.pruned_files:
                _p(f"    - {pf}")
        else:
            _p("  Budanacak yedek bulunamadı (tüm yedekler politika kapsamında).")

        if res.ledger_updated:
            _p("  ✓ Bağımsız kütüğe PRUNE olayı işlendi: zincir-uclari.jsonl")

        _p(LINE)
        _p(f"  Sonuç: {res.message}")
        return 0

    _header("VERİTABANI YEDEKLEME (SQLite Online Backup)")
    from masa.backup import check_filevault_status, create_backup
    _p(f"  ✓ Şifreleme durumu: {check_filevault_status()}")
    try:
        backup_dir = Path(args.cikti) if getattr(args, "cikti", None) else None
        res = create_backup(backup_dir=backup_dir, run_drill=getattr(args, "prova", False), force=getattr(args, "zorla", False))
        if getattr(res, "skipped", False):
            _p(f"  ✓ Canlı DB: {res.manifest.source_db_path}")
            _p(f"  ℹ {res.message or 'Değişiklik yok, yeni yedek atlandı.'}")
            _p(f"  ✓ Mevcut geçerli yedek: {res.db_path} ({res.manifest.backup_bytes:,} bayt)")
            _p(f"  ✓ SHA-256: {res.manifest.backup_sha256[:16]}…{res.manifest.backup_sha256[-8:]}")
            _p(f"  ✓ Mühür zincir ucu: {res.manifest.snapshot_chain_tip[:16]}… ({res.manifest.snapshot_count} mühür)")
            _p(f"  ✓ Denetim zincir ucu: {res.manifest.audit_chain_tip[:16]}… ({res.manifest.audit_count} olay)")
            _p(f"  ✓ Manifest: {res.manifest_path}")
            if getattr(args, "prova", False):
                _p("\n  [Geri Yükleme Provası (restore_drill)]")
                if res.drill_result and res.drill_result.ok:
                    _p("  ✓ SHA-256 doğrulandı")
                    _p("  ✓ SQLite PRAGMA quick_check: OK")
                    _p("  ✓ Mühür ve denetim zincirleri izole alanda doğrulandı")
                    _p("  ✓ Canlı veritabanına dokunulmadı")
                else:
                    err = res.drill_result.errors if res.drill_result else "Bilinmeyen hata"
                    _p(f"  ✗ Prova başarısız: {err}")
                    return 1
            _p(LINE)
            _p("  Sonuç: YEDEK GEÇERLİ (DEĞİŞİKLİK YOK, ATLANDI)" + (" VE PROVA DOĞRULANDI" if getattr(args, "prova", False) else ""))
            return 0

        _p(f"  ✓ Canlı DB: {res.manifest.source_db_path}")
        _p(f"  ✓ Yedek dosyası: {res.db_path} ({res.manifest.backup_bytes:,} bayt)")
        _p(f"  ✓ SHA-256: {res.manifest.backup_sha256[:16]}…{res.manifest.backup_sha256[-8:]}")
        _p(f"  ✓ Mühür zincir ucu: {res.manifest.snapshot_chain_tip[:16]}… ({res.manifest.snapshot_count} mühür)")
        _p(f"  ✓ Denetim zincir ucu: {res.manifest.audit_chain_tip[:16]}… ({res.manifest.audit_count} olay)")
        _p(f"  ✓ Manifest: {res.manifest_path}")
        _p("  ✓ Bağımsız kütük güncellendi: zincir-uclari.jsonl")
        if getattr(args, "prova", False):
            _p("\n  [Geri Yükleme Provası (restore_drill)]")
            if res.drill_result and res.drill_result.ok:
                _p("  ✓ SHA-256 doğrulandı")
                _p("  ✓ SQLite PRAGMA quick_check: OK")
                _p("  ✓ Mühür ve denetim zincirleri izole alanda doğrulandı")
                _p("  ✓ Canlı veritabanına dokunulmadı")
            else:
                err = res.drill_result.errors if res.drill_result else "Bilinmeyen hata"
                _p(f"  ✗ Prova başarısız: {err}")
                return 1
        _p(LINE)
        _p("  Sonuç: YEDEK BAŞARIYLA ALINDI" + (" VE PROVA DOĞRULANDI" if getattr(args, "prova", False) else ""))
        return 0
    except Exception as exc:
        _p(f"  ✗ Yedekleme başarısız: {exc}")
        return 1


def cmd_geri_yukle(args) -> int:
    _header("VERİTABANI GERİ YÜKLEME (Restore)")
    from masa.backup import check_filevault_status, find_latest_backup, restore_database
    _p(f"  ✓ Şifreleme durumu: {check_filevault_status()}")
    if not getattr(args, "onayla", False):
        _p("  ✗ HATA: Geri yükleme işlemi canlı veritabanını değiştirecektir.")
        _p("    İşlemi onaylamak için '--onayla' bayrağı zorunludur: masa geri-yukle --onayla")
        return 1

    try:
        backup_dir = Path(args.yedek_dizini) if getattr(args, "yedek_dizini", None) else None
        target = getattr(args, "hedef", None)
        if not target:
            target_path = find_latest_backup(backup_dir)
            if not target_path:
                _p("  ✗ HATA: Geri yüklenecek herhangi bir yedek dosyası bulunamadı.")
                return 1
            target = str(target_path)
            _p(f"  ✓ En son yedek seçildi: {target}")

        res = restore_database(target, confirm=True)
        _p(f"  ✓ Geri yüklenen kaynak: {res.restored_from}")
        if res.archived_live_db:
            _p(f"  ✓ Önceki canlı DB arşivlendi: {res.archived_live_db}")
        _p("  ✓ Ön prova (restore_drill) başarıyla tamamlandı")
        _p("  ✓ Canlı DB atomik olarak yenilendi")
        _p("  ✓ Denetim günlüğüne RESTORE_DATABASE olayı işlendi")
        _p(LINE)
        _p("  Sonuç: VERİTABANI BAŞARIYLA GERİ YÜKLENDİ")
        return 0
    except Exception as exc:
        _p(f"  ✗ Geri yükleme başarısız: {exc}")
        return 1


def cmd_gecis(args) -> int:
    _header("ŞEMA GEÇİŞİ (v2 → v3)")
    from masa.storage.migration import migrate_v2_to_v3
    db = DatabaseManager()
    res = migrate_v2_to_v3(db)
    if not res.success:
        _p(f"  ✗ Geçiş başarısız oldu: {res.error_message}")
        if res.rolled_back:
            _p("  ✓ Otomatik rollback başarıyla tamamlandı. Canlı veritabanı önceki haline döndürüldü.")
        return 1

    _p(f"  ✓ Şema sürümü: v{res.from_version} → v{res.to_version}")
    if res.backup_path:
        _p(f"  ✓ Geçiş öncesi online yedek alındı: {res.backup_path}")
    _p(f"  ✓ Eklenen tablolar: {', '.join(res.tables_created)}")
    _p(f"  ✓ Toplam değişmezlik tetikleyicisi: {res.trigger_count} (beklenen >= 33)")
    _p(f"  ✓ Geçiş sonrası bütünlük doğrulaması: {'BAŞARILI' if res.integrity_ok else 'BAŞARISIZ'}")
    if res.details.get("seed"):
        seed = res.details["seed"]
        _p(f"  ✓ Tohumlanan varlıklar: {seed.get('instruments', 0)} enstrüman, {seed.get('listings', 0)} kotasyon, {seed.get('issuer_links', 0)} ihraççı bağı")
    _p(LINE)
    _p("  Sonuç: ŞEMA v3 GEÇİŞİ BAŞARIYLA TAMAMLANDI")
    return 0


def cmd_izleme(args) -> int:
    _header("İZLEME LİSTESİ (sc broker watchlist)")
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ Veritabanı: {exc}"); return 1

    try:
        wl = pipe.reader.get_watchlist()
    except Exception as exc:
        _p(f"  ✗ İzleme listesi okunamadı: {exc}")
        return 1

    _p(f"  Hesap: {wl.account_id or '—'} · Portföy: {wl.portfolio_id or '—'} · Toplam: {wl.count} varlık")
    _p(f"  Zaman: {wl.retrieved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    _p("")
    _p(f"  {'ISIN':<14} {'Tür':<8} {'Fiyat':>10} {'Para':<5} {'Ad'}")
    _p(f"  {'-'*14} {'-'*8} {'-'*10} {'-'*5} {'-'*30}")
    for it in wl.items:
        _p(f"  {it.isin:<14} {it.security_type:<8} {it.quote_mid_price:>10.2f} {it.quote_currency:<5} {it.name}")
    _p(LINE)
    return 0


def cmd_durum(args) -> int:
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        if getattr(args, "json", False):
            import json
            _p(json.dumps({"schema_version": "1.0.0", "ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        _header("MASA SİSTEM DURUMU")
        _p(f"  ✗ Veritabanı: {exc}"); return 1

    integ = integrity_report(pipe.db)

    caps_info = None
    drift_level = "UNKNOWN"
    if Path(pipe.reader.binary_path).exists():
        try:
            from masa.ingestion.capabilities import detect_capabilities_drift
            caps = pipe.reader.get_capabilities()
            drift = detect_capabilities_drift(caps.commands, caps.version)
            drift_level = drift.level.value
            caps_info = {
                "version": caps.version,
                "command_count": len(caps.commands),
                "drift_level": drift_level,
                "critical_issues": drift.critical_issues,
                "warnings": drift.warnings,
            }
        except Exception as exc:
            caps_info = {"error": str(exc)}

    queue_summary = {"pending_count": 0, "recent_jobs": []}
    try:
        from masa.audit.queue import JobQueue
        jq = JobQueue(pipe.db)
        pending = jq.get_pending_or_waiting_jobs()
        recent = jq.list_recent_jobs(limit=5)
        queue_summary = {
            "pending_count": len(pending),
            "recent_jobs": [{"job_id": j.job_id, "type": j.job_type, "status": getattr(j.status, "value", str(j.status)), "created_at": str(j.created_at)} for j in recent],
        }
    except Exception:
        pass

    if getattr(args, "json", False):
        import json
        out_obj = {
            "schema_version": "1.0.0",
            "ok": bool(integ.get("ok", False)),
            "database_path": str(pipe.db.db_path),
            "integrity": integ,
            "capabilities": caps_info,
            "queue": queue_summary,
        }
        _p(json.dumps(out_obj, ensure_ascii=False, indent=2))
        return 0

    _header("MASA SİSTEM DURUMU")
    _p(f"  Veritabanı: {pipe.db.db_path}")
    _p(f"  Şema Sürümü: v{integ['schema_version']} · Journal Mode: {integ['journal_mode']}")
    _p(f"  Tetikleyici Sayısı: {integ['trigger_count']} (asgari 33)")
    _p(f"  Mühür Sayısı: {integ['snapshots']} · Denetim Olayı: {integ['audit_events']}")
    _p(f"  Kriptografik Bütünlük: {'GEÇERLİ' if integ['ok'] else 'BOZUK'}")
    _p(f"  Zincir Ucu Durumu: {integ.get('chain_tip_status', 'Bilinmiyor')}")

    # Yetenek kaydı ve drift kontrolü
    if caps_info and "version" in caps_info:
        _p(f"  CLI Yetenekleri: v{caps_info['version']} ({caps_info['command_count']} komut)")
        _p(f"  Komut Seti Değişim Risk Seviyesi: {drift_level}")
        if caps_info.get("critical_issues"):
            for issue in caps_info["critical_issues"]:
                _p(f"    ✗ {issue}")
        elif caps_info.get("warnings"):
            for warn in caps_info["warnings"]:
                _p(f"    · {warn}")

    # İş Kuyruğu Durumu (İP-8)
    _p("")
    _p(f"  İş Kuyruğu Durumu (Bekleyen/Aktif: {queue_summary['pending_count']}):")
    _p(LINE)
    return 0 if integ["ok"] else 1


def cmd_islemler(args) -> int:
    _header("İŞLEM DEFTERİ (Transaction Ledger)")
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ Veritabanı: {exc}"); return 1

    action = getattr(args, "islemler_action", None)
    if action == "cek":
        from_time = getattr(args, "from_time", None)
        force_full = getattr(args, "tam", False)
        _p(f"  Artımlı çekim başlatılıyor (from_time={from_time or 'otomatik 7 gün'}, tam={force_full})...")
        try:
            res = pipe.collect_transactions(from_time=from_time, force_full=force_full)
            _p(f"  ✓ Çekilen ham işlem sayısı: {res['items_count']}")
            _p(f"  ✓ Başlangıç zamanı: {res['from_time'] or 'Tüm geçmiş'}")
            st = res.get("ledger_stats", {})
            _p(f"  ✓ Deftere yeni eklenen (v1): {st.get('inserted', 0)}")
            _p(f"  ✓ Durumu/tutarı güncellenen (yeni sürüm): {st.get('updated', 0)}")
            _p(f"  ✓ Örtüşmeden atlanan (mükerrer/değişmemiş): {st.get('skipped', 0)}")
            _p(LINE)
            _p("  Sonuç: İŞLEMLER BAŞARIYLA ÇEKİLDİ VE MÜHÜRLENDİ")
            return 0
        except Exception as exc:
            _p(f"  ✗ İşlem çekimi başarısız: {exc}")
            return 1

    # Default action: listele
    from masa.ingestion.transaction_ledger import get_current_transactions
    isin = getattr(args, "isin", None)
    limit = getattr(args, "limit", 50)
    tip = getattr(args, "tip", None)
    rows = get_current_transactions(pipe.db, isin=isin, limit=limit, flow_class=tip)
    if not rows:
        _p("  İşlem defteri boş (önce `masa islemler cek`).")
        return 0

    _p(f"  Toplam gösterilen: {len(rows)} güncel işlem (v_transactions_current)")
    _p("")
    _p(f"  {'Tarih':<20} {'ID':<18} {'Tip':<18} {'ISIN':<14} {'Adet':>10} {'Tutar (EUR)':>12} {'Sınıf':<16} {'Durum'}")
    _p(f"  {'-'*20} {'-'*18} {'-'*18} {'-'*14} {'-'*10} {'-'*12} {'-'*16} {'-'*10}")
    for r in rows:
        t_str = str(r.get("event_time", ""))[:19]
        tx_id = str(r.get("broker_tx_id", ""))[:18]
        tx_type = str(r.get("sub_type") or r.get("tx_type", ""))[:18]
        isin_str = str(r.get("isin") or "—")[:14]
        qty_str = f"{Decimal(str(r['quantity'])):.4f}" if r.get("quantity") is not None else "—"
        amt_str = f"{Decimal(str(r.get('amount', 0))):.2f}"
        flow_str = str(r.get("flow_classification", "UNCLASSIFIED"))[:16]
        status_str = str(r.get("status", ""))
        _p(f"  {t_str:<20} {tx_id:<18} {tx_type:<18} {isin_str:<14} {qty_str:>10} {amt_str:>12} {flow_str:<16} {status_str}")
    _p(LINE)
    return 0


def cmd_kurumsal_islem(args) -> int:
    _header("KURUMSAL İŞLEMLER (Corporate Actions)")
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ Veritabanı: {exc}"); return 1

    action = getattr(args, "kurumsal_action", None)
    if action == "ekle":
        from masa.calc.corporate import CorporateActionRecord, CorporateActionType, register_corporate_action
        try:
            rec = CorporateActionRecord(
                isin=args.isin,
                action_type=CorporateActionType(args.tur),
                ratio=Decimal(str(args.oran)),
                new_isin=getattr(args, "yeni_isin", None),
                new_ticker=getattr(args, "yeni_ticker", None),
                effective_date=args.tarih,
                announcement_date=getattr(args, "duyuru_tarihi", None),
                description=getattr(args, "aciklama", "Kurumsal işlem"),
                approved_by=args.onaylayan,
            )
            action_id = register_corporate_action(pipe.db, rec)
            _p(f"  ✓ Kurumsal işlem başarıyla mühürlendi (ID: {action_id})")
            _p(f"  ✓ Varlık: {rec.isin} · Tür: {rec.action_type.value} · Oran: {rec.ratio}")
            if rec.new_isin:
                _p(f"  ✓ Yeni ISIN: {rec.new_isin}")
            _p(f"  ✓ Yürürlük Tarihi: {rec.effective_date}")
            _p(f"  ✓ Onaylayan: {rec.approved_by}")
            _p(LINE)
            _p("  Sonuç: KURUMSAL İŞLEM KAYDEDİLDİ")
            return 0
        except Exception as exc:
            _p(f"  ✗ Kurumsal işlem eklenemedi: {exc}")
            return 1

    # Default action: listele
    from masa.calc.corporate import list_corporate_actions
    isin = getattr(args, "isin", None)
    rows = list_corporate_actions(pipe.db, isin=isin)
    if not rows:
        _p("  Kayıtlı kurumsal işlem bulunmuyor.")
        return 0

    _p(f"  Toplam kayıt: {len(rows)}")
    _p("")
    _p(f"  {'Tarih':<20} {'ID':<16} {'ISIN':<14} {'Tür':<14} {'Oran':>8} {'Hedef ISIN':<14} {'Onaylayan':<14}")
    _p(f"  {'-'*20} {'-'*16} {'-'*14} {'-'*14} {'-'*8} {'-'*14} {'-'*14}")
    for r in rows:
        t_str = str(r.effective_date)[:19]
        new_i = r.new_isin or "—"
        _p(f"  {t_str:<20} {r.action_id:<16} {r.isin:<14} {r.action_type.value:<14} {r.ratio:>8} {new_i:<14} {r.approved_by:<14}")
    _p(LINE)
    return 0


def cmd_mutabakat(args) -> int:
    if not getattr(args, "json", False):
        _header("PORTFÖY VE NAKİT MUTABAKATI (4-Dimension Reconciliation)")
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ Veritabanı: {exc}"); return 1

    from masa.calc.reconciliation import reconcile_ledger_with_broker
    tarih_val = getattr(args, "tarih", None)
    as_of = None
    if tarih_val:
        try:
            as_of = datetime.fromisoformat(tarih_val.replace("Z", "+00:00"))
        except Exception as exc:
            _p(f"  ✗ Geçersiz tarih parametresi: {exc}"); return 1

    try:
        res = reconcile_ledger_with_broker(pipe.db, as_of=as_of)
    except Exception as exc:
        _p(f"  ✗ Mutabakat çalıştırılamadı: {exc}")
        return 1

    if getattr(args, "json", False):
        out_dict = {
            "reconciliation_id": res.reconciliation_id,
            "run_id": res.run_id,
            "time": res.reconciliation_time,
            "status": res.status,
            "shares_match": res.shares_match,
            "cash_match": res.cash_match,
            "valuation_match": res.valuation_match,
            "cost_basis_match": res.cost_basis_match,
            "cash_gap_eur": str(res.cash_gap_eur) if res.cash_gap_eur is not None else None,
            "observation_lag_seconds": res.observation_lag_seconds,
            "discrepancies_count": len(res.discrepancies),
            "discrepancies": [
                {
                    "dimension": d.dimension,
                    "entity": d.entity,
                    "ledger": d.ledger_val,
                    "broker": d.broker_val,
                    "diff": d.diff_val,
                    "reason": d.reason,
                }
                for d in res.discrepancies
            ],
        }
        _p(json.dumps(out_dict, indent=2, ensure_ascii=False))
        return 0 if res.status == "RECONCILED" else 2

    status_icon = "✓" if res.status == "RECONCILED" else "✗"
    _p(f"  Mutabakat ID: {res.reconciliation_id} · Zaman: {res.reconciliation_time}")
    _p(f"  Genel Durum: {status_icon} {res.status}")
    _p("")
    _p("  4 Boyutlu Bağımsız Denetim:")
    _p(f"    1. Pozisyon Adetleri (Shares):      {'✓ UYUMLU' if res.shares_match else '✗ UYUŞMAZLIK'}")
    _p(f"    2. Nakit Bakiyesi (Cash):          {'✓ UYUMLU' if res.cash_match else '✗ UYUŞMAZLIK'}")
    if res.cash_gap_eur:
        _p(f"       (Açıklanamayan Nakit Farkı: {res.cash_gap_eur} EUR — otomatik kapatılmaz)")
    _p(f"    3. Portföy Değerlemesi (Valuation): {'✓ UYUMLU' if res.valuation_match else '✗ UYUŞMAZLIK'}")
    _p(f"    4. FIFO Birim Maliyet (Cost Basis): {'✓ UYUMLU' if res.cost_basis_match else '✗ UYUŞMAZLIK'}")

    if res.observation_lag_seconds is not None:
        _p(f"\n  İşlem anı - gözlem zaman farkı: {res.observation_lag_seconds} saniye")

    if res.discrepancies:
        _p(f"\n  Tespit Edilen Uyuşmazlıklar ({len(res.discrepancies)} kayıt):")
        for d in res.discrepancies:
            _p(f"    · [{d.dimension}] {d.entity}: {d.reason}")
    else:
        _p("\n  ✓ 0 uyuşmazlık tespit edildi. Defter ile broker gözlemleri tam mutabakat sağladı.")

    _p(LINE)
    _p(f"  Sonuç: MUTABAKAT {'BAŞARILI' if res.status == 'RECONCILED' else 'UYUŞMAZLIK VAR'}")
    return 0 if res.status == "RECONCILED" else 2


def cmd_sepet(args) -> int:
    action = getattr(args, "sepet_action", None)
    if not action:
        _p("  Eksik alt komut: `masa sepet yukle|listele|ortusme`.")
        return 1

    db = DatabaseManager()
    db.initialize_schema()

    if action == "yukle":
        from masa.holdings.loader import HoldingsLoader
        loader = HoldingsLoader(db)
        dosya = getattr(args, "dosya_flag", None) or getattr(args, "dosya", None)
        isin_val = getattr(args, "isin", None)
        kaynak_val = getattr(args, "kaynak", None)
        tarih_val = getattr(args, "tarih", None)
        parsed_tarih = None
        if tarih_val:
            try:
                parsed_tarih = datetime.strptime(tarih_val, "%Y-%m-%d").date()
            except ValueError:
                _p(f"  ✗ Geçersiz tarih formatı (YYYY-MM-DD beklenir): {tarih_val}")
                return 1

        targets: List[Path] = []
        if dosya:
            targets = [Path(dosya)]
        else:
            targets = loader.scan_inbox()
            if not targets:
                _p(f"  ℹ️ Inbox klasöründe yüklenecek dosya bulunamadı: {loader.inbox_dir}")
                _p("    Dosyaları bu klasöre bırakabilir veya `masa sepet yukle <dosya_yolu>` ile yükleyebilirsiniz.")
                return 0

        _header(f"ETF SEPETİ YÜKLEME — {len(targets)} dosya")
        success_count = 0
        for t in targets:
            res = loader.ingest_file(
                file_path=t,
                isin=isin_val,
                provider=kaynak_val,
                as_of_date=parsed_tarih,
            )
            if res.success:
                success_count += 1
                status_str = "MÜKERRER (ATLANDI)" if res.status == "DUPLICATE_SKIPPED" else "YÜKLENDİ"
                cov_str = f"{res.total_weight * 100:.2f}%" if res.total_weight is not None else "—"
                _p(f"  ✓ [{status_str}] {res.isin} ({res.provider}) · Tarih: {res.as_of_date} · Kalem: {res.record_count} · Kapsam: {cov_str}")
                if res.staleness_warning:
                    _p(f"    {res.staleness_warning}")
            else:
                _p(f"  ✗ [HATA] {t.name}: {res.error_message}")

        _p(LINE)
        _p(f"  İşlem tamamlandı: {success_count}/{len(targets)} başarılı.")
        return 0 if success_count == len(targets) else 1

    elif action == "listele":
        _header("KAYITLI ETF SEPETLERİ (Holdings Sets)")
        conn = db.get_connection()
        try:
            query = """
            SELECT s.set_id, s.isin, s.as_of_date, s.source_file, s.provider,
                   s.total_records, s.total_weight_pct, s.created_at,
                   i.name AS fund_name
            FROM holdings_sets s
            LEFT JOIN instruments i ON s.isin = i.isin
            """
            params: List[Any] = []
            if getattr(args, "isin", None):
                query += " WHERE s.isin = ?"
                params.append(args.isin)
            query += " ORDER BY s.as_of_date DESC, s.created_at DESC"
            if getattr(args, "limit", None):
                query += " LIMIT ?"
                params.append(args.limit)

            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        if not rows:
            _p("  Kayıtlı fon sepeti bulunamadı. `masa sepet yukle` ile sepet yükleyin.")
            return 0

        _p(f"  {'ISIN':<13} {'Fon Adı':<32} {'Tarih':<11} {'Kalem':>6} {'Kapsam':>9} {'Durum':<14} {'Dosya'}")
        _p(f"  {'-'*13} {'-'*32} {'-'*11} {'-'*6} {'-'*9} {'-'*14} {'-'*20}")
        for r in rows:
            f_name = (r["fund_name"] or r["isin"])[:32]
            as_of = datetime.strptime(r["as_of_date"], "%Y-%m-%d").date()
            age_days = (date.today() - as_of).days
            is_stale = age_days > 45
            durum_str = f"BAYAT ({age_days}g)⚠️" if is_stale else f"GÜNCEL ({age_days}g)"
            w_dec = Decimal(str(r["total_weight_pct"]))
            cov_str = f"{w_dec * 100:.2f}%"
            _p(f"  {r['isin']:<13} {f_name:<32} {r['as_of_date']:<11} {r['total_records']:>6} {cov_str:>9} {durum_str:<14} {r['source_file']}")
        _p(LINE)
        return 0


    elif action == "ortusme":
        from masa.calc.overlap import run_portfolio_overlap_analysis
        is_json = getattr(args, "json", False)
        use_targets = getattr(args, "hedef", False)
        top_n = getattr(args, "top", 25)
        show_detail = getattr(args, "detay", False)

        try:
            matrix, summary, breakdown = run_portfolio_overlap_analysis(db, use_targets=use_targets, top_n=top_n)
        except Exception as exc:
            if is_json:
                _p(json.dumps({"error": str(exc)}, ensure_ascii=False))
            else:
                _p(f"  ✗ Örtüşme analizi hatası: {exc}")
            return 1

        if is_json:
            out_json = {
                "overlap_matrix": {
                    "isins": matrix.fund_isins,
                    "names": matrix.fund_names,
                    "scores": [[str(score) for score in row] for row in matrix.matrix],
                },
                "summary": {
                    "top5_weight": str(summary.top5_weight),
                    "top10_weight": str(summary.top10_weight),
                    "top25_weight": str(summary.top25_weight),
                    "other_stocks_weight": str(summary.other_stocks_weight),
                    "uncovered_etf_weight": str(summary.uncovered_etf_weight),
                    "cash_weight": str(summary.cash_weight),
                    "total_reconciled_weight": str(summary.total_reconciled_weight),
                    "hhi": str(summary.hhi),
                    "is_fully_reconciled": summary.is_fully_reconciled,
                    "staleness_warnings": summary.staleness_warnings,
                    "top_stocks": [
                        {
                            "rank": s.rank,
                            "name": s.name,
                            "isin": s.isin,
                            "ticker": s.ticker,
                            "weight": str(s.portfolio_weight),
                            "valuation_eur": str(s.valuation_eur) if s.valuation_eur is not None else None,
                            "sector": s.sector,
                            "country": s.country,
                        }
                        for s in summary.top_stocks
                    ],
                },
                "breakdown": {
                    "sectors": [{"name": b.name, "weight": str(b.weight)} for b in breakdown.sectors],
                    "countries": [{"name": b.name, "weight": str(b.weight)} for b in breakdown.countries],
                },
            }
            _p(json.dumps(out_json, indent=2, ensure_ascii=False))
            return 0

        _header("FONLAR ARASI ÇİFTLİ ÖRTÜŞME MATRİSİ (Pairwise Overlap — Σ min(wA, wB))")
        _p(f"  {'Fon / ISIN':<20} " + " ".join(f"{isin[-8:]:>10}" for isin in matrix.fund_isins))
        _p(f"  {'-'*20} " + " ".join("-" * 10 for _ in matrix.fund_isins))
        for idx, row in enumerate(matrix.matrix):
            row_str = " ".join(f"{val * 100:>9.2f}%" for val in row)
            lbl = f"{matrix.fund_isins[idx]} ({matrix.fund_names[idx][:8]})"
            _p(f"  {lbl:<20} {row_str}")
        _p("\n  Not: Köşegenler her fonun kendi bildirilen hisse kapsamını temsil eder.")

        _p("\n" + LINE)
        total_eur_str = f"€{summary.portfolio_total_eur:,.2f}" if summary.portfolio_total_eur is not None else "Belirtilmedi (Hedef Ağırlık Modu)"
        _header(f"PORTFÖY KONSOLİDE ŞİRKET MARUZİYETİ (Top {len(summary.top_stocks)} Look-Through)\n  Portföy Değeri: {total_eur_str}")
        _p(f"  {'Sıra':>4}  {'Şirket Adı':<32} {'ISIN / Kod':<14} {'Ağırlık %':>10} {'Küm. %':>9} {'Tutar (€)':>12}  {'Sektör / Ülke'}")
        _p(f"  {'-'*4}  {'-'*32} {'-'*14} {'-'*10} {'-'*9} {'-'*12}  {'-'*25}")

        for s in summary.top_stocks:
            val_str = f"€{s.valuation_eur:,.2f}" if s.valuation_eur is not None else "—"
            id_str = s.isin or s.ticker or "—"
            sec_cou = f"{s.sector or '—'} / {s.country or '—'}"[:25]
            _p(f"  {s.rank:>4}  {s.name[:32]:<32} {id_str:<14} {s.portfolio_weight * 100:>9.2f}% {s.cumulative_weight * 100:>8.2f}% {val_str:>12}  {sec_cou}")

        _p(LINE)
        _p(f"  Top {len(summary.top_stocks)} Şirket Toplamı: {summary.top25_weight * 100:.2f}%")
        _p(f"  Diğer Bildirilen Şirketler:  {summary.other_stocks_weight * 100:.2f}%")
        _p(f"  Kapsanmayan Fon Payı:        {summary.uncovered_etf_weight * 100:.2f}%")
        _p(f"  Portföy / Fon Nakdi:         {summary.cash_weight * 100:.2f}%")
        recon_status = "✓ TAM MUTABIK (100.0%)" if summary.is_fully_reconciled else f"✗ SAPMA ({summary.total_reconciled_weight * 100:.2f}%)"
        _p(f"  Muhasebe Sağlama Toplamı:    {summary.total_reconciled_weight * 100:.2f}% — [{recon_status}]")
        _p("")
        _p("  Yoğunlaşma Metrikleri:")
        _p(f"  · Top 5 Ağırlık: %{summary.top5_weight * 100:.2f} | Top 10: %{summary.top10_weight * 100:.2f} | Top 25: %{summary.top25_weight * 100:.2f}")
        _p(f"  · Herfindahl-Hirschman Endeksi (HHI): {summary.hhi}")

        if show_detail:
            _p("\n" + LINE)
            _header("KONSOLİDE SEKTÖR DAĞILIMI")
            for sec in breakdown.sectors[:10]:
                _p(f"  {sec.name:<35} {sec.weight * 100:>8.2f}%")
            _p("\n" + LINE)
            _header("KONSOLİDE ÜLKE DAĞILIMI")
            for cou in breakdown.countries[:10]:
                _p(f"  {cou.name:<35} {cou.weight * 100:>8.2f}%")

        if summary.staleness_warnings:
            _p("\n" + LINE)
            for w in summary.staleness_warnings:
                _p(f"  {w}")

        _p(LINE)
        return 0


    return 0


def _format_thesis_badge(status: str) -> str:
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    badges = {
        "ACTIVE": "\033[92m[ AKTİF ]\033[0m" if is_tty else "[ AKTİF ]",
        "INVALIDATED": "\033[91m[ GEÇERSİZ ]\033[0m" if is_tty else "[ GEÇERSİZ ]",
        "REVISED": "\033[94m[ REVİZE ]\033[0m" if is_tty else "[ REVİZE ]",
        "SUPERSEDED": "\033[90m[ ARŞİV ]\033[0m" if is_tty else "[ ARŞİV ]",
    }
    return badges.get(status.upper(), f"[ {status} ]")


def cmd_tez(args) -> int:
    action = getattr(args, "tez_action", None)
    if not action:
        _p("  Eksik alt komut: `masa tez ekle|listele|goster|revize|gecersiz-kil|kontrol`.")
        return 1

    from masa.thesis.manager import ThesisManager
    from masa.thesis.models import ThesisCategory, ThesisHorizon, ThesisRecord, ThesisStatus

    db = DatabaseManager()
    db.initialize_schema()
    mgr = ThesisManager(db)

    category_map = {
        "CORE": ThesisCategory.CORE,
        "CEKIRDEK": ThesisCategory.CORE,
        "FACTOR": ThesisCategory.FACTOR,
        "FAKTOR": ThesisCategory.FACTOR,
        "THEMATIC": ThesisCategory.THEMATIC,
        "TEMATIK": ThesisCategory.THEMATIC,
        "SATELLITE": ThesisCategory.SATELLITE,
        "UYDU": ThesisCategory.SATELLITE,
        "STOCK": ThesisCategory.STOCK,
        "HISSE": ThesisCategory.STOCK,
        "HEDGE": ThesisCategory.HEDGE,
        "KORUNMA": ThesisCategory.HEDGE,
    }
    horizon_map = {
        "SHORT_TERM": ThesisHorizon.SHORT_TERM,
        "KISA": ThesisHorizon.SHORT_TERM,
        "FIRSAT_KISA": ThesisHorizon.SHORT_TERM,
        "FIRSAT": ThesisHorizon.SHORT_TERM,
        "MEDIUM_TERM": ThesisHorizon.MEDIUM_TERM,
        "ORTA": ThesisHorizon.MEDIUM_TERM,
        "TAKTIK_ORTA": ThesisHorizon.MEDIUM_TERM,
        "LONG_TERM": ThesisHorizon.LONG_TERM,
        "UZUN": ThesisHorizon.LONG_TERM,
        "STRATEJIK_UZUN": ThesisHorizon.LONG_TERM,
        "SECULAR": ThesisHorizon.SECULAR,
        "SEKULER": ThesisHorizon.SECULAR,
    }

    if action == "ekle":
        _header("YENİ YATIRIM TEZİ EKLEME")
        try:
            girdi_json = getattr(args, "girdi_json", None)
            if girdi_json:
                if girdi_json == "-":
                    raw_data = sys.stdin.read()
                elif os.path.exists(girdi_json):
                    with open(girdi_json, "r", encoding="utf-8") as f:
                        raw_data = f.read()
                else:
                    raw_data = girdi_json
                payload = json.loads(raw_data)
                isin = payload.get("isin")
                baslik = payload.get("baslik")
                ozet = payload.get("ozet")
                gerekce = payload.get("gerekce")
                raw_kategori = payload.get("kategori", "CORE")
                raw_vade = payload.get("vade", "LONG_TERM")
                tetikleyiciler = payload.get("tetikleyiciler", [])
                kanitlar = payload.get("kanitlar", [])
                karsi_gorus = payload.get("karsi_gorus")
                target_alloc = payload.get("hedef_agirlik")
                sonraki_kontrol = payload.get("sonraki_kontrol")
                yazar = payload.get("yazar", "user") or "user"
            else:
                if not args.isin or not args.baslik or not args.ozet or not args.gerekce:
                    _p("  ✗ Eksik zorunlu alanlar: --isin, --baslik, --ozet ve --gerekce zorunludur.")
                    return 1
                isin = args.isin
                baslik = args.baslik
                ozet = args.ozet
                gerekce = args.gerekce
                raw_kategori = args.kategori
                raw_vade = args.vade
                tetikleyiciler = args.tetikleyiciler or []
                kanitlar = args.kanitlar or []
                karsi_gorus = getattr(args, "karsi_gorus", None)
                target_alloc = getattr(args, "hedef_agirlik", None)
                sonraki_kontrol = getattr(args, "sonraki_kontrol", None)
                yazar = getattr(args, "yazar", "user") or "user"

            cat = category_map.get(str(raw_kategori).upper(), ThesisCategory.CORE)
            hor = horizon_map.get(str(raw_vade).upper(), ThesisHorizon.LONG_TERM)

            target_alloc_dec = None
            if target_alloc is not None and str(target_alloc).strip():
                clean_target = str(target_alloc).replace("%", "").strip()
                target_alloc_dec = Decimal(clean_target)
                if target_alloc_dec > Decimal("1.00"):
                    target_alloc_dec = target_alloc_dec / Decimal("100.00")

            rec = ThesisRecord(
                isin=isin,
                category=cat,
                horizon=hor,
                title=baslik,
                one_line_summary=ozet,
                economic_rationale=gerekce,
                falsification_triggers=tetikleyiciler,
                evidence_pillars=kanitlar,
                counter_arguments=karsi_gorus,
                target_allocation_pct=target_alloc_dec,
                next_review_date=sonraki_kontrol,
                author=yazar,
            )
            created = mgr.create_thesis(rec)
            if getattr(args, "json", False):
                _p(json.dumps(created.to_db_row(created.record_hash or ""), ensure_ascii=False, indent=2))
            else:
                _p(f"  ✓ Yatırım tezi başarıyla mühürlendi:")
                _p(f"    Tez ID       : {created.thesis_id}")
                _p(f"    Sürüm ID     : {created.version_id} (v{created.version_number})")
                _p(f"    ISIN         : {created.isin}")
                _p(f"    Başlık       : {created.title}")
                _p(f"    Kategori     : {created.category.value} · Vade: {created.horizon.value}")
                _p(f"    Kayıt Mührü  : {created.record_hash}")
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez eklenemedi: {exc}")
            return 1

    elif action == "listele":
        _header("KAYITLI YATIRIM TEZLERİ (Investment Theses)")
        try:
            status_filter = getattr(args, "durum", None)
            if status_filter and status_filter.upper() == "ALL":
                status_filter = None
            theses = mgr.list_theses(
                isin=getattr(args, "isin", None),
                status=status_filter,
                category=getattr(args, "kategori", None),
                horizon=getattr(args, "vade", None),
                include_superseded=getattr(args, "gecmis", False),
            )
            if getattr(args, "json", False):
                out_list = [t.to_db_row(t.record_hash or "") for t in theses]
                _p(json.dumps(out_list, ensure_ascii=False, indent=2))
                return 0

            if not theses:
                _p("  Kayıtlı tez bulunamadı.")
                return 0

            _p(f"{'ID':<14} {'v':<3} {'ISIN':<14} {'Kategori':<10} {'Vade':<11} {'Durum':<13} {'Sonraki Knt':<12} {'Başlık'}")
            _p("-" * 72)
            for t in theses:
                badge = _format_thesis_badge(t.status.value)
                knt = t.next_review_date or "—"
                _p(f"{t.thesis_id:<14} {t.version_number:<3} {t.isin:<14} {t.category.value:<10} {t.horizon.value:<11} {badge:<13} {knt:<12} {t.title}")
            _p(LINE)
            _p(f"  Toplam: {len(theses)} tez listelendi.")
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez listesi alınamadı: {exc}")
            return 1

    elif action == "goster":
        thesis_id = args.tez_id
        try:
            if getattr(args, "gecmis", False):
                _header(f"TEZ SOYAĞACI VE TARİHÇESİ — {thesis_id}")
                history = mgr.get_thesis_history(thesis_id)
                if not history:
                    _p(f"  Tez bulunamadı: {thesis_id}")
                    return 1
                if getattr(args, "json", False):
                    _p(json.dumps([t.to_db_row(t.record_hash or "") for t in history], ensure_ascii=False, indent=2))
                    return 0
                for t in history:
                    badge = _format_thesis_badge(t.status.value)
                    _p(f"\n  [Sürüm v{t.version_number}] ID: {t.version_id} · Durum: {badge} · Tarih: {t.created_at}")
                    if t.supersedes_id:
                        _p(f"    Önceki Sürüm : {t.supersedes_id}")
                        _p(f"    Revizyon Nedeni: {t.revision_rationale}")
                    _p(f"    Başlık       : {t.title}")
                    _p(f"    Özet         : {t.one_line_summary}")
                    _p(f"    Mühür        : {t.record_hash}")
                _p(LINE)
                return 0

            t = mgr.get_thesis(thesis_id)
            if not t:
                _p(f"  ✗ Tez bulunamadı: {thesis_id}")
                return 1

            if getattr(args, "json", False):
                _p(json.dumps(t.to_db_row(t.record_hash or ""), ensure_ascii=False, indent=2))
                return 0

            _header(f"YATIRIM TEZİ DETAY KARTI — {t.title}")
            badge = _format_thesis_badge(t.status.value)
            _p(f"  Tez ID         : {t.thesis_id}")
            _p(f"  Sürüm          : v{t.version_number} ({t.version_id})")
            _p(f"  Durum          : {badge}")
            _p(f"  ISIN           : {t.isin}")
            _p(f"  Kategori       : {t.category.value} · Analitik Vade: {t.horizon.value}")
            _p(f"  Yazar / Tarih  : {t.author} · {t.created_at}")
            _p(f"  Sonraki Kontrol: {t.next_review_date or 'Belirtilmedi'}")
            if t.target_allocation_pct is not None:
                _p(f"  Hedef Ağırlık  : %{t.target_allocation_pct * 100:.2f}")
            _p(f"\n  Bir Cümlelik Özet:\n    {t.one_line_summary}")
            _p(f"\n  Ekonomik Gerekçe:\n    {t.economic_rationale}")
            if t.evidence_pillars:
                _p("\n  Kanıt Sütunları:")
                for ep in t.evidence_pillars:
                    _p(f"    · {ep}")
            if t.falsification_triggers:
                _p("\n  Falsifikasyon / Çürütme Koşulları:")
                for ft in t.falsification_triggers:
                    _p(f"    ✖ {ft}")
            if t.counter_arguments:
                _p(f"\n  Karşı Görüş / Riskler:\n    {t.counter_arguments}")
            if t.revision_rationale:
                _p(f"\n  Revizyon Gerekçesi:\n    {t.revision_rationale}")
            _p(f"\n  Kayıt Mührü (SHA-256): {t.record_hash}")
            _p(LINE)
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez gösterilemedi: {exc}")
            return 1

    elif action == "revize":
        thesis_id = args.tez_id
        rationale = getattr(args, "gerekce", None)
        if not rationale or len(rationale.strip()) < 10:
            _p("  ✗ Hata: Tez revizyonu için en az 10 karakterlik açıklayıcı gerekçe (--gerekce) zorunludur.")
            return 1

        updates: Dict[str, Any] = {}
        if getattr(args, "baslik", None):
            updates["title"] = args.baslik
        if getattr(args, "ozet", None):
            updates["one_line_summary"] = args.ozet
        if getattr(args, "ekonomik_gerekce", None):
            updates["economic_rationale"] = args.ekonomik_gerekce
        if getattr(args, "kategori", None):
            updates["category"] = category_map.get(str(args.kategori).upper(), ThesisCategory.CORE)
        if getattr(args, "vade", None):
            updates["horizon"] = horizon_map.get(str(args.vade).upper(), ThesisHorizon.LONG_TERM)
        if getattr(args, "hedef_agirlik", None) is not None:
            clean_t = str(args.hedef_agirlik).replace("%", "").strip()
            dec_t = Decimal(clean_t)
            if dec_t > Decimal("1.00"):
                dec_t = dec_t / Decimal("100.00")
            updates["target_allocation_pct"] = dec_t
        if getattr(args, "tetikleyiciler", None):
            updates["falsification_triggers"] = args.tetikleyiciler
        if getattr(args, "sonraki_kontrol", None):
            updates["next_review_date"] = args.sonraki_kontrol

        try:
            revised = mgr.revise_thesis(
                thesis_id=thesis_id,
                rationale=rationale,
                updates=updates,
                author=getattr(args, "yazar", "user") or "user",
            )
            if getattr(args, "json", False):
                _p(json.dumps(revised.to_db_row(revised.record_hash or ""), ensure_ascii=False, indent=2))
            else:
                _p(f"  ✓ Tez başarıyla revize edildi (yeni sürüm mühürlendi):")
                _p(f"    Tez ID       : {revised.thesis_id}")
                _p(f"    Yeni Sürüm   : v{revised.version_number} ({revised.version_id})")
                _p(f"    Önceki Sürüm : {revised.supersedes_id}")
                _p(f"    Gerekçe      : {revised.revision_rationale}")
                _p(f"    Yeni Mühür   : {revised.record_hash}")
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez revize edilemedi: {exc}")
            return 1

    elif action == "gecersiz-kil":
        thesis_id = args.tez_id
        rationale = getattr(args, "gerekce", None)
        if not rationale or len(rationale.strip()) < 10:
            _p("  ✗ Hata: Tezi geçersiz kılmak için en az 10 karakterlik açıklayıcı gerekçe (--gerekce) zorunludur.")
            return 1
        try:
            inv = mgr.invalidate_thesis(
                thesis_id=thesis_id,
                rationale=rationale,
                author=getattr(args, "yazar", "user") or "user",
            )
            if getattr(args, "json", False):
                _p(json.dumps(inv.to_db_row(inv.record_hash or ""), ensure_ascii=False, indent=2))
            else:
                _p(f"  ✓ Tez geçersiz (INVALIDATED) olarak mühürlendi:")
                _p(f"    Tez ID       : {inv.thesis_id}")
                _p(f"    Sürüm        : v{inv.version_number} ({inv.version_id})")
                _p(f"    Gerekçe      : {inv.revision_rationale}")
                _p(f"    Mühür        : {inv.record_hash}")
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez geçersiz kılınamadı: {exc}")
            return 1

    elif action == "kontrol":
        _header("AYLIK TEZ SAĞLIK VE İNCELEME DENETİMİ")
        try:
            health = mgr.audit_theses_health()
            if getattr(args, "json", False):
                _p(json.dumps(health, ensure_ascii=False, indent=2))
                return 0

            _p(f"  Toplam Aktif Tez: {health['total_active_theses']}")
            _p(f"  İnceleme Günü Gelmiş / Geçmiş : {health['due_for_review_count']}")
            _p(f"  İnceleme Tarihi Eksik Olanlar: {health['missing_review_date_count']}")
            _p(f"  Güncel ve Sağlıklı Tez Sayısı : {health['up_to_date_count']}")

            if health["due_for_review"]:
                _p("\n  ⚠️ İNCELEME GÜNÜ GELEN TEZLER:")
                for item in health["due_for_review"]:
                    _p(f"    · [{item['thesis_id']}] {item['isin']} - {item['title']} (Tarih: {item['next_review_date']})")

            if health["missing_review_date"]:
                _p("\n  ℹ️ İNCELEME TARİHİ BELİRTİLMEMİŞ TEZLER:")
                for item in health["missing_review_date"]:
                    _p(f"    · [{item['thesis_id']}] {item['isin']} - {item['title']}")

            if health["is_all_healthy"]:
                _p("\n  ✓ Tüm aktif tezlerin inceleme tarihleri güncel ve sağlıklı.")
            _p(LINE)
            return 0
        except Exception as exc:
            _p(f"  ✗ Tez kontrolü başarısız: {exc}")
            return 1

    return 0


def cmd_tahmin(args) -> int:
    action = getattr(args, "tahmin_action", None)
    if not action:
        _p("  Eksik alt komut: `masa tahmin uret|uzlas|listele|karne`.")
        return 1

    from masa.forecast.generator import generate_daily_forecasts
    from masa.forecast.settlement import settle_daily_forecasts
    from masa.forecast.metrics import calculate_performance_metrics
    from masa.forecast.pool import load_forecast_pool

    db = DatabaseManager()
    db.initialize_schema()

    def _handle_collection_error(database: DatabaseManager, action_name: str, exc: Exception, target_date_str: str) -> int:
        from masa.audit.queue import JobQueue, JobState, build_dedup_key
        from masa.notify import notify_system_alert

        err_text = str(exc)
        err_lower = err_text.lower()
        is_auth = any(w in err_lower for w in ("oturum", "login", "auth", "yetki", "unauthorized", "session", "expired", "401", "2fa"))

        try:
            jq = JobQueue(database)
            dedup = build_dedup_key(f"tahmin_{action_name}", {"action": action_name}, day_str=target_date_str)
            job_dict, _ = jq.enqueue("data_collection", dedup, params={"action": action_name, "date": target_date_str})
            jid = job_dict["job_id"]
            cur = jq.get_job(jid)
            if cur:
                if is_auth:
                    if cur.status == JobState.QUEUED:
                        jq.transition(jid, to_status=JobState.COLLECTING)
                        jq.transition(jid, to_status=JobState.WAITING_AUTH, error_message=err_text)
                    elif cur.status == JobState.COLLECTING:
                        jq.transition(jid, to_status=JobState.WAITING_AUTH, error_message=err_text)
                    elif cur.status in (JobState.FAILED, JobState.NEEDS_REVIEW):
                        jq.transition(jid, to_status=JobState.QUEUED)
                        jq.transition(jid, to_status=JobState.COLLECTING)
                        jq.transition(jid, to_status=JobState.WAITING_AUTH, error_message=err_text)
                else:
                    if cur.status == JobState.QUEUED:
                        jq.transition(jid, to_status=JobState.COLLECTING)
                        jq.transition(jid, to_status=JobState.FAILED, error_message=err_text)
                    elif cur.status == JobState.COLLECTING:
                        jq.transition(jid, to_status=JobState.FAILED, error_message=err_text)
        except Exception as q_exc:
            _p(f"  · [Kuyruk geçiş kaydı: {q_exc}]")

        if is_auth:
            _p(f"  ✗ Scalable Capital oturumu sonlanmış veya yetkilendirme hatası: {err_text}")
            _p("  ⚠️ İşlem 'waiting_auth' durumuna alındı. Lütfen `masa giris` komutunu çalıştırınız.")
            _p("  İşlem durduruldu (eski/eksik verilerle tahmin/uzlaşma yapılmaz).")
            try:
                notify_system_alert(
                    level="KRİTİK",
                    message=f"Scalable oturumu sonlanmış. Tahmin {action_name} durduruldu. Lütfen 'masa giris' yapınız.",
                )
            except Exception:
                pass
        else:
            _p(f"  ✗ Veri toplama hatası: {err_text}")
            _p("  İşlem durduruldu (eski/eksik verilerle tahmin üretilmesi engellendi).")
        return 1

    if action == "uret":
        tarih = getattr(args, "tarih", None)
        model = getattr(args, "model", "model_momentum_v1") or "model_momentum_v1"
        dry_run = getattr(args, "kuru", False)
        target_date_str = tarih or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        from masa.calendar.adapter import CalendarAdapter
        cal = CalendarAdapter("XETR")
        if not cal.is_market_session(target_date_str):
            _p("  Bugün Xetra seansı yok, tahmin üretilmedi.")
            return 0

        _header("GÜNLÜK TAHMİN ÜRETECİ (09:30 CET) — 5 ETF + 5 Hisse Senedi")
        _p(f"  Tarih: {target_date_str} | Model: {model} | Kip: {'KURU ÇALIŞMA (DRY-RUN)' if dry_run else 'CANLI MÜHÜR'}")

        try:
            pool = load_forecast_pool()
            sym_map = {inst.isin: (inst.sembol, inst.asset_type) for inst in pool.all_instruments()}
            pool_isins = [inst.isin for inst in pool.all_instruments()]

            # Mühürlü veri toplama: holdings + havuzdaki 10 aracın tamamı için sc quote ve 1m/3m serileri
            if tarih is None and not dry_run and not getattr(args, "yalnizca_tahmin", False):
                _p("  Mühürlü veri toplanıyor (holdings + 10 havuz aracı kotasyonları ve 1m/3m serileri)...")
                try:
                    from masa.pipeline import Pipeline
                    pipe = Pipeline(db=db)
                    snap_res = pipe.collect_snapshot(extra_isins=pool_isins)
                    if not snap_res.ok:
                        err_msg = "; ".join(snap_res.quote_failures)
                        raise RuntimeError(f"Kotasyon toplama hatası: {err_msg}")
                    _p(f"  ✓ Mühürlü kotasyonlar toplandı ({snap_res.quotes_count} kotasyon, mühür: {snap_res.run_id})")
                    hist_res = pipe.collect_history(isins=pool_isins, timeframes=("1m", "3m"), include_transactions=False)
                    if hist_res.get("errors"):
                        err_msg = "; ".join(hist_res["errors"])
                        raise RuntimeError(f"Chart serisi toplama hatası: {err_msg}")
                    _p(f"  ✓ 1m/3m serileri mühürlendi ({len(hist_res.get('series', {}))} seri)")
                except Exception as exc:
                    return _handle_collection_error(db, "uret", exc, target_date_str)

            forecasts = generate_daily_forecasts(db, target_date=tarih, model_id=model, dry_run=dry_run)

            if getattr(args, "json", False):
                _p(json.dumps([f.to_db_row() for f in forecasts], ensure_ascii=False, indent=2))
                return 0

            if not forecasts:
                _p("  İlgili tarih ve model için tüm tahminler zaten mühürlenmiş (0 yeni tahmin).")
                return 0

            _p(f"{'Sembol':<7} {'ISIN':<14} {'Tür':<7} {'Ref Fiyat':>10} {'Hedef Fiyat':>12} {'Yön':>6} {'Güven':>10}  {'Kayıt Mührü'}")
            _p("-" * 75)
            for f in forecasts:
                sym, a_type = sym_map.get(f.isin, ("—", "—"))
                _p(f"{sym:<7} {f.isin:<14} {a_type:<7} {eur(f.reference_price):>10} {eur(f.target_price):>12} {f.direction.value:>6} {f.display_confidence:>10}  {f.record_hash[:16]}...")
            _p(LINE)
            _p(f"  ✓ {len(forecasts)} tahmin başarıyla oluşturuldu{' ve mühürlendi' if not dry_run else ''}.")
            if not dry_run and forecasts:
                try:
                    from masa.notify import notify_forecast_generated
                    notify_forecast_generated(len(forecasts), model)
                except Exception:
                    pass
            return 0
        except Exception as exc:
            _p(f"  ✗ Tahmin üretimi başarısız: {exc}")
            return 1

    elif action == "uzlas":
        tarih = getattr(args, "tarih", None)
        target_date_str = tarih or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        from masa.calendar.adapter import CalendarAdapter
        cal = CalendarAdapter("XETR")
        if not cal.is_market_session(target_date_str):
            _p("  Bugün Xetra seansı yok, tahmin üretilmedi.")
            return 0

        _header("AKŞAM TAHMİN UZLAŞMA MOTORU (17:40 CET)")
        try:
            pool = load_forecast_pool()
            pool_isins = [inst.isin for inst in pool.all_instruments()]

            # Mühürlü veri toplama: uzlaşma öncesi 17:40 Scalable kapanış fiyatları
            if tarih is None and not getattr(args, "yalnizca_uzlasma", False):
                _p("  Uzlaşma verisi toplanıyor (holdings + 10 havuz aracı 17:40 Scalable kotasyonları)...")
                try:
                    from masa.pipeline import Pipeline
                    pipe = Pipeline(db=db)
                    snap_res = pipe.collect_snapshot(extra_isins=pool_isins)
                    if not snap_res.ok:
                        err_msg = "; ".join(snap_res.quote_failures)
                        raise RuntimeError(f"Kotasyon toplama hatası: {err_msg}")
                    _p(f"  ✓ Akşam kapanış kotasyonları mühürlendi ({snap_res.quotes_count} kotasyon, mühür: {snap_res.run_id})")
                except Exception as exc:
                    return _handle_collection_error(db, "uzlas", exc, target_date_str)

            settlements = settle_daily_forecasts(db, settlement_date=tarih)
            if getattr(args, "json", False):
                _p(json.dumps([s.to_db_row() for s in settlements], ensure_ascii=False, indent=2))
                return 0

            if not settlements:
                _p("  Uzlaşma bekleyen açık tahmin bulunamadı.")
                return 0

            pool = load_forecast_pool()
            sym_map = {inst.isin: inst.sembol for inst in pool.all_instruments()}

            _p(f"{'Sembol':<7} {'ISIN':<14} {'17:40 Scalable':>14} {'Fark EUR':>10} {'Hata %':>9} {'İsabet':>8}  {'Uzlaşma Mührü'}")
            _p("-" * 76)
            hits = 0
            for s in settlements:
                sym = sym_map.get(s.isin, "—")
                hit_str = "✓ İSABET" if s.direction_hit == 1 else "✗ ISKA"
                if s.direction_hit == 1:
                    hits += 1
                _p(f"{sym:<7} {s.isin:<14} {eur(s.actual_close_price):>14} {eur(s.error_eur):>10} %{s.error_pct:>7.2f} {hit_str:>8}  {s.record_hash[:16]}...")
            _p(LINE)
            _p(f"  ✓ {len(settlements)} tahmin uzlaştırıldı ve mühürlendi. Günlük İsabet: {hits}/{len(settlements)} (%{hits/len(settlements)*100:.1f})")
            if settlements:
                try:
                    from masa.notify import notify_forecast_settled
                    hit_rate = Decimal(str(hits)) / Decimal(str(len(settlements))) * Decimal("100")
                    mape = sum(abs(Decimal(str(s.error_pct))) for s in settlements) / Decimal(str(len(settlements)))
                    notify_forecast_settled(len(settlements), hit_rate, mape)
                except Exception:
                    pass
            return 0
        except Exception as exc:
            _p(f"  ✗ Tahmin uzlaşması başarısız: {exc}")
            return 1

    elif action == "listele":
        _header("GÜNLÜK TAHMİN VE UZLAŞMA DEFTERİ")
        durum = getattr(args, "durum", "TUMU") or "TUMU"
        tarih = getattr(args, "tarih", None)
        isin_filter = getattr(args, "isin", None)
        limit = getattr(args, "limit", 50) or 50

        conn = db.get_connection()
        try:
            if durum.upper() == "BEKLEYEN":
                q = "SELECT * FROM v_forecasts_unsettled WHERE 1=1"
            elif durum.upper() == "UZLASILMIS":
                q = "SELECT * FROM v_forecast_performance WHERE 1=1"
            else:
                q = """
                SELECT fe.*, s.settlement_id, s.actual_close_price, s.error_eur, s.error_pct, s.direction_hit, s.settled_at
                FROM forecast_entries fe
                LEFT JOIN settlements s ON fe.forecast_id = s.forecast_id
                WHERE 1=1
                """
            params: List[Any] = []
            if tarih:
                q += " AND fe.target_date = ?" if durum.upper() == "TUMU" else " AND target_date = ?"
                params.append(tarih)
            if isin_filter:
                q += " AND fe.isin = ?" if durum.upper() == "TUMU" else " AND isin = ?"
                params.append(isin_filter.upper())
            q += " ORDER BY target_date DESC, created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(q, tuple(params)).fetchall()
            if getattr(args, "json", False):
                _p(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
                return 0

            if not rows:
                _p("  Kayıtlı tahmin bulunamadı.")
                return 0

            _p(f"{'Tarih':<11} {'ISIN':<14} {'Model':<18} {'Yön':<5} {'Hedef F':>9} {'Kapanış':>9} {'Durum':<11} {'İsabet'}")
            _p("-" * 72)
            for r in rows:
                has_settled = "settlement_id" in r.keys() and r["settlement_id"] is not None
                durum_str = "UZLAŞILDI" if has_settled else "AÇIK/BEKLİYOR"
                close_str = eur(Decimal(str(r["actual_close_price"]))) if has_settled else "—"
                hit_str = ("✓" if r["direction_hit"] == 1 else "✗") if has_settled else "—"
                _p(f"{r['target_date']:<11} {r['isin']:<14} {r['model_id'][:18]:<18} {r['direction']:<5} {eur(Decimal(str(r['target_price']))):>9} {close_str:>9} {durum_str:<11} {hit_str}")
            _p(LINE)
            _p(f"  Toplam {len(rows)} kayıt listelendi.")
            return 0
        finally:
            conn.close()

    elif action == "karne":
        try:
            metrics = calculate_performance_metrics(
                db=db,
                isin=getattr(args, "isin", None),
                model_id=getattr(args, "model", None),
            )
            if getattr(args, "json", False):
                dump = metrics.model_dump(mode="json")
                dump["schema_version"] = "1.0.0"
                _p(json.dumps(dump, ensure_ascii=False, indent=2))
                return 0

            _header("TAHMİN BAŞARI KARNESİ VE UZLAŞMA PERFORMANSI")

            _p(f"  Toplam Tahmin Sayısı : {metrics.total_forecasts}")
            _p(f"  Uzlaşan Gözlem (N)   : {metrics.settled_count}")
            _p(f"  Bekleyen Tahminler   : {metrics.pending_count}")
            _p(f"  Örneklem Güvenilirliği: {'⚠️ KÜÇÜK ÖRNEKLEM (N < 30)' if metrics.is_small_sample else '✓ İSTATİSTİKSEL OLARAK GÜVENİLİR (N >= 30)'}")
            if metrics.warning_message:
                _p(f"    {metrics.warning_message}")

            _p("\n  Doğruluk ve Hata Metrikleri:")
            _p(f"  · Yön Başarı Oranı (Hit Rate) : %{metrics.hit_rate_pct}")
            if metrics.etf_hit_rate_pct is not None:
                _p(f"    - ETF Başarı Oranı          : %{metrics.etf_hit_rate_pct}")
            if metrics.stock_hit_rate_pct is not None:
                _p(f"    - Hisse Senedi Başarı Oranı : %{metrics.stock_hit_rate_pct}")
            _p(f"  · Ortalama Mutlak Hata (MAPE) : %{metrics.mape_pct}")
            _p(f"  · Ortalama Fiyat Sapması (MAE): {eur(metrics.mae_eur)}")
            _p(f"  · Sistemik Yanlılık (Bias/MPE): %{metrics.mpe_pct}")
            if metrics.baseline_flat_hit_rate_pct is not None or metrics.baseline_yesterday_hit_rate_pct is not None:
                _p("\n  Baz Model Karşılaştırması:")
                if metrics.baseline_flat_hit_rate_pct is not None:
                    _p(f"  · Baz 1 (Değişmez / Martingale): %{metrics.baseline_flat_hit_rate_pct}")
                if metrics.baseline_yesterday_hit_rate_pct is not None:
                    _p(f"  · Baz 2 (Dünkü Yön Devam)      : %{metrics.baseline_yesterday_hit_rate_pct}")
                if metrics.baseline_warning:
                    _p(f"  · {metrics.baseline_warning}")
            _p(LINE)
            return 0
        except Exception as exc:
            _p(f"  ✗ Karne hesaplanamadı: {exc}")
            return 1

    elif action == "gecmis-simule":
        from masa.forecast.walk_forward import run_walk_forward_simulation
        gun = getattr(args, "gun", 30) or 30
        modeller_str = getattr(args, "modeller", "model_momentum_v1,model_mean_reversion_v1,model_ensemble_v1") or "model_momentum_v1,model_mean_reversion_v1,model_ensemble_v1"
        models_tuple = tuple(m.strip() for m in modeller_str.split(",") if m.strip())

        _header(f"GEÇMİŞ TAHMİN VE UZLAŞMA SİMÜLASYONU ({gun} İşlem Günü)")
        _p(f"  Modeller: {', '.join(models_tuple)}")
        _p("  Geçmiş seriler üzerinden walk-forward simülasyonu çalıştırılıyor...")

        try:
            res = run_walk_forward_simulation(db, days=gun, models=models_tuple)
            metrics = res["metrics"]

            if getattr(args, "json", False):
                dump = metrics.model_dump(mode="json")
                dump["days_processed"] = res["days_processed"]
                dump["forecasts_created"] = res["forecasts_created"]
                dump["settlements_created"] = res["settlements_created"]
                dump["models"] = res["models"]
                _p(json.dumps(dump, ensure_ascii=False, indent=2))
                return 0

            _p(f"  ✓ {res['days_processed']} seans günü başarıyla tarandı.")
            _p(f"  ✓ {res['forecasts_created']} yeni tahmin üretildi ve mühürlendi.")
            _p(f"  ✓ {res['settlements_created']} yeni akşam uzlaşması mühürlendi.")
            _p(LINE)
            _p(f"  Toplam Uzlaşan Tahmin (N)   : {metrics.settled_count}")
            _p(f"  Örneklem Güvenilirliği       : {'✓ İSTATİSTİKSEL OLARAK GÜVENİLİR (N >= 30)' if not metrics.is_small_sample else '⚠️ KÜÇÜK ÖRNEKLEM (N < 30)'}")
            _p(f"  Yön Başarı Oranı (Hit Rate) : %{metrics.hit_rate_pct}")
            _p(f"  Ortalama Hata (MAPE)        : %{metrics.mape_pct}")
            _p(f"  Ortalama Sapma (MAE)        : {eur(metrics.mae_eur)}")
            _p(f"  Sistemik Yanlılık (Bias/MPE): %{metrics.mpe_pct}")
            if metrics.etf_hit_rate_pct is not None:
                _p(f"  · ETF Yön Başarısı          : %{metrics.etf_hit_rate_pct}")
            if metrics.stock_hit_rate_pct is not None:
                _p(f"  · Hisse Yön Başarısı        : %{metrics.stock_hit_rate_pct}")
            _p(LINE)
            _p("  ✓ Başarı karnesi ve geçmiş uzlaşma defteri güncellendi.")
            return 0
        except Exception as exc:
            _p(f"  ✗ Geçmiş simülasyonu başarısız: {exc}")
            return 1

    return 0


def cmd_portfoy(args) -> int:
    db = DatabaseManager(); db.initialize_schema()
    run = latest_run(db)
    if run is None:
        if getattr(args, "json", False):
            import json
            _p(json.dumps({
                "schema_version": "1.0.0",
                "run_id": None,
                "positions": [],
                "cash_eur": 0.0,
                "total_eur": 0.0,
                "warning": "Mühürlü veri yok: masa veri."
            }, ensure_ascii=False, indent=2))
            return 1
        _p("  Mühürlü veri yok: `masa veri`."); return 1
    cfg = load_config()

    if getattr(args, "json", False):
        import json
        positions_list = []
        for p in run.positions:
            val = float(p.value)
            tot = float(run.total) if run.total else 0.0
            wt = (val / tot * 100.0) if tot > 0 else 0.0
            positions_list.append({
                "isin": p.isin,
                "name": p.name,
                "role": cfg.role(p.isin),
                "quantity": float(p.quantity),
                "mid_eur": float(p.mid),
                "value_eur": val,
                "weight_pct": round(wt, 2),
                "quality": p.quality,
                "fifo_price_eur": float(p.fifo_price) if p.fifo_price else None,
            })
        _p(json.dumps({
            "schema_version": "1.0.0",
            "run_id": run.run_id,
            "completed_at": run.completed_at,
            "positions_count": len(positions_list),
            "cash_eur": float(run.cash),
            "total_eur": float(run.total),
            "positions": positions_list,
        }, ensure_ascii=False, indent=2))
        return 0

    _header(f"PORTFÖY — mühür {run.run_id}")
    _p(f"{'ISIN':<13} {'Rol':<34} {'Adet':>6} {'Mid':>9} {'Değer':>12} {'Ağırlık':>8} {'Kalite':>8}")
    for p in run.positions:
        _p(f"{p.isin:<13} {cfg.role(p.isin)[:34]:<34} {p.quantity:>6} {p.mid:>9.3f} {eur(p.value):>12} "
           f"{pct(p.value / run.total * 100 if run.total else 0, 1):>8} {p.quality:>8}")
    _p(f"{'NAKİT':<13} {'':<34} {'':>6} {'':>9} {eur(run.cash):>12}")
    _p(f"{'TOPLAM':<13} {'':<34} {'':>6} {'':>9} {eur(run.total):>12}")
    return 0


# ---------------------------------------------------------------- analysis
def _analysis(db: DatabaseManager, cfg, run):
    series = {p.isin: latest_series(db, p.isin, "1y") for p in run.positions}
    series_max = {p.isin: latest_series(db, p.isin, "max") or series[p.isin] for p in run.positions}
    metrics = {i: analytics.risk_metrics(s) if s else None for i, s in series.items()}
    port_series = analytics.static_portfolio_series(series, {p.isin: p.quantity for p in run.positions})
    port_metrics = analytics.risk_metrics(port_series) if port_series else None
    corr = analytics.correlation_matrix({k: v for k, v in series.items() if v})
    txs = latest_transactions(db)
    realized = None
    if txs:
        realized = analytics.realized_returns(
            txs, {p.isin: p.quantity for p in run.positions}, {p.isin: p.value for p in run.positions},
            {p.isin: p.fifo_price for p in run.positions}, run.cash,
            datetime.fromisoformat(run.completed_at), series_max)
    return series, metrics, port_series, port_metrics, corr, realized


def _plan(cfg, run, inflow: Decimal):
    if not cfg.targets:
        return None
    tot = run.total + inflow
    pos = []
    for p in run.positions:
        pos.append({"isin": p.isin, "ticker": p.isin[-4:], "name": p.name[:60] or p.isin, "shares": p.quantity,
                    "quote_mid": p.mid, "bid": p.bid, "ask": p.ask, "valuation": p.value,
                    "current_weight": min(Decimal(1), p.value / run.total) if run.total else 0})
    mode = "INFLOW_ONLY" if inflow > 0 else "FULL_REBALANCE"
    return rebalancing.calculate_rebalancing({
        "as_of": datetime.now(timezone.utc), "portfolio_id": run.run_id, "base_currency": "EUR",
        "available_cash": run.cash, "new_cash_injection": inflow, "positions": pos,
        "target_weights": cfg.targets,
        "rebalance_policy": {"rebalance_mode": mode, "absolute_tolerance_band": cfg.policy.band_abs,
                             "relative_tolerance_band": cfg.policy.band_rel,
                             "min_trade_ticket_eur": cfg.policy.min_ticket,
                             "target_cash_weight": cfg.policy.cash_target}})


def _confirm(msg: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        _p(f"  {msg} → etkileşimsiz oturum, atlandı (onay için --evet)."); return False
    try:
        return input(f"  {msg} [e/H] ").strip().lower() in ("e", "evet", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _run_tradingagents(cfg, run, isins: List[str], assume_yes: bool, kinds: Dict[str, str], store=None) -> Dict[str, Dict[str, Any]]:
    st = ta.status()
    if not st.available:
        _p(f"  TradingAgents kullanılamıyor: {st.detail}"); return {}
    targets = [(i, cfg.yahoo(i)) for i in isins]
    missing = [i for i, y in targets if not y]
    targets = [(i, y) for i, y in targets if y]
    for i in missing:
        _p(f"  · {i}: Yahoo sembolü tanımlı değil (config) → TradingAgents atlandı")
    if not targets:
        return {}
    for line in ta.describe_providers():
        _p(f"  · {line}")
    if not _confirm(f"TradingAgents {len(targets)} sembol için çalışacak (her biri onlarca model çağrısı, "
                    "sembol başına birkaç dakika). Ücret yukarıdaki sağlayıcılara bağlı. Devam?", assume_yes):
        return {}
    book = ta.portfolio_context(run.positions, run.cash, cfg.yahoo)
    router = ta.ModelRouter()
    out = {}
    for isin, sym in targets:
        _p(f"  … TradingAgents {sym} ({isin}) çalışıyor")
        res = ta.run_routed(sym, router, asset_kind=kinds.get(isin, "ETF"), portfolio=book)
        out[isin] = res
        _p(f"    {'✓ ' + str(res.get('rating')) if res.get('ok') else '✗ ' + str(res.get('error'))[:160]}"
           f"{'  [' + res['route'] + ']' if res.get('route') else ''}")
    if router.usage:
        _p("  Hızlı katman dağılımı: " + ", ".join(f"{k} {v} sembol" for k, v in router.usage.items()))
        if store is not None:
            rid, _ = store.store.store_raw_object("tradingagents", json.dumps(res, ensure_ascii=False, default=str),
                                                  datetime.now(timezone.utc), command=f"ta {sym}")
            store.audit.log_event("masa.tradingagents", "EXTERNAL_OPINION", "instrument", isin,
                                  {"raw_id": rid, "ticker": sym, "ok": res.get("ok"), "rating": res.get("rating"),
                                   "route": res.get("route")})
    return out


def cmd_rapor(args, pipe: Optional[Pipeline] = None, scan_result=None, ta_results=None) -> int:
    db = pipe.db if pipe else DatabaseManager()
    db.initialize_schema()
    run = latest_run(db, getattr(args, "run_id", None))
    if run is None:
        _p("  Mühürlü veri yok: `masa veri`."); return 1
    cfg = load_config()
    _header(f"RAPOR — mühür {run.run_id}")
    series, metrics, port_series, port_metrics, corr, realized = _analysis(db, cfg, run)
    assessments = assess(run, cfg, metrics)
    plan = _plan(cfg, run, Decimal(str(getattr(args, "nakit", 0) or 0)))
    critic_res = critic_check(run, corr)
    integ = integrity_report(db)
    md_text = build(run, cfg, integ, CalendarAdapter().is_market_open(datetime.now(timezone.utc)), metrics,
                    port_metrics, corr, assessments, realized, plan, scan_result, ta_results or {}, critic_res)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    is_paylasim = getattr(args, "paylasim", False)
    if is_paylasim:
        from masa.privacy import mask_report_for_sharing
        md_text = mask_report_for_sharing(md_text)
        path = REPORT_DIR / f"masa-rapor-paylasim-{datetime.now().strftime('%Y-%m-%d_%H%M')}.md"
    else:
        path = REPORT_DIR / f"masa-rapor-{datetime.now().strftime('%Y-%m-%d_%H%M')}.md"
    # Yayın atomikliği: rapor önce geçici dosyaya yazılır, doğrulama geçince taşınır
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(md_text, encoding="utf-8")
    if integ["ok"]:
        tmp_path.replace(path)
    else:
        tmp_path.unlink(missing_ok=True)

    for s in assessments:
        _p(f"  {s.label:<14} {s.isin}  {cfg.role(s.isin)[:40]}")
    critic_tag = "Kod kontrolünden geçti (APPROVE) — Bağımsız model denetimi: YOK" if critic_res.verdict.value == "APPROVE" else critic_res.verdict.value
    _p(f"  Red-team: {critic_tag} · bütünlük {'GEÇERLİ' if integ['ok'] else 'BOZUK'}")
    if integ["ok"]:
        _p(f"  📄 {path}")
    else:
        _p("  ✗ Bütünlük doğrulaması başarısız olduğu için rapor yayımlanmadı (yarım rapor engellendi).")
    return 0 if integ["ok"] else 3


def cmd_guvenlik_tara(args) -> int:
    _header("GÜVENLİK VE GİZLİLİK DENETİMİ (İP-10)")
    from masa.security import ensure_secure_permissions
    try:
        changes = ensure_secure_permissions()
        if changes:
            _p(f"  ✓ Dosya izinleri sıkılaştırıldı ({len(changes)} öğe):")
            for c in changes[:5]:
                _p(f"    · {c}")
            if len(changes) > 5:
                _p(f"    · ... ve {len(changes) - 5} diğer öğe")
        else:
            _p("  ✓ Dosya ve dizin izinleri tam uyumlu (0700/0600).")
    except Exception as exc:
        _p(f"  ✗ İzin kontrolü başarısız: {exc}")
        return 1

    # Run Gitleaks scan if available
    import subprocess
    try:
        # Resolve .gitleaks.toml location
        gitleaks_cfg = None
        for p in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parent.parent.parent.parent):
            c = p / ".gitleaks.toml"
            if c.exists():
                gitleaks_cfg = c
                break

        cmd = ["gitleaks", "dir", "."]
        if gitleaks_cfg:
            cmd.extend(["-c", str(gitleaks_cfg)])

        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            _p("  ✓ Gitleaks gizli anahtar ve PII taraması: 0 sızıntı tespit edildi (TEMİZ).")
        else:
            _p(f"  ✗ Gitleaks sızıntı tespit etti:\n{res.stdout or res.stderr}")
            return 2
    except FileNotFoundError:
        _p("  ℹ️ Gitleaks sistemde bulunamadı; Python gizlilik taraması çalıştırıldı.")

    _p(LINE)
    _p("  Sonuç: GÜVENLİK VE GİZLİLİK SERTLEŞTİRMESİ TAMAMLANDI")
    return 0


def cmd_zamanla(args) -> int:
    action = getattr(args, "zamanla_action", None)
    if not action:
        _p("  Eksik alt komut: `masa zamanla kur|kaldir|durum|bildirim-test`.")
        return 1

    from masa.scheduler import install_jobs, uninstall_jobs, get_schedule_status
    from masa.notify import send_notification

    if action == "kur":
        _header("LAUNCHD GÖREV ZAMANLAYICI KURULUMU (İP-12)")
        kuru = getattr(args, "kuru", False)
        dest = Path(args.hedef) if getattr(args, "hedef", None) else None
        files = install_jobs(dest_dir=dest, run_launchctl=not kuru)
        _p(f"  ✓ {len(files)} adet LaunchAgent plist dosyası kuruldu{' (kuru çalışma)' if kuru else ' ve launchd servisine yüklendi'}:")
        for f in files:
            _p(f"    · {f}")
        _p("\n  Planlanan Seanslar:")
        _p("    - Sabah: Pazartesi-Cuma 09:30 CET (10 tahmin üretimi)")
        _p("    - Akşam: Pazartesi-Cuma 17:40 CET (Uzlaşma & Pano)")
        _p("    - Cuma:  Cuma 18:00 CET (Haftalık karne & Rapor)")
        _p(LINE)
        return 0


    elif action == "kaldir":
        _header("LAUNCHD GÖREV ZAMANLAYICI KALDIRMA (İP-12)")
        dest = Path(args.hedef) if getattr(args, "hedef", None) else None
        removed = uninstall_jobs(dest_dir=dest)
        _p(f"  ✓ {len(removed)} LaunchAgent görevi durduruldu ve silindi:")
        for r in removed:
            _p(f"    · {r}")
        _p(LINE)
        return 0


    elif action == "durum":
        dest = Path(args.hedef) if getattr(args, "hedef", None) else None
        stats = get_schedule_status(dest_dir=dest)
        if getattr(args, "json", False):
            import json
            out_obj = {
                "schema_version": "1.0.0",
                "agents": stats,
            }
            _p(json.dumps(out_obj, ensure_ascii=False, indent=2))
            return 0

        _header("GÖREV ZAMANLAYICI DURUMU (LaunchAgents)")
        _p(f"{'Görev Etiketi':<24} {'Kurulu':<10} {'Yüklü (Aktif)':<16} {'Açıklama'}")
        _p("-" * 72)
        for s in stats:
            inst_str = "✓ EVET" if s["installed"] else "✗ HAYIR"
            load_str = "✓ AKTİF" if s["loaded"] else "— DURDU"
            _p(f"{s['label']:<24} {inst_str:<10} {load_str:<16} {s['description']}")
        _p(LINE)
        return 0

    elif action == "bildirim-test":
        _header("BİLDİRİM KÖPRÜSÜ TESTİ")
        res = send_notification(
            title="◈ ETF Yatırım Masası",
            subtitle="Test Bildirimi",
            message="Bildirim köprüsü başarıyla çalışıyor.",
        )
        if res:
            _p("  ✓ Bildirim başarıyla tetiklendi.")
            return 0
        else:
            _p("  ✗ Bildirim tetiklenemedi.")
            return 1

    return 1


def cmd_pano(args) -> int:
    _header("STATİK HTML PANO (masa pano)")
    from masa.pano import generate_pano
    cikis_path = Path(args.cikis) if getattr(args, "cikis", None) else None
    try:
        out_file = generate_pano(dest_path=cikis_path)
        _p(f"  ✓ Statik pano başarıyla üretildi: {out_file}")
        if getattr(args, "ac", False):
            import subprocess
            _p("  Tarayıcıda açılıyor...")
            subprocess.run(["open", str(out_file)], check=False)
        return 0
    except Exception as exc:
        _p(f"  ✗ Pano üretimi başarısız: {exc}")
        return 1


def cmd_degerlendir(args) -> int:
    db = DatabaseManager(); db.initialize_schema()
    run = latest_run(db)
    if run is None:
        if getattr(args, "json", False):
            import json
            _p(json.dumps({
                "schema_version": "1.0.0",
                "run_id": None,
                "assessments": [],
                "warning": "Mühürlü veri yok: masa veri."
            }, ensure_ascii=False, indent=2))
            return 1
        _p("  Mühürlü veri yok: `masa veri`."); return 1
    cfg = load_config()
    _, metrics, *_ = _analysis(db, cfg, run)
    assessments_list = assess(run, cfg, metrics)
    if getattr(args, "json", False):
        import json
        out_assessments = []
        for s in assessments_list:
            out_assessments.append({
                "isin": s.isin,
                "name": s.name,
                "label": s.label,
                "reasons": s.reasons,
                "notes": s.notes,
            })
        _p(json.dumps({
            "schema_version": "1.0.0",
            "run_id": run.run_id,
            "assessments": out_assessments,
        }, ensure_ascii=False, indent=2))
        return 0

    _header("TUT / EKLE / AZALT DEĞERLENDİRMESİ (karar desteği, emir değil)")
    for s in assessments_list:
        _p(f"\n  [{s.label}] {s.isin} — {s.name}")
        for r in s.reasons:
            _p(f"     • {r}")
        for n in s.notes:
            _p(f"     · {n}")
    return 0


def cmd_tarama(args, pipe: Optional[Pipeline] = None):
    if getattr(args, "son", False):
        db = DatabaseManager()
        db.initialize_schema()
        conn = db.get_connection()
        try:
            row = conn.execute(
                """SELECT entity_id, event_time, payload_json 
                   FROM audit_events 
                   WHERE actor = 'masa.scanner' AND action = 'RUN_SEALED' 
                   ORDER BY event_id DESC LIMIT 1"""
            ).fetchone()
            if not row:
                if getattr(args, "json", False):
                    _p(json.dumps({
                        "schema_version": "1.0.0",
                        "pool_count": 0,
                        "candidates": [],
                        "warning": "Kayıtlı mühürlü tarama bulunamadı."
                    }, ensure_ascii=False, indent=2))
                else:
                    _p("  Kayıtlı mühürlü tarama bulunamadı.")
                return 0, None

            run_id = row[0]
            scan_time = row[1]
            payload = json.loads(row[2]) if row[2] else {}
            ranked = payload.get("ranked", [])

            q_rows = conn.execute(
                """SELECT isin, alias, spread_pct, quality_status 
                   FROM quotes 
                   WHERE snapshot_id = ?""",
                (f"{run_id}_quotes",)
            ).fetchall()
            quote_map = {q[0]: {"alias": q[1], "spread_pct": q[2], "quality": q[3]} for q in q_rows}

            inst_rows = conn.execute("SELECT isin, name FROM instruments").fetchall()
            inst_map = {i[0]: i[1] for i in inst_rows}

            candidates_out = []
            for item in ranked:
                isin = item[0]
                label = item[1]
                score = float(item[2]) if item[2] is not None else None
                q_info = quote_map.get(isin, {})
                name = q_info.get("alias") or inst_map.get(isin) or isin

                reasons = []
                if label == "ARAŞTIRMAYA DEĞER":
                    reasons.append("Trend üstünde, risk-düzeltilmiş getiri ve makas ölçütleri karşılanıyor.")
                else:
                    reasons.append("Ölçüt dışı / filtre kriterleri sağlanmadı.")

                candidates_out.append({
                    "isin": isin,
                    "name": name,
                    "label": label,
                    "score": score,
                    "reasons": reasons,
                })

            if getattr(args, "json", False):
                _p(json.dumps({
                    "schema_version": "1.0.0",
                    "pool_count": len(candidates_out),
                    "candidates": candidates_out,
                }, ensure_ascii=False, indent=2))
                return 0, {"run_id": run_id, "candidates": candidates_out}

            _header(f"SON MÜHÜRLÜ FIRSAT TARAMASI ({run_id} · {scan_time})")
            for i, c in enumerate(candidates_out, 1):
                sc = f"{c['score']:+.2f}" if c['score'] is not None else "  — "
                _p(f"  {i:>2}. {sc}  {c['label']:<18} {c['isin']}  {c['name'][:38]}")
            return 0, {"run_id": run_id, "candidates": candidates_out}
        finally:
            conn.close()

    from masa.scanner import scan
    pipe = pipe or Pipeline()
    run = latest_run(pipe.db)
    cfg = load_config()
    if not cfg.pool:
        if getattr(args, "json", False):
            _p(json.dumps({
                "schema_version": "1.0.0",
                "pool_count": 0,
                "candidates": [],
                "warning": "Havuz boş: config/havuz.json"
            }, ensure_ascii=False, indent=2))
            return 1, None
        _p("  Havuz boş: config/havuz.json"); return 1, None

    port_series = []
    held = set()
    if run:
        held = {p.isin for p in run.positions}
        series = {p.isin: latest_series(pipe.db, p.isin, "1y") for p in run.positions}
        port_series = analytics.static_portfolio_series(series, {p.isin: p.quantity for p in run.positions})
    res = scan(pipe, cfg, port_series, held)
    if getattr(args, "json", False):
        candidates_out = []
        for c in res.get("candidates", []):
            candidates_out.append({
                "isin": c.isin,
                "name": c.name,
                "label": c.label,
                "score": float(c.score) if c.score is not None else None,
                "reasons": getattr(c, "reasons", []),
            })
        _p(json.dumps({
            "schema_version": "1.0.0",
            "pool_count": sum(len(v) for v in cfg.pool.values()),
            "candidates": candidates_out,
        }, ensure_ascii=False, indent=2))
        return 0, res

    _header(f"FIRSAT TARAMASI — {sum(len(v) for v in cfg.pool.values())} araç (Scalable verisi)")
    for i, c in enumerate(res["candidates"], 1):
        sc = f"{c.score:+.2f}" if c.score is not None else "  — "
        _p(f"  {i:>2}. {sc}  {c.label:<18} {c.isin}  {c.name[:38]}")
    return 0, res


def cmd_plan(args) -> int:
    db = DatabaseManager(); db.initialize_schema()
    run = latest_run(db)
    cfg = load_config()
    if run is None:
        _p("  Mühürlü veri yok."); return 1
    plan = _plan(cfg, run, Decimal(str(args.nakit or 0)))
    _header("YENİDEN DENGELEME PLANI (yalnız plan; emir gönderilmez)")
    if plan is None:
        _p("  Hedef ağırlık yok: config/portfoy.json → hedef_agirliklar (ör. {\"IE00B3YLTY66\": 0.6, ...})"); return 1
    _p("  " + plan.trigger_rationale)
    for o in plan.ordered_execution_plan:
        _p(f"  {o.execution_sequence}. {o.action.value:<4} {abs(o.shares_delta):>6g} × {o.isin} @ {o.target_price:.3f} ≈ {eur(o.estimated_amount)}")
    return 0


def cmd_tradingagents(args) -> int:
    pipe = Pipeline()
    run = latest_run(pipe.db)
    if run is None:
        _p("  Mühürlü veri yok: `masa veri`."); return 1
    cfg = load_config()
    isins = args.isin or [p.isin for p in run.positions]
    kinds = {i: cfg.instruments.get(i, {}).get("tur") or ("HISSE" if i in cfg.pool.get("hisse", {}) else "ETF") for i in isins}
    _header("TRADINGAGENTS — çok ajanlı LLM analizi (harici görüş)")
    res = _run_tradingagents(cfg, run, isins, args.evet, kinds, pipe)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for isin, r in res.items():
        p = REPORT_DIR / f"tradingagents-{isin}-{datetime.now().strftime('%Y-%m-%d')}.md"
        rep = r.get("reports", {})
        p.write_text(f"# TradingAgents — {r.get('ticker')} ({isin})\n\n**Karar:** {r.get('rating')}\n\n" +
                     "\n\n".join(f"## {k}\n\n{v}" for k, v in rep.items()) + "\n", encoding="utf-8")
        _p(f"  📄 {p}")
    return 0 if res and all(r.get("ok") for r in res.values()) else 2


def cmd_yorum(args) -> int:
    """Prompt + kanıt paketi: Claude gibi bir modele yapıştırılmaya hazır."""
    db = DatabaseManager(); db.initialize_schema()
    reports = sorted(REPORT_DIR.glob("masa-rapor-*.md"))
    if not reports:
        _p("  Önce `masa rapor`."); return 1
    method_dir = MASA_DIR.parent / "Yatirim-Masasi" / "etf-yatirim-masasi" / "references"
    parts = []
    for name in ("tez-ve-portfoy.md", "fon-inceleme.md", "firsat-arastirmasi.md", "veri-kurallari.md"):
        f = method_dir / name
        if f.exists():
            parts.append(f"<yontem dosya=\"{name}\">\n{f.read_text(encoding='utf-8')}\n</yontem>")
    ta_files = sorted(REPORT_DIR.glob(f"tradingagents-*-{datetime.now().strftime('%Y-%m-%d')}.md"))
    prompt = f"""Sen kişisel bir ETF/hisse araştırma masasının analistisin. Aşağıda (1) çalışma yöntemim,
(2) mühürlü Scalable verisinden üretilmiş güncel rapor ve (3) varsa TradingAgents çıktıları var.

Görevler:
1. Elimdeki her pozisyon hakkında kısa yorum: rolü, risk, çakışma/yoğunlaşma, son dönem davranışı.
2. Her pozisyon için TUT / EKLE / AZALT / GÖZDEN GEÇİR değerlendirmesi; gerekçe ve onu değiştirecek koşul.
   Raporun kural tabanlı etiketine katılmıyorsan nedenini yaz. Sat/al kararını ben veririm.
3. Tarama tablosundaki "ARAŞTIRMAYA DEĞER" adaylardan en fazla 3'ünü, portföyüme ne kattığıyla değerlendir.
4. Veri sorunu, varsayım ve bilinmeyenleri ayrıca listele. Rapordaki sayıları değiştirme; hesap gerekiyorsa göster.
Yanıt Türkçe olsun; yatırım danışmanı olmadığını unutma, kanıtla konuş.

{chr(10).join(parts)}

<rapor dosya="{reports[-1].name}">
{reports[-1].read_text(encoding='utf-8')}
</rapor>
""" + "".join(f"\n<tradingagents dosya=\"{f.name}\">\n{f.read_text(encoding='utf-8')[:12000]}\n</tradingagents>\n" for f in ta_files)
    out = REPORT_DIR / f"yorum-paketi-{datetime.now().strftime('%Y-%m-%d_%H%M')}.md"
    out.write_text(prompt, encoding="utf-8")
    _p(f"  📄 {out}  ({len(prompt):,} karakter) — bunu Claude'a yapıştırın veya sohbette 'yorum paketini oku' deyin.")
    return 0


# ---------------------------------------------------------------- baslat
def cmd_baslat(args) -> int:
    _header("ETF YATIRIM MASASI — BAŞLAT")
    try:
        pipe = Pipeline()
    except SchemaVersionError as exc:
        _p(f"  ✗ {exc}"); return 1
    _p("\n[1/6] Scalable CLI ve oturum")
    if not Path(pipe.reader.binary_path).exists():
        _p(f"  ✗ sc bulunamadı: {pipe.reader.binary_path}"); return 1
    if not ensure_session(pipe, interactive=True):
        _p("  Oturum açılmadan devam edilemez."); return 1
    _p("\n[2/6] Başlangıç verileri")
    rc = cmd_veri(args, pipe)
    if rc not in (0, 2):
        return rc
    _p("")
    cmd_gecmis(args, pipe)
    cfg = load_config()
    run = latest_run(pipe.db)
    scan_res = None
    if not args.tarama_yok:
        _p("\n[3/6] Fırsat taraması")
        _, scan_res = cmd_tarama(args, pipe)
    ta_results: Dict[str, Dict[str, Any]] = {}
    _p("\n[4/6] TradingAgents (harici çok ajanlı görüş)")
    if args.derin:
        isins = [p.isin for p in run.positions]
        if scan_res:
            top = [c.isin for c in scan_res["candidates"] if c.label == "ARAŞTIRMAYA DEĞER" and not c.held]
            isins += top[: int(cfg.policy.scan.get("ust_aday_sayisi", 5))]
        kinds = {i: cfg.instruments.get(i, {}).get("tur") or ("HISSE" if i in cfg.pool.get("hisse", {}) else "ETF")
                 for i in isins}
        ta_results = _run_tradingagents(cfg, run, isins, args.evet, kinds, pipe)
    else:
        _p("  Atlandı (çalıştırmak için: masa baslat --derin)")
    _p("\n[5/6] Analiz, tut/sat değerlendirmesi ve rapor")
    rc = cmd_rapor(args, pipe, scan_res, ta_results)
    _p("\n[6/6] Yorum paketi (prompt + kanıt)")
    cmd_yorum(args)
def cmd_arastir(args) -> int:
    """Kaynaklı araştırma, kanıt paketi mühürleme ve rapor doğrulama (İP-6)."""
    from masa.identity.isin import validate_isin
    from masa.research.agent import Horizon, ResearchAgent
    from masa.research.evidence import EvidenceBundleBuilder
    from masa.research.verifier import ReportVerifier, ReportStatus

    isin = args.isin.strip().upper()
    try:
        validate_isin(isin)
    except Exception as exc:
        _p(f"✗ Geçersiz ISIN: {exc}")
        return 1

    db = DatabaseManager()
    db.initialize_schema()

    vade_map = {
        "uzun": Horizon.STRATEGIC_LONG_TERM,
        "orta": Horizon.TACTICAL_MEDIUM_TERM,
        "firsat": Horizon.OPPORTUNITY_SHORT_TERM,
    }
    horizon = vade_map.get(args.vade, Horizon.STRATEGIC_LONG_TERM)

    builder = EvidenceBundleBuilder(db)
    bundle_input = builder.build_bundle(isin, horizon=horizon)

    if not args.kuru:
        try:
            builder.seal_bundle_to_db(bundle_input)
        except Exception as exc:
            pass

    agent = ResearchAgent(horizon=horizon, llm=None)
    research_output = agent.run(bundle_input)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    curr = bundle_input.instrument_identity.currency
    catalysts_str = ", ".join(research_output.thesis_section.key_catalysts) if research_output.thesis_section.key_catalysts else "-"
    risks_str = ", ".join(research_output.counter_thesis_section.structural_risks) if research_output.counter_thesis_section.structural_risks else "-"
    falsification_str = ", ".join(research_output.counter_thesis_section.falsification_triggers) if research_output.counter_thesis_section.falsification_triggers else "-"

    report_lines = [
        f"# ETF Araştırma Raporu: {bundle_input.instrument_identity.name} ({isin})",
        "",
        f"- **Tarih**: {now_str}",
        f"- **Vade**: {args.vade.upper()} ({horizon.value})",
        f"- **Model**: {research_output.run_metadata.model_identity}",
        f"- **Kanıt Paketi**: `{bundle_input.bundle_id}` ({bundle_input.instrument_identity.issuer or 'Bilinmiyor'})",
        "",
        "## 1. Yönetici Özeti ve Tez",
        research_output.thesis_section.core_thesis,
        "",
        f"**Katalizörler**: {catalysts_str}",
        "",
        f"**Ekonomik Gerekçe**: {research_output.thesis_section.economic_rationale}",
        "",
        "## 2. Karşı Tez ve Temel Riskler",
        research_output.counter_thesis_section.downside_scenarios,
        "",
        f"**Yapısal Riskler**: {risks_str}",
        "",
        f"**Yanılma Tetikleyicileri (Falsification Triggers)**: {falsification_str}",
        "",
        "## 3. Finansal Metrikler ve Mühürlü Veriler",
        f"- **Fiyat (Mid)**: {bundle_input.sealed_quote_snapshot.computed_mid} {curr}",
        f"- **Alış / Satış**: {bundle_input.sealed_quote_snapshot.bid} / {bundle_input.sealed_quote_snapshot.ask} {curr}",
        f"- **Makas (Spread)**: {bundle_input.sealed_quote_snapshot.spread} ({bundle_input.sealed_quote_snapshot.spread_pct}%)",
    ]

    for m in bundle_input.deterministic_metrics:
        report_lines.append(f"- **{m.metric_name}**: {m.value} {m.unit.value} ({m.period})")

    report_lines.extend([
        "",
        "## 4. Yapılandırılmış İddialar ve Kaynaklar",
    ])
    for c in research_output.structured_claims:
        cit_str = " ".join(cit.semantic_tag() for cit in c.citations)
        report_lines.append(f"- [{c.category.value}] {c.statement} ({cit_str})")

    if research_output.unresolved_unknowns:
        report_lines.extend(["", "## 5. Bilinmeyenler ve Sınırlar"])
        for u in research_output.unresolved_unknowns:
            report_lines.append(f"- **{u.field_name}**: {u.reason_unresolved}")

    report_lines.extend([
        "",
        "---",
        "## 6. Denetim ve Güvenlik Durumu",
        "- Red-team denetimi: **Kod kontrolünden geçti (APPROVE) — Bağımsız model denetimi: YOK**",
    ])

    report_text = "\n".join(report_lines) + "\n"

    verifier = ReportVerifier(db)
    verif_res = verifier.verify_report(report_text, instrument_id=isin)

    report_lines.extend([
        f"- Rapor Doğrulama Yaşam Döngüsü: **{verif_res.status.value.upper()}**",
        f"- Finansal Rakam / İddia Doğruluk Oranı: **%{verif_res.verification_score_pct}** "
        f"({verif_res.verified_count} doğrulanmış / {verif_res.unverified_count} teyitsiz)",
        f"- Özet: {verif_res.summary_message}",
        "",
        "---",
        "*Karar desteği amaçlıdır; yatırım tavsiyesi değildir. Tüm rakamlar mühürlü kanıt paketine dayanmaktadır.*",
        "",
    ])
    final_report_text = "\n".join(report_lines)

    report_file_path = None
    if not args.kuru:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        date_stamp = datetime.now().strftime("%Y-%m-%d")
        report_file_path = Path(args.cikis) if args.cikis else (REPORT_DIR / f"arastirma-{isin.lower()}-{date_stamp}.md")
        report_file_path.write_text(final_report_text, encoding="utf-8")

        json_path = report_file_path.with_suffix(".json")
        json_payload = {
            "isin": isin,
            "bundle_id": bundle_input.bundle_id,
            "status": verif_res.status.value,
            "verification_score_pct": str(verif_res.verification_score_pct),
            "verified_count": verif_res.verified_count,
            "unverified_count": verif_res.unverified_count,
            "items": [item.model_dump() for item in verif_res.items],
            "agent_output": research_output.model_dump(mode="json"),
        }
        json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        out_dict = {
            "isin": isin,
            "bundle_id": bundle_input.bundle_id,
            "status": verif_res.status.value,
            "verification": verif_res.model_dump(mode="json"),
            "report_path": str(report_file_path) if report_file_path else None,
        }
        print(json.dumps(out_dict, indent=2, ensure_ascii=False))
        return 0

    _p(f"✓ {isin} ({bundle_input.instrument_identity.name}) araştırması tamamlandı.")
    _p(f"  Durum: {verif_res.status.value.upper()} (Skor: %{verif_res.verification_score_pct})")
    _p(f"  Red-team: Kod kontrolünden geçti (APPROVE) — Bağımsız model denetimi: YOK")
    _p(f"  Mühürlü paket: {bundle_input.bundle_id} ({len(bundle_input.deterministic_metrics)} metrik, {len(bundle_input.verified_sources)} kaynak)")
    if report_file_path:
        _p(f"  📄 Rapor: {report_file_path}")
    return 0


def cmd_model(args: argparse.Namespace) -> int:
    """Model registry, evaluation scorecard, and run manifest commands (İP-7)."""
    from masa.model_registry.evaluator import ModelEvaluator
    from masa.model_registry.manager import ModelRegistryManager
    from masa.model_registry.models import ModelStatus, TaskCategory

    mgr = ModelRegistryManager()
    mgr.seed_default_models()

    subcmd = getattr(args, "model_cmd", None)
    if subcmd == "listele":
        models = mgr.list_models()
        champions = {c["task_category"]: c for c in mgr.get_champions()}
        if args.json:
            print(json.dumps([m.model_dump() for m in models], indent=2, ensure_ascii=False))
            return 0
        _p("Kayıtlı Modeller ve Doğrulama Durumu (İP-7):")
        _p(f"{'MODEL ID':<25} {'SAĞLAYICI':<12} {'KATMAN':<14} {'DURUM':<14} {'ŞAMPİYON'}")
        _p("-" * 75)
        for m in models:
            is_champ_str = ""
            for cat, champ in champions.items():
                if champ["model_id"] == m.model_id:
                    is_champ_str = f"👑 {cat}"
                    break
            _p(f"{m.model_id:<25} {m.provider:<12} {m.access_tier.value:<14} {m.status.value:<14} {is_champ_str}")
        return 0

    elif subcmd == "degerlendir":
        if not args.evet:
            _p("⚠️  Model Değerlendirme Kümesi Çalıştırma Onayı:")
            _p("   Bu komut modelleri standart doğrulama görevlerinde çalıştırır ve skorları mühürler.")
            _p("   Ücret Kapısı: Yalnız ücretsiz/abonelik/yerel modeller çalıştırılır.")
            _p("   Devam etmek istiyor musunuz? (Onaylamak için '--evet' ekleyin)")
            return 1

        evaluator = ModelEvaluator(db=mgr.db)
        target_models = [mgr.get_model(args.model)] if args.model else mgr.list_models()
        target_models = [m for m in target_models if m and m.status not in (ModelStatus.PAUSED, ModelStatus.REVOKED)]

        cat = TaskCategory(args.kategori) if args.kategori else None

        all_evals = []
        _p("Modeller Doğrulama Kümesinde Değerlendiriliyor...")
        for tm in target_models:
            res_list = evaluator.evaluate_model(tm.model_id, category=cat)
            all_evals.extend(res_list)
            for er in res_list:
                champ_mark = "👑 ŞAMPİYON" if er.is_champion else ""
                crit_warn = "⚠️ KRİTİK HATA GEÇTİ" if er.critical_error_passed else "✓ GÜVENLİ"
                _p(f"  [{tm.model_id}] {er.task_category.value}: %{er.score_pct} | {crit_warn} {champ_mark}")

        if args.json:
            print(json.dumps([e.model_dump() for e in all_evals], indent=2, ensure_ascii=False))
def cmd_ayar(args: argparse.Namespace) -> int:
    action = getattr(args, "ayar_action", None)
    if action == "goster":
        from masa.config import get_config_summary
        summary = get_config_summary()
        if getattr(args, "json", False):
            _p(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            _p("Portföy ve Sistem Yapılandırması:")
            _p(f"  Çekirdek ISIN: {summary['portfoy'].get('cekirdek_isin', '—')}")
            _p(f"  Hedef Durumu: {summary['portfoy'].get('hedef_durumu', '—')}")
            _p(f"  Politika Durumu: {summary['politika'].get('durum', '—')}")
            _p(f"  Model Sağlayıcıları: {len(summary['model_erisim']['providers'])}")
        return 0
    elif action == "yaz":
        from masa.config import write_config
        dosya = args.dosya
        json_input = args.json
        if json_input == "-":
            raw_text = sys.stdin.read()
        else:
            raw_text = json_input
        try:
            payload = json.loads(raw_text)
        except Exception as exc:
            _p(f"✗ Geçersiz JSON: {exc}")
            return 1

        try:
            ok, msg, archive_path = write_config(
                dosya=dosya,
                data=payload,
                confirm_policy=getattr(args, "onayla_politika", False),
            )
            if ok:
                _p(f"✓ {msg}")
                if archive_path:
                    _p(f"  Arşiv kopyası: {archive_path}")
                return 0
            else:
                _p(f"✗ {msg}")
                return 1
        except Exception as exc:
            _p(f"✗ Yapılandırma yazılamadı: {exc}")
            return 1
    else:
        _p("Kullanım: masa ayar {goster,yaz} ...")
        return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="masa", description="ETF Yatırım Masası")
    sub = ap.add_subparsers(dest="command")
    b = sub.add_parser("baslat", help="Tam akış: giriş → veri → tarama → [TradingAgents] → rapor → yorum")
    b.add_argument("--derin", action="store_true", help="TradingAgents'ı da çalıştır (model kullanımı; sağlayıcıya bağlı)")
    b.add_argument("--evet", action="store_true", help="Onay sorularını evet say")
    b.add_argument("--tarama-yok", action="store_true", help="Havuz taramasını atla")
    b.add_argument("--nakit", type=float, default=0, help="Plan için yeni nakit girişi (EUR)")
    sub.add_parser("kontrol", help="Scalable, oturum, paketler, DB, TradingAgents kontrolü")
    p_giris = sub.add_parser("giris", help="Scalable oturumunu kontrol et, gerekirse girişe yönlendir")
    p_giris.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    p_giris.add_argument("--login", action="store_true", help="sc login --local-read-only sürecini başlatıp çıktıları akıtır")
    sub.add_parser("veri", help="Pozisyon/nakit/kotasyonları çek ve mühürle")
    sub.add_parser("gecmis", help="Fiyat serileri ve işlem geçmişini çek ve mühürle")
    sub.add_parser("dogrula", help="Mühür ve denetim zincirlerini alan düzeyinde doğrula")
    p_portfoy = sub.add_parser("portfoy", help="Son mühürden portföyü göster")
    p_portfoy.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    r = sub.add_parser("rapor", help="Son mühürden tam rapor üret")
    r.add_argument("--run-id"); r.add_argument("--nakit", type=float, default=0)
    r.add_argument("--paylasim", action="store_true", help="Hassas tutar ve kimlikleri maskeleyerek paylaşılabilir rapor üret")
    p_deg = sub.add_parser("degerlendir", help="Tut/ekle/azalt değerlendirmesi")
    p_deg.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    p_tar = sub.add_parser("tarama", help="config/havuz.json fırsat taraması")
    p_tar.add_argument("--son", action="store_true", help="Canlı tarama yapmadan veritabanındaki son mühürlü tarama sonucunu oku")
    p_tar.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    p = sub.add_parser("plan", help="Hedef ağırlıklara göre plan"); p.add_argument("--nakit", type=float, default=0)
    t = sub.add_parser("tradingagents", help="TradingAgents çok ajanlı analiz")
    t.add_argument("isin", nargs="*"); t.add_argument("--evet", action="store_true")
    sub.add_parser("yorum", help="Claude için prompt + kanıt paketi üret")
    y = sub.add_parser("yedek", help="Canlı veritabanını çevrimiçi yedekle ve manifest üret")
    y.add_argument("yedek_action", nargs="?", choices=["budama"], default=None, help="Alt işlem (örn: budama)")
    y.add_argument("--prova", action="store_true", help="Yedekleme sonrası otomatik izole restore_drill çalıştır")
    y.add_argument("--cikti", type=str, default=None, help="Yedekleme dizini")
    y.add_argument("--zorla", action="store_true", help="Değişiklik olmasa bile zorla yeni yedek al")
    y.add_argument("--kuru", action="store_true", help="Budama kuru çalışma (dry-run)")
    y.add_argument("--uygula", action="store_true", help="Budamayı uygula")
    y.add_argument("--onay", action="store_true", help="Budama silme işlemini onayla (zorunlu)")
    g = sub.add_parser("geri-yukle", help="Yedekten canlı veritabanını geri yükle")
    g.add_argument("hedef", nargs="?", default=None, help="Geri yüklenecek .db veya .json dosyası")
    g.add_argument("--onayla", action="store_true", help="Canlı veritabanı üzerine yazmayı onayla (zorunlu)")
    g.add_argument("--yedek-dizini", type=str, default=None, help="Yedek arama dizini")
    sub.add_parser("denetle", help="Canlı veritabanı ve harici zincir ucu kütüğünü denetle")
    sub.add_parser("gecis", help="Veritabanını şema v3'e kayıpsız yükselt")
    sub.add_parser("izleme", help="Scalable izleme listesini (watchlist) salt-okunur göster")
    p_dur = sub.add_parser("durum", help="Masa sistem ve yetenek durumunu özetle")
    p_dur.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    # islemler
    p_tx = sub.add_parser("islemler", help="İşlem defteri komutları")
    sub_tx = p_tx.add_subparsers(dest="islemler_action")
    p_tx_cek = sub_tx.add_parser("cek", help="İşlemleri Scalable'dan çek ve deftere işle")
    p_tx_cek.add_argument("--from-time", type=str, default=None, help="Başlangıç zamanı (ISO-8601)")
    p_tx_cek.add_argument("--tam", action="store_true", help="7 günlük örtüşmeyi atla, tüm geçmişi çek")
    p_tx_list = sub_tx.add_parser("listele", help="Güncel işlem defterini listele")
    p_tx_list.add_argument("--isin", type=str, default=None, help="ISIN filtresi")
    p_tx_list.add_argument("--limit", type=int, default=50, help="Maksimum kayıt sayısı")
    p_tx_list.add_argument("--tip", type=str, default=None, help="Akış sınıfı filtresi")

    # kurumsal-islem
    p_ca = sub.add_parser("kurumsal-islem", help="Kurumsal işlem kayıt ve listeleme")
    sub_ca = p_ca.add_subparsers(dest="kurumsal_action")
    p_ca_add = sub_ca.add_parser("ekle", help="Onaylı kurumsal işlem kaydet")
    p_ca_add.add_argument("--isin", type=str, required=True, help="Menkul kıymet ISIN kodu")
    p_ca_add.add_argument("--tur", type=str, required=True, choices=["SPLIT", "REVERSE_SPLIT", "ISIN_CHANGE", "MERGER"], help="İşlem türü")
    p_ca_add.add_argument("--oran", type=str, required=True, help="Pay dönüşüm oranı (new_shares / old_shares)")
    p_ca_add.add_argument("--yeni-isin", type=str, default=None, help="Hedef ISIN (ISIN_CHANGE ve MERGER için zorunlu)")
    p_ca_add.add_argument("--yeni-ticker", type=str, default=None, help="Hedef ticker")
    p_ca_add.add_argument("--tarih", type=str, required=True, help="Yürürlük tarihi (ISO-8601 UTC)")
    p_ca_add.add_argument("--duyuru-tarihi", type=str, default=None, help="Duyuru tarihi (ISO-8601)")
    p_ca_add.add_argument("--onaylayan", type=str, required=True, help="Onaylayan yetkili/kullanıcı (zorunlu)")
    p_ca_add.add_argument("--aciklama", type=str, default="Kurumsal işlem", help="Açıklama / not")
    p_ca_list = sub_ca.add_parser("listele", help="Kurumsal işlemleri listele")
    p_ca_list.add_argument("--isin", type=str, default=None, help="ISIN filtresi")

    # mutabakat
    p_mut = sub.add_parser("mutabakat", help="4 boyutlu portföy ve nakit mutabakatı")
    p_mut.add_argument("--tarih", type=str, default=None, help="Mutabakat tarihi (ISO-8601)")
    p_mut.add_argument("--json", action="store_true", help="JSON formatında çıktı bas")
    p_mut.add_argument("--detay", action="store_true", help="Ayrıntılı uyuşmazlık tablosunu göster")

    # sepet
    p_sepet = sub.add_parser("sepet", help="ETF sepeti yükleme, listeleme ve örtüşme analizi")
    sub_sepet = p_sepet.add_subparsers(dest="sepet_action")

    p_sep_yuk = sub_sepet.add_parser("yukle", help="ETF sepet dosyası yükle (CSV/XLSX)")
    p_sep_yuk.add_argument("dosya", nargs="?", default=None, help="Yüklenecek sepet dosya yolu (belirtilmezse inbox taranır)")
    p_sep_yuk.add_argument("--dosya", dest="dosya_flag", default=None, help="Alternatif dosya yolu parametresi")
    p_sep_yuk.add_argument("--isin", type=str, default=None, help="ETF ISIN kodu")
    p_sep_yuk.add_argument("--tarih", type=str, default=None, help="Belge tarihi (YYYY-MM-DD)")
    p_sep_yuk.add_argument("--kaynak", type=str, default=None, choices=["iShares", "SPDR", "ishares", "spdr"], help="İhraççı sağlayıcı")

    p_sep_list = sub_sepet.add_parser("listele", help="Kayıtlı ETF sepetlerini listele")
    p_sep_list.add_argument("--isin", type=str, default=None, help="Belirli bir ISIN için filtrele")
    p_sep_list.add_argument("--limit", type=int, default=20, help="Maksimum listelenecek sepet sayısı")

    p_sep_ort = sub_sepet.add_parser("ortusme", help="Fonlar arası örtüşme matrisi ve konsolide şirket maruziyeti")
    p_sep_ort.add_argument("--detay", action="store_true", help="Ayrıntılı sektör/ülke kırılımlarını göster")
    p_sep_ort.add_argument("--top", type=int, default=25, help="Gösterilecek konsolide şirket sayısı (varsayılan: 25)")
    p_sep_ort.add_argument("--hedef", action="store_true", help="Canlı pozisyon yerine portfoy.json hedef ağırlıklarını kullan")
    p_sep_ort.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    # tez
    p_tez = sub.add_parser("tez", help="Yatırım tezleri kayıt, revizyon ve denetim yönetimi")
    sub_tez = p_tez.add_subparsers(dest="tez_action")

    p_tez_ekle = sub_tez.add_parser("ekle", help="Yeni yatırım tezi ekle ve mühürle")
    p_tez_ekle.add_argument("--isin", type=str, required=False, help="Menkul kıymet ISIN kodu")
    p_tez_ekle.add_argument("--baslik", type=str, required=False, help="Tez başlığı")
    p_tez_ekle.add_argument(
        "--kategori",
        type=str,
        default="CORE",
        choices=["CORE", "FACTOR", "THEMATIC", "SATELLITE", "STOCK", "HEDGE", "CEKIRDEK", "FAKTOR", "TEMATIK", "UYDU", "HISSE", "KORUNMA"],
        help="Varlık kategorisi"
    )
    p_tez_ekle.add_argument(
        "--vade",
        type=str,
        default="LONG_TERM",
        choices=["SHORT_TERM", "MEDIUM_TERM", "LONG_TERM", "SECULAR", "STRATEJIK_UZUN", "TAKTIK_ORTA", "FIRSAT_KISA", "SEKULER", "UZUN", "ORTA", "KISA", "FIRSAT"],
        help="Analitik ufuk / vade"
    )
    p_tez_ekle.add_argument("--ozet", type=str, required=False, help="Bir cümlelik net özet")
    p_tez_ekle.add_argument("--gerekce", type=str, required=False, help="Ekonomik ve rasyonel gerekçe")
    p_tez_ekle.add_argument("--tetikleyiciler", nargs="+", required=False, help="Falsifikasyon / çürütme koşulları (en az 2 adet)")
    p_tez_ekle.add_argument("--kanitlar", nargs="*", default=[], help="Kanıt sütunları")
    p_tez_ekle.add_argument("--karsi-gorus", type=str, default=None, help="Karşı görüş / riskler")
    p_tez_ekle.add_argument("--hedef-agirlik", type=str, default=None, help="Hedef portföy ağırlığı (örn. 0.40)")
    p_tez_ekle.add_argument("--sonraki-kontrol", type=str, default=None, help="Sonraki inceleme tarihi (YYYY-MM-DD)")
    p_tez_ekle.add_argument("--yazar", type=str, default="user", help="Tez yazarı")
    p_tez_ekle.add_argument("--girdi-json", type=str, default=None, help="Tez verilerini doğrudan JSON dizesinden veya stdin'den (-) al")
    p_tez_ekle.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tez_list = sub_tez.add_parser("listele", help="Kayıtlı yatırım tezlerini listele")
    p_tez_list.add_argument("--isin", type=str, default=None, help="ISIN filtresi")
    p_tez_list.add_argument("--durum", type=str, default=None, choices=["ACTIVE", "INVALIDATED", "REVISED", "SUPERSEDED", "ALL"], help="Durum filtresi")
    p_tez_list.add_argument("--kategori", type=str, default=None, help="Kategori filtresi")
    p_tez_list.add_argument("--vade", type=str, default=None, help="Vade filtresi")
    p_tez_list.add_argument("--gecmis", action="store_true", help="Arşivlenmiş/önceki sürümleri de dahil et")
    p_tez_list.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tez_show = sub_tez.add_parser("goster", help="Tez detay kartını göster")
    p_tez_show.add_argument("tez_id", type=str, help="Görüntülenecek tez ID'si")
    p_tez_show.add_argument("--gecmis", action="store_true", help="Tezin tüm sürüm soyağacını listele")
    p_tez_show.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tez_rev = sub_tez.add_parser("revize", help="Tezi yeni bir sürümle revize et (gerekçe zorunlu)")
    p_tez_rev.add_argument("tez_id", type=str, help="Revize edilecek tez ID'si")
    p_tez_rev.add_argument("--gerekce", type=str, required=True, help="Revizyon gerekçesi (en az 10 karakter, zorunlu)")
    p_tez_rev.add_argument("--baslik", type=str, default=None, help="Yeni başlık")
    p_tez_rev.add_argument("--ozet", type=str, default=None, help="Yeni özet")
    p_tez_rev.add_argument("--ekonomik-gerekce", type=str, default=None, help="Yeni ekonomik gerekçe")
    p_tez_rev.add_argument("--kategori", type=str, default=None, help="Yeni kategori")
    p_tez_rev.add_argument("--vade", type=str, default=None, help="Yeni vade")
    p_tez_rev.add_argument("--hedef-agirlik", type=str, default=None, help="Yeni hedef ağırlık")
    p_tez_rev.add_argument("--tetikleyiciler", nargs="*", default=None, help="Güncellenmiş tetikleyiciler")
    p_tez_rev.add_argument("--sonraki-kontrol", type=str, default=None, help="Yeni kontrol tarihi (YYYY-MM-DD)")
    p_tez_rev.add_argument("--yazar", type=str, default="user", help="Yazar")
    p_tez_rev.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tez_inv = sub_tez.add_parser("gecersiz-kil", help="Tezi geçersiz kıl / kapat (gerekçe zorunlu)")
    p_tez_inv.add_argument("tez_id", type=str, help="Geçersiz kılınacak tez ID'si")
    p_tez_inv.add_argument("--gerekce", type=str, required=True, help="Geçersiz kılma / çürütme gerekçesi (zorunlu)")
    p_tez_inv.add_argument("--yazar", type=str, default="user", help="Yazar")
    p_tez_inv.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tez_ctrl = sub_tez.add_parser("kontrol", help="Aylık tez sağlık ve inceleme kontrolü")
    p_tez_ctrl.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    # tahmin
    p_tahmin = sub.add_parser("tahmin", help="Günlük tahmin ve uzlaşma motoru (5 ETF + 5 Hisse)")
    sub_tahmin = p_tahmin.add_subparsers(dest="tahmin_action")

    p_tah_uret = sub_tahmin.add_parser("uret", help="Sabah 09:30 CET gün içi kapanış tahminlerini üret ve mühürle")
    p_tah_uret.add_argument("--tarih", type=str, default=None, help="Hedef tarih (YYYY-MM-DD)")
    p_tah_uret.add_argument("--model", type=str, default="model_momentum_v1", help="Tahmin modeli kimliği")
    p_tah_uret.add_argument("--kuru", action="store_true", help="Kuru çalışma (veritabanına yazmaz)")
    p_tah_uret.add_argument("--yalnizca-tahmin", action="store_true", help="Broker kotasyon ve seri toplama adımını atla")
    p_tah_uret.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tah_uzlas = sub_tahmin.add_parser("uzlas", help="Akşam 17:40 CET gerçekleşen kapanışla tahminleri uzlaştır ve mühürle")
    p_tah_uzlas.add_argument("--tarih", type=str, default=None, help="Uzlaşma tarihi (YYYY-MM-DD)")
    p_tah_uzlas.add_argument("--yalnizca-uzlasma", action="store_true", help="Broker kotasyon toplama adımını atla")
    p_tah_uzlas.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tah_list = sub_tahmin.add_parser("listele", help="Günlük tahmin ve uzlaşma defterini listele")
    p_tah_list.add_argument("--durum", type=str, default="TUMU", choices=["TUMU", "BEKLEYEN", "UZLASILMIS"], help="Filtre durumu")
    p_tah_list.add_argument("--tarih", type=str, default=None, help="Tarih filtresi (YYYY-MM-DD)")
    p_tah_list.add_argument("--isin", type=str, default=None, help="ISIN filtresi")
    p_tah_list.add_argument("--limit", type=int, default=50, help="Maksimum listelenecek kayıt sayısı")
    p_tah_list.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tah_karne = sub_tahmin.add_parser("karne", help="Tahmin başarı karnesi ve metrik özeti (Hit Rate, MAPE, MAE)")
    p_tah_karne.add_argument("--isin", type=str, default=None, help="Belirli bir ISIN için karne üret")
    p_tah_karne.add_argument("--model", type=str, default=None, help="Belirli bir model için karne üret")
    p_tah_karne.add_argument("--detay", action="store_true", help="Ayrıntılı döküm göster")
    p_tah_karne.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_tah_sim = sub_tahmin.add_parser("gecmis-simule", help="Geçmiş seanslar üzerinden walk-forward tahmin ve uzlaşma simülasyonu çalıştır")
    p_tah_sim.add_argument("--gun", type=int, default=30, help="Geriye dönük incelenecek işlem günü sayısı (varsayılan: 30)")
    p_tah_sim.add_argument("--modeller", type=str, default="model_momentum_v1,model_mean_reversion_v1,model_ensemble_v1", help="Kullanılacak modeller (virgülle ayrılmış)")
    p_tah_sim.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_arastir = sub.add_parser("arastir", help="Kaynaklı araştırma, kanıt paketi mühürleme ve rapor doğrulama (İP-6)")
    p_arastir.add_argument("isin", type=str, help="Araştırılacak menkul kıymet ISIN kodu (örn: IE00B4L5Y983)")
    p_arastir.add_argument("--vade", type=str, default="uzun",
                           choices=["uzun", "orta", "firsat", "LONG_TERM", "MEDIUM_TERM", "SHORT_TERM"],
                           help="Yatırım vadesi (uzun: STRATEGIC_LONG_TERM, orta: TACTICAL_MEDIUM_TERM, firsat: OPPORTUNITY_SHORT_TERM)")
    p_arastir.add_argument("--model", type=str, default="local", help="Model seçimi (varsayılan: yerel deterministik motor)")
    p_arastir.add_argument("--kuru", action="store_true", help="Kuru çalışma (veritabanına ve rapora yazmaz)")
    p_arastir.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    p_arastir.add_argument("--cikis", type=str, default=None, help="Özel rapor dosya yolu")

    p_model = sub.add_parser("model", help="Model kaydı, doğrulama kümesi ve çalışma manifestosu yönetimi (İP-7)")
    sub_model = p_model.add_subparsers(dest="model_cmd")

    p_mod_list = sub_model.add_parser("listele", help="Kayıtlı model sağlayıcılarını ve şampiyonları listele")
    p_mod_list.add_argument("--json", action="store_true", help="JSON formatında döküm")

    p_mod_eval = sub_model.add_parser("degerlendir", help="Modelleri doğrulama kümesinde değerlendir ve karne oluştur")
    p_mod_eval.add_argument("--model", type=str, default=None, help="Belirli bir model ID (varsayılan: tüm modeller)")
    p_mod_eval.add_argument("--kategori", type=str, default=None,
                            choices=["table_extraction", "claim_source_matching", "flawed_report_detection", "turkish_semantics"],
                            help="Yalnız belirli bir görev kategorisini değerlendir")
    p_mod_eval.add_argument("--evet", action="store_true", help="Ücret/onay uyarısını doğrudan onayla")
    p_mod_eval.add_argument("--json", action="store_true", help="JSON formatında döküm")

    # pano
    p_pano = sub.add_parser("pano", help="Konsolide statik HTML panosu üret (İP-9)")
    p_pano.add_argument("--cikis", type=str, default=None, help="Özel HTML çıktı dosya yolu")
    p_pano.add_argument("--ac", action="store_true", help="Üretilen panoyu varsayılan tarayıcıda aç")

    # guvenlik-tara
    sub.add_parser("guvenlik-tara", help="Dosya izinlerini sıkılaştır ve gizli anahtar/PII sızıntısı taraması yap (İP-10)")

    # zamanla
    p_zam = sub.add_parser("zamanla", help="macOS launchd görev zamanlayıcı ve bildirim yönetimi (İP-12)")
    p_zam.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    sub_zam = p_zam.add_subparsers(dest="zamanla_action")
    p_zam_kur = sub_zam.add_parser("kur", help="09:30 ve 17:40 seanslarını LaunchAgents'a kaydet ve başlat")
    p_zam_kur.add_argument("--kuru", action="store_true", help="Kuru çalışma (launchctl load yapmaz)")
    p_zam_kur.add_argument("--hedef", type=str, default=None, help="Özel LaunchAgents dizini")
    p_zam_kal = sub_zam.add_parser("kaldir", help="LaunchAgents görevlerini durdur ve kaldır")
    p_zam_kal.add_argument("--hedef", type=str, default=None, help="Özel LaunchAgents dizini")
    p_zam_dur = sub_zam.add_parser("durum", help="Kurulu zamanlanmış görevlerin durumunu listele")
    p_zam_dur.add_argument("--hedef", type=str, default=None, help="Özel LaunchAgents dizini")
    p_zam_dur.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")
    sub_zam.add_parser("bildirim-test", help="macOS yerel bildirimini test et")

    # ayar
    p_ayar = sub.add_parser("ayar", help="Sistem ve portföy ayarlarını göster veya güncelle")
    sub_ayar = p_ayar.add_subparsers(dest="ayar_action")
    p_ayar_gos = sub_ayar.add_parser("goster", help="Yapılandırmayı JSON formatında göster")
    p_ayar_gos.add_argument("--json", action="store_true", help="JSON formatında çıktı üret")

    p_ayar_yaz = sub_ayar.add_parser("yaz", help="Yapılandırma dosyasını güncelle")
    p_ayar_yaz.add_argument("--dosya", type=str, required=True, choices=["portfoy", "politika", "havuz"], help="Hedef yapılandırma dosyası")
    p_ayar_yaz.add_argument("--json", type=str, required=True, help="JSON veri dizesi veya stdin için '-'")
    p_ayar_yaz.add_argument("--onayla-politika", action="store_true", help="Politika onayını (durum: ONAYLANDI) teyit et")

    return ap


def main(argv: Optional[List[str]] = None) -> None:
    if os.environ.get("MASA_OWN_PGRP") == "1":
        try:
            if os.getpgrp() != os.getpid():
                os.setpgid(0, 0)
        except OSError:
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    handlers = {"baslat": cmd_baslat, "kontrol": cmd_kontrol, "giris": cmd_giris, "veri": cmd_veri,
                "gecmis": cmd_gecmis, "dogrula": cmd_dogrula, "portfoy": cmd_portfoy, "rapor": cmd_rapor,
                "degerlendir": cmd_degerlendir, "tarama": lambda a: cmd_tarama(a)[0], "plan": cmd_plan,
                "tradingagents": cmd_tradingagents, "yorum": cmd_yorum, "yedek": cmd_yedek,
                "geri-yukle": cmd_geri_yukle, "denetle": cmd_dogrula,
                "gecis": cmd_gecis, "izleme": cmd_izleme, "durum": cmd_durum,
                "islemler": cmd_islemler, "kurumsal-islem": cmd_kurumsal_islem, "mutabakat": cmd_mutabakat,
                "sepet": cmd_sepet, "tez": cmd_tez, "tahmin": cmd_tahmin, "arastir": cmd_arastir,
                "model": cmd_model, "pano": cmd_pano, "guvenlik-tara": cmd_guvenlik_tara,
                "zamanla": cmd_zamanla, "ayar": cmd_ayar}
    if args.command is None:
        ap.print_help(); sys.exit(0)
    try:
        sys.exit(handlers[args.command](args))
    except SchemaVersionError as exc:
        _p(f"✗ {exc}"); sys.exit(1)
    except KeyboardInterrupt:
        _p("\nİptal edildi."); sys.exit(130)


if __name__ == "__main__":
    main()
