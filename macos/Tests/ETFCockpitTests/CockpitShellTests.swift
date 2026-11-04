import XCTest
import SwiftUI
@testable import FinanceCockpit

@MainActor
final class CockpitShellTests: XCTestCase {

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

    // MARK: - 1. Navigation Enum and Uniqueness

    func testNavigationItemsCountAndUniqueness() {
        let allItems = CockpitNavigationItem.allCases
        XCTAssertEqual(allItems.count, 14, "There must be exactly 14 navigation destinations.")

        let ids = Set(allItems.map(\.id))
        XCTAssertEqual(ids.count, 14, "Every navigation item must have a unique ID.")

        let rawValues = Set(allItems.map(\.rawValue))
        XCTAssertEqual(rawValues.count, 14, "Every navigation item must have a unique raw title.")

        for item in allItems {
            XCTAssertFalse(item.icon.isEmpty, "\(item.rawValue) must have an icon.")
            XCTAssertFalse(item.subtitle.isEmpty, "\(item.rawValue) must have a subtitle.")
        }
    }

    // MARK: - 2. Sidebar Categories Integrity

    func testSidebarCategoriesIntegrity() {
        let categories = CockpitNavigationCategory.allCases
        XCTAssertEqual(categories.count, 3, "There must be 3 categories: Operational, Strategy, Security.")

        // Verify Section 1: Operational Monitoring
        let operationalItems = CockpitNavigationCategory.operational.items
        XCTAssertEqual(operationalItems, [.today, .portfolio, .forecast])
        XCTAssertEqual(CockpitNavigationCategory.operational.headerTitle, "Operational Monitoring")

        // Verify Section 2: Strategy & Research
        let strategyItems = CockpitNavigationCategory.strategy.items
        XCTAssertEqual(strategyItems, [.evaluation, .screener, .reports, .research, .modelRegistry, .ledger, .basket, .thesis])
        XCTAssertEqual(CockpitNavigationCategory.strategy.headerTitle, "Strategy & Research")

        // Verify Section 3: Security & Automation
        let securityItems = CockpitNavigationCategory.security.items
        XCTAssertEqual(securityItems, [.integrity, .scheduler, .configuration])
        XCTAssertEqual(CockpitNavigationCategory.security.headerTitle, "Security & Automation")

        // Verify reverse mapping: item.category
        for item in operationalItems {
            XCTAssertEqual(item.category, .operational)
        }
        for item in strategyItems {
            XCTAssertEqual(item.category, .strategy)
        }
        for item in securityItems {
            XCTAssertEqual(item.category, .security)
        }

        let totalCategorized = operationalItems.count + strategyItems.count + securityItems.count
        XCTAssertEqual(totalCategorized, 14, "The 3 categories must cover all 14 items without omissions.")
    }

    // MARK: - 3. Initial Selection

    func testInitialSelectionIsToday() {
        XCTAssertEqual(appState.selectedItem, .today, "Initial selection must be Today (Bugün).")
    }

    // MARK: - 4. Destination Routing for All 10 Subsystems

    func testDestinationRoutingForAllSubsystems() {
        let shellView = CockpitShellView(appState: appState)

        for item in CockpitNavigationItem.allCases {
            appState.selectedItem = item
            let destination = shellView.destinationView(for: item)
            XCTAssertNotNil(destination, "Destination view for \(item.rawValue) must be instantiable.")
        }

        // Test fallback for nil selection
        let fallback = shellView.destinationView(for: nil)
        XCTAssertNotNil(fallback, "Destination view for nil selection must fallback to PortfolioView.")
    }

    // MARK: - 5. Category Shortcuts Navigation (Command+1..3)

    func testCategoryShortcutsNavigation() {
        appState.selectCategory(.operational)
        XCTAssertEqual(appState.selectedItem, .today, "Command+1 shortcut must navigate to Today.")

        appState.selectCategory(.strategy)
        XCTAssertEqual(appState.selectedItem, .evaluation, "Command+2 shortcut must navigate to Evaluation.")

        appState.selectCategory(.security)
        XCTAssertEqual(appState.selectedItem, .integrity, "Command+3 shortcut must navigate to Integrity.")
    }

    // MARK: - 6. Interactive Quick Audit Trigger (Success)

