import SwiftUI
import Combine

public enum BasketTab: String, CaseIterable, Identifiable, Sendable {
    case overlapMatrix = "Overlap Matrix"
    case topConsolidated = "Top 25 Consolidated Holdings"
    case driftRebalance = "Rebalancing & Drift"
    case holdingsSets = "Loaded Baskets"

    public var id: String { rawValue }
}

@MainActor
public final class TargetBasketOverlapViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol
    public let configURL: URL?

    public var effectiveConfigURL: URL {
        if let configURL { return configURL }
        return CockpitPathResolver.defaultPortfolioConfigURL
    }

    // MARK: - Published State
    @Published public var holdingsSets: [HoldingsSetItem] = []
    @Published public var overlapData: HoldingsOverlapData = HoldingsOverlapData()
    @Published public var top25Consolidated: [ConsolidatedHoldingItem] = []
    @Published public var drifts: [RebalanceDriftItem] = []
    @Published public var ucitsStatus: UCITSComplianceStatus = UCITSComplianceStatus(isCompliant: false, maxSingleWeightPct: 0, groupBetween5and10Pct: 0, violations: [], isEvaluated: false)

    @Published public var selectedTab: BasketTab = .overlapMatrix
    @Published public var simulatedCashEur: Double = 1000.0
    @Published public var searchText: String = ""
    @Published public var selectedSetId: String? = nil
    @Published public var selectedConstituents: [HoldingConstituentItem] = []

    @Published public var targetWeights: [(isin: String, name: String, targetWeight: Double)] = []

    public var hasTargetWeights: Bool {
        !targetWeights.isEmpty
    }

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol,
        configURL: URL? = nil
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
        self.configURL = configURL
    }

    // MARK: - Target Weights Loading

    public func loadTargetWeightsFromConfig() {
        let url = effectiveConfigURL
        guard FileManager.default.fileExists(atPath: url.path) else {
            self.targetWeights = []
            return
        }

        do {
            let data = try Data(contentsOf: url)
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.targetWeights = []
                return
            }

            let rawTargets = json["hedef_agirliklar"] as? [String: Any] ?? [:]
            let rawAraclar = json["araclar"] as? [String: [String: Any]] ?? [:]

            var newTargets: [(isin: String, name: String, targetWeight: Double)] = []
            for (isin, val) in rawTargets {
                var weight: Double = 0
                if let num = val as? NSNumber {
                    weight = num.doubleValue
                } else if let str = val as? String, let parsed = Double(str) {
                    weight = parsed
                }

                // If targets are in decimal form <= 1.0 (e.g. 0.45), normalize to percent (45.0)
                if weight > 0 && weight <= 1.0 {
                    weight = weight * 100.0
                }

                let inst = rawAraclar[isin]
                let name = inst?["rol"] as? String ?? isin
                newTargets.append((isin: isin, name: name, targetWeight: weight))
            }

            self.targetWeights = newTargets.sorted(by: { $0.targetWeight > $1.targetWeight })
        } catch {
            CockpitLogger.shared.warning("Failed to parse portfoy.json: \(error.localizedDescription)")
            self.targetWeights = []
        }
    }

    // MARK: - Data Loading

    public func loadData() async {
        isLoading = true
        errorMessage = nil

        loadTargetWeightsFromConfig()

        do {
            async let setsTask = databaseService.fetchHoldingsSets()
            async let overlapTask = databaseService.fetchHoldingsOverlap()
            async let positionsTask = databaseService.fetchPositions()

            let (sets, overlap, positions) = try await (setsTask, overlapTask, positionsTask)

            self.holdingsSets = sets
            self.overlapData = overlap
            self.top25Consolidated = overlap.topConsolidatedHoldings

            if selectedSetId == nil || !sets.contains(where: { $0.id == selectedSetId }) {
                self.selectedSetId = sets.first?.setId
            }

            if let activeSetId = self.selectedSetId {
                await loadConstituents(setId: activeSetId)
            }

            computeDriftAndRebalance(positions: positions)
            evaluateUCITSCompliance()

            lastRefreshDate = Date()
            isLoading = false
        } catch {
            CockpitLogger.shared.error("TargetBasketOverlapViewModel.loadData failed: \(error.localizedDescription)")
            self.errorMessage = "Failed to load basket and overlap data: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func loadConstituents(setId: String) async {
        do {
            let constituents = try await databaseService.fetchHoldingConstituents(setId: setId)
            self.selectedConstituents = constituents
        } catch {
            CockpitLogger.shared.error("Failed to fetch constituents: \(error.localizedDescription)")
        }
    }

    // MARK: - Drift & Rebalance Calculations

    public func computeDriftAndRebalance(positions: [PositionItem]) {
        guard !targetWeights.isEmpty else {
            self.drifts = []
            return
        }

        let totalValuation = positions.reduce(0.0) { $0 + NSDecimalNumber(decimal: $1.brokerValuation).doubleValue }

        var liveWeights: [String: Double] = [:]
        for p in positions {
            let val = NSDecimalNumber(decimal: p.brokerValuation).doubleValue
            let w = totalValuation > 0 ? (val / totalValuation) * 100.0 : 0.0
            liveWeights[p.isin] = w
        }

        var newDrifts: [RebalanceDriftItem] = []
        for target in targetWeights {
            let liveW = liveWeights[target.isin] ?? 0.0
            let drift = liveW - target.targetWeight

            // Tolerance bands: ±5.0% absolute or ±25.0% relative
            let isDrifting = abs(drift) > 5.0 || (target.targetWeight > 0 && abs(drift / target.targetWeight) > 0.25)

            // Rebalance cash injection suggestion: target * (total + cash) - current
            let currentVal = (liveW / 100.0) * totalValuation
            let targetVal = (target.targetWeight / 100.0) * (totalValuation + simulatedCashEur)
            let suggestedOrder = max(0.0, targetVal - currentVal)

            newDrifts.append(RebalanceDriftItem(
                isin: target.isin,
                name: target.name,
                targetWeightPct: target.targetWeight,
                liveWeightPct: liveW,
                driftPct: drift,
                isDrifting: isDrifting,
                suggestedOrderEur: suggestedOrder
            ))
        }

        self.drifts = newDrifts
    }

    public func updateSimulatedCash(cash: Double) {
        self.simulatedCashEur = cash
        Task {
            do {
                let positions = try await databaseService.fetchPositions()
                computeDriftAndRebalance(positions: positions)
            } catch {
                // Keep existing drifts
            }
        }
    }

    // MARK: - UCITS 5/10/40 Compliance Check

    public func evaluateUCITSCompliance() {
        guard !holdingsSets.isEmpty else {
            ucitsStatus = UCITSComplianceStatus(
                isCompliant: false,
                maxSingleWeightPct: 0,
                groupBetween5and10Pct: 0,
                violations: [],
                isEvaluated: false
            )
            return
        }

        let topHoldings = top25Consolidated
        guard !topHoldings.isEmpty else {
            ucitsStatus = UCITSComplianceStatus(
                isCompliant: false,
                maxSingleWeightPct: 0,
                groupBetween5and10Pct: 0,
                violations: [],
                isEvaluated: false
            )
            return
        }

        var maxWeight = 0.0
        var group5to10Sum = 0.0
        var violations: [String] = []

        for item in topHoldings {
            let w = item.consolidatedWeightPct
            if w > maxWeight {
                maxWeight = w
            }

            if w > 10.0 {
                violations.append("Single issuer limit violation: \(item.constituentName) (\(String(format: "%.2f", w))% > 10.0%)")
            } else if w >= 5.0 && w <= 10.0 {
                group5to10Sum += w
            }
        }

        if group5to10Sum > 40.0 {
            violations.append("5-10% concentration group limit violation: Total \(String(format: "%.2f", group5to10Sum))% > 40.0%")
        }

        let isCompliant = violations.isEmpty
        ucitsStatus = UCITSComplianceStatus(
            isCompliant: isCompliant,
            maxSingleWeightPct: maxWeight,
            groupBetween5and10Pct: group5to10Sum,
            violations: violations,
            isEvaluated: true
        )
    }

    // MARK: - Filtered Views & Computed Statistics

    public var filteredTopHoldings: [ConsolidatedHoldingItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if query.isEmpty {
            return top25Consolidated
        }
        return top25Consolidated.filter {
            $0.constituentName.lowercased().contains(query) ||
            ($0.ticker?.lowercased().contains(query) ?? false) ||
            ($0.constituentIsin?.lowercased().contains(query) ?? false) ||
            ($0.sector?.lowercased().contains(query) ?? false) ||
            ($0.country?.lowercased().contains(query) ?? false)
        }
    }

    public var maxOverlapPct: Double {
        var maxVal = 0.0
        for (isinA, row) in overlapData.overlapMatrix {
            for (isinB, val) in row {
                if isinA != isinB && val > maxVal {
                    maxVal = val
                }
            }
        }
        return maxVal
    }

    public var highestConsolidatedHolding: ConsolidatedHoldingItem? {
        top25Consolidated.first
    }

    public var hasDriftWarning: Bool {
        drifts.contains { $0.isDrifting }
    }

    // MARK: - Actions

    public func triggerRebalancePlan() async {
        guard hasTargetWeights else {
            errorMessage = "No target weights defined. Please configure targets in the Configuration section."
            return
        }

        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Calculating rebalancing plan..."

        do {
            let result = try await cliRunner.runCommand(arguments: ["plan"])
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Rebalancing plan updated."
                await loadData()
            } else {
                errorMessage = "Plan calculation failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Command error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }
}
