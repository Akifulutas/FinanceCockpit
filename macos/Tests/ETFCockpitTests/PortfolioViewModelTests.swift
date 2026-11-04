import XCTest
@testable import FinanceCockpit

@MainActor
final class PortfolioViewModelTests: XCTestCase {

    var mockDb: MockDatabaseService!
    var mockCli: MockCLIProcessRunner!
    var viewModel: PortfolioViewModel!

    override func setUp() async throws {
        mockDb = MockDatabaseService()
        mockCli = MockCLIProcessRunner()

        // Setup sample test positions
        mockDb.mockPositions = [
            PositionItem(
                isin: "IE00B3YLTY66",
                displayName: "SPDR MSCI ACWI IMI",
                securityType: "ETF",
                quantity: Decimal(158),
                brokerValuation: Decimal(1826.01),
                brokerCostBasis: Decimal(10.50),
                bid: Decimal(11.55),
                ask: Decimal(11.57),
                computedMid: Decimal(11.56),
                spreadPct: Decimal(0.17),
                qualityStatus: "FRESH",
                quoteTimestamp: "2026-10-31T17:35:00Z",
                asOfTime: "2026-10-31T20:00:00Z"
            ),
            PositionItem(
                isin: "IE00BKM4GZ66",
                displayName: "iShares Core MSCI EM IMI",
                securityType: "ETF",
                quantity: Decimal(50),
                brokerValuation: Decimal(1500.00),
                brokerCostBasis: Decimal(28.00),
                bid: Decimal(29.95),
                ask: Decimal(30.05),
                computedMid: Decimal(30.00),
                spreadPct: Decimal(0.33),
                qualityStatus: "FRESH",
                quoteTimestamp: "2026-10-31T17:35:00Z",
                asOfTime: "2026-10-31T20:00:00Z"
            ),
            PositionItem(
                isin: "US0378331005",
                displayName: "Apple Inc.",
                securityType: "EQUITY",
                quantity: Decimal(10),
                brokerValuation: Decimal(2000.00),
                brokerCostBasis: Decimal(180.00),
                bid: Decimal(199.50),
                ask: Decimal(200.50),
                computedMid: Decimal(200.00),
                spreadPct: Decimal(0.50),
                qualityStatus: "FRESH",
                quoteTimestamp: "2026-10-31T17:35:00Z",
                asOfTime: "2026-10-31T20:00:00Z"
            )
        ]

        // Setup sample cash
        mockDb.mockCash = CashObservation(
            accountIdMasked: "rSw…aJ",
            currency: "EUR",
            settledCash: Decimal(450.00),
            unsettledCash: Decimal(50.00),
            accruedCash: Decimal(5.00),
            totalCash: Decimal(500.00),
            buyingPower: Decimal(450.00),
            pendingBuyOrdersAmount: Decimal(100.00),
            possibleTaxes: Decimal(15.00),
            observedAt: "2026-10-31T20:00:00Z"
        )

        viewModel = PortfolioViewModel(databaseService: mockDb, cliRunner: mockCli)
    }

    func testLoadDataCalculatesCorrectValuations() async {
        await viewModel.loadData()

        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertEqual(viewModel.positions.count, 3)

        // Invested assets = 1826.01 + 1500.00 + 2000.00 = 5326.01
        XCTAssertEqual(viewModel.investedAssets, Decimal(5326.01))

        // Total cash = 500.00
        XCTAssertEqual(viewModel.totalCash, Decimal(500.00))

        // Total portfolio valuation = 5326.01 + 500.00 = 5826.01
        XCTAssertEqual(viewModel.totalValuation, Decimal(5826.01))

        // Cash details
        XCTAssertEqual(viewModel.settledCash, Decimal(450.00))
        XCTAssertEqual(viewModel.unsettledCash, Decimal(50.00))
        XCTAssertEqual(viewModel.accruedCash, Decimal(5.00))
        XCTAssertEqual(viewModel.buyingPower, Decimal(450.00))
        XCTAssertEqual(viewModel.pendingBuyOrders, Decimal(100.00))
        XCTAssertEqual(viewModel.possibleTaxes, Decimal(15.00))
    }

