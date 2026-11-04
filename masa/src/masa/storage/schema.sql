-- ============================================================================
-- ETF YATIRIM MASASI — SQLite Semasi v3
-- Veritabani: masa/var/private/masa.db
-- Guvenlik: TRUNCATE journal, foreign_keys, recursive_triggers (REPLACE korumasi),
--           append-only tetikleyiciler, tum alanlari kapsayan SHA-256 kayit ozetleri.
-- Tum finansal degerler kayipsiz TEXT (Decimal) olarak saklanir.
-- ============================================================================

-- 1. HAM NESNELER: her sc komutunun stdout'u oldugu gibi
CREATE TABLE IF NOT EXISTS raw_objects (
    raw_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    command TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL UNIQUE,
    payload_text TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_objects_source ON raw_objects(source);
CREATE INDEX IF NOT EXISTS idx_raw_objects_retrieved ON raw_objects(retrieved_at);

-- 2. MUHURLER (zincir basliklari)
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL DEFAULT '',
    snapshot_type TEXT NOT NULL,
    collection_started_at TEXT NOT NULL,
    collection_completed_at TEXT NOT NULL,
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    source TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    quality_status TEXT NOT NULL,
    connector_version TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    curr_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_type ON snapshots(snapshot_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_run ON snapshots(run_id);

-- 3. KOTASYONLAR
CREATE TABLE IF NOT EXISTS quotes (
    quote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    isin TEXT NOT NULL,
    alias TEXT,
    currency TEXT NOT NULL,
    bid TEXT NOT NULL,
    ask TEXT NOT NULL,
    provider_mid TEXT,
    computed_mid TEXT NOT NULL,
    spread TEXT NOT NULL,
    spread_pct TEXT NOT NULL,
    quote_timestamp TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    quote_age_seconds TEXT,
    source TEXT NOT NULL,
    exchange TEXT,
    provider_outdated TEXT,
    quality_status TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotes_snapshot ON quotes(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_quotes_isin ON quotes(isin);

-- 4. POZISYON GOZLEMLERI (brokerin bildirdigi)
CREATE TABLE IF NOT EXISTS position_observations (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    isin TEXT NOT NULL,
    display_name TEXT,
    security_type TEXT,
    quantity TEXT,
    blocked_quantity TEXT,
    pending_quantity TEXT,
    unit_price_displayed TEXT,
    value_eur TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    broker_cost_basis TEXT,
    quote_timestamp TEXT,
    provider_outdated TEXT,
    observed_at TEXT,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_snapshot ON position_observations(snapshot_id);

-- 5. NAKIT GOZLEMLERI
CREATE TABLE IF NOT EXISTS cash_observations (
    cash_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    account_id_masked TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    settled_cash TEXT NOT NULL,
    unsettled_cash TEXT,
    accrued_cash TEXT,
    total_cash TEXT NOT NULL,
    buying_power TEXT,
    pending_buy_orders_amount TEXT,
    possible_taxes TEXT,
    observed_at TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cash_snapshot ON cash_observations(snapshot_id);

-- 6. ISLEM GOZLEMLERI (broker islem gecmisi)
CREATE TABLE IF NOT EXISTS transaction_observations (
    tx_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    broker_tx_id TEXT NOT NULL,
    tx_type TEXT NOT NULL,
    cash_transaction_type TEXT,
    security_transaction_type TEXT,
    side TEXT,
    isin TEXT,
    description TEXT,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    quantity TEXT,
    limit_price TEXT,
    status TEXT NOT NULL,
    is_cancellation TEXT NOT NULL,
    event_time TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_snapshot ON transaction_observations(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_tx_broker_id ON transaction_observations(broker_tx_id);

-- 7. SERI NOKTALARI (sc broker chart: fiyat / portfoy gecmisi)
CREATE TABLE IF NOT EXISTS series_points (
    point_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    raw_object_id INTEGER REFERENCES raw_objects(raw_id),
    series_key TEXT NOT NULL,
    series_kind TEXT NOT NULL,
    point_time TEXT NOT NULL,
    value TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_series_snapshot ON series_points(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_series_key ON series_points(series_key, point_time);

-- 8. DENETIM OLAYLARI
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,
    event_time TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    curr_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(event_time);

-- 9. IS KUYRUGU (degisebilir durum tablosu)
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    params_json TEXT NOT NULL,
    result_json TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

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

-- 13. TRANSACTION_VERSIONS (Surumlendirilmis ve tekillestirilmis islem defteri)
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

-- V_TRANSACTIONS_CURRENT (En guncel aktif surum gorunumu)
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

-- 14. CORPORATE_ACTIONS (Onayli kurumsal islemler)
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

-- 15. RECONCILIATIONS (4 boyutlu mutabakat kayitlari)
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

-- 21. SOURCES (Araştırma ve kanıt kaynakları)
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

-- 22. EVIDENCE_BUNDLES (Enstrüman bazlı kanıt paketleri)
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

-- 23. CLAIMS (Kanıt paketi iddiaları ve doğrulanmış alıntılar)
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

-- 24. METRICS (Doğrulanmış finansal gösterge ve ölçümler)
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

-- 25. MODEL_REGISTRY (Kayıtlı modeller, erişim katmanı ve gizlilik sınıfı)
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

-- 26. MODEL_EVALUATIONS (Model doğrulama testleri ve karne skorları)
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

-- 27. MODEL_RUNS (Model çalıştırma manifestoları ve kota izleme)
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

-- VIEW: v_evidence_verified (Doğrulanmış araştırma iddiaları ve kaynak eşleştirmesi)
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

-- ============================================================================
-- DEGISMEZLIK TETIKLEYICILERI
-- UPDATE/DELETE engeli + mevcut anahtarin uzerine INSERT (REPLACE/UPSERT) engeli.
-- recursive_triggers=ON oldugunda REPLACE'in ortulu silmesi de DELETE tetikleyicisine takilir.
-- ============================================================================

-- raw_objects
CREATE TRIGGER IF NOT EXISTS prevent_update_raw_objects BEFORE UPDATE ON raw_objects
BEGIN SELECT RAISE(ABORT, 'raw_objects degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_raw_objects BEFORE DELETE ON raw_objects
BEGIN SELECT RAISE(ABORT, 'raw_objects kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_raw_objects BEFORE INSERT ON raw_objects
WHEN EXISTS (SELECT 1 FROM raw_objects WHERE raw_id = NEW.raw_id) OR EXISTS (SELECT 1 FROM raw_objects WHERE payload_sha256 = NEW.payload_sha256)
BEGIN SELECT RAISE(ABORT, 'raw_objects: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- snapshots
CREATE TRIGGER IF NOT EXISTS prevent_update_snapshots BEFORE UPDATE ON snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_snapshots BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'snapshots kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_snapshots BEFORE INSERT ON snapshots
WHEN EXISTS (SELECT 1 FROM snapshots WHERE snapshot_id = NEW.snapshot_id) OR EXISTS (SELECT 1 FROM snapshots WHERE curr_hash = NEW.curr_hash)
BEGIN SELECT RAISE(ABORT, 'snapshots: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- quotes
CREATE TRIGGER IF NOT EXISTS prevent_update_quotes BEFORE UPDATE ON quotes
BEGIN SELECT RAISE(ABORT, 'quotes degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_quotes BEFORE DELETE ON quotes
BEGIN SELECT RAISE(ABORT, 'quotes kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_quotes BEFORE INSERT ON quotes
WHEN EXISTS (SELECT 1 FROM quotes WHERE quote_id = NEW.quote_id)
BEGIN SELECT RAISE(ABORT, 'quotes: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- position_observations
CREATE TRIGGER IF NOT EXISTS prevent_update_position_observations BEFORE UPDATE ON position_observations
BEGIN SELECT RAISE(ABORT, 'position_observations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_position_observations BEFORE DELETE ON position_observations
BEGIN SELECT RAISE(ABORT, 'position_observations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_position_observations BEFORE INSERT ON position_observations
WHEN EXISTS (SELECT 1 FROM position_observations WHERE position_id = NEW.position_id)
BEGIN SELECT RAISE(ABORT, 'position_observations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- cash_observations
CREATE TRIGGER IF NOT EXISTS prevent_update_cash_observations BEFORE UPDATE ON cash_observations
BEGIN SELECT RAISE(ABORT, 'cash_observations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_cash_observations BEFORE DELETE ON cash_observations
BEGIN SELECT RAISE(ABORT, 'cash_observations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_cash_observations BEFORE INSERT ON cash_observations
WHEN EXISTS (SELECT 1 FROM cash_observations WHERE cash_id = NEW.cash_id)
BEGIN SELECT RAISE(ABORT, 'cash_observations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- transaction_observations
CREATE TRIGGER IF NOT EXISTS prevent_update_transaction_observations BEFORE UPDATE ON transaction_observations
BEGIN SELECT RAISE(ABORT, 'transaction_observations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_transaction_observations BEFORE DELETE ON transaction_observations
BEGIN SELECT RAISE(ABORT, 'transaction_observations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_transaction_observations BEFORE INSERT ON transaction_observations
WHEN EXISTS (SELECT 1 FROM transaction_observations WHERE tx_row_id = NEW.tx_row_id)
BEGIN SELECT RAISE(ABORT, 'transaction_observations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- series_points
CREATE TRIGGER IF NOT EXISTS prevent_update_series_points BEFORE UPDATE ON series_points
BEGIN SELECT RAISE(ABORT, 'series_points degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_series_points BEFORE DELETE ON series_points
BEGIN SELECT RAISE(ABORT, 'series_points kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_series_points BEFORE INSERT ON series_points
WHEN EXISTS (SELECT 1 FROM series_points WHERE point_id = NEW.point_id)
BEGIN SELECT RAISE(ABORT, 'series_points: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- audit_events
CREATE TRIGGER IF NOT EXISTS prevent_update_audit_events BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_audit_events BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_audit_events BEFORE INSERT ON audit_events
WHEN EXISTS (SELECT 1 FROM audit_events WHERE event_id = NEW.event_id) OR EXISTS (SELECT 1 FROM audit_events WHERE event_uuid = NEW.event_uuid) OR EXISTS (SELECT 1 FROM audit_events WHERE curr_hash = NEW.curr_hash)
BEGIN SELECT RAISE(ABORT, 'audit_events: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- instruments
CREATE TRIGGER IF NOT EXISTS prevent_update_instruments BEFORE UPDATE ON instruments
BEGIN SELECT RAISE(ABORT, 'instruments degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_instruments BEFORE DELETE ON instruments
BEGIN SELECT RAISE(ABORT, 'instruments kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_instruments BEFORE INSERT ON instruments
WHEN EXISTS (SELECT 1 FROM instruments WHERE instrument_id = NEW.instrument_id) OR EXISTS (SELECT 1 FROM instruments WHERE isin = NEW.isin)
BEGIN SELECT RAISE(ABORT, 'instruments: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- listings
CREATE TRIGGER IF NOT EXISTS prevent_update_listings BEFORE UPDATE ON listings
BEGIN SELECT RAISE(ABORT, 'listings degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_listings BEFORE DELETE ON listings
BEGIN SELECT RAISE(ABORT, 'listings kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_listings BEFORE INSERT ON listings
WHEN EXISTS (SELECT 1 FROM listings WHERE listing_id = NEW.listing_id) OR EXISTS (SELECT 1 FROM listings WHERE mic = NEW.mic AND ticker = NEW.ticker AND currency = NEW.currency)
BEGIN SELECT RAISE(ABORT, 'listings: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- issuer_links
CREATE TRIGGER IF NOT EXISTS prevent_update_issuer_links BEFORE UPDATE ON issuer_links
BEGIN SELECT RAISE(ABORT, 'issuer_links degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_issuer_links BEFORE DELETE ON issuer_links
BEGIN SELECT RAISE(ABORT, 'issuer_links kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_issuer_links BEFORE INSERT ON issuer_links
WHEN EXISTS (SELECT 1 FROM issuer_links WHERE link_id = NEW.link_id)
BEGIN SELECT RAISE(ABORT, 'issuer_links: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- transaction_versions
CREATE TRIGGER IF NOT EXISTS prevent_update_transaction_versions BEFORE UPDATE ON transaction_versions
BEGIN SELECT RAISE(ABORT, 'transaction_versions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_transaction_versions BEFORE DELETE ON transaction_versions
BEGIN SELECT RAISE(ABORT, 'transaction_versions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_transaction_versions BEFORE INSERT ON transaction_versions
WHEN EXISTS (SELECT 1 FROM transaction_versions WHERE version_id = NEW.version_id)
  OR EXISTS (SELECT 1 FROM transaction_versions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'transaction_versions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- corporate_actions
CREATE TRIGGER IF NOT EXISTS prevent_update_corporate_actions BEFORE UPDATE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_corporate_actions BEFORE DELETE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_corporate_actions BEFORE INSERT ON corporate_actions
WHEN EXISTS (SELECT 1 FROM corporate_actions WHERE action_id = NEW.action_id)
  OR EXISTS (SELECT 1 FROM corporate_actions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'corporate_actions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- reconciliations
CREATE TRIGGER IF NOT EXISTS prevent_update_reconciliations BEFORE UPDATE ON reconciliations
BEGIN SELECT RAISE(ABORT, 'reconciliations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_reconciliations BEFORE DELETE ON reconciliations
BEGIN SELECT RAISE(ABORT, 'reconciliations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_reconciliations BEFORE INSERT ON reconciliations
WHEN EXISTS (SELECT 1 FROM reconciliations WHERE reconciliation_id = NEW.reconciliation_id)
  OR EXISTS (SELECT 1 FROM reconciliations WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'reconciliations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- holdings_sets
CREATE TRIGGER IF NOT EXISTS prevent_update_holdings_sets BEFORE UPDATE ON holdings_sets
BEGIN SELECT RAISE(ABORT, 'holdings_sets degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_holdings_sets BEFORE DELETE ON holdings_sets
BEGIN SELECT RAISE(ABORT, 'holdings_sets kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_holdings_sets BEFORE INSERT ON holdings_sets
WHEN EXISTS (SELECT 1 FROM holdings_sets WHERE set_id = NEW.set_id)
  OR EXISTS (SELECT 1 FROM holdings_sets WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'holdings_sets: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- holding_items
CREATE TRIGGER IF NOT EXISTS prevent_update_holding_items BEFORE UPDATE ON holding_items
BEGIN SELECT RAISE(ABORT, 'holding_items degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_holding_items BEFORE DELETE ON holding_items
BEGIN SELECT RAISE(ABORT, 'holding_items kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_holding_items BEFORE INSERT ON holding_items
WHEN EXISTS (SELECT 1 FROM holding_items WHERE item_id = NEW.item_id)
  OR EXISTS (SELECT 1 FROM holding_items WHERE set_id = NEW.set_id AND item_order = NEW.item_order)
BEGIN SELECT RAISE(ABORT, 'holding_items: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- thesis_versions
CREATE TRIGGER IF NOT EXISTS prevent_update_thesis_versions BEFORE UPDATE ON thesis_versions
BEGIN SELECT RAISE(ABORT, 'thesis_versions degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_thesis_versions BEFORE DELETE ON thesis_versions
BEGIN SELECT RAISE(ABORT, 'thesis_versions kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_thesis_versions BEFORE INSERT ON thesis_versions
WHEN EXISTS (SELECT 1 FROM thesis_versions WHERE version_id = NEW.version_id)
  OR EXISTS (SELECT 1 FROM thesis_versions WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'thesis_versions: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- forecast_entries
CREATE TRIGGER IF NOT EXISTS prevent_update_forecast_entries BEFORE UPDATE ON forecast_entries
BEGIN SELECT RAISE(ABORT, 'forecast_entries degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_forecast_entries BEFORE DELETE ON forecast_entries
BEGIN SELECT RAISE(ABORT, 'forecast_entries kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_forecast_entries BEFORE INSERT ON forecast_entries
WHEN EXISTS (SELECT 1 FROM forecast_entries WHERE forecast_id = NEW.forecast_id)
  OR EXISTS (SELECT 1 FROM forecast_entries WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'forecast_entries: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- settlements
CREATE TRIGGER IF NOT EXISTS prevent_update_settlements BEFORE UPDATE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_settlements BEFORE DELETE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlements kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_settlements BEFORE INSERT ON settlements
WHEN EXISTS (SELECT 1 FROM settlements WHERE settlement_id = NEW.settlement_id)
  OR EXISTS (SELECT 1 FROM settlements WHERE record_hash = NEW.record_hash)
  OR EXISTS (SELECT 1 FROM settlements WHERE forecast_id = NEW.forecast_id)
BEGIN SELECT RAISE(ABORT, 'settlements: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- sources
CREATE TRIGGER IF NOT EXISTS prevent_update_sources BEFORE UPDATE ON sources
BEGIN SELECT RAISE(ABORT, 'sources degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_sources BEFORE DELETE ON sources
BEGIN SELECT RAISE(ABORT, 'sources kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_sources BEFORE INSERT ON sources
WHEN EXISTS (SELECT 1 FROM sources WHERE source_id = NEW.source_id)
  OR EXISTS (SELECT 1 FROM sources WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'sources: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- evidence_bundles
CREATE TRIGGER IF NOT EXISTS prevent_update_evidence_bundles BEFORE UPDATE ON evidence_bundles
BEGIN SELECT RAISE(ABORT, 'evidence_bundles degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_evidence_bundles BEFORE DELETE ON evidence_bundles
BEGIN SELECT RAISE(ABORT, 'evidence_bundles kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_evidence_bundles BEFORE INSERT ON evidence_bundles
WHEN EXISTS (SELECT 1 FROM evidence_bundles WHERE bundle_id = NEW.bundle_id)
  OR EXISTS (SELECT 1 FROM evidence_bundles WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'evidence_bundles: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- claims
CREATE TRIGGER IF NOT EXISTS prevent_update_claims BEFORE UPDATE ON claims
BEGIN SELECT RAISE(ABORT, 'claims degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_claims BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'claims kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_claims BEFORE INSERT ON claims
WHEN EXISTS (SELECT 1 FROM claims WHERE claim_id = NEW.claim_id)
  OR EXISTS (SELECT 1 FROM claims WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'claims: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- metrics
CREATE TRIGGER IF NOT EXISTS prevent_update_metrics BEFORE UPDATE ON metrics
BEGIN SELECT RAISE(ABORT, 'metrics degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_metrics BEFORE DELETE ON metrics
BEGIN SELECT RAISE(ABORT, 'metrics kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_metrics BEFORE INSERT ON metrics
WHEN EXISTS (SELECT 1 FROM metrics WHERE metric_id = NEW.metric_id)
  OR EXISTS (SELECT 1 FROM metrics WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'metrics: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- model_registry
CREATE TRIGGER IF NOT EXISTS prevent_update_model_registry BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_registry BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_registry BEFORE INSERT ON model_registry
WHEN EXISTS (SELECT 1 FROM model_registry WHERE model_id = NEW.model_id)
  OR EXISTS (SELECT 1 FROM model_registry WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_registry: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- model_evaluations
CREATE TRIGGER IF NOT EXISTS prevent_update_model_evaluations BEFORE UPDATE ON model_evaluations
BEGIN SELECT RAISE(ABORT, 'model_evaluations degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_evaluations BEFORE DELETE ON model_evaluations
BEGIN SELECT RAISE(ABORT, 'model_evaluations kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_evaluations BEFORE INSERT ON model_evaluations
WHEN EXISTS (SELECT 1 FROM model_evaluations WHERE evaluation_id = NEW.evaluation_id)
  OR EXISTS (SELECT 1 FROM model_evaluations WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_evaluations: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;

-- model_runs
CREATE TRIGGER IF NOT EXISTS prevent_update_model_runs BEFORE UPDATE ON model_runs
BEGIN SELECT RAISE(ABORT, 'model_runs degistirilemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_delete_model_runs BEFORE DELETE ON model_runs
BEGIN SELECT RAISE(ABORT, 'model_runs kaydi silinemez (append-only).'); END;
CREATE TRIGGER IF NOT EXISTS prevent_overwrite_model_runs BEFORE INSERT ON model_runs
WHEN EXISTS (SELECT 1 FROM model_runs WHERE run_id = NEW.run_id)
  OR EXISTS (SELECT 1 FROM model_runs WHERE record_hash = NEW.record_hash)
BEGIN SELECT RAISE(ABORT, 'model_runs: mevcut kaydin uzerine yazma (REPLACE/UPSERT) yasak.'); END;





