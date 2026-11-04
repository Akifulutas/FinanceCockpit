import SwiftUI
import Combine

public enum ForecastSegment: String, CaseIterable, Identifiable, Sendable {
    case today = "Today's Forecasts"
    case ledger = "Settlement Ledger"
    case scorecard = "Model Scorecard"

    public var id: String { rawValue }
}

public enum ForecastSortField: String, CaseIterable, Sendable {
    case expectedReturn = "Expected Return"
    case targetPrice = "Target Price"
    case referencePrice = "Reference Price"
    case isin = "ISIN"
    case model = "Model"
    case direction = "Direction"
    case confidence = "Confidence"
}

public enum ForecastSortOrder: Sendable {
    case ascending
    case descending

    public mutating func toggle() {
        self = (self == .ascending) ? .descending : .ascending
    }
}

@MainActor
public final class ForecastSettlementViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var forecastEntries: [ForecastEntryItem] = []
    @Published public var performanceSummary: ForecastPerformanceSummary?

    @Published public var selectedSegment: ForecastSegment = .today
    @Published public var searchText: String = ""
    @Published public var selectedDate: String?
    @Published public var sortField: ForecastSortField = .expectedReturn
    @Published public var sortOrder: ForecastSortOrder = .descending

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var statusMessage: String?
    @Published public var errorMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
    }

    // MARK: - Computed Properties

    public var totalSettledCount: Int {
        performanceSummary?.totalSettledCount ?? 0
    }

    public var hitsCount: Int {
        performanceSummary?.hitsCount ?? 0
    }

    public var hitRatePct: Double? {
        performanceSummary?.hitRatePct
    }

    public var mapePct: Double? {
        performanceSummary?.mapePct
    }

    public var maeEur: Double? {
        performanceSummary?.maeEur
    }

    public var unsettledCount: Int {
        performanceSummary?.unsettledCount ?? 0
    }

    public var isEmpiricallyReliable: Bool {
        Formatters.isEmpiricallyReliable(observationCount: totalSettledCount)
    }

    /// MANDATORY EMPIRICAL CONFIDENCE:
    /// Suppressed to "—" when totalSettledCount < 30.
    public var empiricalConfidenceDisplay: String {
        Formatters.formatEmpiricalConfidence(observationCount: totalSettledCount, hitRatePct: hitRatePct)
    }

    public var martingaleFlatHitRatePct: Double? {
        performanceSummary?.martingaleFlatHitRatePct
    }

    public var momentumHitRatePct: Double? {
        performanceSummary?.momentumHitRatePct
    }

    public var baselineOutperformance: Bool? {
        performanceSummary?.baselineOutperformance
    }

    public func toggleSort(field: ForecastSortField) {
        if sortField == field {
            sortOrder.toggle()
        } else {
            sortField = field
            switch field {
            case .expectedReturn, .referencePrice, .targetPrice, .confidence:
                sortOrder = .descending
            case .isin, .model, .direction:
                sortOrder = .ascending
            }
        }
    }

    public var filteredTodayForecasts: [ForecastEntryItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let filtered = query.isEmpty ? forecastEntries : forecastEntries.filter {
            $0.isin.lowercased().contains(query) ||
            $0.modelId.lowercased().contains(query) ||
            $0.direction.rawValue.lowercased().contains(query)
        }

        return filtered.sorted { a, b in
            let isAsc = sortOrder == .ascending
            switch sortField {
            case .isin:
                return isAsc ? a.isin < b.isin : a.isin > b.isin
            case .model:
                return isAsc ? a.modelId < b.modelId : a.modelId > b.modelId
            case .direction:
                return isAsc ? a.direction.rawValue < b.direction.rawValue : a.direction.rawValue > b.direction.rawValue
            case .referencePrice:
                return isAsc ? a.referencePrice < b.referencePrice : a.referencePrice > b.referencePrice
            case .targetPrice:
                return isAsc ? a.targetPrice < b.targetPrice : a.targetPrice > b.targetPrice
            case .expectedReturn:
                let retA = a.expectedReturnPct ?? 0
                let retB = b.expectedReturnPct ?? 0
                return isAsc ? retA < retB : retA > retB
            case .confidence:
                let confA = a.confidencePct ?? 0
                let confB = b.confidencePct ?? 0
                return isAsc ? confA < confB : confA > confB
            }
        }
    }

    public var filteredLedgerRecords: [ForecastPerformanceItem] {
        let records = performanceSummary?.recentRecords ?? []
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if query.isEmpty {
            return records
        }
        return records.filter {
            $0.isin.lowercased().contains(query) ||
            $0.modelId.lowercased().contains(query) ||
            $0.targetDate.contains(query)
        }
    }

    // MARK: - Actions

    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            async let entriesTask = databaseService.fetchForecastEntries(targetDate: selectedDate)
            async let perfTask = databaseService.fetchForecastPerformance()

            let (entries, perf) = try await (entriesTask, perfTask)
            self.forecastEntries = entries
            self.performanceSummary = perf
            self.lastRefreshDate = Date()
            self.isLoading = false
        } catch {
            self.errorMessage = "Failed to load forecast data: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func triggerMorningForecast() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Generating morning forecasts (09:30 CET)..."

        do {
            let result = try await cliRunner.runForecastMorning()
            self.lastActionResult = result
            if result.isSuccess {
                statusMessage = "Morning forecasts generated and cryptographically sealed."
                await loadData()
            } else {
                errorMessage = "Forecast generation failed: \(result.message)"
            }
        } catch {
            errorMessage = "Forecast command error: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func triggerEveningSettlement() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Executing evening settlement (17:40 CET)..."

        do {
            let result = try await cliRunner.runSettleEvening()
            self.lastActionResult = result
            if result.isSuccess {
                statusMessage = "Evening settlement completed and scorecard updated."
                await loadData()
            } else {
                errorMessage = "Settlement failed: \(result.message)"
            }
        } catch {
            errorMessage = "Settlement command error: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func triggerSimulation(days: Int = 30) async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Running historical session simulation (\(days) days)..."

        do {
            let result = try await cliRunner.runForecastSimulation(days: days)
            self.lastActionResult = result
            if result.isSuccess {
                statusMessage = "Historical simulation completed and scorecard sealed."
                await loadData()
            } else {
                errorMessage = "Simulation failed: \(result.message)"
            }
        } catch {
            errorMessage = "Simulation command error: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }
}
