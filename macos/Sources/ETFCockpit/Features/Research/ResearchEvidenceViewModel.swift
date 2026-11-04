import SwiftUI
import Combine

public enum ResearchTab: String, CaseIterable, Identifiable, Sendable {
    case claims = "Claims & Evidence"
    case metrics = "Metrics"
    case sources = "Sources"
    case critic = "Red-Team Critic Audit"

    public var id: String { rawValue }
}

public enum ClaimTypeFilter: String, CaseIterable, Identifiable, Sendable {
    case all = "All"
    case fact = "fact"
    case sourcedEstimate = "sourced_estimate"
    case computation = "computation"
    case inference = "inference"

    public var id: String { rawValue }

    public var displayTitle: String {
        switch self {
        case .all: return "All"
        case .fact: return "Fact"
        case .sourcedEstimate: return "Sourced Estimate"
        case .computation: return "Computation"
        case .inference: return "Inference"
        }
    }
}

public enum VerificationFilter: String, CaseIterable, Identifiable, Sendable {
    case all = "All"
    case verified = "VERIFIED"
    case unverified = "UNVERIFIED"
    case contradicted = "CONTRADICTED"

    public var id: String { rawValue }

    public var displayTitle: String {
        switch self {
        case .all: return "All"
        case .verified: return "Verified"
        case .unverified: return "Unverified"
        case .contradicted: return "Contradicted / Refuted"
        }
    }
}

@MainActor
public final class ResearchEvidenceViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var evidenceBundles: [EvidenceBundleItem] = []
    @Published public var selectedBundle: EvidenceBundleItem?
    @Published public var metrics: [MetricItem] = []
    @Published public var sources: [SourceItem] = []

    @Published public var selectedTab: ResearchTab = .claims
    @Published public var selectedClaimTypeFilter: ClaimTypeFilter = .all
    @Published public var selectedVerificationFilter: VerificationFilter = .all
    @Published public var searchText: String = ""

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    // Action sheet / research launcher state
    @Published public var isShowingResearchSheet: Bool = false
    @Published public var researchTargetTickerOrIsin: String = "IE00B3YLTY66"
    @Published public var researchHorizon: String = "uzun"

    // Red-Team Critic Engine State
    @Published public var criticReportStatus: CriticVerdict = .notRun
    @Published public var criticScorePct: Double? = nil
    @Published public var criticFindings: [CriticFindingItem] = []

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
            async let bundlesTask = databaseService.fetchEvidenceBundles()
            async let sourcesTask = databaseService.fetchSources()
            async let metricsTask = databaseService.fetchMetrics(bundleId: nil)

            let (bundles, fetchedSources, fetchedMetrics) = try await (bundlesTask, sourcesTask, metricsTask)

            self.evidenceBundles = bundles
            self.sources = fetchedSources
            self.metrics = fetchedMetrics

            if selectedBundle == nil || !bundles.contains(where: { $0.id == selectedBundle?.id }) {
                self.selectedBundle = bundles.first
            }

            evaluateCriticStatus()
            lastRefreshDate = Date()
            isLoading = false
        } catch {
            CockpitLogger.shared.error("ResearchEvidenceViewModel.loadData failed: \(error.localizedDescription)")
            self.errorMessage = "Failed to load research data: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func selectBundle(bundle: EvidenceBundleItem) {
        self.selectedBundle = bundle
        evaluateCriticStatus()
    }

    // MARK: - Filtered Views

    public var currentClaims: [ClaimItem] {
        selectedBundle?.claims ?? evidenceBundles.flatMap { $0.claims }
    }

    public var filteredClaims: [ClaimItem] {
        var result = currentClaims

        if selectedClaimTypeFilter != .all {
            result = result.filter { $0.claimType.lowercased() == selectedClaimTypeFilter.rawValue.lowercased() }
        }

        if selectedVerificationFilter != .all {
            result = result.filter { $0.verificationStatus.uppercased() == selectedVerificationFilter.rawValue.uppercased() }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                $0.claimText.lowercased().contains(query) ||
                ($0.quoteVerbatim?.lowercased().contains(query) ?? false) ||
                ($0.sourceTitle?.lowercased().contains(query) ?? false) ||
                ($0.publisher?.lowercased().contains(query) ?? false)
            }
        }

        return result
    }

    public var filteredMetrics: [MetricItem] {
        let currentBundleId = selectedBundle?.bundleId
        var result = metrics
        if let currentBundleId = currentBundleId, !currentBundleId.isEmpty {
            let bundleSpecific = metrics.filter { $0.bundleId == currentBundleId }
            if !bundleSpecific.isEmpty {
                result = bundleSpecific
            }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                $0.metricName.lowercased().contains(query) ||
                $0.value.lowercased().contains(query) ||
                ($0.unit?.lowercased().contains(query) ?? false)
            }
        }

        return result
    }

    public var filteredSources: [SourceItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if query.isEmpty {
            return sources
        }
        return sources.filter {
            $0.title.lowercased().contains(query) ||
            ($0.publisher?.lowercased().contains(query) ?? false) ||
            $0.sourceType.lowercased().contains(query) ||
            ($0.contentSha256?.lowercased().contains(query) ?? false)
        }
    }

    // MARK: - Computed Statistics

    public var totalClaimsCount: Int {
        currentClaims.count
    }

    public var verifiedClaimsCount: Int {
        currentClaims.filter { $0.verificationStatus.uppercased() == "VERIFIED" }.count
    }

    public var unverifiedClaimsCount: Int {
        currentClaims.filter { $0.verificationStatus.uppercased() != "VERIFIED" }.count
    }

    public var totalMetricsCount: Int {
        filteredMetrics.count
    }

    public var totalSourcesCount: Int {
        sources.count
    }

    public var verificationRatePct: Double? {
        guard totalClaimsCount > 0 else { return nil }
        return (Double(verifiedClaimsCount) / Double(totalClaimsCount)) * 100.0
    }

    // MARK: - Critic Engine Evaluation

    private func evaluateCriticStatus() {
        let claims = currentClaims
        if claims.isEmpty {
            criticReportStatus = .notRun
            criticScorePct = nil
            criticFindings = []
            return
        }

        let unverified = claims.filter { $0.verificationStatus.uppercased() != "VERIFIED" }
        let score = (Double(claims.count - unverified.count) / Double(claims.count)) * 100.0
        criticScorePct = score

        if score >= 90.0 {
            criticReportStatus = .pass
        } else if score >= 75.0 {
            criticReportStatus = .needsReview
        } else if score >= 50.0 {
            criticReportStatus = .materialWarning
        } else {
            criticReportStatus = .fatalDefect
        }

        criticFindings = [
            CriticFindingItem(
                name: "Verified Claim Ratio",
                description: "Proportion of claims in the sealed bundle backed by primary sources.",
                isPassed: unverified.isEmpty,
                detail: "\(claims.count - unverified.count)/\(claims.count) claims verified (\(unverified.count) unverified)"
            )
        ]
    }

    // MARK: - Action Execution

    public func triggerResearch(query: String?, ticker: String?) async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Starting deep sourced research..."

        do {
            let result = try await cliRunner.runResearch(query: query, ticker: ticker)
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Research successfully completed and sealed."
                await loadData()
            } else {
                errorMessage = "Research failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Research execution error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }

    public func triggerResearch(isin: String, horizon: String?) async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Running research for \(isin)..."

        do {
            let result = try await cliRunner.runResearch(isin: isin, horizon: horizon)
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "\(isin) research sealed."
                await loadData()
            } else {
                errorMessage = "Research failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }
}