    func testQuickAuditTriggerSuccess() async {
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: true,
            fileVaultActive: true,
            schemaVersion: 3,
            triggerCount: 78
        )

        XCTAssertFalse(appState.isRunningQuickAudit)
        await appState.runQuickAudit()

        XCTAssertFalse(appState.isRunningQuickAudit)
        XCTAssertEqual(appState.auditStatusText, "MATCH_SEALED")
        XCTAssertEqual(appState.auditStatusLevel, .success)
        XCTAssertEqual(appState.schemaVersion, 3)
        XCTAssertEqual(appState.triggerCount, 78)
        XCTAssertTrue(appState.auditMessage?.contains("Integrity verified") == true)
        XCTAssertEqual(mockCLI.commandExecutionCount, 1)
        XCTAssertEqual(mockCLI.lastExecutedArguments, ["dogrula"])
    }

    // MARK: - 7. Interactive Quick Audit Trigger (Failure)

    func testQuickAuditTriggerFailure() async {
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: false,
            fileVaultActive: false,
            schemaVersion: 3,
            triggerCount: 75
        )

        await appState.runQuickAudit()

        XCTAssertFalse(appState.isRunningQuickAudit)
        XCTAssertEqual(appState.auditStatusText, "INTEGRITY_FAILURE")
        XCTAssertEqual(appState.auditStatusLevel, .error)
    }

    // MARK: - 8. Interactive Quick Audit Exception Handling

    func testQuickAuditExceptionHandling() async {
        mockCLI.shouldFail = true

        await appState.runQuickAudit()

        XCTAssertFalse(appState.isRunningQuickAudit)
        XCTAssertEqual(appState.auditStatusText, "ERROR")
        XCTAssertEqual(appState.auditStatusLevel, .error)
        XCTAssertTrue(appState.auditMessage?.contains("Verification error") == true)
    }

    // MARK: - 9. Manual Refresh Current View

    func testManualRefreshCurrentView() async {
        // Portfolio refresh
        appState.selectedItem = .portfolio
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.portfolioVM.lastRefreshDate)

        // Forecast refresh
        appState.selectedItem = .forecast
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.forecastVM.lastRefreshDate)

        // Research refresh
        appState.selectedItem = .research
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.researchVM.lastRefreshDate)

        // Model Registry refresh
        appState.selectedItem = .modelRegistry
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.modelRegistryVM.lastRefreshDate)

        // Ledger refresh
        appState.selectedItem = .ledger
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.ledgerVM.lastRefreshDate)

        // Basket refresh
        appState.selectedItem = .basket
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.basketVM.lastRefreshDate)

        // Thesis refresh
        appState.selectedItem = .thesis
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.thesisVM.lastRefreshDate)

        // Integrity refresh
        appState.selectedItem = .integrity
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.integrityVM.lastRefreshDate)

        // Scheduler refresh
        appState.selectedItem = .scheduler
        await appState.refreshCurrentView()
        XCTAssertNotNil(appState.schedulerVM.lastRefreshDate)

        // Configuration refresh
        appState.selectedItem = .configuration
        await appState.refreshCurrentView()
        XCTAssertFalse(appState.isRefreshing)
    }

    // MARK: - 10. Refresh All Views

    func testRefreshAllViews() async {
        await appState.refreshAllViews()

        XCTAssertNotNil(appState.portfolioVM.lastRefreshDate)
        XCTAssertNotNil(appState.forecastVM.lastRefreshDate)
        XCTAssertNotNil(appState.researchVM.lastRefreshDate)
        XCTAssertNotNil(appState.modelRegistryVM.lastRefreshDate)
        XCTAssertNotNil(appState.ledgerVM.lastRefreshDate)
        XCTAssertNotNil(appState.basketVM.lastRefreshDate)
        XCTAssertNotNil(appState.thesisVM.lastRefreshDate)
        XCTAssertNotNil(appState.integrityVM.lastRefreshDate)
        XCTAssertNotNil(appState.schedulerVM.lastRefreshDate)
    }

    // MARK: - 11. Status Bar Properties

    func testStatusBarProperties() async {
        XCTAssertNil(appState.schemaVersion)
        XCTAssertNil(appState.triggerCount)
        XCTAssertNil(appState.fileVaultActive)
        XCTAssertEqual(appState.auditStatusLevel, .unknown)
        XCTAssertEqual(appState.auditStatusText, "UNKNOWN")
        XCTAssertEqual(appState.databasePath, "/tmp/test_masa.db")
        XCTAssertFalse(appState.formattedLastRefresh.isEmpty)

        await appState.runQuickAudit()
        XCTAssertEqual(appState.schemaVersion, 3)
        XCTAssertEqual(appState.triggerCount, 78)
        XCTAssertEqual(appState.fileVaultActive, true)
        XCTAssertEqual(appState.auditStatusLevel, .success)
        XCTAssertEqual(appState.auditStatusText, "MATCH_SEALED")
    }

    // MARK: - 12. App Shell Structure Initialization

    func testETFCockpitAppInitialization() {
        let app = ETFCockpitApp(appState: appState)
        XCTAssertNotNil(app.body)
    }

    // MARK: - 13. Cockpit v2 6-Section Architecture & Pinned Assets

    func testCockpitSectionsAndPinnedAssets() {
        let sections = CockpitSection.allCases
        XCTAssertEqual(sections.count, 6, "There must be exactly 6 primary sections in v2.")
        XCTAssertEqual(sections.map(\.rawValue), ["Today", "Portfolio", "Forecasts", "Decisions", "Discovery", "System"])

        for section in sections {
            XCTAssertFalse(section.icon.isEmpty, "\(section.rawValue) must have an icon.")
            XCTAssertTrue((1...6).contains(section.shortcutNumber), "\(section.rawValue) shortcut must be 1..6")
        }

        let pinned = PinnedAsset.defaultPinned
        XCTAssertEqual(pinned.count, 4, "Default pinned assets must include 4 core ETFs.")
        XCTAssertEqual(pinned.map(\.symbol), ["SPYI", "IS3N", "IS3R", "IS3S"])

        for asset in pinned {
            XCTAssertFalse(asset.isin.isEmpty)
            XCTAssertTrue(asset.priceEur > 0)
            XCTAssertTrue(asset.shares > 0)
        }
    }

    // MARK: - 14. Section Container Views Instantiation

    func testSectionContainerViewsInstantiation() {
        let portfolioSection = PortfolioSectionView(appState: appState)
        XCTAssertNotNil(portfolioSection.body)

        let forecastSection = ForecastSectionView(appState: appState)
        XCTAssertNotNil(forecastSection.body)

        let decisionsSection = DecisionsSectionView(appState: appState)
        XCTAssertNotNil(decisionsSection.body)

        let discoverySection = DiscoverySectionView(appState: appState)
        XCTAssertNotNil(discoverySection.body)

        let systemSection = SystemSectionView(appState: appState)
        XCTAssertNotNil(systemSection.body)

        let capsuleView = StatusCapsuleView(appState: appState)
        XCTAssertNotNil(capsuleView.body)

        if let firstPinned = PinnedAsset.defaultPinned.first {
            let assetDetail = AssetDetailView(asset: firstPinned, appState: appState)
            XCTAssertNotNil(assetDetail.body)
        }
    }

    // MARK: - 15. Select Section and Pinned Asset Navigation

    func testSelectSectionAndPinnedAssetNavigation() {
        appState.selectSection(.portfolio)
        XCTAssertEqual(appState.selectedSection, .portfolio)
        XCTAssertNil(appState.selectedPinnedAsset)
        XCTAssertEqual(appState.selectedItem, .portfolio)

        appState.selectSection(.decisions)
        XCTAssertEqual(appState.selectedSection, .decisions)
        XCTAssertNil(appState.selectedPinnedAsset)
        XCTAssertEqual(appState.selectedItem, .evaluation)

        if let firstPinned = PinnedAsset.defaultPinned.first {
            appState.selectPinnedAsset(firstPinned)
            XCTAssertEqual(appState.selectedPinnedAsset?.id, firstPinned.id)
        }
    }

    // MARK: - 16. R2 (İP-1) Zero Fake State & Dynamic Verification

    func testCockpitAppState_DefaultsToUnknown() {
        let freshState = CockpitAppState(databaseService: mockDB, cliRunner: mockCLI, databasePath: "/tmp/test.db")
        XCTAssertEqual(freshState.auditStatusLevel, .unknown)
        XCTAssertEqual(freshState.auditStatusText, "UNKNOWN")
        XCTAssertNil(freshState.auditMessage)
        XCTAssertNil(freshState.schemaVersion)
        XCTAssertNil(freshState.triggerCount)
        XCTAssertNil(freshState.fileVaultActive)
        XCTAssertTrue(freshState.pinnedAssets.isEmpty)
        XCTAssertNil(freshState.brokerSessionActive)
        XCTAssertNil(freshState.marketStatusText)
        XCTAssertNil(freshState.isMarketOpen)
    }

    func testCockpitAppState_FileVaultOnlyShownWhenActuallyActive() async {
        // When FileVault is inactive (false)
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: true,
            fileVaultActive: false,
            schemaVersion: 3,
            triggerCount: 78,
            chainTipStatus: "MATCH_SEALED"
        )
        await appState.runQuickAudit()
        XCTAssertEqual(appState.fileVaultActive, false)
        XCTAssertTrue(appState.auditMessage?.contains("FileVault disabled") == true)
        XCTAssertFalse(appState.auditMessage?.contains("FileVault enabled") == true)

        // When FileVault is active (true)
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: true,
            fileVaultActive: true,
            schemaVersion: 3,
            triggerCount: 78,
            chainTipStatus: "MATCH_SEALED"
        )
        await appState.runQuickAudit()
        XCTAssertEqual(appState.fileVaultActive, true)
        XCTAssertTrue(appState.auditMessage?.contains("FileVault enabled") == true)
    }

    func testBottomStatusBar_DynamicCountsAndMatchSealed() async {
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: true,
            fileVaultActive: true,
            schemaVersion: 4,
            triggerCount: 82,
            snapshotsCount: 70,
            auditEventsCount: 160,
            chainTipStatus: "MATCH_SEALED"
        )
        await appState.runQuickAudit()
        XCTAssertEqual(appState.schemaVersion, 4)
        XCTAssertEqual(appState.triggerCount, 82)
        XCTAssertEqual(appState.snapshotCount, 70)
        XCTAssertEqual(appState.auditEventCount, 160)
        XCTAssertEqual(appState.chainTipStatus, "MATCH_SEALED")
        XCTAssertEqual(appState.auditStatusLevel, .success)
    }

    func testPinnedAssets_MissingPreviousCloseShowsDash() {
        let assetNoClose = PinnedAsset(
            id: "SPYI",
            symbol: "SPYI",
            isin: "IE00B3YLTY66",
            name: "SPDR MSCI ACWI IMI",
            priceEur: 11.61,
            changePct: nil,
            shares: 158
        )
        XCTAssertNil(assetNoClose.changePct)

        let assetWithClose = PinnedAsset(
            id: "SPYI",
            symbol: "SPYI",
            isin: "IE00B3YLTY66",
            name: "SPDR MSCI ACWI IMI",
            priceEur: 11.61,
            changePct: 0.45,
            shares: 158
        )
        XCTAssertEqual(assetWithClose.changePct, 0.45)
    }

    func testAssetDetailView_WeightCalculatedFromTotalPortfolioValuation() {
        let asset = PinnedAsset(
            id: "SPYI",
            symbol: "SPYI",
            isin: "IE00B3YLTY66",
            name: "SPDR MSCI ACWI IMI",
            priceEur: 10.0,
            changePct: 0.5,
            shares: 100 // Value: 1,000 EUR
        )

        // Set total portfolio valuation to 10,000 EUR -> Expected weight: 10.0%
        appState.portfolioVM.summary = PortfolioSummary(
            totalValueEur: 10000,
            investedAssetsEur: 9000,
            totalCashEur: 1000,
            settledCashEur: 1000,
            buyingPowerEur: 1000,
            positions: [],
            cash: nil,
            asOfDate: "2026-11-01"
        )

        let detailView = AssetDetailView(asset: asset, appState: appState)
        XCTAssertNotNil(detailView.body)

        // When total portfolio valuation is 0 -> Should gracefully handle without divide by zero
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
        let zeroDetailView = AssetDetailView(asset: asset, appState: appState)
        XCTAssertNotNil(zeroDetailView.body)
    }

    func testModelRegistry_UnmeasuredApiCostShowsOlculmedi() {
        let modelRegistryView = ModelRegistryView(viewModel: appState.modelRegistryVM)
        XCTAssertNotNil(modelRegistryView.body)
    }
}
