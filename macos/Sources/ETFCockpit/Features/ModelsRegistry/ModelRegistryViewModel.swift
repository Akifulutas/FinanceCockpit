import SwiftUI
import Combine

public enum ModelRegistryTab: String, CaseIterable, Identifiable, Sendable {
    case registry = "Registered Models"
    case scorecard = "Benchmark Scorecard"
    case runs = "Execution Manifests"
    case comparison = "Local vs Cloud Analysis"

    public var id: String { rawValue }
}

public struct LocalVsLLMComparison: Sendable, Equatable {
    public let localModelCount: Int
    public let cloudModelCount: Int
    public let localChampionCount: Int
    public let cloudChampionCount: Int
    public let localAvgScorePct: Double
    public let cloudAvgScorePct: Double
    public let zeroCostEnforcement: Bool
    public let confidentialDataPrivacyEnforced: Bool

    public init(
        localModelCount: Int = 0,
        cloudModelCount: Int = 0,
        localChampionCount: Int = 0,
        cloudChampionCount: Int = 0,
        localAvgScorePct: Double = 0,
        cloudAvgScorePct: Double = 0,
        zeroCostEnforcement: Bool = true,
        confidentialDataPrivacyEnforced: Bool = true
    ) {
        self.localModelCount = localModelCount
        self.cloudModelCount = cloudModelCount
        self.localChampionCount = localChampionCount
        self.cloudChampionCount = cloudChampionCount
        self.localAvgScorePct = localAvgScorePct
        self.cloudAvgScorePct = cloudAvgScorePct
        self.zeroCostEnforcement = zeroCostEnforcement
        self.confidentialDataPrivacyEnforced = confidentialDataPrivacyEnforced
    }
}

@MainActor
public final class ModelRegistryViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var registeredModels: [ModelRegistryItem] = []
    @Published public var championModels: [ModelChampionItem] = []
    @Published public var evaluations: [ModelEvaluationItem] = []
    @Published public var modelRuns: [ModelRunItem] = []

    @Published public var selectedTab: ModelRegistryTab = .registry
    @Published public var selectedProvider: String? = nil
    @Published public var selectedTaskCategory: String? = nil
    @Published public var searchText: String = ""
    @Published public var selectedRun: ModelRunItem? = nil

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    // 4 Benchmark Tasks defined in specification
    public static let benchmarkTasks = [
        ("table_extraction", "Table & Cell Extraction", "doc.text.below.ecg"),
        ("claim_source_matching", "Claim-Source Matching", "link.badge.checkmark"),
        ("flawed_report_detection", "Flawed Report Detection (Red-Team)", "exclamationmark.shield"),
        ("turkish_semantics", "Financial Semantics & Reasoning", "character.book.closed")
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
            async let modelsTask = databaseService.fetchModelRegistry()
            async let championsTask = databaseService.fetchModelChampions()
            async let evalsTask = databaseService.fetchModelEvaluations()
            async let runsTask = databaseService.fetchModelRuns()

            let (models, champions, evals, runs) = try await (modelsTask, championsTask, evalsTask, runsTask)

            self.registeredModels = models
            self.championModels = champions
            self.evaluations = evals
            self.modelRuns = runs

            if selectedRun == nil || !runs.contains(where: { $0.id == selectedRun?.id }) {
                self.selectedRun = runs.first
            }

            lastRefreshDate = Date()
            isLoading = false
        } catch {
            CockpitLogger.shared.error("ModelRegistryViewModel.loadData failed: \(error.localizedDescription)")
            self.errorMessage = "Failed to load model registry data: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    // MARK: - Computed Properties & Filtering

    public var filteredModels: [ModelRegistryItem] {
        var result = registeredModels

        if let provider = selectedProvider, !provider.isEmpty {
            result = result.filter { $0.provider.lowercased() == provider.lowercased() }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                $0.modelName.lowercased().contains(query) ||
                $0.modelId.lowercased().contains(query) ||
                $0.provider.lowercased().contains(query) ||
                $0.accessTier.lowercased().contains(query)
            }
        }

        return result
    }

    public var filteredEvaluations: [ModelEvaluationItem] {
        var result = evaluations

        if let category = selectedTaskCategory, !category.isEmpty {
            result = result.filter { $0.taskCategory.lowercased() == category.lowercased() }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                $0.modelId.lowercased().contains(query) ||
                $0.taskCategory.lowercased().contains(query)
            }
        }

        return result
    }

    public var filteredRuns: [ModelRunItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if query.isEmpty {
            return modelRuns
        }
        return modelRuns.filter {
            $0.runId.lowercased().contains(query) ||
            $0.taskName.lowercased().contains(query) ||
            ($0.quickModelId?.lowercased().contains(query) ?? false) ||
            ($0.deepModelId?.lowercased().contains(query) ?? false) ||
            ($0.routeLabel?.lowercased().contains(query) ?? false)
        }
    }

    public func championForTask(category: String) -> ModelChampionItem? {
        championModels.first { $0.taskCategory.lowercased() == category.lowercased() }
    }

    public var totalModelsCount: Int {
        registeredModels.count
    }

    public var activeEligibleCount: Int {
        registeredModels.filter { $0.status.lowercased() == "eligible" || $0.status.lowercased() == "access_verified" }.count
    }

    public var championsCount: Int {
        championModels.count
    }

    public var localVsLLMComparisonMetrics: LocalVsLLMComparison {
        let localModels = registeredModels.filter { $0.provider.lowercased() == "local" || $0.provider.lowercased() == "lmstudio" }
        let cloudModels = registeredModels.filter { $0.provider.lowercased() != "local" && $0.provider.lowercased() != "lmstudio" }

        let localChampions = championModels.filter { $0.provider.lowercased() == "local" || $0.provider.lowercased() == "lmstudio" }
        let cloudChampions = championModels.filter { $0.provider.lowercased() != "local" && $0.provider.lowercased() != "lmstudio" }

        let localEvals = evaluations.filter { eval in
            localModels.contains(where: { $0.modelId == eval.modelId })
        }
        let cloudEvals = evaluations.filter { eval in
            cloudModels.contains(where: { $0.modelId == eval.modelId })
        }

        let localAvg = localEvals.isEmpty ? 0 : localEvals.reduce(0.0) { $0 + NSDecimalNumber(decimal: $1.scorePct).doubleValue } / Double(localEvals.count)
        let cloudAvg = cloudEvals.isEmpty ? 0 : cloudEvals.reduce(0.0) { $0 + NSDecimalNumber(decimal: $1.scorePct).doubleValue } / Double(cloudEvals.count)

        return LocalVsLLMComparison(
            localModelCount: localModels.count,
            cloudModelCount: cloudModels.count,
            localChampionCount: localChampions.count,
            cloudChampionCount: cloudChampions.count,
            localAvgScorePct: localAvg,
            cloudAvgScorePct: cloudAvg,
            zeroCostEnforcement: true,
            confidentialDataPrivacyEnforced: true
        )
    }

    // MARK: - Actions

    public func triggerModelEvaluation() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Evaluating models against verification benchmark suites..."

        do {
            let result = try await cliRunner.runCommand(arguments: ["model", "degerlendir"])
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Model evaluation completed and champions updated."
                await loadData()
            } else {
                errorMessage = "Model evaluation failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Evaluation execution error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }
}
