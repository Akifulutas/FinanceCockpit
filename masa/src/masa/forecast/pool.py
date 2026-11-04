"""Forecast pool loader and instruments validation (IP-5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from masa.config import CONFIG_DIR
from masa.forecast.models import ForecastPoolConfig, PoolInstrument


def load_forecast_pool(config_path: Optional[Path | str] = None) -> ForecastPoolConfig:
    """Load and validate 5 ETF + 5 Equity pool from config/tahmin_havuzu.json."""
    path = Path(config_path) if config_path else (CONFIG_DIR / "tahmin_havuzu.json")
    if not path.exists():
        raise FileNotFoundError(f"Tahmin havuzu yapılandırma dosyası bulunamadı: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))

    etfs: Dict[str, PoolInstrument] = {}
    for isin, data in raw.get("etf", {}).items():
        instrument = PoolInstrument(
            isin=isin,
            ad=data["ad"],
            sembol=data["sembol"],
            yahoo=data["yahoo"],
            rol=data["rol"],
            mic=data["mic"],
            para_birimi=data.get("para_birimi", "EUR"),
            asset_type="ETF",
        )
        etfs[isin] = instrument

    hisseler: Dict[str, PoolInstrument] = {}
    for isin, data in raw.get("hisse", {}).items():
        instrument = PoolInstrument(
            isin=isin,
            ad=data["ad"],
            sembol=data["sembol"],
            yahoo=data["yahoo"],
            rol=data["rol"],
            mic=data["mic"],
            para_birimi=data.get("para_birimi", "EUR"),
            asset_type="EQUITY",
        )
        hisseler[isin] = instrument

    return ForecastPoolConfig(
        schema_version=raw.get("schema_version", 1),
        guncellenme_tarihi=raw.get("guncellenme_tarihi", ""),
        etf=etfs,
        hisse=hisseler,
    )


def seed_pool_instruments(db: Any, runner: Optional[Any] = None) -> None:
    """Ensure all 10 pool instruments exist in instruments and listings tables with real names."""
    from masa.identity.registry import IdentityRegistry
    from masa.ingestion.sc_reader import ScalableReader

    pool = load_forecast_pool()
    reg = IdentityRegistry(db=db)
    try:
        reg.seed_from_configs(verify=False)
    except Exception:
        pass
    reader = ScalableReader(runner=runner) if runner else None

    for inst in pool.all_instruments():
        real_name = inst.ad
        # Try to query real title from Scalable quote if reader available
        if reader:
            try:
                q_raw = reader.get_quote(inst.isin)
                if q_raw and hasattr(q_raw, "stdout_raw"):
                    parsed = json.loads(q_raw.stdout_raw)
                    title = parsed.get("title") or parsed.get("name") or parsed.get("data", {}).get("name")
                    if title:
                        real_name = str(title).strip()
            except Exception:
                pass

        issuer_id = "iss_vanguard_ie" if "vanguard" in real_name.lower() else (
            "iss_blackrock_ie" if "ishares" in real_name.lower() or "blackrock" in real_name.lower() else "iss_apple_us"
        )
        try:
            reg.ensure_issuer_link(issuer_id=issuer_id, name=issuer_id, country="IE")
        except Exception:
            pass
        inst_id = reg.ensure_instrument(
            isin=inst.isin,
            name=real_name,
            instrument_type=inst.asset_type,
            issuer_id=issuer_id,
            is_ucits=True if inst.asset_type == "ETF" else False,
            domicile="IE" if inst.asset_type == "ETF" else "DE",
            base_currency=inst.para_birimi,
        )
        reg.ensure_listing(
            instrument_id=inst_id,
            mic=inst.mic,
            ticker=inst.sembol,
            currency=inst.para_birimi,
            source="config_tahmin_havuzu",
            is_primary=True,
        )
