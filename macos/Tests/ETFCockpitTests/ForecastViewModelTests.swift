import XCTest
@testable import FinanceCockpit

@MainActor
final class ForecastViewModelTests: XCTestCase {

    var mockDb: MockDatabaseService!
    var mockCli: MockCLIProcessRunner!
    var viewModel: ForecastSettlementViewModel!

    override func setUp() async throws {
        mockDb = MockDatabaseService()
        mockCli = MockCLIProcessRunner()

        // Setup sample forecasts
        mockDb.mockForecastEntries = [
            ForecastEntryItem(
                forecastId: "fc_2026-10-31_IE00B3YLTY66_ensemble_v1",
                isin: "IE00B3YLTY66",
                targetDate: "2026-10-31",
                forecastType: "DAILY_CLOSE",
                direction: .up,
                referencePrice: Decimal(11.55),
                targetPrice: Decimal(11.65),
                confidencePct: Decimal(68.4),
                modelId: "ensemble_v1",
                createdAt: "2026-10-31T09:30:00Z"
            ),
            ForecastEntryItem(
                forecastId: "fc_2026-10-31_IE00BKM4GZ66_ensemble_v1",
                isin: "IE00BKM4GZ66",
                targetDate: "2026-10-31",
                forecastType: "DAILY_CLOSE",
                direction: .down,
                referencePrice: Decimal(30.00),
                targetPrice: Decimal(29.70),
                confidencePct: Decimal(55.0),
                modelId: "ensemble_v1",
                createdAt: "2026-10-31T09:30:00Z"
            )
        ]

        viewModel = ForecastSettlementViewModel(databaseService: mockDb, cliRunner: mockCli)
    }

    // MARK: - MANDATORY N < 30 Empirical Confidence Suppression Rule Tests

    func testEmpiricalConfidenceSuppressedWhenNLessThan30() async {
        // Case 1: N = 0
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 0,
            hitsCount: 0,
            hitRatePct: nil,
            mapePct: nil,
            maeEur: nil,
            unsettledCount: 2
        )
        await viewModel.loadData()
        XCTAssertEqual(viewModel.totalSettledCount, 0)
        XCTAssertFalse(viewModel.isEmpiricallyReliable)
        XCTAssertEqual(viewModel.empiricalConfidenceDisplay, "—", "N = 0 MUST be suppressed to '—'")

