import Foundation
@testable import FinanceCockpit

public final class MockDatabaseService: DatabaseServiceProtocol, @unchecked Sendable {
    public var mockPositions: [PositionItem] = []
    public var mockCash: CashObservation?
    public var mockQuotes: [QuoteItem] = []
    public var mockPortfolioSummary: PortfolioSummary?
    public var mockForecastEntries: [ForecastEntryItem] = []
    public var mockForecastPerformance: ForecastPerformanceSummary?
    public var mockEvidenceBundles: [EvidenceBundleItem] = []
    public var mockSources: [SourceItem] = []
    public var mockMetrics: [MetricItem] = []
    public var mockModelRegistry: [ModelRegistryItem] = []
    public var mockModelChampions: [ModelChampionItem] = []
    public var mockModelEvaluations: [ModelEvaluationItem] = []
    public var mockModelRuns: [ModelRunItem] = []
    public var mockTransactions: [TransactionItem] = []
    public var mockCorporateActions: [CorporateActionItem] = []
    public var mockReconciliations: [ReconciliationItem] = []
    public var mockHoldingsSets: [HoldingsSetItem] = []
    public var mockConstituents: [String: [HoldingConstituentItem]] = [:]
    public var mockHoldingsOverlap: HoldingsOverlapData?
    public var mockTheses: [ThesisItem] = []
    public var mockAuditEvents: [AuditEventItem] = []
    public var mockJobs: [JobQueueItem] = []
    public var shouldThrowError: Bool = false

    public init() {}