    func testWeightCalculations() async {
        await viewModel.loadData()

        let total = viewModel.totalValuation
        XCTAssertEqual(total, Decimal(5826.01))

        let p0 = viewModel.positions[0] // 1826.01
        let p1 = viewModel.positions[1] // 1500.00
        let p2 = viewModel.positions[2] // 2000.00

        let w0 = viewModel.weight(for: p0)
        let w1 = viewModel.weight(for: p1)
        let w2 = viewModel.weight(for: p2)

        // w0 = (1826.01 / 5826.01) * 100 ≈ 31.34%
        XCTAssertEqual(NSDecimalNumber(decimal: w0).doubleValue, 31.34, accuracy: 0.1)

        // w1 = (1500.00 / 5826.01) * 100 ≈ 25.75%
        XCTAssertEqual(NSDecimalNumber(decimal: w1).doubleValue, 25.75, accuracy: 0.1)

        // w2 = (2000.00 / 5826.01) * 100 ≈ 34.33%
        XCTAssertEqual(NSDecimalNumber(decimal: w2).doubleValue, 34.33, accuracy: 0.1)

        // Total sum of weights + cash weight ≈ 100%
        let cashWeight = (Decimal(500.00) / total) * 100
        let totalWeights = w0 + w1 + w2 + cashWeight
        XCTAssertEqual(NSDecimalNumber(decimal: totalWeights).doubleValue, 100.0, accuracy: 0.01)
    }

    func testUnrealizedPnLCalculations() async {
        await viewModel.loadData()

        // Total cost basis:
        // p0: 158 * 10.50 = 1659.00
        // p1: 50 * 28.00 = 1400.00
        // p2: 10 * 180.00 = 1800.00
        // Total cost = 4859.00
        XCTAssertEqual(viewModel.totalCostBasis, Decimal(4859.00))

        // Total unrealized PnL = 5326.01 - 4859.00 = 467.01
        XCTAssertEqual(viewModel.totalUnrealizedPnLEur, Decimal(467.01))

        // Total unrealized PnL % = (467.01 / 4859.00) * 100 ≈ 9.61%
        let pct = viewModel.totalUnrealizedPnLPct
        XCTAssertNotNil(pct)
        XCTAssertEqual(NSDecimalNumber(decimal: pct!).doubleValue, 9.61, accuracy: 0.05)
    }

    func testAssetAllocationBreakdown() async {
        await viewModel.loadData()

        let slices = viewModel.assetAllocationBreakdown
        XCTAssertEqual(slices.count, 3)

        let etfSlice = slices.first(where: { $0.name.contains("ETF") })
        let eqSlice = slices.first(where: { $0.name.contains("Equities") })
        let cashSlice = slices.first(where: { $0.name.contains("Cash") })

        XCTAssertNotNil(etfSlice)
        XCTAssertNotNil(eqSlice)
        XCTAssertNotNil(cashSlice)

        // ETF Total = 1826.01 + 1500.00 = 3326.01
        XCTAssertEqual(etfSlice!.value, 3326.01, accuracy: 0.01)

        // Equity Total = 2000.00
        XCTAssertEqual(eqSlice!.value, 2000.00, accuracy: 0.01)

        // Cash Total = 500.00
        XCTAssertEqual(cashSlice!.value, 500.00, accuracy: 0.01)

        let sumPct = etfSlice!.percentage + eqSlice!.percentage + cashSlice!.percentage
        XCTAssertEqual(sumPct, 100.0, accuracy: 0.1)
    }

    func testGeographicExposureBreakdown() async {
        await viewModel.loadData()

        let slices = viewModel.geographicExposureBreakdown
        XCTAssertFalse(slices.isEmpty)

        let irelandSlice = slices.first(where: { $0.title.contains("Ireland") })
        let usSlice = slices.first(where: { $0.title.contains("US") })
        let cashSlice = slices.first(where: { $0.title.contains("Cash") })

        XCTAssertNotNil(irelandSlice)
        XCTAssertNotNil(usSlice)
        XCTAssertNotNil(cashSlice)

        // Ireland has 2 ETF positions
        XCTAssertEqual(irelandSlice!.count, 2)
        XCTAssertEqual(irelandSlice!.value, 3326.01, accuracy: 0.01)
    }