        // Case 2: N = 10
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 10,
            hitsCount: 7,
            hitRatePct: 70.0,
            mapePct: 0.45,
            maeEur: 0.12,
            unsettledCount: 2
        )
        await viewModel.loadData()
        XCTAssertEqual(viewModel.totalSettledCount, 10)
        XCTAssertFalse(viewModel.isEmpiricallyReliable)
        XCTAssertEqual(viewModel.empiricalConfidenceDisplay, "—", "N = 10 (< 30) MUST be strictly suppressed to '—'")

        // Case 3: N = 29 (boundary condition)
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 29,
            hitsCount: 20,
            hitRatePct: 68.96,
            mapePct: 0.38,
            maeEur: 0.09,
            unsettledCount: 2
        )
        await viewModel.loadData()
        XCTAssertEqual(viewModel.totalSettledCount, 29)
        XCTAssertFalse(viewModel.isEmpiricallyReliable)
        XCTAssertEqual(viewModel.empiricalConfidenceDisplay, "—", "N = 29 (< 30) MUST be strictly suppressed to '—'")
    }

    func testEmpiricalConfidenceDisplayedWhenNEqualOrGreaterThan30() async {
        // Case 1: N = 30 (exact threshold)
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 30,
            hitsCount: 21,
            hitRatePct: 70.0,
            mapePct: 0.35,
            maeEur: 0.08,
            martingaleFlatHitRatePct: 33.3,
            momentumHitRatePct: 45.0,
            baselineOutperformance: true,
            unsettledCount: 2
        )
        await viewModel.loadData()
        XCTAssertEqual(viewModel.totalSettledCount, 30)
        XCTAssertTrue(viewModel.isEmpiricallyReliable)
        XCTAssertEqual(viewModel.empiricalConfidenceDisplay, "70,0%", "N = 30 MUST format and display hit rate")
        XCTAssertEqual(viewModel.baselineOutperformance, true)

        // Case 2: N = 120 (large sample)
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 120,
            hitsCount: 75,
            hitRatePct: 62.5,
            mapePct: 0.28,
            maeEur: 0.06,
            martingaleFlatHitRatePct: 33.3,
            momentumHitRatePct: 45.0,
            baselineOutperformance: true,
            unsettledCount: 0
        )
        await viewModel.loadData()
        XCTAssertEqual(viewModel.totalSettledCount, 120)
        XCTAssertTrue(viewModel.isEmpiricallyReliable)
        XCTAssertEqual(viewModel.empiricalConfidenceDisplay, "62,5%", "N = 120 MUST display hit rate")
    }

    // MARK: - Forecast Loading & Deadband Calculations

    func testLoadForecastEntries() async {
        await viewModel.loadData()

        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertEqual(viewModel.forecastEntries.count, 2)

        let entry1 = viewModel.forecastEntries[0]
        XCTAssertEqual(entry1.isin, "IE00B3YLTY66")
        XCTAssertEqual(entry1.direction, .up)
        XCTAssertEqual(entry1.referencePrice, Decimal(11.55))
        XCTAssertEqual(entry1.targetPrice, Decimal(11.65))

        // Expected return: ((11.65 - 11.55) / 11.55) * 100 ≈ +0.8658%
        let ret1 = entry1.expectedReturnPct
        XCTAssertNotNil(ret1)
        XCTAssertEqual(NSDecimalNumber(decimal: ret1!).doubleValue, 0.8658, accuracy: 0.01)

        let entry2 = viewModel.forecastEntries[1]
        XCTAssertEqual(entry2.isin, "IE00BKM4GZ66")
        XCTAssertEqual(entry2.direction, .down)
        // Expected return: ((29.70 - 30.00) / 30.00) * 100 = -1.0%
        let ret2 = entry2.expectedReturnPct
        XCTAssertNotNil(ret2)
        XCTAssertEqual(NSDecimalNumber(decimal: ret2!).doubleValue, -1.0, accuracy: 0.001)
    }

    func testFilteringForecasts() async {
        await viewModel.loadData()

        viewModel.searchText = "IE00B3"
        XCTAssertEqual(viewModel.filteredTodayForecasts.count, 1)
        XCTAssertEqual(viewModel.filteredTodayForecasts.first?.isin, "IE00B3YLTY66")

        viewModel.searchText = "ensemble"
        XCTAssertEqual(viewModel.filteredTodayForecasts.count, 2)

        viewModel.searchText = "NONEXISTENT"
        XCTAssertTrue(viewModel.filteredTodayForecasts.isEmpty)
    }

    // MARK: - CLI Trigger Actions

    func testTriggerMorningForecastAction() async {
        await viewModel.triggerMorningForecast()

        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertEqual(mockCli.commandExecutionCount, 1)
        XCTAssertEqual(mockCli.lastExecutedArguments, ["tahmin", "uret"])
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertTrue(viewModel.statusMessage!.contains("sealed"))
        XCTAssertNil(viewModel.errorMessage)
    }

    func testTriggerEveningSettlementAction() async {
        await viewModel.triggerEveningSettlement()

        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertEqual(mockCli.commandExecutionCount, 1)
        XCTAssertEqual(mockCli.lastExecutedArguments, ["tahmin", "uzlas"])
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertTrue(viewModel.statusMessage!.contains("updated"))
        XCTAssertNil(viewModel.errorMessage)
    }

    func testActionFailureHandling() async {
        mockCli.shouldFail = true

        await viewModel.triggerMorningForecast()
        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertNotNil(viewModel.errorMessage)

        await viewModel.triggerEveningSettlement()
        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertNotNil(viewModel.errorMessage)

        await viewModel.triggerSimulation(days: 30)
        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertNotNil(viewModel.errorMessage)
    }

    func testTriggerSimulationSuccess() async {
        await viewModel.triggerSimulation(days: 30)

        XCTAssertFalse(viewModel.isExecutingAction)
        XCTAssertEqual(mockCli.lastExecutedArguments, ["tahmin", "gecmis-simule", "--gun", "30"])
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertTrue(viewModel.statusMessage!.contains("completed"))
        XCTAssertNil(viewModel.errorMessage)
    }

    func testForecastSortingByExpectedReturn() async {
        await viewModel.loadData()
        XCTAssertEqual(viewModel.forecastEntries.count, 2)

        // Item 1 has (11.65 - 11.55) / 11.55 = +0.86%
        // Item 2 has (29.70 - 30.00) / 30.00 = -1.00%
        // Default sort is expectedReturn descending (highest first)
        viewModel.sortField = .expectedReturn
        viewModel.sortOrder = .descending

        var sorted = viewModel.filteredTodayForecasts
        XCTAssertEqual(sorted.first?.isin, "IE00B3YLTY66")
        XCTAssertEqual(sorted.last?.isin, "IE00BKM4GZ66")

        // Toggle sort order to ascending (lowest first)
        viewModel.toggleSort(field: .expectedReturn)
        XCTAssertEqual(viewModel.sortOrder, .ascending)
        sorted = viewModel.filteredTodayForecasts
        XCTAssertEqual(sorted.first?.isin, "IE00BKM4GZ66")
        XCTAssertEqual(sorted.last?.isin, "IE00B3YLTY66")
    }

    func testForecastSortingToggleOrder() async {
        await viewModel.loadData()
        // Switching to a text field defaults to ascending
        viewModel.toggleSort(field: .isin)
        XCTAssertEqual(viewModel.sortField, .isin)
        XCTAssertEqual(viewModel.sortOrder, .ascending)

        // Toggling same field switches to descending
        viewModel.toggleSort(field: .isin)
        XCTAssertEqual(viewModel.sortOrder, .descending)

        // Switching to targetPrice defaults to descending
        viewModel.toggleSort(field: .targetPrice)
        XCTAssertEqual(viewModel.sortField, .targetPrice)
        XCTAssertEqual(viewModel.sortOrder, .descending)
    }

    func testLiveDatabaseIntegration() async throws {
        let liveDbPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path
        guard FileManager.default.fileExists(atPath: liveDbPath) else { return }
        let liveDb = try DatabaseService(databasePath: liveDbPath)
        let liveViewModel = ForecastSettlementViewModel(databaseService: liveDb, cliRunner: mockCli)
        await liveViewModel.loadData()

        XCTAssertFalse(liveViewModel.isLoading)
        XCTAssertNil(liveViewModel.errorMessage)
        
        // Empirically reliable behavior depending on sample size N
        if liveViewModel.totalSettledCount < 30 {
            XCTAssertEqual(liveViewModel.empiricalConfidenceDisplay, "—", "Live database N<30 MUST suppress confidence to '—'")
            XCTAssertFalse(liveViewModel.isEmpiricallyReliable)
        } else {
            XCTAssertTrue(liveViewModel.isEmpiricallyReliable, "Live database N>=30 must be empirically reliable")
            XCTAssertNotEqual(liveViewModel.empiricalConfidenceDisplay, "—", "Live database N>=30 must show empirical confidence")
        }
    }
}
