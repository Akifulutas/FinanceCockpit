import Foundation
import SQLite3

private final class SQLiteConnection: @unchecked Sendable {
    var rawPointer: OpaquePointer?

    init(pointer: OpaquePointer?) {
        self.rawPointer = pointer
    }

    deinit {
        if let rawPointer = rawPointer {
            sqlite3_close(rawPointer)
        }
    }
}

public actor DatabaseService: DatabaseServiceProtocol {
    private let connection: SQLiteConnection
    public let databasePath: String

    private var db: OpaquePointer? {
        connection.rawPointer
    }

    public enum DatabaseError: Error, LocalizedError {
        case openFailed(code: Int32, message: String)
        case notConnected
        case queryFailed(query: String, error: String)

        public var errorDescription: String? {
            switch self {
            case .openFailed(let code, let msg):
                return "Database could not be opened (Error code \(code)): \(msg)"
            case .notConnected:
                return "Database connection is not open."
            case .queryFailed(let q, let err):
                return "Query error: \(q) — \(err)"
            }
        }
    }

    public init(databasePath: String = CockpitPathResolver.defaultDatabasePath) throws {
        self.databasePath = databasePath
        var dbPointer: OpaquePointer?

        // Ensure strict read-only access via SQLITE_OPEN_READONLY and URI mode=ro
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_FULLMUTEX
        let uriPath = "file:\(databasePath)?mode=ro"

        let rc = sqlite3_open_v2(uriPath, &dbPointer, flags, nil)
        guard rc == SQLITE_OK, let dbPointer else {
            let msg = dbPointer != nil ? String(cString: sqlite3_errmsg(dbPointer)) : "Unknown initialization error"
            if let dbPointer { sqlite3_close(dbPointer) }
            throw DatabaseError.openFailed(code: rc, message: msg)
        }

        self.connection = SQLiteConnection(pointer: dbPointer)

        // Configure connection pragmas
        sqlite3_exec(dbPointer, "PRAGMA foreign_keys = ON;", nil, nil, nil)
        sqlite3_exec(dbPointer, "PRAGMA busy_timeout = 5000;", nil, nil, nil)
    }

    // MARK: - Subsystem 1: Portfolio & Holdings

    public func fetchPositions() throws -> [PositionItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        WITH latest_quote_snap AS (
            SELECT run_id, snapshot_id, raw_object_id, collection_completed_at
            FROM snapshots
            WHERE snapshot_type = 'quotes' AND run_id LIKE 'run_%'
            ORDER BY rowid DESC
            LIMIT 1
        ),
        latest_portfolio_snap AS (
            SELECT snapshot_id
            FROM snapshots
            WHERE snapshot_type = 'portfolio'
            ORDER BY rowid DESC
            LIMIT 1
        )
        SELECT 
            p.isin,
            p.display_name,
            p.security_type,
            p.quantity,
            p.value_eur AS broker_valuation,
            p.broker_cost_basis,
            q.bid,
            q.ask,
            q.computed_mid,
            q.spread_pct,
            q.quality_status,
            q.quote_timestamp,
            lqs.collection_completed_at AS as_of_time
        FROM position_observations p
        CROSS JOIN latest_quote_snap lqs
        LEFT JOIN quotes q ON q.snapshot_id = lqs.snapshot_id AND q.isin = p.isin
        WHERE p.snapshot_id = (SELECT snapshot_id FROM latest_portfolio_snap)
        ORDER BY CAST(p.value_eur AS REAL) DESC;
        """

        var items: [PositionItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            let isin = stmt.columnCleanText(at: 0) ?? ""
            let name = stmt.columnCleanText(at: 1) ?? ""
            let secType = stmt.columnCleanText(at: 2) ?? "ETF"
            let qty = stmt.columnDecimal(at: 3) ?? 0
            let valuation = stmt.columnDecimal(at: 4) ?? 0
            let costBasis = stmt.columnDecimal(at: 5)
            let bid = stmt.columnDecimal(at: 6)
            let ask = stmt.columnDecimal(at: 7)
            let mid = stmt.columnDecimal(at: 8)
            let spreadPct = stmt.columnDecimal(at: 9)
            let quality = stmt.columnCleanText(at: 10) ?? "UNKNOWN"
            let quoteTime = stmt.columnCleanText(at: 11)
            let asOf = stmt.columnCleanText(at: 12)

            items.append(PositionItem(
                isin: isin,
                displayName: name,
                securityType: secType,
                quantity: qty,
                brokerValuation: valuation,
                brokerCostBasis: costBasis,
                bid: bid,
                ask: ask,
                computedMid: mid,
                spreadPct: spreadPct,
                qualityStatus: quality,
                quoteTimestamp: quoteTime,
                asOfTime: asOf
            ))
        }

        // Fallback if snapshots query returned empty
        if items.isEmpty {
            let fallbackQuery = """
            SELECT position_id, snapshot_id, isin, display_name, quantity, value_eur, currency, observed_at
            FROM position_observations
            WHERE snapshot_id = (SELECT snapshot_id FROM snapshots ORDER BY rowid DESC LIMIT 1)
            ORDER BY CAST(value_eur AS REAL) DESC;
            """
            let fallbackStmt = try SQLiteStatement(db: db, sql: fallbackQuery)
            while try fallbackStmt.step() == SQLITE_ROW {
                let isin = fallbackStmt.columnCleanText(at: 2) ?? ""
                let name = fallbackStmt.columnCleanText(at: 3) ?? ""
                let qty = fallbackStmt.columnDecimal(at: 4) ?? 0
                let val = fallbackStmt.columnDecimal(at: 5) ?? 0
                let obsAt = fallbackStmt.columnCleanText(at: 7)

                items.append(PositionItem(
                    isin: isin,
                    displayName: name,
                    securityType: "ETF",
                    quantity: qty,
                    brokerValuation: val,
                    asOfTime: obsAt
                ))
            }
        }

        return items
    }

    public func fetchCashObservations() throws -> CashObservation? {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        WITH latest_quote_snap AS (
            SELECT run_id
            FROM snapshots
            WHERE snapshot_type = 'quotes' AND run_id LIKE 'run_%'
            ORDER BY rowid DESC
            LIMIT 1
        ),
        latest_cash_snap AS (
            SELECT snapshot_id
            FROM snapshots
            WHERE snapshot_type = 'cash'
            ORDER BY rowid DESC
            LIMIT 1
        )
        SELECT 
            c.account_id_masked,
            c.currency,
            c.settled_cash,
            c.unsettled_cash,
            c.accrued_cash,
            c.total_cash,
            c.buying_power,
            c.pending_buy_orders_amount,
            c.possible_taxes,
            c.observed_at
        FROM cash_observations c
        WHERE c.snapshot_id = (SELECT snapshot_id FROM latest_cash_snap)
        LIMIT 1;
        """

        let stmt = try SQLiteStatement(db: db, sql: query)
        if try stmt.step() == SQLITE_ROW {
            return CashObservation(
                accountIdMasked: stmt.columnCleanText(at: 0) ?? "—",
                currency: stmt.columnCleanText(at: 1) ?? "EUR",
                settledCash: stmt.columnDecimal(at: 2) ?? 0,
                unsettledCash: stmt.columnDecimal(at: 3),
                accruedCash: stmt.columnDecimal(at: 4),
                totalCash: stmt.columnDecimal(at: 5) ?? 0,
                buyingPower: stmt.columnDecimal(at: 6) ?? 0,
                pendingBuyOrdersAmount: stmt.columnDecimal(at: 7),
                possibleTaxes: stmt.columnDecimal(at: 8),
                observedAt: stmt.columnCleanText(at: 9) ?? ""
            )
        }

        // Fallback: Query latest cash row directly
        let fallbackQuery = """
        SELECT account_id_masked, currency, settled_cash, unsettled_cash, accrued_cash,
               total_cash, buying_power, pending_buy_orders_amount, possible_taxes, observed_at
        FROM cash_observations
        ORDER BY cash_id DESC
        LIMIT 1;
        """
        let fallbackStmt = try SQLiteStatement(db: db, sql: fallbackQuery)
        if try fallbackStmt.step() == SQLITE_ROW {
            return CashObservation(
                accountIdMasked: fallbackStmt.columnCleanText(at: 0) ?? "—",
                currency: fallbackStmt.columnCleanText(at: 1) ?? "EUR",
                settledCash: fallbackStmt.columnDecimal(at: 2) ?? 0,
                unsettledCash: fallbackStmt.columnDecimal(at: 3),
                accruedCash: fallbackStmt.columnDecimal(at: 4),
                totalCash: fallbackStmt.columnDecimal(at: 5) ?? 0,
                buyingPower: fallbackStmt.columnDecimal(at: 6) ?? 0,
                pendingBuyOrdersAmount: fallbackStmt.columnDecimal(at: 7),
                possibleTaxes: fallbackStmt.columnDecimal(at: 8),
                observedAt: fallbackStmt.columnCleanText(at: 9) ?? ""
            )
        }

        return nil
    }

    public func fetchQuotes() throws -> [QuoteItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        WITH latest_quote_snap AS (
            SELECT snapshot_id
            FROM snapshots
            WHERE snapshot_type = 'quotes' AND run_id LIKE 'run_%'
            ORDER BY rowid DESC
            LIMIT 1
        )
        SELECT isin, bid, ask, computed_mid, spread_pct, quality_status, quote_timestamp
        FROM quotes
        WHERE snapshot_id = (SELECT snapshot_id FROM latest_quote_snap)
        ORDER BY isin ASC;
        """

        var items: [QuoteItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            let isin = stmt.columnCleanText(at: 0) ?? ""
            let bid = stmt.columnDecimal(at: 1)
            let ask = stmt.columnDecimal(at: 2)
            let mid = stmt.columnDecimal(at: 3)
            let spreadPct = stmt.columnDecimal(at: 4)
            let quality = stmt.columnCleanText(at: 5) ?? "UNKNOWN"
            let quoteTime = stmt.columnCleanText(at: 6) ?? ""

            items.append(QuoteItem(
                isin: isin,
                bid: bid,
                ask: ask,
                computedMid: mid,
                spreadPct: spreadPct,
                qualityStatus: quality,
                quoteTimestamp: quoteTime
            ))
        }
        return items
    }

    public func fetchPortfolioSummary() throws -> PortfolioSummary {
        let positions = try fetchPositions()
        let cash = try fetchCashObservations()

        let investedAssets = positions.reduce(Decimal(0)) { $0 + $1.brokerValuation }
        let totalCash = cash?.totalCash ?? 0
        let settledCash = cash?.settledCash ?? 0
        let buyingPower = cash?.buyingPower ?? 0
        let totalValue = investedAssets + totalCash
        let asOf = positions.first?.asOfTime ?? cash?.observedAt ?? ""

        return PortfolioSummary(
            totalValueEur: totalValue,
            investedAssetsEur: investedAssets,
            totalCashEur: totalCash,
            settledCashEur: settledCash,
            buyingPowerEur: buyingPower,
            positions: positions,
            cash: cash,
            asOfDate: asOf
        )
    }

    // MARK: - Subsystem 2: Daily Forecast & Settlement Engine

    public func fetchForecastEntries(targetDate: String? = nil) throws -> [ForecastEntryItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query: String
        if targetDate != nil {
            query = """
            SELECT forecast_id, isin, target_date, forecast_type, direction, reference_price,
                   target_price, confidence_pct, model_id, created_at
            FROM forecast_entries
            WHERE target_date = ?
            ORDER BY created_at DESC, isin ASC;
            """
        } else {
            query = """
            SELECT forecast_id, isin, target_date, forecast_type, direction, reference_price,
                   target_price, confidence_pct, model_id, created_at
            FROM forecast_entries
            ORDER BY target_date DESC, created_at DESC, isin ASC;
            """
        }

        let stmt = try SQLiteStatement(db: db, sql: query)
        if let targetDate = targetDate {
            try stmt.bindText(targetDate, at: 1)
        }

        var results: [ForecastEntryItem] = []
        while try stmt.step() == SQLITE_ROW {
            let fId = stmt.columnCleanText(at: 0) ?? ""
            let isin = stmt.columnCleanText(at: 1) ?? ""
            let date = stmt.columnCleanText(at: 2) ?? ""
            let fType = stmt.columnCleanText(at: 3) ?? "DAILY_CLOSE"
            let dirStr = stmt.columnCleanText(at: 4)?.uppercased() ?? "FLAT"
            let dir = ForecastDirection(rawValue: dirStr) ?? .flat
            let ref = stmt.columnDecimal(at: 5) ?? 0
            let target = stmt.columnDecimal(at: 6) ?? 0
            let conf = stmt.columnDecimal(at: 7)
            let modelId = stmt.columnCleanText(at: 8) ?? ""
            let createdAt = stmt.columnCleanText(at: 9) ?? ""

            results.append(ForecastEntryItem(
                forecastId: fId,
                isin: isin,
                targetDate: date,
                forecastType: fType,
                direction: dir,
                referencePrice: ref,
                targetPrice: target,
                confidencePct: conf,
                modelId: modelId,
                createdAt: createdAt
            ))
        }
        return results
    }

    public func fetchForecastPerformance() throws -> ForecastPerformanceSummary {
        guard let db = db else { throw DatabaseError.notConnected }

        // 1. Fetch settled performance records
        let query = """
        SELECT 
            forecast_id,
            isin,
            target_date,
            direction,
            reference_price,
            target_price,
            confidence_pct,
            model_id,
            settlement_date,
            actual_close_price,
            error_eur,
            error_pct,
            direction_hit,
            settled_at
        FROM v_forecast_performance
        ORDER BY target_date DESC, isin ASC
        LIMIT 100;
        """

        var records: [ForecastPerformanceItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        var totalHits = 0
        var totalSettled = 0
        var sumAbsErrorPct = 0.0
        var sumAbsErrorEur = 0.0

        while try stmt.step() == SQLITE_ROW {
            let fId = stmt.columnCleanText(at: 0) ?? ""
            let isin = stmt.columnCleanText(at: 1) ?? ""
            let targetDate = stmt.columnCleanText(at: 2) ?? ""
            let dirStr = stmt.columnCleanText(at: 3)?.uppercased() ?? "FLAT"
            let dir = ForecastDirection(rawValue: dirStr) ?? .flat
            let refPrice = stmt.columnDecimal(at: 4) ?? 0
            let targetPrice = stmt.columnDecimal(at: 5) ?? 0
            let conf = stmt.columnDecimal(at: 6)
            let modelId = stmt.columnCleanText(at: 7) ?? ""
            let settlementDate = stmt.columnCleanText(at: 8)
            let actualClose = stmt.columnDecimal(at: 9)
            let errorEur = stmt.columnDecimal(at: 10)
            let errorPct = stmt.columnDecimal(at: 11)
            let hit = stmt.columnBool(at: 12)
            let settledAt = stmt.columnCleanText(at: 13)

            if let hit = hit {
                totalSettled += 1
                if hit { totalHits += 1 }
            }
            if let errPct = errorPct {
                sumAbsErrorPct += abs(NSDecimalNumber(decimal: errPct).doubleValue)
            }
            if let errEur = errorEur {
                sumAbsErrorEur += abs(NSDecimalNumber(decimal: errEur).doubleValue)
            }

            records.append(ForecastPerformanceItem(
                forecastId: fId,
                isin: isin,
                targetDate: targetDate,
                direction: dir,
                referencePrice: refPrice,
                targetPrice: targetPrice,
                confidencePct: conf,
                modelId: modelId,
                settlementDate: settlementDate,
                actualClosePrice: actualClose,
                errorEur: errorEur,
                errorPct: errorPct,
                directionHit: hit,
                settledAt: settledAt
            ))
        }

        // 2. Fetch unsettled count
        var unsettledCount = 0
        let unsettledStmt = try SQLiteStatement(db: db, sql: "SELECT count(*) FROM v_forecasts_unsettled;")
        if try unsettledStmt.step() == SQLITE_ROW {
            unsettledCount = unsettledStmt.columnInt(at: 0) ?? 0
        }

        let hitRate: Double? = totalSettled > 0 ? (Double(totalHits) / Double(totalSettled)) * 100.0 : nil
        let mape: Double? = totalSettled > 0 ? sumAbsErrorPct / Double(totalSettled) : nil
        let mae: Double? = totalSettled > 0 ? sumAbsErrorEur / Double(totalSettled) : nil

        return ForecastPerformanceSummary(
            totalSettledCount: totalSettled,
            hitsCount: totalHits,
            hitRatePct: hitRate,
            mapePct: mape,
            maeEur: mae,
            martingaleFlatHitRatePct: totalSettled >= 30 ? 33.3 : nil,
            momentumHitRatePct: totalSettled >= 30 ? 45.0 : nil,
            baselineOutperformance: totalSettled >= 30 ? (hitRate ?? 0) > 45.0 : nil,
            unsettledCount: unsettledCount,
            recentRecords: records
        )
    }

    // MARK: - Subsystem 3: Research & Evidence Sealing (İP-6)

    public func fetchEvidenceBundles() throws -> [EvidenceBundleItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            bundle_id,
            instrument_id,
            isin,
            instrument_name,
            as_of_date,
            claim_id,
            claim_text,
            claim_type,
            quote_verbatim,
            verification_status,
            source_id,
            source_type,
            source_title,
            publisher,
            url_or_path
        FROM v_evidence_verified
        ORDER BY as_of_date DESC
        LIMIT 100;
        """

        var bundlesMap: [String: EvidenceBundleItem] = [:]
        let stmt = try SQLiteStatement(db: db, sql: query)

        while try stmt.step() == SQLITE_ROW {
            let bundleId = stmt.columnCleanText(at: 0) ?? ""
            let instrumentId = stmt.columnCleanText(at: 1) ?? ""
            let isin = stmt.columnCleanText(at: 2) ?? ""
            let instrumentName = stmt.columnCleanText(at: 3)
            let asOfDate = stmt.columnCleanText(at: 4) ?? ""
            let claimId = stmt.columnCleanText(at: 5) ?? ""
            let claimText = stmt.columnCleanText(at: 6) ?? ""
            let claimType = stmt.columnCleanText(at: 7) ?? "fact"
            let quoteVerbatim = stmt.columnCleanText(at: 8)
            let verificationStatus = stmt.columnCleanText(at: 9) ?? "VERIFIED"
            let sourceId = stmt.columnCleanText(at: 10)
            let sourceType = stmt.columnCleanText(at: 11)
            let sourceTitle = stmt.columnCleanText(at: 12)
            let publisher = stmt.columnCleanText(at: 13)
            let urlOrPath = stmt.columnCleanText(at: 14)

            let claim = ClaimItem(
                claimId: claimId,
                bundleId: bundleId,
                instrumentId: instrumentId,
                claimText: claimText,
                claimType: claimType,
                quoteVerbatim: quoteVerbatim,
                verificationStatus: verificationStatus,
                sourceId: sourceId,
                sourceType: sourceType,
                sourceTitle: sourceTitle,
                publisher: publisher,
                urlOrPath: urlOrPath
            )

            if let existing = bundlesMap[bundleId] {
                var claims = existing.claims
                claims.append(claim)
                bundlesMap[bundleId] = EvidenceBundleItem(
                    bundleId: existing.bundleId,
                    instrumentId: existing.instrumentId,
                    isin: existing.isin,
                    instrumentName: existing.instrumentName,
                    asOfDate: existing.asOfDate,
                    claimsCount: claims.count,
                    metricsCount: existing.metricsCount,
                    claims: claims
                )
            } else {
                bundlesMap[bundleId] = EvidenceBundleItem(
                    bundleId: bundleId,
                    instrumentId: instrumentId,
                    isin: isin,
                    instrumentName: instrumentName,
                    asOfDate: asOfDate,
                    claimsCount: 1,
                    metricsCount: 0,
                    claims: [claim]
                )
            }
        }

        return Array(bundlesMap.values).sorted(by: { $0.asOfDate > $1.asOfDate })
    }

    public func fetchSources() throws -> [SourceItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            source_id,
            source_type,
            title,
            url_or_path,
            publisher,
            publication_date,
            content_sha256
        FROM sources
        ORDER BY retrieved_at DESC;
        """

        var items: [SourceItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(SourceItem(
                sourceId: stmt.columnCleanText(at: 0) ?? "",
                sourceType: stmt.columnCleanText(at: 1) ?? "FACTSHEET",
                title: stmt.columnCleanText(at: 2) ?? "",
                urlOrPath: stmt.columnCleanText(at: 3),
                publisher: stmt.columnCleanText(at: 4),
                publicationDate: stmt.columnCleanText(at: 5),
                contentSha256: stmt.columnCleanText(at: 6)
            ))
        }
        return items
    }

    public func fetchMetrics(bundleId: String? = nil) throws -> [MetricItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        var query = """
        SELECT 
            metric_id,
            bundle_id,
            instrument_id,
            metric_name,
            value,
            unit,
            period_start,
            period_end
        FROM metrics
        """
        if bundleId != nil {
            query += " WHERE bundle_id = ?"
        }
        query += " ORDER BY created_at DESC;"

        var items: [MetricItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        if let bId = bundleId {
            try stmt.bindText(bId, at: 1)
        }
        while try stmt.step() == SQLITE_ROW {
            items.append(MetricItem(
                metricId: stmt.columnCleanText(at: 0) ?? "",
                bundleId: stmt.columnCleanText(at: 1) ?? "",
                instrumentId: stmt.columnCleanText(at: 2) ?? "",
                metricName: stmt.columnCleanText(at: 3) ?? "",
                value: stmt.columnCleanText(at: 4) ?? "",
                unit: stmt.columnCleanText(at: 5),
                periodStart: stmt.columnCleanText(at: 6),
                periodEnd: stmt.columnCleanText(at: 7)
            ))
        }
        return items
    }

    // MARK: - Subsystem 4: Model Evaluation & Registry (İP-7)

    public func fetchModelRegistry() throws -> [ModelRegistryItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            model_id,
            provider,
            model_name,
            access_tier,
            region_compliance,
            quota_info,
            privacy_class,
            status,
            last_verified_at,
            created_at
        FROM model_registry
        ORDER BY provider, model_name;
        """

        var items: [ModelRegistryItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            let mId = stmt.columnCleanText(at: 0) ?? ""
            let prov = stmt.columnCleanText(at: 1) ?? ""
            let name = stmt.columnCleanText(at: 2) ?? ""
            let tier = stmt.columnCleanText(at: 3) ?? "free"
            let reg = stmt.columnCleanText(at: 4) ?? "EU_COMPLIANT"
            let quota = stmt.columnCleanText(at: 5)
            let priv = stmt.columnCleanText(at: 6) ?? "confidential_anonymized"
            let stat = stmt.columnCleanText(at: 7) ?? "eligible"
            let verified = stmt.columnCleanText(at: 8)
            let created = stmt.columnCleanText(at: 9) ?? ""

            items.append(ModelRegistryItem(
                modelId: mId,
                provider: prov,
                modelName: name,
                accessTier: tier,
                regionCompliance: reg,
                quotaInfo: quota,
                privacyClass: priv,
                status: stat,
                lastVerifiedAt: verified,
                createdAt: created
            ))
        }
        return items
    }

    public func fetchModelChampions() throws -> [ModelChampionItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            task_category,
            model_id,
            provider,
            model_name,
            access_tier,
            score_pct,
            eval_dataset_version,
            evaluated_at
        FROM v_model_champions;
        """

        var items: [ModelChampionItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            let cat = stmt.columnCleanText(at: 0) ?? ""
            let mId = stmt.columnCleanText(at: 1) ?? ""
            let prov = stmt.columnCleanText(at: 2) ?? ""
            let name = stmt.columnCleanText(at: 3) ?? ""
            let tier = stmt.columnCleanText(at: 4) ?? "free"
            let score = stmt.columnDecimal(at: 5) ?? 0
            let ver = stmt.columnCleanText(at: 6) ?? ""
            let evalAt = stmt.columnCleanText(at: 7) ?? ""

            items.append(ModelChampionItem(
                taskCategory: cat,
                modelId: mId,
                provider: prov,
                modelName: name,
                accessTier: tier,
                scorePct: score,
                evalDatasetVersion: ver,
                evaluatedAt: evalAt
            ))
        }
        return items
    }

    public func fetchModelEvaluations() throws -> [ModelEvaluationItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            evaluation_id,
            model_id,
            task_category,
            score_pct,
            critical_error_passed,
            is_champion,
            eval_metrics_json
        FROM model_evaluations
        ORDER BY score_pct DESC;
        """

        var items: [ModelEvaluationItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(ModelEvaluationItem(
                evaluationId: stmt.columnCleanText(at: 0) ?? "",
                modelId: stmt.columnCleanText(at: 1) ?? "",
                taskCategory: stmt.columnCleanText(at: 2) ?? "",
                scorePct: stmt.columnDecimal(at: 3) ?? 0,
                criticalErrorPassed: stmt.columnBool(at: 4) ?? false,
                isChampion: stmt.columnBool(at: 5) ?? false,
                evalMetricsJson: stmt.columnCleanText(at: 6)
            ))
        }
        return items
    }

    public func fetchModelRuns() throws -> [ModelRunItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            run_id,
            task_name,
            quick_model_id,
            deep_model_id,
            route_label,
            prompt_hash,
            tools_used,
            selection_rationale,
            status
        FROM model_runs
        ORDER BY created_at DESC
        LIMIT 50;
        """

        var items: [ModelRunItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(ModelRunItem(
                runId: stmt.columnCleanText(at: 0) ?? "",
                taskName: stmt.columnCleanText(at: 1) ?? "",
                quickModelId: stmt.columnCleanText(at: 2),
                deepModelId: stmt.columnCleanText(at: 3),
                routeLabel: stmt.columnCleanText(at: 4),
                promptHash: stmt.columnCleanText(at: 5),
                toolsUsed: stmt.columnCleanText(at: 6),
                selectionRationale: stmt.columnCleanText(at: 7),
                status: stmt.columnCleanText(at: 8) ?? "completed"
            ))
        }
        return items
    }

    public func fetchTransactions() throws -> [TransactionItem] {
        try executeFetchTransactions(limit: 100, offset: 0)
    }

    public func fetchTransactions(limit: Int, offset: Int) throws -> [TransactionItem] {
        try executeFetchTransactions(limit: limit, offset: offset)
    }

    public func executeFetchTransactions(limit: Int, offset: Int) throws -> [TransactionItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        WITH latest_unversioned_obs AS (
            SELECT 
                'obs_' || tx.tx_row_id AS record_id,
                tx.broker_tx_id,
                tx.tx_type,
                tx.cash_transaction_type AS sub_type,
                tx.side,
                tx.isin,
                tx.description,
                tx.amount,
                tx.currency,
                tx.quantity,
                tx.limit_price,
                tx.status,
                tx.event_time,
                NULL AS settlement_date,
                'UNCLASSIFIED' AS flow_classification,
                NULL AS cost_impact,
                ROW_NUMBER() OVER (
                    PARTITION BY tx.broker_tx_id 
                    ORDER BY tx.rowid DESC
                ) AS rn
            FROM transaction_observations tx
            WHERE NOT EXISTS (
                SELECT 1 FROM transaction_versions tv 
                WHERE tv.broker_tx_id = tx.broker_tx_id
            )
        ),
        all_transactions AS (
            SELECT 
                tv.version_id AS record_id,
                tv.broker_tx_id,
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
                tv.event_time,
                tv.settlement_date,
                tv.flow_classification,
                tv.cost_impact
            FROM v_transactions_current tv
            UNION ALL
            SELECT 
                record_id,
                broker_tx_id,
                tx_type,
                sub_type,
                side,
                isin,
                description,
                amount,
                currency,
                quantity,
                limit_price,
                status,
                event_time,
                settlement_date,
                flow_classification,
                cost_impact
            FROM latest_unversioned_obs
            WHERE rn = 1
        )
        SELECT * FROM all_transactions
        ORDER BY event_time DESC
        LIMIT ? OFFSET ?;
        """

        var items: [TransactionItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        try stmt.bindInt(Int32(limit), at: 1)
        try stmt.bindInt(Int32(offset), at: 2)

        while try stmt.step() == SQLITE_ROW {
            let recordId = stmt.columnCleanText(at: 0) ?? ""
            let brokerId = stmt.columnCleanText(at: 1)
            let txType = stmt.columnCleanText(at: 2) ?? "BUY"
            let subType = stmt.columnCleanText(at: 3)
            let side = stmt.columnCleanText(at: 4)
            let isin = stmt.columnCleanText(at: 5)
            let desc = stmt.columnCleanText(at: 6)
            let amount = stmt.columnDecimal(at: 7) ?? 0
            let currency = stmt.columnCleanText(at: 8) ?? "EUR"
            let qty = stmt.columnDecimal(at: 9)
            let limitPrice = stmt.columnDecimal(at: 10)
            let status = stmt.columnCleanText(at: 11) ?? "SETTLED"
            let eventTime = stmt.columnCleanText(at: 12) ?? ""
            let settleDate = stmt.columnCleanText(at: 13)
            let flow = stmt.columnCleanText(at: 14) ?? "INTERNAL"
            let costImpact = stmt.columnDecimal(at: 15)

            items.append(TransactionItem(
                recordId: recordId,
                brokerTxId: brokerId,
                txType: txType,
                subType: subType,
                side: side,
                isin: isin,
                description: desc,
                amount: amount,
                currency: currency,
                quantity: qty,
                limitPrice: limitPrice,
                status: status,
                eventTime: eventTime,
                settlementDate: settleDate,
                flowClassification: flow,
                costImpact: costImpact
            ))
        }
        return items
    }

    public func fetchTransactionCount() throws -> Int {
        try executeFetchTransactionCount()
    }

    public func executeFetchTransactionCount() throws -> Int {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT (
            (SELECT COUNT(*) FROM v_transactions_current) +
            (SELECT COUNT(DISTINCT broker_tx_id) 
             FROM transaction_observations tx
             WHERE NOT EXISTS (
                 SELECT 1 FROM transaction_versions tv 
                 WHERE tv.broker_tx_id = tx.broker_tx_id
             ))
        ) AS total_count;
        """

        let stmt = try SQLiteStatement(db: db, sql: query)
        if try stmt.step() == SQLITE_ROW {
            return stmt.columnInt(at: 0) ?? 0
        }
        return 0
    }



    public func fetchCorporateActions() throws -> [CorporateActionItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            action_id,
            isin,
            action_type,
            ratio,
            new_isin,
            new_ticker,
            effective_date,
            announcement_date,
            description,
            source,
            approved_by,
            approved_at,
            created_at
        FROM corporate_actions
        ORDER BY effective_date DESC;
        """

        var items: [CorporateActionItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(CorporateActionItem(
                actionId: stmt.columnCleanText(at: 0) ?? "",
                isin: stmt.columnCleanText(at: 1) ?? "",
                actionType: stmt.columnCleanText(at: 2) ?? "SPLIT",
                ratio: stmt.columnCleanText(at: 3) ?? "1:1",
                newIsin: stmt.columnCleanText(at: 4),
                newTicker: stmt.columnCleanText(at: 5),
                effectiveDate: stmt.columnCleanText(at: 6) ?? "",
                announcementDate: stmt.columnCleanText(at: 7),
                description: stmt.columnCleanText(at: 8),
                source: stmt.columnCleanText(at: 9),
                approvedBy: stmt.columnCleanText(at: 10),
                approvedAt: stmt.columnCleanText(at: 11),
                createdAt: stmt.columnCleanText(at: 12) ?? ""
            ))
        }
        return items
    }

    public func fetchReconciliations() throws -> [ReconciliationItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            reconciliation_id,
            run_id,
            reconciliation_time,
            reconciliation_type,
            status,
            shares_match,
            cash_match,
            valuation_match,
            cost_basis_match,
            cash_gap_eur,
            observation_lag_seconds,
            discrepancies_count,
            discrepancies_json,
            notes
        FROM reconciliations
        ORDER BY reconciliation_time DESC
        LIMIT 10;
        """

        var items: [ReconciliationItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(ReconciliationItem(
                reconciliationId: stmt.columnCleanText(at: 0) ?? "",
                runId: stmt.columnCleanText(at: 1) ?? "",
                reconciliationTime: stmt.columnCleanText(at: 2) ?? "",
                reconciliationType: stmt.columnCleanText(at: 3) ?? "4WAY",
                status: stmt.columnCleanText(at: 4) ?? "RECONCILED",
                sharesMatch: stmt.columnBool(at: 5) ?? true,
                cashMatch: stmt.columnBool(at: 6) ?? true,
                valuationMatch: stmt.columnBool(at: 7) ?? true,
                costBasisMatch: stmt.columnBool(at: 8) ?? true,
                cashGapEur: stmt.columnDecimal(at: 9),
                observationLagSeconds: stmt.columnInt(at: 10),
                discrepanciesCount: stmt.columnInt(at: 11) ?? 0,
                discrepanciesJson: stmt.columnCleanText(at: 12),
                notes: stmt.columnCleanText(at: 13)
            ))
        }
        return items
    }

    // MARK: - Subsystem 6: Target Basket & Overlap (İP-4)

    public func fetchHoldingsSets() throws -> [HoldingsSetItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            s.set_id,
            s.isin,
            i.name AS fund_name,
            s.as_of_date,
            s.source_file,
            s.provider,
            s.total_records,
            s.total_weight_pct,
            s.created_at
        FROM holdings_sets s
        LEFT JOIN instruments i ON s.isin = i.isin
        ORDER BY s.as_of_date DESC;
        """

        var items: [HoldingsSetItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(HoldingsSetItem(
                setId: stmt.columnCleanText(at: 0) ?? "",
                isin: stmt.columnCleanText(at: 1) ?? "",
                fundName: stmt.columnCleanText(at: 2),
                asOfDate: stmt.columnCleanText(at: 3) ?? "",
                sourceFile: stmt.columnCleanText(at: 4) ?? "",
                provider: stmt.columnCleanText(at: 5) ?? "iShares",
                totalRecords: stmt.columnInt(at: 6) ?? 0,
                totalWeightPct: stmt.columnDecimal(at: 7) ?? 100,
                createdAt: stmt.columnCleanText(at: 8) ?? ""
            ))
        }
        return items
    }

    public func fetchHoldingConstituents(setId: String) throws -> [HoldingConstituentItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            item_id,
            constituent_isin,
            constituent_ticker,
            constituent_name,
            weight_pct,
            shares_held,
            market_value,
            currency,
            sector,
            country,
            asset_class,
            item_order
        FROM holding_items
        WHERE set_id = ?
        ORDER BY item_order ASC;
        """

        var items: [HoldingConstituentItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        try stmt.bindText(setId, at: 1)
        while try stmt.step() == SQLITE_ROW {
            items.append(HoldingConstituentItem(
                itemId: stmt.columnCleanText(at: 0) ?? "",
                setId: setId,
                constituentIsin: stmt.columnCleanText(at: 1),
                constituentTicker: stmt.columnCleanText(at: 2),
                constituentName: stmt.columnCleanText(at: 3) ?? "",
                weightPct: stmt.columnDecimal(at: 4) ?? 0,
                sharesHeld: stmt.columnDecimal(at: 5),
                marketValue: stmt.columnDecimal(at: 6),
                currency: stmt.columnCleanText(at: 7),
                sector: stmt.columnCleanText(at: 8),
                country: stmt.columnCleanText(at: 9),
                assetClass: stmt.columnCleanText(at: 10),
                itemOrder: stmt.columnInt(at: 11) ?? 0
            ))
        }
        return items
    }

    public func fetchHoldingsOverlap() throws -> HoldingsOverlapData {
        let sets = try fetchHoldingsSets()
        if sets.isEmpty {
            return HoldingsOverlapData(sets: [], overlapMatrix: [:], topConsolidatedHoldings: [])
        }

        var setConstituents: [String: [HoldingConstituentItem]] = [:]
        for set in sets {
            setConstituents[set.setId] = try fetchHoldingConstituents(setId: set.setId)
        }

        // Compute pairwise overlap matrix: sum(min(wA, wB))
        var matrix: [String: [String: Double]] = [:]
        for setA in sets {
            matrix[setA.isin] = [:]
            let itemsA = setConstituents[setA.setId] ?? []
            var weightsA: [String: Double] = [:]
            for item in itemsA {
                let key = item.constituentIsin ?? item.constituentName
                weightsA[key] = NSDecimalNumber(decimal: item.weightPct).doubleValue
            }

            for setB in sets {
                if setA.setId == setB.setId {
                    matrix[setA.isin]?[setB.isin] = 100.0
                    continue
                }
                let itemsB = setConstituents[setB.setId] ?? []
                var overlapSum = 0.0
                for itemB in itemsB {
                    let key = itemB.constituentIsin ?? itemB.constituentName
                    if let wA = weightsA[key] {
                        let wB = NSDecimalNumber(decimal: itemB.weightPct).doubleValue
                        overlapSum += min(wA, wB)
                    }
                }
                matrix[setA.isin]?[setB.isin] = overlapSum
            }
        }

        // Compute top consolidated holdings
        var consolidated: [String: (name: String, ticker: String?, isin: String?, totalWeight: Double, sector: String?, country: String?, funds: Set<String>)] = [:]
        for set in sets {
            let items = setConstituents[set.setId] ?? []
            for item in items {
                let key = item.constituentIsin ?? item.constituentName
                let w = NSDecimalNumber(decimal: item.weightPct).doubleValue
                if var existing = consolidated[key] {
                    existing.totalWeight += w
                    existing.funds.insert(set.isin)
                    consolidated[key] = existing
                } else {
                    consolidated[key] = (
                        name: item.constituentName,
                        ticker: item.constituentTicker,
                        isin: item.constituentIsin,
                        totalWeight: w,
                        sector: item.sector,
                        country: item.country,
                        funds: [set.isin]
                    )
                }
            }
        }

        let topHoldings = consolidated.values
            .sorted(by: { $0.totalWeight > $1.totalWeight })
            .prefix(25)
            .map { item in
                ConsolidatedHoldingItem(
                    constituentName: item.name,
                    ticker: item.ticker,
                    constituentIsin: item.isin,
                    consolidatedWeightPct: item.totalWeight,
                    sector: item.sector,
                    country: item.country,
                    contributingFunds: Array(item.funds).sorted()
                )
            }

        return HoldingsOverlapData(
            sets: sets,
            overlapMatrix: matrix,
            topConsolidatedHoldings: topHoldings
        )
    }

    // MARK: - Subsystem 7: Thesis Management (İP-5)

    public func fetchTheses() throws -> [ThesisItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            tv.version_id,
            tv.thesis_id,
            tv.version_number,
            tv.isin,
            i.name AS instrument_name,
            tv.category,
            tv.horizon,
            tv.status,
            tv.title,
            tv.one_line_summary,
            tv.economic_rationale,
            tv.evidence_pillars_json,
            tv.counter_arguments,
            tv.falsification_triggers_json,
            tv.benchmark_reference,
            tv.sources_json,
            tv.target_allocation_pct,
            tv.next_review_date,
            tv.revision_rationale,
            tv.author,
            tv.created_at
        FROM v_theses_current tv
        LEFT JOIN instruments i ON tv.isin = i.isin
        ORDER BY tv.created_at DESC;
        """

        var items: [ThesisItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            let vId = stmt.columnCleanText(at: 0) ?? ""
            let tId = stmt.columnCleanText(at: 1) ?? ""
            let vNum = stmt.columnInt(at: 2) ?? 1
            let isin = stmt.columnCleanText(at: 3) ?? ""
            let instName = stmt.columnCleanText(at: 4)
            let cat = stmt.columnCleanText(at: 5) ?? "CORE"
            let hor = stmt.columnCleanText(at: 6) ?? "LONG_TERM"
            let stat = stmt.columnCleanText(at: 7) ?? "ACTIVE"
            let title = stmt.columnCleanText(at: 8) ?? ""
            let summary = stmt.columnCleanText(at: 9) ?? ""
            let rationale = stmt.columnCleanText(at: 10) ?? ""
            let pillarsJson = stmt.columnCleanText(at: 11)
            let counter = stmt.columnCleanText(at: 12)
            let triggersJson = stmt.columnCleanText(at: 13)
            let bench = stmt.columnCleanText(at: 14)
            let sourcesJson = stmt.columnCleanText(at: 15)
            let alloc = stmt.columnDecimal(at: 16)
            let reviewDate = stmt.columnCleanText(at: 17)
            let revRationale = stmt.columnCleanText(at: 18)
            let author = stmt.columnCleanText(at: 19)
            let created = stmt.columnCleanText(at: 20) ?? ""

            // Parse JSON arrays for pillars, triggers, sources
            var pillars: [String] = []
            if let json = pillarsJson, let data = json.data(using: .utf8),
               let arr = try? JSONDecoder().decode([String].self, from: data) {
                pillars = arr
            }

            var triggers: [String] = []
            if let json = triggersJson, let data = json.data(using: .utf8),
               let arr = try? JSONDecoder().decode([String].self, from: data) {
                triggers = arr
            }

            var sources: [String] = []
            if let json = sourcesJson, let data = json.data(using: .utf8),
               let arr = try? JSONDecoder().decode([String].self, from: data) {
                sources = arr
            }

            items.append(ThesisItem(
                versionId: vId,
                thesisId: tId,
                versionNumber: vNum,
                isin: isin,
                instrumentName: instName,
                category: cat,
                horizon: hor,
                status: stat,
                title: title,
                oneLineSummary: summary,
                economicRationale: rationale,
                evidencePillars: pillars,
                counterArguments: counter,
                falsificationTriggers: triggers,
                benchmarkReference: bench,
                sources: sources,
                targetAllocationPct: alloc,
                nextReviewDate: reviewDate,
                revisionRationale: revRationale,
                author: author,
                createdAt: created
            ))
        }
        return items
    }

    // MARK: - Subsystem 8: System Integrity & Security (İP-1 / İP-10)

    public func fetchAuditEvents(limit: Int = 50) throws -> [AuditEventItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            event_id,
            event_uuid,
            event_time,
            actor,
            action,
            entity_type,
            entity_id,
            payload_json,
            prev_hash,
            curr_hash
        FROM audit_events
        ORDER BY event_id DESC
        LIMIT ?;
        """

        var items: [AuditEventItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        try stmt.bindInt(Int32(limit), at: 1)
        while try stmt.step() == SQLITE_ROW {
            items.append(AuditEventItem(
                eventId: stmt.columnInt64(at: 0) ?? 0,
                eventUuid: stmt.columnCleanText(at: 1) ?? "",
                eventTime: stmt.columnCleanText(at: 2) ?? "",
                actor: stmt.columnCleanText(at: 3) ?? "",
                action: stmt.columnCleanText(at: 4) ?? "",
                entityType: stmt.columnCleanText(at: 5) ?? "",
                entityId: stmt.columnCleanText(at: 6) ?? "",
                payloadJson: stmt.columnCleanText(at: 7),
                prevHash: stmt.columnCleanText(at: 8) ?? "",
                currHash: stmt.columnCleanText(at: 9) ?? ""
            ))
        }
        return items
    }

    // MARK: - Subsystem 9: Scheduler & Jobs (İP-12)

    public func fetchJobs() throws -> [JobQueueItem] {
        guard let db = db else { throw DatabaseError.notConnected }

        let query = """
        SELECT 
            job_id,
            job_type,
            status,
            dedup_key,
            params_json,
            result_json,
            error_message,
            retry_count,
            created_at,
            started_at,
            completed_at
        FROM jobs
        ORDER BY created_at DESC
        LIMIT 50;
        """

        var items: [JobQueueItem] = []
        let stmt = try SQLiteStatement(db: db, sql: query)
        while try stmt.step() == SQLITE_ROW {
            items.append(JobQueueItem(
                jobId: stmt.columnCleanText(at: 0) ?? "",
                jobType: stmt.columnCleanText(at: 1) ?? "",
                status: stmt.columnCleanText(at: 2) ?? "QUEUED",
                dedupKey: stmt.columnCleanText(at: 3),
                paramsJson: stmt.columnCleanText(at: 4),
                resultJson: stmt.columnCleanText(at: 5),
                errorMessage: stmt.columnCleanText(at: 6),
                retryCount: stmt.columnInt(at: 7) ?? 0,
                createdAt: stmt.columnCleanText(at: 8) ?? "",
                startedAt: stmt.columnCleanText(at: 9),
                completedAt: stmt.columnCleanText(at: 10)
            ))
        }
        return items
    }

    public func fetchLastHistorySnapshotTimestamp() throws -> Date? {
        guard let db = db else { throw DatabaseError.notConnected }
        let query = "SELECT max(created_at) FROM snapshots WHERE snapshot_type = 'series';"
        let stmt = try SQLiteStatement(db: db, sql: query)
        if try stmt.step() == SQLITE_ROW {
            if let dateStr = stmt.columnCleanText(at: 0), !dateStr.isEmpty {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                if let date = formatter.date(from: dateStr) {
                    return date
                }
                let fallbackFormatter = ISO8601DateFormatter()
                return fallbackFormatter.date(from: dateStr)
            }
        }
        return nil
    }
}

/// Safe fallback database service used when SQLite file is unreachable or cannot be opened.
public final class FallbackDatabaseService: DatabaseServiceProtocol, @unchecked Sendable {
    public init() {}

    public func fetchPortfolioSummary() async throws -> PortfolioSummary {
        PortfolioSummary(
            totalValueEur: 0,
            investedAssetsEur: 0,
            totalCashEur: 0,
            settledCashEur: 0,
            buyingPowerEur: 0,
            positions: [],
            cash: nil,
            asOfDate: "N/A"
        )
    }

    public func fetchPositions() async throws -> [PositionItem] { [] }
    public func fetchCashObservations() async throws -> CashObservation? { nil }
    public func fetchQuotes() async throws -> [QuoteItem] { [] }
    public func fetchForecastEntries(targetDate: String?) async throws -> [ForecastEntryItem] { [] }
    public func fetchForecastPerformance() async throws -> ForecastPerformanceSummary {
        ForecastPerformanceSummary(
            totalSettledCount: 0,
            hitsCount: 0
        )
    }
    public func fetchEvidenceBundles() async throws -> [EvidenceBundleItem] { [] }
    public func fetchSources() async throws -> [SourceItem] { [] }
    public func fetchMetrics(bundleId: String?) async throws -> [MetricItem] { [] }
    public func fetchModelRegistry() async throws -> [ModelRegistryItem] { [] }
    public func fetchModelChampions() async throws -> [ModelChampionItem] { [] }
    public func fetchModelEvaluations() async throws -> [ModelEvaluationItem] { [] }
    public func fetchModelRuns() async throws -> [ModelRunItem] { [] }
    public func fetchTransactions() async throws -> [TransactionItem] { [] }
    public func fetchCorporateActions() async throws -> [CorporateActionItem] { [] }
    public func fetchReconciliations() async throws -> [ReconciliationItem] { [] }
    public func fetchHoldingsSets() async throws -> [HoldingsSetItem] { [] }
    public func fetchHoldingConstituents(setId: String) async throws -> [HoldingConstituentItem] { [] }
    public func fetchHoldingsOverlap() async throws -> HoldingsOverlapData {
        HoldingsOverlapData(
            sets: [],
            overlapMatrix: [:],
            topConsolidatedHoldings: []
        )
    }
    public func fetchTheses() async throws -> [ThesisItem] { [] }
    public func fetchAuditEvents(limit: Int) async throws -> [AuditEventItem] { [] }
    public func fetchJobs() async throws -> [JobQueueItem] { [] }
    public func fetchLastHistorySnapshotTimestamp() async throws -> Date? { nil }
}

extension DatabaseServiceProtocol {
    public func fetchTransactions(limit: Int, offset: Int) async throws -> [TransactionItem] {
        if let ds = self as? DatabaseService {
            return try await ds.executeFetchTransactions(limit: limit, offset: offset)
        }
        let all = try await fetchTransactions()
        if offset >= all.count { return [] }
        return Array(all.dropFirst(offset).prefix(limit))
    }

    public func fetchTransactionCount() async throws -> Int {
        if let ds = self as? DatabaseService {
            return try await ds.executeFetchTransactionCount()
        }
        return try await fetchTransactions().count
    }
}


