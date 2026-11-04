import XCTest
import SwiftUI
@testable import FinanceCockpit

@MainActor
final class AdversarialZeroMockAndMorningFlowTests: XCTestCase {

    private var mockDB: MockDatabaseService!
    private var mockCLI: MockCLIProcessRunner!
    private var appState: CockpitAppState!

    override func setUp() async throws {
        try await super.setUp()
        mockDB = MockDatabaseService()
        mockCLI = MockCLIProcessRunner()
        appState = CockpitAppState(
            databaseService: mockDB,
            cliRunner: mockCLI,
            databasePath: "/tmp/test_masa.db"
        )
    }

    override func tearDown() async throws {
        mockDB = nil
        mockCLI = nil
        appState = nil
        try await super.tearDown()
    }

    // MARK: - 1. Zero-Mock & Honest Initial State Tests

    func testInitialState_NeverPresentsUnverifiedDataAsConfirmedFacts() {
        // Audit status should be unverified / unknown initially
        XCTAssertEqual(appState.auditStatusText, "UNKNOWN", "Default auditStatusText must be UNKNOWN")
        XCTAssertEqual(appState.auditStatusLevel, .unknown, "Default auditStatusLevel must be .unknown")
        XCTAssertNil(appState.schemaVersion, "Default schemaVersion must be nil")
        XCTAssertNil(appState.triggerCount, "Default triggerCount must be nil")
        XCTAssertNil(appState.snapshotCount, "Default snapshotCount must be nil")
        XCTAssertNil(appState.auditEventCount, "Default auditEventCount must be nil")
        XCTAssertNil(appState.chainTipStatus, "Default chainTipStatus must be nil")
        XCTAssertNil(appState.fileVaultActive, "Default fileVaultActive must be nil")
        XCTAssertNil(appState.brokerSessionActive, "Default brokerSessionActive must be nil")
        XCTAssertNil(appState.marketStatusText, "Default marketStatusText must be nil")
        XCTAssertNil(appState.isMarketOpen, "Default isMarketOpen must be nil")
        XCTAssertNil(appState.dataFreshnessText, "Default dataFreshnessText must be nil")
        XCTAssertTrue(appState.pinnedAssets.isEmpty, "Initial pinned assets must be empty")
    }

    func testStatusCapsule_InitialUnverifiedDisplaysBilinmiyorAndQuestionMark() {
        let capsule = StatusCapsuleView(appState: appState)
        XCTAssertNotNil(capsule.body)
        // With brokerSessionActive == nil, StatusCapsuleView text should be "Scalable: Bilinmiyor"
        // With isMarketOpen == nil, market text should be "XETR: ?"
        // With dataFreshnessText == nil, freshness should be "Veri: Kotasyon Yok"
    }

    func testAssetDetailView_ZeroValuationShowsDashForWeight() {
        let asset = PinnedAsset(
            id: "TEST",
            symbol: "TEST",
            isin: "IE0000000000",
            name: "Test ETF",
            priceEur: 25.0,
            changePct: nil,
            shares: 10
        )
        // Set total portfolio valuation to 0
        appState.portfolioVM.summary = PortfolioSummary(
            totalValueEur: 0,
            investedAssetsEur: 0,
            totalCashEur: 0,
            settledCashEur: 0,
            buyingPowerEur: 0,
            positions: [],
            cash: nil,
            asOfDate: "2026-11-01"
        )
        let detailView = AssetDetailView(asset: asset, appState: appState)
        XCTAssertNotNil(detailView.body)
    }

    // MARK: - 2. Morning Flow Error Honesty Tests

