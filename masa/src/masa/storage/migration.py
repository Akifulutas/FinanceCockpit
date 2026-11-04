"""Database migration manager for Schema v2 to v3 transition.

Guarantees:
1. Zero Data Loss: v2 snapshots, raw objects, quotes, audit events are preserved untouched.
2. Pre-migration Online Backup: SQLite online backup + restore_drill executed before DDL.
3. Safe DDL Only: CREATE TABLE IF NOT EXISTS and CREATE TRIGGER IF NOT EXISTS only.
4. Post-migration Verification: Full integrity_report() checking hash chains and >= 33 triggers.
5. Automatic Rollback: If any verification step fails, restore_database() restores the pre-backup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from masa.audit.events import AuditLogger
from masa.pipeline import integrity_report
from masa.storage.db import DatabaseManager

logger = logging.getLogger(__name__)

SCHEMA_V3_UPGRADE_SQL = """
-- 10. INSTRUMENTS (Ekonomik menkul kıymet / pay sınıfı)
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    isin TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    is_ucits INTEGER,
    domicile TEXT,
    base_currency TEXT NOT NULL,
    underlying_asset_class TEXT,
    ter_bps INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instruments_isin ON instruments(isin);
CREATE INDEX IF NOT EXISTS idx_instruments_type ON instruments(instrument_type);
CREATE INDEX IF NOT EXISTS idx_instruments_issuer ON instruments(issuer_id);

-- 11. LISTINGS (Borsa kotasyon ve işlem hattı)
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    mic TEXT NOT NULL,
    ticker TEXT NOT NULL,
    currency TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'config',
    validation_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    validation_evidence TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    UNIQUE(mic, ticker, currency)
);
CREATE INDEX IF NOT EXISTS idx_listings_instrument ON listings(instrument_id);
CREATE INDEX IF NOT EXISTS idx_listings_mic_ticker ON listings(mic, ticker);
CREATE INDEX IF NOT EXISTS idx_listings_ticker ON listings(ticker);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(validation_status);

