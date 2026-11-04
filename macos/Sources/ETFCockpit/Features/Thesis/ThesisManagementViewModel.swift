import SwiftUI
import Combine

public enum ThesisStatusFilter: String, CaseIterable, Identifiable, Sendable {
    case all = "ALL"
    case active = "ACTIVE"
    case invalidated = "INVALIDATED"
    case superseded = "SUPERSEDED"

    public var id: String { rawValue }

    public var displayTitle: String {
        switch self {
        case .all: return "All"
        case .active: return "Active"
        case .invalidated: return "Invalidated"
        case .superseded: return "Superseded"
        }
    }
}

@MainActor
public final class ThesisManagementViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var theses: [ThesisItem] = []
    @Published public var heldPositions: [PositionItem] = []
    @Published public var selectedThesis: ThesisItem? = nil

    @Published public var selectedStatusFilter: ThesisStatusFilter = .active
    @Published public var selectedCategoryFilter: String? = nil
    @Published public var searchText: String = ""

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    // Drawer / Sheet state
    @Published public var isShowingDetailSheet: Bool = false
    @Published public var isShowingCreateSheet: Bool = false

    // New Thesis Form State (Starts completely blank per R3.3)
    @Published public var newTitle: String = ""
    @Published public var newIsin: String = ""
    @Published public var newCategory: String = "CORE"
    @Published public var newHorizon: String = "LONG_TERM"
    @Published public var newSummary: String = ""
    @Published public var newRationale: String = ""
    @Published public var newEvidencePillarsText: String = ""
    @Published public var newCounterArguments: String = ""
    @Published public var newFalsificationTriggersText: String = ""
    @Published public var newBenchmark: String = ""
    @Published public var newTargetAllocationPct: String = ""
    @Published public var newReviewDate: String = ""

    public static let categories = [
        ("CORE", "Core", "globe"),
        ("FACTOR", "Factor", "bolt"),
        ("THEMATIC", "Thematic", "sparkles"),
        ("SATELLITE", "Satellite Asset", "antenna.radiowaves.left.and.right"),
        ("STOCK", "Single Stock", "chart.line.uptrend.xyaxis"),
        ("HEDGE", "Hedge / Risk-Off", "shield")
    ]

    public static let horizons = [
        ("SHORT_TERM", "Short Term (<1Y)"),
        ("MEDIUM_TERM", "Medium Term (1-3Y)"),
        ("LONG_TERM", "Long Term (3-10Y)"),
        ("SECULAR", "Secular (>10Y)")
    ]

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
    }

    // MARK: - Data Loading

    public func loadData() async {
        isLoading = true
        errorMessage = nil

        do {
            let fetchedTheses = try await databaseService.fetchTheses()
            self.theses = fetchedTheses

            if let positions = try? await databaseService.fetchPositions() {
                self.heldPositions = positions
            }

            if selectedThesis == nil || !fetchedTheses.contains(where: { $0.id == selectedThesis?.id }) {
                self.selectedThesis = fetchedTheses.first
            }

            lastRefreshDate = Date()
            isLoading = false
        } catch {
            CockpitLogger.shared.error("ThesisManagementViewModel.loadData failed: \(error.localizedDescription)")
            self.errorMessage = "Failed to load investment theses: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func openCreateThesis(for position: PositionItem) {
        newIsin = position.isin
        newTitle = "\(!position.displayName.isEmpty ? position.displayName : position.isin) Investment Thesis"
        newCategory = "CORE"
        newHorizon = "LONG_TERM"
        newSummary = ""
        newRationale = ""
        newFalsificationTriggersText = ""
        newEvidencePillarsText = ""
        newCounterArguments = ""
        newBenchmark = ""
        newTargetAllocationPct = ""
        newReviewDate = ""
        isShowingCreateSheet = true
    }

    // MARK: - Filtering & Views

    public var filteredTheses: [ThesisItem] {
        var result = theses

        if selectedStatusFilter != .all {
            result = result.filter { $0.status.uppercased() == selectedStatusFilter.rawValue }
        }

        if let category = selectedCategoryFilter, !category.isEmpty {
            result = result.filter { $0.category.uppercased() == category.uppercased() }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                $0.title.lowercased().contains(query) ||
                $0.isin.lowercased().contains(query) ||
                $0.oneLineSummary.lowercased().contains(query) ||
                ($0.instrumentName?.lowercased().contains(query) ?? false)
            }
        }

        return result
    }

    // MARK: - Computed Health & Statistics

    public var totalThesesCount: Int {
        theses.count
    }

    public var activeThesesCount: Int {
        theses.filter { $0.status.uppercased() == "ACTIVE" }.count
    }

    public var invalidatedThesesCount: Int {
        theses.filter { $0.status.uppercased() == "INVALIDATED" }.count
    }

    public var hasBreachedThesis: Bool {
        theses.contains { falsificationStatus(for: $0) == .breached }
    }

    public var hasDelayedReview: Bool {
        theses.contains { healthStatus(for: $0) == .gecikmis }
    }

    public var kpiActiveThesesText: String {
        theses.isEmpty ? "No data" : "\(activeThesesCount)"
    }

    public var kpiHealthSummaryText: String {
        if theses.isEmpty { return "No data" }
        if theses.contains(where: { healthStatus(for: $0) == .gecikmis }) {
            return "Overdue"
        }
        if theses.contains(where: { healthStatus(for: $0) == .incelemeGunu }) {
            return "Review Due"
        }
        return "Current"
    }

    public var kpiFalsificationSummaryText: String {
        if theses.isEmpty { return "No data" }
        if theses.contains(where: { falsificationStatus(for: $0) == .breached }) {
            return "BREACHED"
        }
        return "GREEN"
    }

    public func healthStatus(for thesis: ThesisItem) -> ThesisHealthStatus {
        guard let reviewDateStr = thesis.nextReviewDate, !reviewDateStr.isEmpty else {
            return .tarihsiz
        }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withFullDate]
        guard let reviewDate = formatter.date(from: reviewDateStr) else {
            return .tarihsiz
        }

        let now = Date()
        if reviewDate < now {
            return .gecikmis
        }

        let calendar = Calendar.current
        if let warningThreshold = calendar.date(byAdding: .day, value: 7, to: now), reviewDate <= warningThreshold {
            return .incelemeGunu
        }

        return .guncel
    }

    public func falsificationStatus(for thesis: ThesisItem) -> FalsificationStatus {
        if thesis.status.uppercased() == "INVALIDATED" {
            return .breached
        }
        return .green
    }

    // MARK: - Validation

    public func validateNewThesis() -> (isValid: Bool, error: String?) {
        let trimmedTitle = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedTitle.count < 3 {
            return (false, "Thesis title must be at least 3 characters.")
        }

        let trimmedIsin = newIsin.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if !ISINValidator.isValid(trimmedIsin) {
            return (false, "Invalid ISIN: Does not comply with ISO 6166 format and Luhn checksum.")
        }

        let trimmedSummary = newSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedSummary.count < 10 {
            return (false, "Thesis summary must be at least 10 characters.")
        }

        let trimmedRationale = newRationale.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedRationale.count < 10 {
            return (false, "Economic rationale must be at least 10 characters.")
        }

        // ENFORCE CRITICAL AUDIT RULE: >= 2 falsification triggers
        let triggers = newFalsificationTriggersText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        if triggers.count < 2 {
            return (false, "Critical Rule Violation: A thesis must define at least 2 falsification triggers. Provided: \(triggers.count)")
        }

        if !newTargetAllocationPct.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let cleanPct = newTargetAllocationPct.replacingOccurrences(of: "%", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard let val = Double(cleanPct), val >= 0, val <= 100 else {
                return (false, "Target weight must be a valid percentage between 0% and 100%.")
            }
        }

        if !newReviewDate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let cleanDate = newReviewDate.trimmingCharacters(in: .whitespacesAndNewlines)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withFullDate]
            guard formatter.date(from: cleanDate) != nil else {
                return (false, "Next review date must be in YYYY-MM-DD format.")
            }
        }

        return (true, nil)
    }

    // MARK: - Actions

    public func triggerThesisHealthCheck() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Executing investment theses health check..."

        do {
            let result = try await cliRunner.runCommand(arguments: ["tez", "kontrol"])
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Thesis health check completed."
                await loadData()
            } else {
                errorMessage = "Thesis check failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Command error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }

    public func triggerCreateThesis() async {
        let validation = validateNewThesis()
        guard validation.isValid else {
            errorMessage = validation.error
            return
        }

        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Sealing new investment thesis..."

        let cleanIsin = newIsin.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let trimmedTitle = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedSummary = newSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedRationale = newRationale.trimmingCharacters(in: .whitespacesAndNewlines)

        let triggers = newFalsificationTriggersText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var payload: [String: Any] = [
            "isin": cleanIsin,
            "baslik": trimmedTitle,
            "ozet": trimmedSummary,
            "gerekce": trimmedRationale,
            "kategori": newCategory,
            "vade": newHorizon,
            "tetikleyiciler": triggers
        ]

        let pillars = newEvidencePillarsText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if !pillars.isEmpty {
            payload["kanitlar"] = pillars
        }

        let counter = newCounterArguments.trimmingCharacters(in: .whitespacesAndNewlines)
        if !counter.isEmpty {
            payload["karsi_gorus"] = counter
        }

        let targetStr = newTargetAllocationPct.replacingOccurrences(of: "%", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !targetStr.isEmpty, let targetVal = Double(targetStr) {
            let norm = targetVal > 1.0 ? targetVal / 100.0 : targetVal
            payload["hedef_agirlik"] = norm
        }

        let reviewDate = newReviewDate.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reviewDate.isEmpty {
            payload["sonraki_kontrol"] = reviewDate
        }

        var cliArgs = [
            "tez", "ekle",
            "--isin", cleanIsin,
            "--baslik", trimmedTitle,
            "--ozet", trimmedSummary,
            "--gerekce", trimmedRationale,
            "--kategori", newCategory,
            "--vade", newHorizon
        ]
        if !triggers.isEmpty {
            cliArgs.append("--tetikleyiciler")
            cliArgs.append(contentsOf: triggers)
        }
        if !pillars.isEmpty {
            cliArgs.append("--kanitlar")
            cliArgs.append(contentsOf: pillars)
        }
        if !counter.isEmpty {
            cliArgs.append(contentsOf: ["--karsi-gorus", counter])
        }
        if !targetStr.isEmpty, let targetVal = Double(targetStr) {
            let norm = targetVal > 1.0 ? targetVal / 100.0 : targetVal
            cliArgs.append(contentsOf: ["--hedef-agirlik", String(format: "%.2f", norm)])
        }
        if !reviewDate.isEmpty {
            cliArgs.append(contentsOf: ["--sonraki-kontrol", reviewDate])
        }

        do {
            let result = try await cliRunner.runCommand(arguments: cliArgs)
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "New thesis successfully sealed."
                isShowingCreateSheet = false
                resetCreateForm()
                await loadData()
            } else {
                errorMessage = "Failed to add thesis: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }

    public func resetCreateForm() {
        newTitle = ""
        newIsin = ""
        newCategory = "CORE"
        newHorizon = "LONG_TERM"
        newSummary = ""
        newRationale = ""
        newEvidencePillarsText = ""
        newCounterArguments = ""
        newFalsificationTriggersText = ""
        newBenchmark = ""
        newTargetAllocationPct = ""
        newReviewDate = ""
    }
}