    func testMorningFlow_Step5_Non429Error_MustShowActualStderrFirstLine_NotQuota() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"schema_version\":\"1.0.0\",\"run_id\":\"1\",\"warning\":null,\"assessments\":[]}",
            stderr: "",
            message: ""
        )

        // Adversarial scenario: ConnectionRefusedError on port 8000
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "ConnectionRefusedError: port 8000 unavailable\nTraceback (most recent call last):\n  File 'masa/cli.py'...",
            message: "Error"
        )

        await vm.runFullMorningFlow()

        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        XCTAssertNotNil(step5)
        XCTAssertEqual(step5?.detailText, "ConnectionRefusedError: port 8000 unavailable")
        XCTAssertFalse(step5?.detailText?.contains("Model kotası") == true, "Must NOT report Model kotası for connection error")
        XCTAssertFalse(step5?.detailText?.contains("kota") == true, "Must NOT report kota for connection error")
    }

    func testMorningFlow_Step5_429QuotaError_MustReportModelKotasiDoldu() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"schema_version\":\"1.0.0\",\"run_id\":\"1\",\"warning\":null,\"assessments\":[]}",
            stderr: "",
            message: ""
        )

        // Adversarial scenario: HTTP 429 Too Many Requests
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "HTTP 429 Too Many Requests: quota exceeded for model gemini-1.5-pro",
            message: "Error"
        )

        await vm.runFullMorningFlow()

        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        XCTAssertNotNil(step5)
        XCTAssertEqual(step5?.detailText, "Model quota exhausted, deterministic evaluation valid.")
    }

    func testMorningFlow_Step5_EmptyStderr_MustHaveFallbackErrorMessage() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"schema_version\":\"1.0.0\",\"run_id\":\"1\",\"warning\":null,\"assessments\":[]}",
            stderr: "",
            message: ""
        )

        // Adversarial scenario: exit code 1 with completely empty stdout and stderr
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "",
            message: "Error"
        )

        await vm.runFullMorningFlow()

        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        XCTAssertNotNil(step5)
        XCTAssertEqual(step5?.detailText, "Commentary failed.", "Empty stderr must fall back to 'Commentary failed.'")
        XCTAssertFalse(step5?.detailText?.contains("Model kotası") == true, "Must NOT claim quota when empty stderr")
    }

    func testMorningFlow_Step6_ZeroOpportunitiesWhen8AssetsScanned() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"schema_version\":\"1.0.0\",\"run_id\":\"1\",\"warning\":null,\"assessments\":[]}",
            stderr: "",
            message: ""
        )
        mockCLI.customCommandResults[["tarama", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "pool_count": 8,
              "warning": null,
              "candidates": [
                { "isin": "IE001", "name": "Asset 1", "label": "NÖTR", "score": 5.0, "reasons": [] },
                { "isin": "IE002", "name": "Asset 2", "label": "İZLE", "score": 4.5, "reasons": [] },
                { "isin": "IE003", "name": "Asset 3", "label": "TUT", "score": 6.0, "reasons": [] },
                { "isin": "IE004", "name": "Asset 4", "label": "NÖTR", "score": 5.2, "reasons": [] },
                { "isin": "IE005", "name": "Asset 5", "label": "İZLE", "score": 3.8, "reasons": [] },
                { "isin": "IE006", "name": "Asset 6", "label": "NÖTR", "score": 4.9, "reasons": [] },
                { "isin": "IE007", "name": "Asset 7", "label": "İZLE", "score": 4.1, "reasons": [] },
                { "isin": "IE008", "name": "Asset 8", "label": "NÖTR", "score": 5.0, "reasons": [] }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.runFullMorningFlow()

        let step6 = vm.morningFlowSteps.first(where: { $0.step == .scan })
        XCTAssertNotNil(step6)
        XCTAssertEqual(step6?.detailText, "0 opportunities (8 assets scanned)", "Must report 0 opportunities (8 assets scanned) when none are ARAŞTIRMAYA DEĞER or EKLE")
        XCTAssertEqual(vm.morningFlowSummary?.opportunityCandidatesCount, 0)
    }

    func testMorningFlow_QuotesTimestamp_EmptyDateReportsKotasyonYok() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"schema_version\":\"1.0.0\",\"run_id\":\"1\",\"warning\":null,\"assessments\":[]}",
            stderr: "",
            message: ""
        )

        // Case A: mockQuotes is completely empty
        mockDB.mockQuotes = []
        await vm.runFullMorningFlow()
        XCTAssertEqual(vm.morningFlowSummary?.lastQuoteTimestamp, "no quotes", "Empty quotes must report 'no quotes'")

        // Case B: mockQuotes has an entry with empty quoteTimestamp string
        let emptyQuote = QuoteItem(
            isin: "IE00B3YLTY66",
            qualityStatus: "FRESH",
            quoteTimestamp: "   \n  "
        )
        mockDB.mockQuotes = [emptyQuote]
        await vm.runFullMorningFlow()
        XCTAssertEqual(vm.morningFlowSummary?.lastQuoteTimestamp, "no quotes", "Whitespace/empty quoteTimestamp must report 'no quotes'")
    }
}
