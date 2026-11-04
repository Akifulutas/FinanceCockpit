"""Kullanici ayarlari: masa/config/{portfoy,politika,havuz}.json (elle duzenlenir)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Tuple

from masa.identity.isin import validate_isin

MASA_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("MASA_CONFIG_DIR", MASA_DIR / "config"))
REPORT_DIR = Path(os.environ.get("MASA_REPORT_DIR", MASA_DIR / "var" / "reports"))
TRADINGAGENTS_DIR = Path(os.environ.get("MASA_TRADINGAGENTS_DIR", str(Path.home() / "TradingAgents")))


def _load(name: str) -> Dict[str, Any]:
    p = CONFIG_DIR / f"{name}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def get_config_summary() -> Dict[str, Any]:
    """Sistem yapılandırma özetini schema v1.0.0 sözleşmesine göre döndürür."""
    port = _load("portfoy")
    pol = _load("politika")
    mod = _load("modeller")

    providers: list[str] = []
    try:
        from masa.integrations.tradingagents import describe_providers
        providers = describe_providers()
    except Exception:
        providers = [
            "hızlı katman sırayla: google gemini-3.8-flash (ağırlık 1) / chatgpt gpt-6.1-sol (ağırlık 1)",
            "derin katman: chatgpt / gpt-6.1-sol",
            "ücret: chatgpt = abonelik limitinden düşer, google = ücretsiz katmanda ücret yok (limitli)",
        ]

    chatgpt_auth = Path.home() / ".tradingagents" / "chatgpt-auth.json"
    chatgpt_auth_exists = chatgpt_auth.exists()

    sc_bin = os.environ.get("SC_CLI_PATH", "/opt/homebrew/bin/sc")
    sc_exists = Path(sc_bin).exists()

    return {
        "schema_version": "1.0.0",
        "portfoy": port,
        "politika": pol,
        "modeller": mod,
        "model_erisim": {
            "providers": providers,
            "chatgpt_auth_exists": chatgpt_auth_exists,
            "chatgpt_auth_path": "~/.tradingagents/chatgpt-auth.json",
            "google_model": "google / gemini-3.8-flash",
        },
        "broker": {
            "cli_path": sc_bin,
            "cli_exists": sc_exists,
        },
    }


def write_config(
    dosya: str,
    data: Dict[str, Any],
    confirm_policy: bool = False,
    db: Optional[Any] = None,
) -> Tuple[bool, str, Optional[Path]]:
    """Yapılandırma dosyasını doğrular, arşivler, atomik yazar ve denetim kaydı oluşturur."""
    if dosya not in ("portfoy", "politika", "havuz"):
        raise ValueError(f"Geçersiz yapılandırma dosyası: {dosya}. Sadece portfoy, politika veya havuz kabul edilir.")

    if dosya == "portfoy":
        raw_targets = data.get("hedef_agirliklar") or {}
        targets: Dict[str, float] = {}
        for k, v in raw_targets.items():
            clean_isin = validate_isin(k)
            val = Decimal(str(v))
            if val < 0:
                raise ValueError(f"Negatif ağırlık geçersiz: {clean_isin} = {val}")
            targets[clean_isin] = float(val)

        total_w = sum(Decimal(str(v)) for v in raw_targets.values()) if raw_targets else Decimal("0")
        if total_w > Decimal("1.0001"):
            raise ValueError("hedef_agirliklar toplamı 1'i aşıyor")
        data["hedef_agirliklar"] = targets

        if "araclar" in data and isinstance(data["araclar"], dict):
            clean_araclar = {}
            for k, v in data["araclar"].items():
                clean_araclar[validate_isin(k)] = v
            data["araclar"] = clean_araclar

        if targets:
            data["hedef_durumu"] = "ONAYLANDI"
        else:
            data["hedef_durumu"] = "ONAYLANMADI — hedef ağırlıkları siz yazana kadar plan üretilmez"

    elif dosya == "politika":
        durum = str(data.get("durum", "TASLAK")).upper()
        if durum == "ONAYLANDI" and not confirm_policy:
            raise ValueError("Politika onayı için --onayla-politika parametresi gereklidir.")
        data["durum"] = durum

        if "tolerans_mutlak" in data:
            v = float(data["tolerans_mutlak"])
            if not (0 < v <= 0.50):
                raise ValueError("tolerans_mutlak (0, 0.50] aralığında olmalıdır")
        if "tolerans_goreli" in data:
            v = float(data["tolerans_goreli"])
            if not (0 < v <= 1.0):
                raise ValueError("tolerans_goreli (0, 1.0] aralığında olmalıdır")
        if "trend_uyari" in data:
            v = float(data["trend_uyari"])
            if not (-0.50 <= v <= 0.0):
                raise ValueError("trend_uyari [-0.50, 0.0] aralığında olmalıdır")
        if "dusus_inceleme" in data:
            v = float(data["dusus_inceleme"])
            if not (-0.90 <= v <= 0.0):
                raise ValueError("dusus_inceleme [-0.90, 0.0] aralığında olmalıdır")
        if "min_emir_eur" in data:
            v = float(data["min_emir_eur"])
            if v < 0:
                raise ValueError("min_emir_eur >= 0 olmalıdır")
        if "nakit_hedefi" in data:
            v = float(data["nakit_hedefi"])
            if not (0.0 <= v <= 1.0):
                raise ValueError("nakit_hedefi [0, 1.0] aralığında olmalıdır")
        if "ucits_kontrolu" in data:
            data["ucits_kontrolu"] = bool(data["ucits_kontrolu"])

    elif dosya == "havuz":
        for grp in ("etf", "hisse"):
            if grp in data and isinstance(data[grp], dict):
                clean_grp = {}
                for k, v in data[grp].items():
                    clean_grp[validate_isin(k)] = v
                data[grp] = clean_grp

    # Yedek Arşivleme
    target_file = CONFIG_DIR / f"{dosya}.json"
    archive_path: Optional[Path] = None
    if target_file.exists():
        archive_dir = CONFIG_DIR / "arsiv"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_path = archive_dir / f"{dosya}-{ts}.json"
        shutil.copy2(target_file, archive_path)

    # Atomik Yazma
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = CONFIG_DIR / f".{dosya}.json.tmp"
    formatted_json = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_file.write_text(formatted_json, encoding="utf-8")
    os.replace(tmp_file, target_file)

    # Denetim Kütüğü (Audit Log)
    sha256 = hashlib.sha256(formatted_json.encode("utf-8")).hexdigest()
    database = db
    if database is None:
        try:
            from masa.storage.db import DatabaseManager
            database = DatabaseManager()
        except Exception:
            database = None

    if database is not None:
        try:
            from masa.audit.events import AuditLogger
            logger = AuditLogger(database)
            logger.log_event(
                actor="user",
                action="CONFIG_UPDATED",
                entity_type="config",
                entity_id=dosya,
                payload={
                    "file": f"{dosya}.json",
                    "archived_to": str(archive_path) if archive_path else None,
                    "checksum_sha256": sha256,
                },
            )
        except Exception:
            pass

    return True, f"{dosya}.json başarıyla güncellendi.", archive_path


@dataclass
class Policy:
    approved: bool
    band_abs: Decimal
    band_rel: Decimal
    trend_warn: float
    drawdown_review: float
    factor_lag: float
    spread_warn_pct: float
    min_ticket: Decimal
    cash_target: Decimal
    scan: Dict[str, Any]
    ucits_kontrolu: bool = False


@dataclass
class Config:
    instruments: Dict[str, Dict[str, Any]]
    core_isin: Optional[str]
    targets: Dict[str, Decimal]
    policy: Policy
    pool: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)

    def role(self, isin: str) -> str:
        return self.instruments.get(isin, {}).get("rol", "—")

    def yahoo(self, isin: str) -> Optional[str]:
        if isin in self.instruments:
            return self.instruments[isin].get("yahoo")
        for group in self.pool.values():
            if isin in group:
                return group[isin].get("yahoo")
        return None

    def is_factor(self, isin: str) -> bool:
        return bool(self.instruments.get(isin, {}).get("faktor"))


def load_config() -> Config:
    port, pol, pool = _load("portfoy"), _load("politika"), _load("havuz")
    targets = {validate_isin(k): Decimal(str(v)) for k, v in (port.get("hedef_agirliklar") or {}).items()}
    if targets and sum(targets.values()) > Decimal("1.0001"):
        raise ValueError("hedef_agirliklar toplamı 1'i aşıyor")
    policy = Policy(
        approved=str(pol.get("durum", "TASLAK")).upper() == "ONAYLANDI",
        band_abs=Decimal(str(pol.get("tolerans_mutlak", 0.05))),
        band_rel=Decimal(str(pol.get("tolerans_goreli", 0.25))),
        trend_warn=float(pol.get("trend_uyari", -0.05)),
        drawdown_review=float(pol.get("dusus_inceleme", -0.20)),
        factor_lag=float(pol.get("faktor_geri_kalma_puan", 0.10)),
        spread_warn_pct=float(pol.get("makas_uyari_yuzde", 1.0)),
        min_ticket=Decimal(str(pol.get("min_emir_eur", 25))),
        cash_target=Decimal(str(pol.get("nakit_hedefi", 0))),
        scan={"min_sharpe": 0.5, "max_makas_yuzde": 0.5, "max_korelasyon": 0.85, "ust_aday_sayisi": 5,
              **(pol.get("tarama") or {})},
        ucits_kontrolu=bool(pol.get("ucits_kontrolu", False)),
    )
    pool_clean = {grp: {validate_isin(k): v for k, v in (pool.get(grp) or {}).items()} for grp in ("etf", "hisse")}
    return Config(instruments={validate_isin(k): v for k, v in (port.get("araclar") or {}).items()},
                  core_isin=port.get("cekirdek_isin"), targets=targets, policy=policy, pool=pool_clean)