    func testFilterPositions() async {
        await viewModel.loadData()

        // 1. All filter
        viewModel.selectedFilter = .all
        XCTAssertEqual(viewModel.filteredPositions.count, 3)

        // 2. ETF filter
        viewModel.selectedFilter = .etf
        XCTAssertEqual(viewModel.filteredPositions.count, 2)
        XCTAssertTrue(viewModel.filteredPositions.allSatisfy { $0.securityType == "ETF" })

        // 3. Equity filter
        viewModel.selectedFilter = .equity
        XCTAssertEqual(viewModel.filteredPositions.count, 1)
        XCTAssertEqual(viewModel.filteredPositions.first?.isin, "US0378331005")

        // 4. Search text filter
        viewModel.selectedFilter = .all
        viewModel.searchText = "Apple"
        XCTAssertEqual(viewModel.filteredPositions.count, 1)
        XCTAssertEqual(viewModel.filteredPositions.first?.displayName, "Apple Inc.")

        viewModel.searchText = "IE00B3"
        XCTAssertEqual(viewModel.filteredPositions.count, 1)
        XCTAssertEqual(viewModel.filteredPositions.first?.isin, "IE00B3YLTY66")

        viewModel.searchText = "NONEXISTENT"
        XCTAssertTrue(viewModel.filteredPositions.isEmpty)
    }

    func testSortingPositions() async {
        await viewModel.loadData()

        // Sort by valuation descending (default)
        viewModel.sortField = .valuation
        viewModel.sortAscending = false
        let sortedDesc = viewModel.filteredPositions
        XCTAssertEqual(sortedDesc[0].brokerValuation, Decimal(2000.00)) // Apple
        XCTAssertEqual(sortedDesc[1].brokerValuation, Decimal(1826.01)) // SPDR
        XCTAssertEqual(sortedDesc[2].brokerValuation, Decimal(1500.00)) // EM

        // Sort by valuation ascending
        viewModel.sortAscending = true
        let sortedAsc = viewModel.filteredPositions
        XCTAssertEqual(sortedAsc[0].brokerValuation, Decimal(1500.00))
        XCTAssertEqual(sortedAsc[1].brokerValuation, Decimal(1826.01))
        XCTAssertEqual(sortedAsc[2].brokerValuation, Decimal(2000.00))
    }

    func testErrorHandling() async {
        mockDb.shouldThrowError = true
        await viewModel.loadData()

        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNotNil(viewModel.errorMessage)
        XCTAssertTrue(viewModel.errorMessage!.contains("Failed"))
    }

    func testRefreshLiveQuotesAction() async {
        await viewModel.refreshLiveQuotes()

        XCTAssertFalse(viewModel.isRefreshing)
        XCTAssertEqual(mockCli.commandExecutionCount, 1)
        XCTAssertEqual(mockCli.lastExecutedArguments, ["veri"])
        XCTAssertEqual(viewModel.statusMessage, "Market quotes updated successfully.")
    }

    func testLiveDatabaseIntegration() async throws {
        let liveDbPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path
        guard FileManager.default.fileExists(atPath: liveDbPath) else { return }
        let liveDb = try DatabaseService(databasePath: liveDbPath)
        let liveViewModel = PortfolioViewModel(databaseService: liveDb, cliRunner: mockCli)
        await liveViewModel.loadData()

        XCTAssertFalse(liveViewModel.isLoading)
        XCTAssertNil(liveViewModel.errorMessage)
        XCTAssertGreaterThan(liveViewModel.totalValuation, 0)
        XCTAssertEqual(liveViewModel.positions.count, 4)
        XCTAssertGreaterThan(liveViewModel.investedAssets, 0)
    }
}
