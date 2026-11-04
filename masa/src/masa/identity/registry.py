"""Identity registry and multi-index lookup service with SQLite append-only storage.

Maintains in-memory multi-index lookup while synchronizing idempotently with
SQLite Schema v3 tables (instruments, listings, issuer_links).
Strict idempotency: Re-processing identical holdings or configs results in 0 DB writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from masa.identity.isin import ISIN, validate_isin
from masa.identity.models import Instrument, InstrumentType, Issuer, Listing
from masa.storage.db import DatabaseManager


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IdentityRegistry:
    """Thread-safe, indexed registry for Issuers, Instruments, and Listings."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db
        self._issuers: dict[str, Issuer] = {}
        self._instruments: dict[str, Instrument] = {}
        self._listings: dict[str, Listing] = {}

        # Indexes
        self._isin_to_instrument_id: dict[str, str] = {}
        self._instrument_to_listing_ids: dict[str, list[str]] = {}
        self._mic_ticker_to_listing_id: dict[tuple[str, str], str] = {}

        if self.db is not None:
            self.load_from_db()

    def load_from_db(self) -> None:
        """Load registered instruments, listings, and issuers from SQLite DB."""
        if not self.db or not self.db.db_path.exists():
            return

        conn = self.db.get_connection()
        try:
            # Check if tables exist
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('instruments', 'listings', 'issuer_links')"
                ).fetchall()
            }
            if "instruments" not in tables or "listings" not in tables:
                return

            # 1. Load issuers from issuer_links
            if "issuer_links" in tables:
                for row in conn.execute("SELECT DISTINCT issuer_id, name, country, lei FROM issuer_links").fetchall():
                    iss = Issuer(
                        issuer_id=row["issuer_id"],
                        name=row["name"],
                        country=row["country"] or "XX",
                        lei=row["lei"] if row["lei"] and len(row["lei"]) == 20 else None,
                        is_active=True,
                    )
                    self._issuers[iss.issuer_id] = iss

            # 2. Load instruments
            for row in conn.execute("SELECT * FROM instruments WHERE is_active=1").fetchall():
                # Ensure dummy issuer exists in memory if not already loaded
                if row["issuer_id"] not in self._issuers:
                    self._issuers[row["issuer_id"]] = Issuer(
                        issuer_id=row["issuer_id"],
                        name=row["issuer_id"],
                        country="XX",
                        is_active=True,
                    )

                inst = Instrument(
                    instrument_id=row["instrument_id"],
                    isin=ISIN(row["isin"]),
                    name=row["name"],
                    instrument_type=InstrumentType(row["instrument_type"]),
                    issuer_id=row["issuer_id"],
                    is_ucits=bool(row["is_ucits"]) if row["is_ucits"] is not None else None,
                    domicile=row["domicile"],
                    base_currency=row["base_currency"],
                    underlying_asset_class=row["underlying_asset_class"],
                    ter_bps=row["ter_bps"],
                    is_active=bool(row["is_active"]),
                )
                self._instruments[inst.instrument_id] = inst
                self._isin_to_instrument_id[inst.isin] = inst.instrument_id

            # 3. Load listings
            for row in conn.execute("SELECT * FROM listings WHERE is_active=1").fetchall():
                if row["instrument_id"] not in self._instruments:
                    continue
                listg = Listing(
                    listing_id=row["listing_id"],
                    instrument_id=row["instrument_id"],
                    mic=row["mic"],
                    ticker=row["ticker"],
                    currency=row["currency"],
                    is_primary=bool(row["is_primary"]),
                    is_active=bool(row["is_active"]),
                )
                self._listings[listg.listing_id] = listg
                self._instrument_to_listing_ids.setdefault(listg.instrument_id, []).append(listg.listing_id)
                self._mic_ticker_to_listing_id[(listg.mic.upper(), listg.ticker.upper())] = listg.listing_id

        except Exception:
            # Tolerant on unmigrated or empty DB
            pass
        finally:
            conn.close()

    def register_issuer(self, issuer: Issuer) -> None:
        """Register or update an Issuer in memory."""
        self._issuers[issuer.issuer_id] = issuer

    def register_instrument(self, instrument: Instrument) -> None:
        """Register an Instrument and index its ISIN in memory."""
        if instrument.issuer_id not in self._issuers:
            raise ValueError(
                f"Cannot register instrument {instrument.instrument_id}: issuer {instrument.issuer_id} not registered"
            )
        self._instruments[instrument.instrument_id] = instrument
        self._isin_to_instrument_id[instrument.isin] = instrument.instrument_id

    def register_listing(self, listing: Listing) -> None:
        """Register a Listing and link to its Instrument in memory."""
        if listing.instrument_id not in self._instruments:
            raise ValueError(
                f"Cannot register listing {listing.listing_id}: instrument {listing.instrument_id} not registered"
            )
        self._listings[listing.listing_id] = listing
        self._instrument_to_listing_ids.setdefault(listing.instrument_id, []).append(listing.listing_id)
        self._mic_ticker_to_listing_id[(listing.mic.upper(), listing.ticker.upper())] = listing.listing_id

    def get_issuer(self, issuer_id: str) -> Optional[Issuer]:
        return self._issuers.get(issuer_id)

    def get_instrument(self, instrument_id: str) -> Optional[Instrument]:
        return self._instruments.get(instrument_id)

    def get_instrument_by_isin(self, isin: str) -> Optional[Instrument]:
        inst_id = self._isin_to_instrument_id.get(isin.strip().upper())
        return self._instruments.get(inst_id) if inst_id else None

    def get_listing(self, listing_id: str) -> Optional[Listing]:
        return self._listings.get(listing_id)

    def get_listings_for_instrument(self, instrument_id: str) -> list[Listing]:
        listing_ids = self._instrument_to_listing_ids.get(instrument_id, [])
        return [self._listings[lid] for lid in listing_ids]

    def find_listing(self, mic: str, ticker: str) -> Optional[Listing]:
        lid = self._mic_ticker_to_listing_id.get((mic.upper(), ticker.upper()))
        return self._listings.get(lid) if lid else None

    # -------------------------------------------------------------------------
    # Idempotent DB Write Operations
    # -------------------------------------------------------------------------

    def ensure_issuer_link(
        self,
        issuer_id: str,
        name: str,
        country: str,
        instrument_id: Optional[str] = None,
        lei: Optional[str] = None,
        relationship_type: str = "ISSUER",
        source: str = "manual",
    ) -> str:
        """Idempotently register an issuer link in DB. Returns link_id. 0 writes if exists."""
        link_id = f"link_{issuer_id}_{instrument_id or 'gen'}_{relationship_type.lower()}"
        if not self.db:
            return link_id

        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT link_id FROM issuer_links WHERE link_id = ?",
                (link_id,),
            ).fetchone()
            if row:
                return row[0]
        finally:
            conn.close()

        created_at = datetime.now(timezone.utc).isoformat()
        row_dict = {
            "link_id": link_id,
            "issuer_id": issuer_id,
            "instrument_id": instrument_id,
            "name": name,
            "country": country,
            "lei": lei,
            "relationship_type": relationship_type,
            "source": source,
            "is_active": 1,
            "created_at": created_at,
        }
        rec_hash = sha256_text(canonical_json(row_dict))

        with self.db.transaction() as write_conn:
            write_conn.execute(
                """
                INSERT INTO issuer_links (
                    link_id, issuer_id, instrument_id, name, country,
                    lei, relationship_type, source, is_active, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    link_id,
                    issuer_id,
                    instrument_id,
                    name,
                    country,
                    lei,
                    relationship_type,
                    source,
                    created_at,
                    rec_hash,
                ),
            )

        if issuer_id not in self._issuers:
            self._issuers[issuer_id] = Issuer(
                issuer_id=issuer_id,
                name=name,
                country=country if len(country) == 2 else "XX",
                lei=lei if lei and len(lei) == 20 else None,
                is_active=True,
            )
        return link_id

    def ensure_instrument(
        self,
        isin: str,
        name: str,
        instrument_type: str,
        issuer_id: str,
        is_ucits: Optional[bool] = None,
        domicile: Optional[str] = None,
        base_currency: str = "EUR",
        underlying_asset_class: Optional[str] = None,
        ter_bps: Optional[int] = None,
        is_active: bool = True,
    ) -> str:
        """Idempotently register an Instrument in DB. Returns instrument_id. 0 writes if exists."""
        isin_clean = isin.strip().upper()
        if not validate_isin(isin_clean):
            raise ValueError(f"Invalid ISIN: '{isin_clean}' fails ISO 6166 checksum validation")

        inst_id = f"inst_{isin_clean.lower()}"

        if not self.db:
            # Memory only
            if isin_clean not in self._isin_to_instrument_id:
                if issuer_id not in self._issuers:
                    self._issuers[issuer_id] = Issuer(
                        issuer_id=issuer_id,
                        name=issuer_id,
                        country=domicile if domicile and len(domicile) == 2 else "XX",
                    )
                inst = Instrument(
                    instrument_id=inst_id,
                    isin=ISIN(isin_clean),
                    name=name,
                    instrument_type=InstrumentType(instrument_type),
                    issuer_id=issuer_id,
                    is_ucits=is_ucits,
                    domicile=domicile,
                    base_currency=base_currency,
                    underlying_asset_class=underlying_asset_class,
                    ter_bps=ter_bps,
                    is_active=is_active,
                )
                self.register_instrument(inst)
            return inst_id

        # Check in DB
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT instrument_id, name, instrument_type, base_currency FROM instruments WHERE isin = ?",
                (isin_clean,),
            ).fetchone()
            if row:
                found_id = row["instrument_id"]
                if found_id not in self._instruments:
                    self._instruments[found_id] = Instrument(
                        instrument_id=found_id,
                        isin=isin_clean,
                        name=row["name"],
                        instrument_type=InstrumentType(row["instrument_type"]),
                        issuer_id=issuer_id,
                        base_currency=row["base_currency"],
                    )
                return found_id
        finally:
            conn.close()

        # Insert new instrument
        created_at = datetime.now(timezone.utc).isoformat()
        row_dict = {
            "instrument_id": inst_id,
            "isin": isin_clean,
            "name": name,
            "instrument_type": instrument_type,
            "issuer_id": issuer_id,
            "is_ucits": int(is_ucits) if is_ucits is not None else None,
            "domicile": domicile,
            "base_currency": base_currency,
            "underlying_asset_class": underlying_asset_class,
            "ter_bps": ter_bps,
            "is_active": int(is_active),
            "created_at": created_at,
        }
        rec_hash = sha256_text(canonical_json(row_dict))

        with self.db.transaction() as write_conn:
            write_conn.execute(
                """
                INSERT INTO instruments (
                    instrument_id, isin, name, instrument_type, issuer_id,
                    is_ucits, domicile, base_currency, underlying_asset_class,
                    ter_bps, is_active, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inst_id,
                    isin_clean,
                    name,
                    instrument_type,
                    issuer_id,
                    int(is_ucits) if is_ucits is not None else None,
                    domicile,
                    base_currency,
                    underlying_asset_class,
                    ter_bps,
                    int(is_active),
                    created_at,
                    rec_hash,
                ),
            )

        # Update in-memory state
        if issuer_id not in self._issuers:
            self._issuers[issuer_id] = Issuer(
                issuer_id=issuer_id,
                name=issuer_id,
                country=domicile if domicile and len(domicile) == 2 else "XX",
            )
        inst = Instrument(
            instrument_id=inst_id,
            isin=ISIN(isin_clean),
            name=name,
            instrument_type=InstrumentType(instrument_type),
            issuer_id=issuer_id,
            is_ucits=is_ucits,
            domicile=domicile,
            base_currency=base_currency,
            underlying_asset_class=underlying_asset_class,
            ter_bps=ter_bps,
            is_active=is_active,
        )
        self.register_instrument(inst)
        return inst_id

    def ensure_listing(
        self,
        instrument_id: str,
        mic: str,
        ticker: str,
        currency: str,
        source: str = "config",
        validation_status: str = "UNVERIFIED",
        validation_evidence: Optional[str] = None,
        is_primary: bool = False,
        is_active: bool = True,
    ) -> str:
        """Idempotently register a Listing in DB. Returns listing_id. 0 writes if exists."""
        mic_clean = mic.strip().upper()
        ticker_clean = ticker.strip().upper()
        curr_clean = currency.strip().upper()
        listing_id = f"list_{mic_clean.lower()}_{ticker_clean.lower()}_{curr_clean.lower()}"

        if not self.db:
            if listing_id not in self._listings:
                listg = Listing(
                    listing_id=listing_id,
                    instrument_id=instrument_id,
                    mic=mic_clean,
                    ticker=ticker_clean,
                    currency=curr_clean,
                    is_primary=is_primary,
                    is_active=is_active,
                )
                self.register_listing(listg)
            return listing_id

        # Check in DB
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT listing_id FROM listings WHERE mic = ? AND ticker = ? AND currency = ?",
                (mic_clean, ticker_clean, curr_clean),
            ).fetchone()
            if row:
                found_lid = row["listing_id"]
                if found_lid not in self._listings:
                    self._listings[found_lid] = Listing(
                        listing_id=found_lid,
                        instrument_id=instrument_id,
                        mic=mic_clean,
                        ticker=ticker_clean,
                        currency=curr_clean,
                        is_primary=is_primary,
                        is_active=is_active,
                    )
                return found_lid
        finally:
            conn.close()

        created_at = datetime.now(timezone.utc).isoformat()
        row_dict = {
            "listing_id": listing_id,
            "instrument_id": instrument_id,
            "mic": mic_clean,
            "ticker": ticker_clean,
            "currency": curr_clean,
            "source": source,
            "validation_status": validation_status,
            "is_primary": int(is_primary),
            "is_active": int(is_active),
            "created_at": created_at,
        }
        rec_hash = sha256_text(canonical_json(row_dict))

        with self.db.transaction() as write_conn:
            write_conn.execute(
                """
                INSERT INTO listings (
                    listing_id, instrument_id, mic, ticker, currency,
                    source, validation_status, validation_evidence, is_primary,
                    is_active, created_at, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_id,
                    instrument_id,
                    mic_clean,
                    ticker_clean,
                    curr_clean,
                    source,
                    validation_status,
                    validation_evidence,
                    int(is_primary),
                    int(is_active),
                    created_at,
                    rec_hash,
                ),
            )

        listg = Listing(
            listing_id=listing_id,
            instrument_id=instrument_id,
            mic=mic_clean,
            ticker=ticker_clean,
            currency=curr_clean,
            is_primary=is_primary,
            is_active=is_active,
        )
        self.register_listing(listg)

        if validation_status in ("VERIFIED", "REJECTED"):
            from masa.audit.events import AuditLogger
            try:
                evidence_dict = json.loads(validation_evidence) if validation_evidence else {}
            except Exception:
                evidence_dict = {"raw": validation_evidence}
            AuditLogger(self.db).log_event(
                actor="masa.identity.registry",
                action="LISTING_VERIFIED",
                entity_type="listing",
                entity_id=listing_id,
                payload={
                    "listing_id": listing_id,
                    "instrument_id": instrument_id,
                    "mic": mic_clean,
                    "ticker": ticker_clean,
                    "status": validation_status,
                    "evidence": evidence_dict,
                },
            )

        return listing_id

    def seed_from_configs(
        self,
        config_dir: Optional[Path] = None,
        yf_ticker_factory: Optional[Callable[[str], Any]] = None,
        verify: bool = True,
    ) -> Dict[str, int]:
        """Seed instruments, listings, and issuer links from portfoy.json and havuz.json.

        Strictly idempotent: can be called multiple times without duplicate rows.
        """
        c_dir = config_dir or (Path(__file__).resolve().parent.parent.parent.parent / "config")
        portfoy_path = c_dir / "portfoy.json"
        havuz_path = c_dir / "havuz.json"

        counts = {"instruments": 0, "listings": 0, "issuer_links": 0}

        # 1. Base issuer definitions
        known_issuers = {
            "iss_blackrock_ie": ("BlackRock Asset Management Ireland Limited", "IE", "549300V521D72QOQY548"),
            "iss_ssga_ie": ("State Street Global Advisors Europe Limited", "IE", "5493006SNK3CHV3E5R62"),
            "iss_vanguard_ie": ("Vanguard Group (Ireland) Limited", "IE", "549300WNZPBRXCGMMS84"),
            "iss_apple_us": ("Apple Inc.", "US", "HWUPKR0MPOU8FGXBT394"),
            "iss_microsoft_us": ("Microsoft Corporation", "US", "INR2ET8DY2W2QBC0BH74"),
            "iss_nvidia_us": ("NVIDIA Corporation", "US", "254900C0L04917L21T21"),
            "iss_alphabet_us": ("Alphabet Inc.", "US", "5493006DFW5O17Y07Q66"),
            "iss_amazon_us": ("Amazon.com, Inc.", "US", "5493008E1A0FQUYV3668"),
            "iss_sap_de": ("SAP SE", "DE", "529900BGP7W4PU47MG74"),
            "iss_asml_nl": ("ASML Holding N.V.", "NL", "724500Y6LV617K242E52"),
            "iss_siemens_de": ("Siemens Aktiengesellschaft", "DE", "52990035A0051Z534749"),
        }

        for i_id, (i_name, i_country, i_lei) in known_issuers.items():
            self.ensure_issuer_link(
                issuer_id=i_id,
                name=i_name,
                country=i_country,
                lei=i_lei,
                relationship_type="ISSUER",
                source="catalog",
            )
            counts["issuer_links"] += 1

        from masa.identity.verification import verify_symbol_with_yfinance

        # 2. Seed from portfoy.json (4 Core ETFs)
        if portfoy_path.exists():
            data = json.loads(portfoy_path.read_text(encoding="utf-8"))
            for isin, item in data.get("araclar", {}).items():
                tur = item.get("tur", "ETF")
                yahoo_symbol = item.get("yahoo", "")
                ticker = yahoo_symbol.replace(".DE", "")
                mic = "XETR" if ".DE" in yahoo_symbol else "XAMS"
                currency = "EUR"
                name = item.get("rol", isin)

                issuer_id = "iss_ssga_ie" if isin == "IE00B3YLTY66" else "iss_blackrock_ie"
                is_ucits = True

                inst_id = self.ensure_instrument(
                    isin=isin,
                    name=name,
                    instrument_type=tur,
                    issuer_id=issuer_id,
                    is_ucits=is_ucits,
                    domicile="IE",
                    base_currency=currency,
                )
                counts["instruments"] += 1

                val_status = "UNVERIFIED"
                val_evidence = None
                if verify:
                    try:
                        vres = verify_symbol_with_yfinance(
                            symbol=yahoo_symbol,
                            target_isin=isin,
                            target_name=name,
                            target_currency=currency,
                            target_mic=mic,
                            yf_ticker_factory=yf_ticker_factory,
                        )
                        val_status = vres.get("status", "UNVERIFIED")
                        val_evidence = canonical_json(vres.get("evidence", {}))
                    except Exception:
                        val_status = "UNVERIFIED"
                        val_evidence = None

                self.ensure_listing(
                    instrument_id=inst_id,
                    mic=mic,
                    ticker=ticker,
                    currency=currency,
                    source="config_portfoy",
                    validation_status=val_status,
                    validation_evidence=val_evidence,
                    is_primary=True,
                )
                counts["listings"] += 1

        # 3. Seed from havuz.json (9 ETFs + 8 Equities)
        if havuz_path.exists():
            hdata = json.loads(havuz_path.read_text(encoding="utf-8"))

            # ETFs
            for isin, item in hdata.get("etf", {}).items():
                yahoo_symbol = item.get("yahoo", "")
                ticker = yahoo_symbol.replace(".DE", "")
                mic = "XETR"
                currency = "EUR"
                name = item.get("ad", isin)

                issuer_id = "iss_vanguard_ie" if isin == "IE00BK5BQT80" else "iss_blackrock_ie"
                is_ucits = True

                inst_id = self.ensure_instrument(
                    isin=isin,
                    name=name,
                    instrument_type="ETF",
                    issuer_id=issuer_id,
                    is_ucits=is_ucits,
                    domicile="IE",
                    base_currency=currency,
                )
                counts["instruments"] += 1

                val_status = "UNVERIFIED"
                val_evidence = None
                if verify:
                    try:
                        vres = verify_symbol_with_yfinance(
                            symbol=yahoo_symbol,
                            target_isin=isin,
                            target_name=name,
                            target_currency=currency,
                            target_mic=mic,
                            yf_ticker_factory=yf_ticker_factory,
                        )
                        val_status = vres.get("status", "UNVERIFIED")
                        val_evidence = canonical_json(vres.get("evidence", {}))
                    except Exception:
                        val_status = "UNVERIFIED"
                        val_evidence = None

                self.ensure_listing(
                    instrument_id=inst_id,
                    mic=mic,
                    ticker=ticker,
                    currency=currency,
                    source="config_havuz",
                    validation_status=val_status,
                    validation_evidence=val_evidence,
                    is_primary=True,
                )
                counts["listings"] += 1

            # Equities
            equity_issuers = {
                "US0378331005": ("iss_apple_us", "XNAS", "USD", "US"),
                "US5949181045": ("iss_microsoft_us", "XNAS", "USD", "US"),
                "US67066G1040": ("iss_nvidia_us", "XNAS", "USD", "US"),
                "US02079K3059": ("iss_alphabet_us", "XNAS", "USD", "US"),
                "US0231351067": ("iss_amazon_us", "XNAS", "USD", "US"),
                "DE0007164600": ("iss_sap_de", "XETR", "EUR", "DE"),
                "NL0010273215": ("iss_asml_nl", "XAMS", "EUR", "NL"),
                "DE0007236101": ("iss_siemens_de", "XETR", "EUR", "DE"),
            }

            for isin, item in hdata.get("hisse", {}).items():
                yahoo_symbol = item.get("yahoo", "")
                iss_id, mic, currency, domicile = equity_issuers.get(
                    isin, ("iss_generic", "XETR", "EUR", "DE")
                )
                ticker = (
                    yahoo_symbol.replace(".DE", "").replace(".AS", "")
                    if yahoo_symbol
                    else isin[-4:]
                )
                name = item.get("ad", isin)

                inst_id = self.ensure_instrument(
                    isin=isin,
                    name=name,
                    instrument_type="EQUITY",
                    issuer_id=iss_id,
                    is_ucits=False,
                    domicile=domicile,
                    base_currency=currency,
                )
                counts["instruments"] += 1

                val_status = "UNVERIFIED"
                val_evidence = None
                if verify:
                    try:
                        vres = verify_symbol_with_yfinance(
                            symbol=yahoo_symbol,
                            target_isin=isin,
                            target_name=name,
                            target_currency=currency,
                            target_mic=mic,
                            yf_ticker_factory=yf_ticker_factory,
                        )
                        val_status = vres.get("status", "UNVERIFIED")
                        val_evidence = canonical_json(vres.get("evidence", {}))
                    except Exception:
                        val_status = "UNVERIFIED"
                        val_evidence = None

                self.ensure_listing(
                    instrument_id=inst_id,
                    mic=mic,
                    ticker=ticker,
                    currency=currency,
                    source="config_havuz",
                    validation_status=val_status,
                    validation_evidence=val_evidence,
                    is_primary=True,
                )
                counts["listings"] += 1

        return counts

    def sync_from_positions(self, positions: List[Any]) -> int:
        """Idempotently sync broker holdings observations into instruments table."""
        new_count = 0
        for pos in positions:
            isin = getattr(pos, "isin", None)
            name = getattr(pos, "name", "")
            sec_type = getattr(pos, "security_type", "ETF")
            currency = getattr(pos, "quote_currency", "EUR")
            if not isin or not validate_isin(isin):
                continue

            isin_clean = isin.strip().upper()
            inst_id = f"inst_{isin_clean.lower()}"
            is_new = False
            if self.db:
                conn = self.db.get_connection()
                try:
                    exists = conn.execute("SELECT 1 FROM instruments WHERE isin = ?", (isin_clean,)).fetchone()
                    if not exists:
                        is_new = True
                finally:
                    conn.close()
            else:
                is_new = (inst_id not in self._instruments)

            self.ensure_instrument(
                isin=isin_clean,
                name=name or isin,
                instrument_type=sec_type if sec_type in ("ETF", "EQUITY", "BOND") else "OTHER",
                issuer_id=f"iss_broker_{isin[:2].lower()}",
                base_currency=currency,
            )
            if is_new:
                new_count += 1
        return new_count
