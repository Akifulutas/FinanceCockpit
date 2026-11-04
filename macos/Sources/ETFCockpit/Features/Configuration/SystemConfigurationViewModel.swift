import SwiftUI
import Combine

public enum ConfigSectionTab: String, CaseIterable, Identifiable, Sendable {
    case portfolio = "Target Basket"
    case policy = "Investment Policy"
    case modelAccess = "Model Access & Broker"
    case notifications = "Notifications & Cadence"

    public var id: String { rawValue }
}

public struct TargetWeightItem: Identifiable, Sendable, Equatable {
    public var id: String { isin }
    public let isin: String
    public let name: String
    public let role: String
    public var weightPct: Decimal // 0 to 100

    public init(isin: String, name: String, role: String, weightPct: Decimal) {
        self.isin = isin
        self.name = name
        self.role = role
        self.weightPct = weightPct
    }
}

@MainActor
public final class SystemConfigurationViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let cliRunner: CLIProcessRunnerProtocol
    public let databaseService: DatabaseServiceProtocol?

    // MARK: - Navigation Tab
    @Published public var selectedTab: ConfigSectionTab = .portfolio

    // MARK: - Portfolio Targets (portfoy.json)
    @Published public var coreIsin: String = ""
    @Published public var targetWeightItems: [TargetWeightItem] = []
    @Published public var minTradeEur: Decimal = 25
    @Published public var targetCashRatio: Decimal = 0.0 // 0 to 1
    @Published public var policyApprovalStatus: String = "TASLAK"
    @Published public var targetStatusMessage: String?
    @Published public var knownInstruments: [String: PortfoyInstrumentDTO] = [:]

    // MARK: - Investment Policies (politika.json)
    @Published public var absoluteTolerance: Decimal = 0.05 // 5%
    @Published public var relativeTolerance: Decimal = 0.25 // 25%
    @Published public var ucitsEnforcement: Bool = false
    @Published public var trendAlertThreshold: Decimal = -0.05 // -5%
    @Published public var drawdownReviewThreshold: Decimal = -0.20 // -20%
    @Published public var spreadWarningPct: Decimal = 1.0 // 1.0%
    @Published public var exchangeCalendar: String = "XETR"

    // MARK: - Model Access & Broker (Read-Only Statuses)
    @Published public var brokerCliPath: String = "/opt/homebrew/bin/sc"
    @Published public var brokerCliExists: Bool = false
    @Published public var brokerAccountIdMasked: String = "—"
    @Published public var modelProviders: [String] = []
    @Published public var chatgptAuthExists: Bool = false
    @Published public var chatgptAuthPath: String = "~/.tradingagents/chatgpt-auth.json"
    @Published public var googleModel: String = "google / gemini-3.8-flash"
    @Published public var lmStudioBaseUrl: String = "http://localhost:1234/v1"

    // MARK: - Notification Preferences & Timeframes
    @Published public var notifications: NotificationPreferences = NotificationPreferences()
    @Published public var availableTimeframes: [String] = ["1M", "3M", "6M", "1Y", "3Y", "ALL"]

    // MARK: - State & Feedback
    @Published public var isSaving: Bool = false
    @Published public var isLoading: Bool = false
    @Published public var showPolicyApprovalDialog: Bool = false
    @Published public var statusMessage: String?
    @Published public var errorMessage: String?
    @Published public var validationWarning: String?

    // MARK: - Initializer
    public init(cliRunner: CLIProcessRunnerProtocol, databaseService: DatabaseServiceProtocol? = nil) {
        self.cliRunner = cliRunner
        self.databaseService = databaseService
        resetToDefaults()
    }

    public func resetToDefaults() {
        self.coreIsin = ""
        self.targetWeightItems = []
        self.minTradeEur = 25
        self.targetCashRatio = 0.0
        self.policyApprovalStatus = "DRAFT"
        self.absoluteTolerance = 0.05
        self.relativeTolerance = 0.25
        self.ucitsEnforcement = false
        self.trendAlertThreshold = -0.05
        self.drawdownReviewThreshold = -0.20
        self.spreadWarningPct = 1.0
        self.exchangeCalendar = "XETR"
        self.targetStatusMessage = "No target defined — Basket targets not configured yet."

        self.brokerCliPath = "/opt/homebrew/bin/sc"
        self.brokerCliExists = false
        self.brokerAccountIdMasked = "—"
        self.googleModel = "google / gemini-3.8-flash"

        self.notifications = NotificationPreferences(
            morningForecastAlerts: true,
            eveningSettlementAlerts: true,
            waitingAuthAlerts: true,
            soundEnabled: true,
            defaultTimeframe: "1Y"
        )
    }

    // MARK: - Computed Properties

    public var totalTargetWeightPct: Decimal {
        targetWeightItems.reduce(Decimal(0)) { $0 + $1.weightPct }
    }

    public var isTargetWeightSumValid: Bool {
        totalTargetWeightPct <= 100.0001 && targetWeightItems.allSatisfy { $0.weightPct >= 0 }
    }

    public var maskedBrokerAccountId: String {
        brokerAccountIdMasked
    }

    // MARK: - Validation

    public func validateTargetWeights() -> (isValid: Bool, sumPct: Decimal, message: String) {
        let sum = totalTargetWeightPct
        if targetWeightItems.contains(where: { $0.weightPct < 0 }) {
            return (false, sum, "Target weights cannot be negative.")
        }
        if sum > 100.0001 {
            let diff = sum - 100.0
            return (false, sum, "Total target weight exceeds 100% (+\(diff)%). Total cannot exceed 100%.")
        }
        return (true, sum, "Target weight sum is valid (\(sum)%).")
    }

    // MARK: - Actions

    public func updateWeight(for isin: String, newWeight: Decimal) {
        if let idx = targetWeightItems.firstIndex(where: { $0.isin == isin }) {
            targetWeightItems[idx].weightPct = max(0, newWeight)
        }
    }

    public func populateFromKnownInstruments() {
        guard targetWeightItems.isEmpty, !knownInstruments.isEmpty else { return }
        self.targetWeightItems = knownInstruments.map { (isin, inst) in
            TargetWeightItem(
                isin: isin,
                name: inst.rol ?? isin,
                role: inst.rol ?? "—",
                weightPct: 0
            )
        }.sorted(by: { $0.isin < $1.isin })
    }

    public func loadConfiguration() async {
        isLoading = true
        errorMessage = nil

        // 1. Fetch cash observation for masked account ID from DB
        if let cash = try? await databaseService?.fetchCashObservations() {
            self.brokerAccountIdMasked = cash.accountIdMasked
        }

        // 2. Fetch CLI config
        do {
            let res = try await cliRunner.runCommand(arguments: ["ayar", "goster", "--json"])
            if res.isSuccess, let data = res.stdout.data(using: .utf8) {
                let decoder = JSONDecoder()
                let config = try decoder.decode(AyarGosterResponse.self, from: data)

                self.coreIsin = config.portfoy.cekirdekIsin ?? ""
                self.knownInstruments = config.portfoy.araclar ?? [:]

                let rawTargets = config.portfoy.hedefAgirliklar
                if rawTargets.isEmpty {
                    self.targetWeightItems = []
                    self.targetStatusMessage = "No target defined — Basket targets not configured yet."
                } else {
                    self.targetWeightItems = rawTargets.sorted(by: { $0.value > $1.value }).map { (isin, weight) in
                        let inst = config.portfoy.araclar?[isin]
                        let name = inst?.rol ?? isin
                        let role = inst?.rol ?? "—"
                        let pct = Decimal(weight * 100.0)
                        return TargetWeightItem(isin: isin, name: name, role: role, weightPct: pct)
                    }
                    self.targetStatusMessage = config.portfoy.hedefDurumu
                }

                self.policyApprovalStatus = config.politika.durum
                self.absoluteTolerance = Decimal(config.politika.toleransMutlak)
                self.relativeTolerance = Decimal(config.politika.toleransGoreli)
                self.trendAlertThreshold = Decimal(config.politika.trendUyari)
                self.drawdownReviewThreshold = Decimal(config.politika.dususInceleme)
                self.minTradeEur = Decimal(config.politika.minEmirEur)
                self.targetCashRatio = Decimal(config.politika.nakitHedefi)
                self.ucitsEnforcement = config.politika.ucitsKontrolu

                self.brokerCliPath = config.broker.cliPath
                self.brokerCliExists = config.broker.cliExists

                self.modelProviders = config.modelErisim.providers
                self.chatgptAuthExists = config.modelErisim.chatgptAuthExists
                self.chatgptAuthPath = config.modelErisim.chatgptAuthPath
                self.googleModel = config.modelErisim.googleModel
            }
        } catch {
            CockpitLogger.shared.warning("Failed to load configuration via CLI: \(error.localizedDescription)")
        }

        isLoading = false
    }

    public func savePortfolioTargets() async -> Bool {
        let validation = validateTargetWeights()
        guard validation.isValid else {
            self.errorMessage = validation.message
            return false
        }

        isSaving = true
        errorMessage = nil
        statusMessage = "Saving portfolio target parameters..."

        var targetsDict: [String: Double] = [:]
        for item in targetWeightItems where item.weightPct > 0 {
            let doubleVal = NSDecimalNumber(decimal: item.weightPct / 100.0).doubleValue
            targetsDict[item.isin] = doubleVal
        }

        var araclarDict: [String: Any] = [:]
        for (isin, inst) in knownInstruments {
            var itemDict: [String: Any] = [:]
            if let r = inst.rol { itemDict["rol"] = r }
            if let t = inst.tur { itemDict["tur"] = t }
            if let y = inst.yahoo { itemDict["yahoo"] = y }
            if let f = inst.faktor { itemDict["faktor"] = f }
            araclarDict[isin] = itemDict
        }

        let payload: [String: Any] = [
            "cekirdek_isin": coreIsin.isEmpty ? "IE00B3YLTY66" : coreIsin,
            "araclar": araclarDict,
            "hedef_agirliklar": targetsDict
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            self.errorMessage = "JSON serialization error"
            self.isSaving = false
            return false
        }

        do {
            let res = try await cliRunner.runCommand(
                arguments: ["ayar", "yaz", "--dosya", "portfoy", "--json", "-"],
                stdin: jsonString
            )
            if res.isSuccess {
                self.statusMessage = "Target basket saved successfully."
                await loadConfiguration()
                self.isSaving = false
                return true
            } else {
                self.errorMessage = res.message.isEmpty ? res.stderr : res.message
                self.isSaving = false
                return false
            }
        } catch {
            self.errorMessage = "CLI error: \(error.localizedDescription)"
            self.isSaving = false
            return false
        }
    }

    public func saveInvestmentPolicies(confirmed: Bool = false) async -> Bool {
        if (policyApprovalStatus == "ONAYLANDI" || policyApprovalStatus == "APPROVED") && !confirmed {
            showPolicyApprovalDialog = true
            return false
        }

        isSaving = true
        errorMessage = nil
        statusMessage = "Updating investment policy..."

        let payload: [String: Any] = [
            "durum": policyApprovalStatus,
            "tolerans_mutlak": NSDecimalNumber(decimal: absoluteTolerance).doubleValue,
            "tolerans_goreli": NSDecimalNumber(decimal: relativeTolerance).doubleValue,
            "trend_uyari": NSDecimalNumber(decimal: trendAlertThreshold).doubleValue,
            "dusus_inceleme": NSDecimalNumber(decimal: drawdownReviewThreshold).doubleValue,
            "min_emir_eur": NSDecimalNumber(decimal: minTradeEur).doubleValue,
            "nakit_hedefi": NSDecimalNumber(decimal: targetCashRatio).doubleValue,
            "ucits_kontrolu": ucitsEnforcement
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            self.errorMessage = "JSON serialization error"
            self.isSaving = false
            return false
        }

        var args = ["ayar", "yaz", "--dosya", "politika", "--json", "-"]
        if confirmed || policyApprovalStatus == "ONAYLANDI" || policyApprovalStatus == "APPROVED" {
            args.append("--onayla-politika")
        }

        do {
            let res = try await cliRunner.runCommand(arguments: args, stdin: jsonString)
            if res.isSuccess {
                self.statusMessage = "Investment policy parameters saved successfully."
                await loadConfiguration()
                self.isSaving = false
                return true
            } else {
                self.errorMessage = res.message.isEmpty ? res.stderr : res.message
                self.isSaving = false
                return false
            }
        } catch {
            self.errorMessage = "CLI error: \(error.localizedDescription)"
            self.isSaving = false
            return false
        }
    }
}