-- 12. ISSUER_LINKS (İhraççı tüzel kişi ve menkul kıymet bağlantıları)
CREATE TABLE IF NOT EXISTS issuer_links (
    link_id TEXT PRIMARY KEY,
    issuer_id TEXT NOT NULL,
    instrument_id TEXT REFERENCES instruments(instrument_id),
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    lei TEXT,
    relationship_type TEXT NOT NULL DEFAULT 'ISSUER',
    source TEXT NOT NULL DEFAULT 'manual',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issuer_links_issuer ON issuer_links(issuer_id);
CREATE INDEX IF NOT EXISTS idx_issuer_links_instrument ON issuer_links(instrument_id);
CREATE INDEX IF NOT EXISTS idx_issuer_links_lei ON issuer_links(lei);

-- Triggers for instruments
CREATE TRIGGER IF NOT EXISTS prevent_update_instruments BEFORE UPDATE ON instruments
BEGIN SELECT RAISE(ABORT, 'instruments degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_instruments BEFORE DELETE ON instruments
BEGIN SELECT RAISE(ABORT, 'instruments kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_instruments BEFORE INSERT ON instruments
WHEN EXISTS (SELECT 1 FROM instruments WHERE instrument_id = NEW.instrument_id) OR EXISTS (SELECT 1 FROM instruments WHERE isin = NEW.isin)
BEGIN SELECT RAISE(ABORT, 'instruments: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for listings
CREATE TRIGGER IF NOT EXISTS prevent_update_listings BEFORE UPDATE ON listings
BEGIN SELECT RAISE(ABORT, 'listings degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_listings BEFORE DELETE ON listings
BEGIN SELECT RAISE(ABORT, 'listings kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_listings BEFORE INSERT ON listings
WHEN EXISTS (SELECT 1 FROM listings WHERE listing_id = NEW.listing_id) OR EXISTS (SELECT 1 FROM listings WHERE mic = NEW.mic AND ticker = NEW.ticker AND currency = NEW.currency)
BEGIN SELECT RAISE(ABORT, 'listings: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for issuer_links
CREATE TRIGGER IF NOT EXISTS prevent_update_issuer_links BEFORE UPDATE ON issuer_links
BEGIN SELECT RAISE(ABORT, 'issuer_links degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_issuer_links BEFORE DELETE ON issuer_links
BEGIN SELECT RAISE(ABORT, 'issuer_links kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_issuer_links BEFORE INSERT ON issuer_links
WHEN EXISTS (SELECT 1 FROM issuer_links WHERE link_id = NEW.link_id)
BEGIN SELECT RAISE(ABORT, 'issuer_links: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- 13. TRANSACTION_VERSIONS
CREATE TABLE IF NOT EXISTS transaction_versions (
    version_id TEXT PRIMARY KEY,
    broker_tx_id TEXT NOT NULL,
    supersedes_id TEXT REFERENCES transaction_versions(version_id),
    version_number INTEGER NOT NULL DEFAULT 1,
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    tx_type TEXT NOT NULL,
    sub_type TEXT,
    side TEXT,
    isin TEXT,
    description TEXT,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    quantity TEXT,
    limit_price TEXT,
    status TEXT NOT NULL,
    is_cancellation INTEGER NOT NULL DEFAULT 0,
    event_time TEXT NOT NULL,
    settlement_date TEXT,
    flow_classification TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
    cost_impact TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_txv_broker_tx ON transaction_versions(broker_tx_id);
CREATE INDEX IF NOT EXISTS idx_txv_supersedes ON transaction_versions(supersedes_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_txv_unique_supersedes ON transaction_versions(supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_txv_isin ON transaction_versions(isin);
CREATE INDEX IF NOT EXISTS idx_txv_event_time ON transaction_versions(event_time);
CREATE INDEX IF NOT EXISTS idx_txv_status ON transaction_versions(status);
CREATE INDEX IF NOT EXISTS idx_txv_flow_class ON transaction_versions(flow_classification);

-- V_TRANSACTIONS_CURRENT
CREATE VIEW IF NOT EXISTS v_transactions_current AS
SELECT
    tv.version_id,
    tv.broker_tx_id,
    tv.supersedes_id,
    tv.version_number,
    tv.raw_object_id,
    tv.snapshot_id,
    tv.tx_type,
    tv.sub_type,
    tv.side,
    tv.isin,
    tv.description,
    tv.amount,
    tv.currency,
    tv.quantity,
    tv.limit_price,
    tv.status,
    tv.is_cancellation,
    tv.event_time,
    tv.settlement_date,
    tv.flow_classification,
    tv.cost_impact,
    tv.payload_json,
    tv.created_at,
    tv.record_hash
FROM transaction_versions tv
WHERE NOT EXISTS (
    SELECT 1 FROM transaction_versions child
    WHERE child.supersedes_id = tv.version_id
);

-- 14. CORPORATE_ACTIONS
CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id TEXT PRIMARY KEY,
    isin TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ratio TEXT NOT NULL,
    new_isin TEXT,
    new_ticker TEXT,
    effective_date TEXT NOT NULL,
    announcement_date TEXT,
    description TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    evidence_json TEXT,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    supersedes_id TEXT REFERENCES corporate_actions(action_id),
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_ca_isin ON corporate_actions(isin);
CREATE INDEX IF NOT EXISTS idx_ca_new_isin ON corporate_actions(new_isin);
CREATE INDEX IF NOT EXISTS idx_ca_effective_date ON corporate_actions(effective_date);
CREATE INDEX IF NOT EXISTS idx_ca_action_type ON corporate_actions(action_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ca_unique_supersedes ON corporate_actions(supersedes_id) WHERE supersedes_id IS NOT NULL;

-- 15. RECONCILIATIONS
CREATE TABLE IF NOT EXISTS reconciliations (
    reconciliation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    reconciliation_time TEXT NOT NULL,
    reconciliation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    cash_observation_id INTEGER REFERENCES cash_observations(cash_id),
    discrepancies_count INTEGER NOT NULL DEFAULT 0,
    discrepancies_json TEXT NOT NULL,
    shares_match INTEGER NOT NULL,
    cash_match INTEGER NOT NULL,
    valuation_match INTEGER NOT NULL,
    cost_basis_match INTEGER NOT NULL,
    cash_gap_eur TEXT,
    observation_lag_seconds TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_rec_run ON reconciliations(run_id);
CREATE INDEX IF NOT EXISTS idx_rec_time ON reconciliations(reconciliation_time);
CREATE INDEX IF NOT EXISTS idx_rec_status ON reconciliations(status);
CREATE INDEX IF NOT EXISTS idx_rec_type ON reconciliations(reconciliation_type);

-- Triggers for transaction_versions
CREATE TRIGGER IF NOT EXISTS prevent_update_transaction_versions BEFORE UPDATE ON transaction_versions
BEGIN SELECT RAISE(ABORT, 'transaction_versions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_transaction_versions BEFORE DELETE ON transaction_versions
BEGIN SELECT RAISE(ABORT, 'transaction_versions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_transaction_versions BEFORE INSERT ON transaction_versions
WHEN EXISTS (SELECT 1 FROM transaction_versions WHERE version_id = NEW.version_id)
  OR EXISTS (SELECT 1 FROM transaction_versions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'transaction_versions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for corporate_actions
CREATE TRIGGER IF NOT EXISTS prevent_update_corporate_actions BEFORE UPDATE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_corporate_actions BEFORE DELETE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_corporate_actions BEFORE INSERT ON corporate_actions
WHEN EXISTS (SELECT 1 FROM corporate_actions WHERE action_id = NEW.action_id)
  OR EXISTS (SELECT 1 FROM corporate_actions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'corporate_actions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for reconciliations
CREATE TRIGGER IF NOT EXISTS prevent_update_reconciliations BEFORE UPDATE ON reconciliations
BEGIN SELECT RAISE(ABORT, 'reconciliations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_reconciliations BEFORE DELETE ON reconciliations
BEGIN SELECT RAISE(ABORT, 'reconciliations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_reconciliations BEFORE INSERT ON reconciliations
WHEN EXISTS (SELECT 1 FROM reconciliations WHERE reconciliation_id = NEW.reconciliation_id)
  OR EXISTS (SELECT 1 FROM reconciliations WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'reconciliations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- 16. HOLDINGS_SETS (ETF Sepet Ustbilgisi ve Muhru)
CREATE TABLE IF NOT EXISTS holdings_sets (
    set_id TEXT PRIMARY KEY,
    isin TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    source_file TEXT NOT NULL,
    provider TEXT NOT NULL,
    total_records INTEGER NOT NULL,
    total_weight_pct TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdings_sets_isin_date ON holdings_sets(isin, as_of_date);
CREATE INDEX IF NOT EXISTS idx_holdings_sets_as_of_date ON holdings_sets(as_of_date);

-- 17. HOLDING_ITEMS (ETF Sepet Bilesenleri)
CREATE TABLE IF NOT EXISTS holding_items (
    item_id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES holdings_sets(set_id),
    constituent_isin TEXT,
    constituent_ticker TEXT,
    constituent_name TEXT NOT NULL,
    weight_pct TEXT NOT NULL,
    shares_held TEXT,
    market_value TEXT,
    currency TEXT,
    sector TEXT,
    country TEXT,
    asset_class TEXT,
    item_order INTEGER NOT NULL,
    record_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holding_items_set_id ON holding_items(set_id);
CREATE INDEX IF NOT EXISTS idx_holding_items_isin ON holding_items(constituent_isin);
CREATE INDEX IF NOT EXISTS idx_holding_items_ticker ON holding_items(constituent_ticker);
CREATE INDEX IF NOT EXISTS idx_holding_items_set_order ON holding_items(set_id, item_order);

-- Triggers for holdings_sets
CREATE TRIGGER IF NOT EXISTS prevent_update_holdings_sets BEFORE UPDATE ON holdings_sets
BEGIN SELECT RAISE(ABORT, 'holdings_sets degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_holdings_sets BEFORE DELETE ON holdings_sets
BEGIN SELECT RAISE(ABORT, 'holdings_sets kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_holdings_sets BEFORE INSERT ON holdings_sets
WHEN EXISTS (SELECT 1 FROM holdings_sets WHERE set_id = NEW.set_id)
  OR EXISTS (SELECT 1 FROM holdings_sets WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'holdings_sets: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for holding_items
CREATE TRIGGER IF NOT EXISTS prevent_update_holding_items BEFORE UPDATE ON holding_items
BEGIN SELECT RAISE(ABORT, 'holding_items degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_holding_items BEFORE DELETE ON holding_items
BEGIN SELECT RAISE(ABORT, 'holding_items kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_holding_items BEFORE INSERT ON holding_items
WHEN EXISTS (SELECT 1 FROM holding_items WHERE item_id = NEW.item_id)
  OR EXISTS (SELECT 1 FROM holding_items WHERE set_id = NEW.set_id AND item_order = NEW.item_order)
BEGIN SELECT RAISE(ABORT, 'holding_items: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- 18. THESIS_VERSIONS (Sürümlendirilmiş yatırım tezleri)
CREATE TABLE IF NOT EXISTS thesis_versions (
    version_id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    supersedes_id TEXT REFERENCES thesis_versions(version_id),
    version_number INTEGER NOT NULL DEFAULT 1,
    isin TEXT NOT NULL REFERENCES instruments(isin),
    category TEXT NOT NULL,
    horizon TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    title TEXT NOT NULL,
    one_line_summary TEXT NOT NULL,
    economic_rationale TEXT NOT NULL,
    evidence_pillars_json TEXT NOT NULL DEFAULT '[]',
    counter_arguments TEXT,
    falsification_triggers_json TEXT NOT NULL DEFAULT '[]',
    benchmark_reference TEXT NOT NULL DEFAULT 'araştırma referansı',
    sources_json TEXT NOT NULL DEFAULT '[]',
    target_allocation_pct TEXT,
    next_review_date TEXT,
    revision_rationale TEXT,
    author TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE,
    CHECK (supersedes_id IS NULL OR supersedes_id != version_id)
);
CREATE INDEX IF NOT EXISTS idx_tv_thesis_id ON thesis_versions(thesis_id);
CREATE INDEX IF NOT EXISTS idx_tv_isin ON thesis_versions(isin);
CREATE INDEX IF NOT EXISTS idx_tv_status ON thesis_versions(status);
CREATE INDEX IF NOT EXISTS idx_tv_category ON thesis_versions(category);
CREATE INDEX IF NOT EXISTS idx_tv_horizon ON thesis_versions(horizon);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tv_unique_supersedes ON thesis_versions(supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tv_unique_root ON thesis_versions(thesis_id) WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tv_thesis_version ON thesis_versions(thesis_id, version_number);

-- VIEW: v_theses_current (Her tezin en güncel uç sürümü)
CREATE VIEW IF NOT EXISTS v_theses_current AS
SELECT tv.*
FROM thesis_versions tv
WHERE NOT EXISTS (
    SELECT 1 FROM thesis_versions child
    WHERE child.supersedes_id = tv.version_id
      AND child.thesis_id = tv.thesis_id
);

-- 19. FORECAST_ENTRIES (Giriş mührüne ve modele bağlı tahmin defteri)
CREATE TABLE IF NOT EXISTS forecast_entries (
    forecast_id TEXT PRIMARY KEY,
    isin TEXT NOT NULL REFERENCES instruments(isin),
    target_date TEXT NOT NULL,
    forecast_type TEXT NOT NULL DEFAULT 'DAILY_CLOSE',
    direction TEXT NOT NULL,
    reference_price TEXT NOT NULL,
    target_price TEXT NOT NULL,
    confidence_pct TEXT NOT NULL,
    model_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_forecast_isin_target ON forecast_entries(isin, target_date);
CREATE INDEX IF NOT EXISTS idx_forecast_target_date ON forecast_entries(target_date);
CREATE INDEX IF NOT EXISTS idx_forecast_created_at ON forecast_entries(created_at);
CREATE INDEX IF NOT EXISTS idx_forecast_model ON forecast_entries(model_id);

-- 20. SETTLEMENTS (Tahmin uzlaşma ve sapma kayıtları)
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    forecast_id TEXT NOT NULL REFERENCES forecast_entries(forecast_id),
    isin TEXT NOT NULL REFERENCES instruments(isin),
    settlement_date TEXT NOT NULL,
    actual_close_price TEXT NOT NULL,
    error_eur TEXT NOT NULL,
    error_pct TEXT NOT NULL,
    direction_hit INTEGER NOT NULL,
    settled_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_settlement_forecast ON settlements(forecast_id);
CREATE INDEX IF NOT EXISTS idx_settlement_isin_date ON settlements(isin, settlement_date);
CREATE INDEX IF NOT EXISTS idx_settlement_date ON settlements(settlement_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_unique_forecast ON settlements(forecast_id);

-- VIEW: v_forecasts_unsettled (Henüz uzlaşması yapılmamış açık tahminler)
CREATE VIEW IF NOT EXISTS v_forecasts_unsettled AS
SELECT
    fe.forecast_id,
    fe.isin,
    fe.target_date,
    fe.forecast_type,
    fe.direction,
    fe.reference_price,
    fe.target_price,
    fe.confidence_pct,
    fe.model_id,
    fe.created_at,
    fe.record_hash
FROM forecast_entries fe
WHERE NOT EXISTS (
    SELECT 1 FROM settlements s
    WHERE s.forecast_id = fe.forecast_id
);

-- VIEW: v_forecast_performance (Tahmin ve uzlaşma birleşik karne görünümü)
CREATE VIEW IF NOT EXISTS v_forecast_performance AS
SELECT
    fe.forecast_id,
    fe.isin,
    fe.target_date,
    fe.forecast_type,
    fe.direction,
    fe.reference_price,
    fe.target_price,
    fe.confidence_pct,
    fe.model_id,
    fe.created_at AS forecast_created_at,
    s.settlement_id,
    s.settlement_date,
    s.actual_close_price,
    s.error_eur,
    s.error_pct,
    s.direction_hit,
    s.settled_at
FROM forecast_entries fe
JOIN settlements s ON fe.forecast_id = s.forecast_id;

-- Triggers for thesis_versions
CREATE TRIGGER IF NOT EXISTS prevent_update_thesis_versions BEFORE UPDATE ON thesis_versions
BEGIN SELECT RAISE(ABORT, 'thesis_versions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_thesis_versions BEFORE DELETE ON thesis_versions
BEGIN SELECT RAISE(ABORT, 'thesis_versions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_thesis_versions BEFORE INSERT ON thesis_versions
WHEN EXISTS (SELECT 1 FROM thesis_versions WHERE version_id = NEW.version_id)
  OR EXISTS (SELECT 1 FROM thesis_versions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'thesis_versions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for forecast_entries
CREATE TRIGGER IF NOT EXISTS prevent_update_forecast_entries BEFORE UPDATE ON forecast_entries
BEGIN SELECT RAISE(ABORT, 'forecast_entries degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_forecast_entries BEFORE DELETE ON forecast_entries
BEGIN SELECT RAISE(ABORT, 'forecast_entries kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_forecast_entries BEFORE INSERT ON forecast_entries
WHEN EXISTS (SELECT 1 FROM forecast_entries WHERE forecast_id = NEW.forecast_id)
  OR EXISTS (SELECT 1 FROM forecast_entries WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'forecast_entries: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for settlements
CREATE TRIGGER IF NOT EXISTS prevent_update_settlements BEFORE UPDATE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_settlements BEFORE DELETE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_settlements BEFORE INSERT ON settlements
WHEN EXISTS (SELECT 1 FROM settlements WHERE settlement_id = NEW.settlement_id)
  OR EXISTS (SELECT 1 FROM settlements WHERE record_hash = NEW.record_hash)
  OR EXISTS (SELECT 1 FROM settlements WHERE forecast_id = NEW.forecast_id)
BEGIN SELECT RAISE(ABORT, 'settlements: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- 21. SOURCES
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url_or_path TEXT NOT NULL,
    publisher TEXT NOT NULL,
    publication_date TEXT,
    retrieved_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_object_id TEXT REFERENCES raw_objects(raw_id),
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_publisher ON sources(publisher);
CREATE INDEX IF NOT EXISTS idx_sources_content_hash ON sources(content_sha256);

-- 22. EVIDENCE_BUNDLES
CREATE TABLE IF NOT EXISTS evidence_bundles (
    bundle_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    run_id TEXT,
    as_of_date TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT 'user',
    claims_count INTEGER NOT NULL DEFAULT 0,
    metrics_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_bundles_instrument ON evidence_bundles(instrument_id);
CREATE INDEX IF NOT EXISTS idx_bundles_as_of_date ON evidence_bundles(as_of_date);

-- 23. CLAIMS
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL REFERENCES evidence_bundles(bundle_id),
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'fact',
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    quote_verbatim TEXT NOT NULL,
    section_ref TEXT,
    page_num INTEGER,
    confidence_pct TEXT NOT NULL DEFAULT '100.00',
    verification_status TEXT NOT NULL DEFAULT 'VERIFIED',
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_claims_bundle ON claims(bundle_id);
CREATE INDEX IF NOT EXISTS idx_claims_instrument ON claims(instrument_id);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(verification_status);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);

-- 24. METRICS
CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT PRIMARY KEY,
    bundle_id TEXT REFERENCES evidence_bundles(bundle_id),
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    metric_name TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_metrics_bundle ON metrics(bundle_id);
CREATE INDEX IF NOT EXISTS idx_metrics_instrument ON metrics(instrument_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_source ON metrics(source_id);

-- VIEW: v_evidence_verified
CREATE VIEW IF NOT EXISTS v_evidence_verified AS
SELECT
    eb.bundle_id,
    eb.instrument_id,
    i.isin,
    i.name AS instrument_name,
    eb.as_of_date,
    c.claim_id,
    c.claim_text,
    c.claim_type,
    c.quote_verbatim,
    c.verification_status,
    s.source_id,
    s.source_type,
    s.title AS source_title,
    s.publisher,
    s.url_or_path
FROM evidence_bundles eb
JOIN instruments i ON eb.instrument_id = i.instrument_id
LEFT JOIN claims c ON eb.bundle_id = c.bundle_id
LEFT JOIN sources s ON c.source_id = s.source_id;

-- Triggers for sources
CREATE TRIGGER IF NOT EXISTS prevent_update_sources BEFORE UPDATE ON sources
BEGIN SELECT RAISE(ABORT, 'sources degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_sources BEFORE DELETE ON sources
BEGIN SELECT RAISE(ABORT, 'sources kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_sources BEFORE INSERT ON sources
WHEN EXISTS (SELECT 1 FROM sources WHERE source_id = NEW.source_id)
  OR EXISTS (SELECT 1 FROM sources WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'sources: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for evidence_bundles
CREATE TRIGGER IF NOT EXISTS prevent_update_evidence_bundles BEFORE UPDATE ON evidence_bundles
BEGIN SELECT RAISE(ABORT, 'evidence_bundles degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_evidence_bundles BEFORE DELETE ON evidence_bundles
BEGIN SELECT RAISE(ABORT, 'evidence_bundles kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_evidence_bundles BEFORE INSERT ON evidence_bundles
WHEN EXISTS (SELECT 1 FROM evidence_bundles WHERE bundle_id = NEW.bundle_id)
  OR EXISTS (SELECT 1 FROM evidence_bundles WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'evidence_bundles: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for claims
CREATE TRIGGER IF NOT EXISTS prevent_update_claims BEFORE UPDATE ON claims
BEGIN SELECT RAISE(ABORT, 'claims degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_claims BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'claims kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_claims BEFORE INSERT ON claims
WHEN EXISTS (SELECT 1 FROM claims WHERE claim_id = NEW.claim_id)
  OR EXISTS (SELECT 1 FROM claims WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'claims: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for metrics
CREATE TRIGGER IF NOT EXISTS prevent_update_metrics BEFORE UPDATE ON metrics
BEGIN SELECT RAISE(ABORT, 'metrics degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_metrics BEFORE DELETE ON metrics
BEGIN SELECT RAISE(ABORT, 'metrics kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_metrics BEFORE INSERT ON metrics
WHEN EXISTS (SELECT 1 FROM metrics WHERE metric_id = NEW.metric_id)
  OR EXISTS (SELECT 1 FROM metrics WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'metrics: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- 25. MODEL_REGISTRY
CREATE TABLE IF NOT EXISTS model_registry (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    access_tier TEXT NOT NULL CHECK (access_tier IN ('subscription', 'free', 'local')),
    region_compliance TEXT NOT NULL DEFAULT 'EU_COMPLIANT',
    quota_info TEXT,
    privacy_class TEXT NOT NULL DEFAULT 'confidential_anonymized' CHECK (privacy_class IN ('confidential_anonymized', 'public_data_only')),
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'access_verified', 'evaluated', 'eligible', 'paused', 'revoked')),
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_model_registry_provider ON model_registry(provider);
CREATE INDEX IF NOT EXISTS idx_model_registry_status ON model_registry(status);

-- 26. MODEL_EVALUATIONS
CREATE TABLE IF NOT EXISTS model_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES model_registry(model_id),
    eval_dataset_version TEXT NOT NULL,
    task_category TEXT NOT NULL CHECK (task_category IN ('table_extraction', 'claim_source_matching', 'flawed_report_detection', 'turkish_semantics')),
    score_pct TEXT NOT NULL,
    critical_error_passed INTEGER NOT NULL DEFAULT 0,
    is_champion INTEGER NOT NULL DEFAULT 0,
    eval_metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_model_eval_model ON model_evaluations(model_id);
CREATE INDEX IF NOT EXISTS idx_model_eval_task ON model_evaluations(task_category);
CREATE INDEX IF NOT EXISTS idx_model_eval_champion ON model_evaluations(is_champion);

-- 27. MODEL_RUNS
CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    quick_model_id TEXT NOT NULL REFERENCES model_registry(model_id),
    deep_model_id TEXT NOT NULL REFERENCES model_registry(model_id),
    route_label TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    tools_used TEXT NOT NULL,
    selection_rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('running', 'completed', 'waiting_quota', 'failed')),
    parent_run_id TEXT REFERENCES model_runs(run_id),
    created_at TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_model_runs_task ON model_runs(task_name);
CREATE INDEX IF NOT EXISTS idx_model_runs_status ON model_runs(status);

-- VIEW: v_model_champions
CREATE VIEW IF NOT EXISTS v_model_champions AS
SELECT
    me.task_category,
    me.model_id,
    mr.provider,
    mr.model_name,
    mr.access_tier,
    me.score_pct,
    me.eval_dataset_version,
    me.created_at AS evaluated_at
FROM model_evaluations me
JOIN model_registry mr ON me.model_id = mr.model_id
WHERE me.is_champion = 1 AND mr.status = 'eligible';

-- Triggers for model_registry
CREATE TRIGGER IF NOT EXISTS prevent_update_model_registry BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_registry BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_registry BEFORE INSERT ON model_registry
WHEN EXISTS (SELECT 1 FROM model_registry WHERE model_id = NEW.model_id)
  OR EXISTS (SELECT 1 FROM model_registry WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_registry: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for model_evaluations
CREATE TRIGGER IF NOT EXISTS prevent_update_model_evaluations BEFORE UPDATE ON model_evaluations
BEGIN SELECT RAISE(ABORT, 'model_evaluations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_evaluations BEFORE DELETE ON model_evaluations
BEGIN SELECT RAISE(ABORT, 'model_evaluations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_evaluations BEFORE INSERT ON model_evaluations
WHEN EXISTS (SELECT 1 FROM model_evaluations WHERE evaluation_id = NEW.evaluation_id)
  OR EXISTS (SELECT 1 FROM model_evaluations WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_evaluations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- Triggers for model_runs
CREATE TRIGGER IF NOT EXISTS prevent_update_model_runs BEFORE UPDATE ON model_runs
BEGIN SELECT RAISE(ABORT, 'model_runs degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_runs BEFORE DELETE ON model_runs
BEGIN SELECT RAISE(ABORT, 'model_runs kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_runs BEFORE INSERT ON model_runs
WHEN EXISTS (SELECT 1 FROM model_runs WHERE run_id = NEW.run_id)
  OR EXISTS (SELECT 1 FROM model_runs WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_runs: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;


"""


class MigrationResult(BaseModel):
    """Schema transition result."""
    model_config = ConfigDict(frozen=True)

    success: bool
    from_version: int
    to_version: int
    backup_path: Optional[str] = None
    manifest_path: Optional[str] = None
    trigger_count: int = 0
    integrity_ok: bool = False
    rolled_back: bool = False
    error_message: Optional[str] = None
    tables_created: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


def migrate_v2_to_v3(
    db_manager: Optional[DatabaseManager] = None,
    backup_dir: Optional[Path | str] = None,
) -> MigrationResult:
    """Migrate database from Schema v2 to Schema v3 with pre-backup and rollback guarantee."""
    mgr = db_manager or DatabaseManager()

    if not mgr.db_path.exists():
        mgr.initialize_schema()
        integ = integrity_report(mgr)
        return MigrationResult(
            success=True,
            from_version=0,
            to_version=3,
            trigger_count=integ["trigger_count"],
            integrity_ok=integ["ok"],
            tables_created=["instruments", "listings", "issuer_links", "transaction_versions", "corporate_actions", "reconciliations", "holdings_sets", "holding_items", "thesis_versions", "forecast_entries", "settlements"],
            details={"message": "Yeni veritabanı doğrudan v3 olarak başlatıldı."},
        )

    conn = mgr.get_connection()
    try:
        current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        has_tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='snapshots'"
        ).fetchone()[0]
    finally:
        conn.close()

    if not has_tables:
        mgr.initialize_schema()
        integ = integrity_report(mgr)
        return MigrationResult(
            success=True,
            from_version=0,
            to_version=3,
            trigger_count=integ["trigger_count"],
            integrity_ok=integ["ok"],
            tables_created=["instruments", "listings", "issuer_links", "transaction_versions", "corporate_actions", "reconciliations", "holdings_sets", "holding_items", "thesis_versions", "forecast_entries", "settlements"],
            details={"message": "Boş veritabanı v3 olarak başlatıldı."},
        )

    if current_version == 3:
        # Idempotently ensure IP-3 tables and triggers exist
        conn = mgr.get_connection()
        try:
            conn.executescript(SCHEMA_V3_UPGRADE_SQL)
        finally:
            conn.close()

        backfill_res = {}
        try:
            from masa.ingestion.transaction_ledger import backfill_unversioned_observations
            backfill_res = backfill_unversioned_observations(mgr)
        except Exception as exc:
            logger.warning(f"Backfill unversioned observations warning in v3: {exc}")
            backfill_res = {"warning": str(exc)}

        integ = integrity_report(mgr)
        return MigrationResult(
            success=True,
            from_version=3,
            to_version=3,
            trigger_count=integ["trigger_count"],
            integrity_ok=integ["ok"],
            tables_created=["instruments", "listings", "issuer_links", "transaction_versions", "corporate_actions", "reconciliations", "holdings_sets", "holding_items", "thesis_versions", "forecast_entries", "settlements"],
            details={"message": "Veritabanı şema v3 güncel.", "backfill": backfill_res},
        )


    if current_version != 2:
        return MigrationResult(
            success=False,
            from_version=current_version,
            to_version=3,
            error_message=f"Yalnızca şema v2'den v3'e geçiş desteklenir (bulunan sürüm: v{current_version}).",
        )

    # -------------------------------------------------------------------------
    # Adım 1: Geçiş Öncesi Online Yedek ve Prova
    # -------------------------------------------------------------------------
    import masa.backup
    from masa.config import MASA_DIR
    canonical_live_path = MASA_DIR / "var" / "private" / "masa.db"
    env_db_path = Path(os.environ["MASA_DB_PATH"]).resolve() if "MASA_DB_PATH" in os.environ else None
    try:
        mgr_resolved = mgr.db_path.resolve()
        is_live = (mgr_resolved == canonical_live_path.resolve()) or (env_db_path and mgr_resolved == env_db_path)
    except Exception:
        is_live = False

    if backup_dir is not None:
        effective_backup_dir = Path(backup_dir)
    elif is_live and os.environ.get("MASA_BACKUP_DIR"):
        effective_backup_dir = Path(os.environ["MASA_BACKUP_DIR"])
    elif is_live:
        effective_backup_dir = None
    else:
        effective_backup_dir = mgr.db_path.parent / "backups"

    old_backup_schema_ver = getattr(masa.backup, "SCHEMA_VERSION", 3)
    backup_res = None
    try:
        masa.backup.SCHEMA_VERSION = 2
        backup_res = masa.backup.create_backup(mgr, backup_dir=effective_backup_dir, run_drill=True)
    except Exception as exc:
        return MigrationResult(
            success=False,
            from_version=2,
            to_version=3,
            error_message=f"Geçiş öncesi online yedek ve prova başarısız oldu: {exc}",
        )
    finally:
        masa.backup.SCHEMA_VERSION = old_backup_schema_ver

    # -------------------------------------------------------------------------
    # Adım 2: DDL İcrası (Yalnızca CREATE TABLE/TRIGGER IF NOT EXISTS)
    # -------------------------------------------------------------------------
    try:
        conn = mgr.get_connection()
        try:
            conn.executescript(SCHEMA_V3_UPGRADE_SQL)
            conn.execute("PRAGMA user_version = 3;")
        finally:
            conn.close()
    except Exception as exc:
        # DDL hatasında yedekten geri yükleme
        logger.error(f"DDL yürütme hatası: {exc}. Otomatik rollback başlatılıyor...")
        rollback_ok = False
        old_ver = getattr(masa.backup, "SCHEMA_VERSION", 3)
        try:
            masa.backup.SCHEMA_VERSION = 2
            masa.backup.restore_database(backup_res.db_path, confirm=True, db_manager=mgr)
            rollback_ok = True
        except Exception as r_exc:
            logger.critical(f"Kritik: Otomatik rollback de başarısız oldu: {r_exc}")
        finally:
            masa.backup.SCHEMA_VERSION = old_ver

        return MigrationResult(
            success=False,
            from_version=2,
            to_version=3,
            backup_path=str(backup_res.db_path),
            manifest_path=str(backup_res.manifest_path),
            rolled_back=rollback_ok,
            error_message=f"DDL yürütme hatası: {exc} (rollback {'başarılı' if rollback_ok else 'BAŞARISIZ'})",
        )

    # -------------------------------------------------------------------------
    # Adım 3: Geçiş Sonrası Bütünlük Denetimi
    # -------------------------------------------------------------------------
    integ = integrity_report(mgr)
    integrity_passes = bool(
        integ["ok"]
        and integ["schema_version"] == 3
        and integ["trigger_count"] >= 33
        and integ["snapshot_chain_ok"]
        and integ["audit_chain_ok"]
    )

    if not integrity_passes:
        # Bütünlük kontrolü başarısız ise OTOMATİK ROLLBACK
        logger.error("Geçiş sonrası bütünlük kontrolü başarısız. Otomatik rollback yapılıyor...")
        rollback_ok = False
        old_ver = getattr(masa.backup, "SCHEMA_VERSION", 3)
        try:
            masa.backup.SCHEMA_VERSION = 2
            masa.backup.restore_database(backup_res.db_path, confirm=True, db_manager=mgr)
            rollback_ok = True
        except Exception as r_exc:
            logger.critical(f"Kritik: Otomatik rollback başarısız oldu: {r_exc}")
        finally:
            masa.backup.SCHEMA_VERSION = old_ver

        return MigrationResult(
            success=False,
            from_version=2,
            to_version=3,
            backup_path=str(backup_res.db_path),
            manifest_path=str(backup_res.manifest_path),
            rolled_back=rollback_ok,
            error_message="Geçiş sonrası bütünlük doğrulaması başarısız oldu. Veritabanı yedeğe geri döndürüldü.",
            details=integ,
        )

    # -------------------------------------------------------------------------
    # Adım 4: Başarı Denetim Olayı (Audit Event) Mühürleme
    # -------------------------------------------------------------------------
    try:
        AuditLogger(mgr).log_event(
            actor="masa.migration",
            action="MIGRATE_V2_TO_V3",
            entity_type="database",
            entity_id=str(mgr.db_path),
            payload={
                "from_version": 2,
                "to_version": 3,
                "backup_path": str(backup_res.db_path),
                "trigger_count": integ["trigger_count"],
            },
        )
    except Exception as exc:
        logger.warning(f"Geçiş denetim kaydı işlenemedi: {exc}")

    # -------------------------------------------------------------------------
    # Adım 5: Gözlem Defteri Backfill (Unversioned Observations Migration)
    # -------------------------------------------------------------------------
    backfill_details = {}
    try:
        from masa.ingestion.transaction_ledger import backfill_unversioned_observations
        backfill_details = backfill_unversioned_observations(mgr)
    except Exception as exc:
        logger.warning(f"Unversioned observations backfill uyarısı: {exc}")
        backfill_details = {"warning": str(exc)}

    # -------------------------------------------------------------------------
    # Adım 6: Konfigürasyon Varlıklarının İdempotent Şekilde Eklenmesi (Seeding)
    # -------------------------------------------------------------------------
    seed_details = {}
    try:
        from masa.identity.registry import IdentityRegistry
        registry = IdentityRegistry(db=mgr)
        seed_details = registry.seed_from_configs()
    except Exception as exc:
        logger.warning(f"Otomatik tohumlama (seeding) uyarısı: {exc}")
        seed_details = {"warning": str(exc)}

    return MigrationResult(
        success=True,
        from_version=2,
        to_version=3,
        backup_path=str(backup_res.db_path),
        manifest_path=str(backup_res.manifest_path),
        trigger_count=integ["trigger_count"],
        integrity_ok=True,
        rolled_back=False,
        tables_created=["instruments", "listings", "issuer_links", "transaction_versions", "corporate_actions", "reconciliations", "holdings_sets", "holding_items", "thesis_versions", "forecast_entries", "settlements"],
        details={"seed": seed_details, "backfill": backfill_details, "integrity": integ},
    )