    public func fetchPortfolioSummary() async throws -> PortfolioSummary {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 1, userInfo: [NSLocalizedDescriptionKey: "Mock fetchPortfolioSummary error"]) }
        if let summary = mockPortfolioSummary { return summary }
        let pos = mockPositions
        let c = mockCash
        let invested = pos.reduce(Decimal(0)) { $0 + $1.brokerValuation }
        let cashVal = c?.totalCash ?? 0
        return PortfolioSummary(
            totalValueEur: invested + cashVal,
            investedAssetsEur: invested,
            totalCashEur: cashVal,
            settledCashEur: c?.settledCash ?? 0,
            buyingPowerEur: c?.buyingPower ?? 0,
            positions: pos,
            cash: c,
            asOfDate: "2026-10-31T20:00:00Z"
        )
    }

    public func fetchPositions() async throws -> [PositionItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 2, userInfo: [NSLocalizedDescriptionKey: "Mock fetchPositions error"]) }
        return mockPositions
    }

    public func fetchCashObservations() async throws -> CashObservation? {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 3, userInfo: [NSLocalizedDescriptionKey: "Mock fetchCashObservations error"]) }
        return mockCash
    }

    public func fetchQuotes() async throws -> [QuoteItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 4, userInfo: [NSLocalizedDescriptionKey: "Mock fetchQuotes error"]) }
        return mockQuotes
    }

    public func fetchForecastEntries(targetDate: String?) async throws -> [ForecastEntryItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 5, userInfo: [NSLocalizedDescriptionKey: "Mock fetchForecastEntries error"]) }
        if let target = targetDate {
            return mockForecastEntries.filter { $0.targetDate == target }
        }
        return mockForecastEntries
    }

    public func fetchForecastPerformance() async throws -> ForecastPerformanceSummary {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 6, userInfo: [NSLocalizedDescriptionKey: "Mock fetchForecastPerformance error"]) }
        return mockForecastPerformance ?? ForecastPerformanceSummary(
            totalSettledCount: 0,
            hitsCount: 0,
            hitRatePct: nil,
            mapePct: nil,
            maeEur: nil,
            martingaleFlatHitRatePct: nil,
            momentumHitRatePct: nil,
            baselineOutperformance: nil,
            unsettledCount: 0,
            recentRecords: []
        )
    }

    public func fetchEvidenceBundles() async throws -> [EvidenceBundleItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 7, userInfo: [NSLocalizedDescriptionKey: "Mock fetchEvidenceBundles error"]) }
        return mockEvidenceBundles
    }

    public func fetchSources() async throws -> [SourceItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 8, userInfo: [NSLocalizedDescriptionKey: "Mock fetchSources error"]) }
        return mockSources
    }

    public func fetchMetrics(bundleId: String?) async throws -> [MetricItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 9, userInfo: [NSLocalizedDescriptionKey: "Mock fetchMetrics error"]) }
        if let bId = bundleId {
            return mockMetrics.filter { $0.bundleId == bId }
        }
        return mockMetrics
    }

    public func fetchModelRegistry() async throws -> [ModelRegistryItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 10, userInfo: [NSLocalizedDescriptionKey: "Mock fetchModelRegistry error"]) }
        return mockModelRegistry
    }

    public func fetchModelChampions() async throws -> [ModelChampionItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 11, userInfo: [NSLocalizedDescriptionKey: "Mock fetchModelChampions error"]) }
        return mockModelChampions
    }

    public func fetchModelEvaluations() async throws -> [ModelEvaluationItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 12, userInfo: [NSLocalizedDescriptionKey: "Mock fetchModelEvaluations error"]) }
        return mockModelEvaluations
    }

    public func fetchModelRuns() async throws -> [ModelRunItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 13, userInfo: [NSLocalizedDescriptionKey: "Mock fetchModelRuns error"]) }
        return mockModelRuns
    }

    public func fetchTransactions() async throws -> [TransactionItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 14, userInfo: [NSLocalizedDescriptionKey: "Mock fetchTransactions error"]) }
        return mockTransactions
    }

    public func fetchCorporateActions() async throws -> [CorporateActionItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 15, userInfo: [NSLocalizedDescriptionKey: "Mock fetchCorporateActions error"]) }
        return mockCorporateActions
    }

    public func fetchReconciliations() async throws -> [ReconciliationItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 16, userInfo: [NSLocalizedDescriptionKey: "Mock fetchReconciliations error"]) }
        return mockReconciliations
    }

    public func fetchHoldingsSets() async throws -> [HoldingsSetItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 17, userInfo: [NSLocalizedDescriptionKey: "Mock fetchHoldingsSets error"]) }
        return mockHoldingsSets
    }

    public func fetchHoldingConstituents(setId: String) async throws -> [HoldingConstituentItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 18, userInfo: [NSLocalizedDescriptionKey: "Mock fetchHoldingConstituents error"]) }
        return mockConstituents[setId] ?? []
    }

    public func fetchHoldingsOverlap() async throws -> HoldingsOverlapData {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 19, userInfo: [NSLocalizedDescriptionKey: "Mock fetchHoldingsOverlap error"]) }
        return mockHoldingsOverlap ?? HoldingsOverlapData(sets: mockHoldingsSets, overlapMatrix: [:], topConsolidatedHoldings: [])
    }

    public func fetchTheses() async throws -> [ThesisItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 20, userInfo: [NSLocalizedDescriptionKey: "Mock fetchTheses error"]) }
        return mockTheses
    }

    public func fetchAuditEvents(limit: Int) async throws -> [AuditEventItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 21, userInfo: [NSLocalizedDescriptionKey: "Mock fetchAuditEvents error"]) }
        return Array(mockAuditEvents.prefix(limit))
    }

    public func fetchJobs() async throws -> [JobQueueItem] {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 22, userInfo: [NSLocalizedDescriptionKey: "Mock fetchJobs error"]) }
        return mockJobs
    }
    public var mockLastHistorySnapshotTimestamp: Date? = nil

    public func fetchLastHistorySnapshotTimestamp() async throws -> Date? {
        if shouldThrowError { throw NSError(domain: "MockDB", code: 23, userInfo: [NSLocalizedDescriptionKey: "Mock fetchLastHistorySnapshotTimestamp error"]) }
        return mockLastHistorySnapshotTimestamp
    }
}

public final class MockCLIProcessRunner: CLIProcessRunnerProtocol, @unchecked Sendable {
    public var commandExecutionCount = 0
    public var lastExecutedArguments: [String] = []
    public var executedCommandsHistory: [[String]] = []
    public var shouldFail: Bool = false
    public var isSchedulerInstalled: Bool = false
    public var isScalableSessionActive: Bool = false
    public var customCommandResults: [[String]: CLIOperationResult] = [:]
    public var mockResult: CLIOperationResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "Success")
    public var mockVerifyResult: IntegrityCheckResult = IntegrityCheckResult(ok: true, fileVaultActive: true, schemaVersion: 3, triggerCount: 78)
    public var mockBackupResult: BackupResult = BackupResult(isSuccess: true, backupFilePath: "/tmp/backup.tar.gz", fileSizeBytes: 1024, sha256: "abcd1234abcd1234abcd1234abcd1234", restoreDrillOk: false)
    public var mockSecurityResult: SecurityScanResult = SecurityScanResult(isSuccess: true, permissionsOk: true, gitleaksLeaksCount: 0)

    public init() {}

    public func runVerifyIntegrity() async throws -> IntegrityCheckResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["dogrula"]
        executedCommandsHistory.append(["dogrula"])
        if shouldFail { throw NSError(domain: "MockCLI", code: 1, userInfo: [NSLocalizedDescriptionKey: "Verify failed"]) }
        return mockVerifyResult
    }

    public func runBackup(drillOnly: Bool) async throws -> BackupResult {
        commandExecutionCount += 1
        let args = drillOnly ? ["yedek", "--prova"] : ["yedek"]
        lastExecutedArguments = args
        executedCommandsHistory.append(args)
        if shouldFail { throw NSError(domain: "MockCLI", code: 2, userInfo: [NSLocalizedDescriptionKey: "Backup failed"]) }
        return mockBackupResult
    }

    public func runSecurityScan() async throws -> SecurityScanResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["guvenlik-tara"]
        executedCommandsHistory.append(["guvenlik-tara"])
        if shouldFail { throw NSError(domain: "MockCLI", code: 3, userInfo: [NSLocalizedDescriptionKey: "Security scan failed"]) }
        return mockSecurityResult
    }

    public func runForecastMorning() async throws -> CLIOperationResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["tahmin", "uret"]
        executedCommandsHistory.append(["tahmin", "uret"])
        if shouldFail {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Morning forecast failed", message: "Error")
        }
        return mockResult
    }

    public func runSettleEvening() async throws -> CLIOperationResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["tahmin", "uzlas"]
        executedCommandsHistory.append(["tahmin", "uzlas"])
        if shouldFail {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Evening settlement failed", message: "Error")
        }
        return mockResult
    }

    public func runForecastSimulation(days: Int) async throws -> CLIOperationResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["tahmin", "gecmis-simule", "--gun", "\(days)"]
        executedCommandsHistory.append(["tahmin", "gecmis-simule", "--gun", "\(days)"])
        if shouldFail {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Simulation failed", message: "Error")
        }
        return mockResult
    }

    public func runResearch(isin: String, horizon: String?) async throws -> CLIOperationResult {
        commandExecutionCount += 1
        executedCommandsHistory.append(["arastir", isin])
        return mockResult
    }

    public func runResearch(query: String?, ticker: String?) async throws -> CLIOperationResult {
        commandExecutionCount += 1
        executedCommandsHistory.append(["arastir", query ?? ticker ?? ""])
        return mockResult
    }

    public func runSchedulerAction(agent: String, action: String) async throws -> CLIOperationResult {
        commandExecutionCount += 1
        lastExecutedArguments = ["zamanla", action]
        executedCommandsHistory.append(["zamanla", action])
        if action == "kur" {
            isSchedulerInstalled = true
        } else if action == "kaldir" {
            isSchedulerInstalled = false
        }
        if shouldFail {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Scheduler action failed", message: "Error")
        }
        return mockResult
    }

    public var lastExecutedStdin: String?
    public var lastExecutedStdoutChunkHandler: (@Sendable (String) -> Void)?
    public var lastExecutedStderrChunkHandler: (@Sendable (String) -> Void)?

    public func runCommand(
        arguments: [String],
        timeoutSeconds: TimeInterval? = nil,
        stdin: String? = nil,
        onStdoutChunk: (@Sendable (String) -> Void)? = nil,
        onStderrChunk: (@Sendable (String) -> Void)? = nil
    ) async throws -> CLIOperationResult {
        commandExecutionCount += 1
        lastExecutedArguments = arguments
        executedCommandsHistory.append(arguments)
        lastExecutedStdin = stdin
        lastExecutedStdoutChunkHandler = onStdoutChunk
        lastExecutedStderrChunkHandler = onStderrChunk

        if shouldFail {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Command failed", message: "Error")
        }

        if let custom = customCommandResults[arguments] {
            if let onStdoutChunk, !custom.stdout.isEmpty {
                onStdoutChunk(custom.stdout)
            }
            if let onStderrChunk, !custom.stderr.isEmpty {
                onStderrChunk(custom.stderr)
            }
            return custom
        }

        var effectiveResult = mockResult

        if arguments == ["giris", "--login"] {
            isScalableSessionActive = true
            let text = "Giriş bağlantısı oluşturuldu. Tarayıcıda ve telefonda onay bekleniyor...\nOturum doğrulandı.\n"
            effectiveResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: text, stderr: "", message: "Success")
        } else if arguments == ["giris", "--json"] && (mockResult.stdout == "OK" || mockResult.stdout.isEmpty || isScalableSessionActive) {
            let active = isScalableSessionActive
            let json = """
            {
              "schema_version": "1.0.0",
              "active": \(active),
              "session_ok": \(active),
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": {
                "account_id": "ACC_TEST_123",
                "email": "test@example.com"
              }
            }
            """
            effectiveResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: json, stderr: "", message: "Success")
        } else if arguments == ["zamanla", "durum", "--json"] && (mockResult.stdout == "OK" || mockResult.stdout.isEmpty) {
            let installed = isSchedulerInstalled
            let json = """
            {
              "schema_version": "1.0.0",
              "agents": [
                {
                  "label": "com.etf.masa.sabah",
                  "description": "Sabah Tahmin Motoru (5 ETF + 5 Hisse)",
                  "schedule": "Pzt-Cum 09:30 CET",
                  "installed": \(installed),
                  "loaded": \(installed),
                  "last_exit_code": \(installed ? "0" : "null"),
                  "plist_path": \(installed ? "\"/Users/test/Library/LaunchAgents/com.etf.masa.sabah.plist\"" : "null"),
                  "log_lines": []
                },
                {
                  "label": "com.etf.masa.aksam",
                  "description": "Akşam Uzlaşma ve Pano Güncelleme",
                  "schedule": "Pzt-Cum 17:40 CET",
                  "installed": \(installed),
                  "loaded": \(installed),
                  "last_exit_code": \(installed ? "0" : "null"),
                  "plist_path": \(installed ? "\"/Users/test/Library/LaunchAgents/com.etf.masa.aksam.plist\"" : "null"),
                  "log_lines": []
                },
                {
                  "label": "com.etf.masa.cuma",
                  "description": "Haftalık Model Performans Karnesi",
                  "schedule": "Cuma 18:00 CET",
                  "installed": \(installed),
                  "loaded": \(installed),
                  "last_exit_code": \(installed ? "0" : "null"),
                  "plist_path": \(installed ? "\"/Users/test/Library/LaunchAgents/com.etf.masa.cuma.plist\"" : "null"),
                  "log_lines": []
                }
              ]
            }
            """
            effectiveResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: json, stderr: "", message: "Success")
        } else if arguments == ["degerlendir", "--json"] && (mockResult.stdout == "OK" || mockResult.stdout.isEmpty) {
            let json = """
            {
              "schema_version": "1.0.0",
              "run_id": "eval_test_01",
              "warning": null,
              "assessments": [
                {
                  "isin": "IE00B4L5Y983",
                  "name": "iShares Core MSCI World UCITS ETF",
                  "label": "TUT",
                  "reasons": ["Hedef ağırlık bandında (%70)", "Volatilite normal"],
                  "notes": ["Teilfreistellung %30", "Karar desteğidir; sistem işlem yapmaz."]
                }
              ]
            }
            """
            effectiveResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: json, stderr: "", message: "Success")
        } else if arguments == ["tarama", "--json"] && (mockResult.stdout == "OK" || mockResult.stdout.isEmpty) {
            let json = """
            {
              "schema_version": "1.0.0",
              "pool_count": 5,
              "warning": null,
              "candidates": [
                {
                  "isin": "IE00B3YLTY66",
                  "name": "SPDR MSCI Europe Small Cap Value",
                  "label": "EKLE",
                  "score": 8.5,
                  "reasons": ["Sharpe 1.2", "Düşük korelasyon"]
                }
              ]
            }
            """
            effectiveResult = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: json, stderr: "", message: "Success")
        }

        if let onStdoutChunk, !effectiveResult.stdout.isEmpty {
            onStdoutChunk(effectiveResult.stdout)
        }
        if let onStderrChunk, !effectiveResult.stderr.isEmpty {
            onStderrChunk(effectiveResult.stderr)
        }

        return effectiveResult
    }
}
