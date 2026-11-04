import SwiftUI
import Combine

/// Central observable state managing Cockpit shell navigation, global toolbar actions,
/// background audit verification, and subsystem ViewModel instances.
@MainActor
public final class CockpitAppState: ObservableObject {
    // MARK: - Navigation
    @Published public var selectedSection: CockpitSection = .today
    @Published public var selectedPinnedAsset: PinnedAsset? = nil
    @Published public var selectedItem: CockpitNavigationItem? = .today {
        didSet {
            if let item = selectedItem {
                selectedSection = item.section
            }
        }
    }

    // MARK: - Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol
    public let databasePath: String

    // MARK: - Subsystem ViewModels
    public let todayVM: TodayDashboardViewModel
    public let portfolioVM: PortfolioViewModel
    public let forecastVM: ForecastSettlementViewModel
    public let evaluationVM: EvaluationViewModel
    public let screenerVM: ScreenerViewModel
    public let reportsVM: ReportsViewModel
    public let researchVM: ResearchEvidenceViewModel
    public let modelRegistryVM: ModelRegistryViewModel
    public let ledgerVM: TransactionLedgerViewModel
    public let basketVM: TargetBasketOverlapViewModel
    public let thesisVM: ThesisManagementViewModel
    public let integrityVM: SystemIntegrityViewModel
    public let schedulerVM: SchedulerAutomationViewModel
    public let configurationVM: SystemConfigurationViewModel

    // MARK: - Global Toolbar & Status Bar State
    @Published public var isRunningQuickAudit: Bool = false
    @Published public var auditStatusText: String = "UNKNOWN"
    @Published public var auditStatusLevel: StatusLevel = .unknown
    @Published public var auditMessage: String? = nil

    @Published public var isRefreshing: Bool = false
    @Published public var lastGlobalRefresh: Date = Date()
    @Published public var schemaVersion: Int? = nil
    @Published public var triggerCount: Int? = nil
    @Published public var fileVaultActive: Bool? = nil
    @Published public var snapshotCount: Int? = nil
    @Published public var auditEventCount: Int? = nil
    @Published public var chainTipStatus: String? = nil

    @Published public var pinnedAssets: [PinnedAsset] = []
    @Published public var brokerSessionActive: Bool? = nil
    @Published public var marketStatusText: String? = nil
    @Published public var isMarketOpen: Bool? = nil
    @Published public var dataFreshnessText: String? = nil

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol? = nil,
        cliRunner: CLIProcessRunnerProtocol? = nil,
        databasePath: String = CockpitPathResolver.defaultDatabasePath,
        todayVM: TodayDashboardViewModel? = nil,
        portfolioVM: PortfolioViewModel? = nil,
        forecastVM: ForecastSettlementViewModel? = nil,
        evaluationVM: EvaluationViewModel? = nil,
        screenerVM: ScreenerViewModel? = nil,
        reportsVM: ReportsViewModel? = nil,
        researchVM: ResearchEvidenceViewModel? = nil,
        modelRegistryVM: ModelRegistryViewModel? = nil,
        ledgerVM: TransactionLedgerViewModel? = nil,
        basketVM: TargetBasketOverlapViewModel? = nil,
        thesisVM: ThesisManagementViewModel? = nil,
        integrityVM: SystemIntegrityViewModel? = nil,
        schedulerVM: SchedulerAutomationViewModel? = nil,
        configurationVM: SystemConfigurationViewModel? = nil
    ) {
        self.databasePath = databasePath

        // Resolve DatabaseService (with robust fallback to avoid crashing on uninitialized environments)
        let resolvedDB: DatabaseServiceProtocol
        if let databaseService {
            resolvedDB = databaseService
        } else {
            do {
                resolvedDB = try DatabaseService(databasePath: databasePath)
            } catch {
                CockpitLogger.shared.warning("Direct DatabaseService failed to open at '\(databasePath)': \(error.localizedDescription). Initializing FallbackDatabaseService.")
                resolvedDB = FallbackDatabaseService()
            }
        }
        self.databaseService = resolvedDB

        // Resolve CLIProcessRunner
        let resolvedCLI: CLIProcessRunnerProtocol = cliRunner ?? CLIProcessRunner()
        self.cliRunner = resolvedCLI

        // Initialize subsystem ViewModels
        self.todayVM = todayVM ?? TodayDashboardViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.portfolioVM = portfolioVM ?? PortfolioViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.forecastVM = forecastVM ?? ForecastSettlementViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.evaluationVM = evaluationVM ?? EvaluationViewModel(cliRunner: resolvedCLI)
        self.screenerVM = screenerVM ?? ScreenerViewModel(cliRunner: resolvedCLI)
        self.reportsVM = reportsVM ?? ReportsViewModel(cliRunner: resolvedCLI)
        self.researchVM = researchVM ?? ResearchEvidenceViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.modelRegistryVM = modelRegistryVM ?? ModelRegistryViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.ledgerVM = ledgerVM ?? TransactionLedgerViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.basketVM = basketVM ?? TargetBasketOverlapViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.thesisVM = thesisVM ?? ThesisManagementViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.integrityVM = integrityVM ?? SystemIntegrityViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.schedulerVM = schedulerVM ?? SchedulerAutomationViewModel(databaseService: resolvedDB, cliRunner: resolvedCLI)
        self.configurationVM = configurationVM ?? SystemConfigurationViewModel(cliRunner: resolvedCLI, databaseService: resolvedDB)
    }

    // MARK: - Formatted Properties
    public var formattedLastRefresh: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: lastGlobalRefresh)
    }

    // MARK: - Navigation Helpers
    public func selectSection(_ section: CockpitSection) {
        selectedPinnedAsset = nil
        selectedSection = section
        selectedItem = section.defaultItem
    }

    public func selectPinnedAsset(_ asset: PinnedAsset) {
        selectedPinnedAsset = asset
    }

    public func selectCategory(_ category: CockpitNavigationCategory) {
        guard let firstItem = category.items.first else { return }
        selectedItem = firstItem
    }

    // MARK: - Quick Audit Trigger
    public func runQuickAudit() async {
        isRunningQuickAudit = true
        auditMessage = "Running integrity verification..."
        do {
            let result = try await cliRunner.runVerifyIntegrity()
            schemaVersion = result.schemaVersion
            triggerCount = result.triggerCount
            fileVaultActive = result.fileVaultActive
            snapshotCount = result.snapshotsCount
            auditEventCount = result.auditEventsCount
            chainTipStatus = result.chainTipStatus

            if result.ok {
                auditStatusText = (result.chainTipStatus.isEmpty || result.chainTipStatus == "UNKNOWN") ? "MATCH_SEALED" : result.chainTipStatus
                auditStatusLevel = .success
                let fvText = result.fileVaultActive ? "FileVault enabled" : "FileVault disabled"
                auditMessage = "Integrity verified: \(result.triggerCount) triggers active, \(fvText), hash chain sealed."
                await integrityVM.loadData()
            } else {
                auditStatusText = (result.chainTipStatus.isEmpty || result.chainTipStatus == "UNKNOWN") ? "INTEGRITY_FAILURE" : result.chainTipStatus
                auditStatusLevel = .error
                auditMessage = "Critical integrity failure detected!"
            }
        } catch {
            auditStatusText = "ERROR"
            auditStatusLevel = .error
            auditMessage = "Verification error: \(error.localizedDescription)"
        }
        isRunningQuickAudit = false
        lastGlobalRefresh = Date()
    }

    // MARK: - Dynamic State Loaders
    public func loadInitialData() async {
        await loadPinnedAssets()
        await loadBrokerSession()
        await loadMarketStatus()
    }

    public func loadPinnedAssets() async {
        do {
            let positions = try await databaseService.fetchPositions()
            if positions.isEmpty {
                self.pinnedAssets = []
                self.dataFreshnessText = "No Quotes"
                return
            }

            self.pinnedAssets = positions.map { pos in
                let price = pos.computedMid.map { NSDecimalNumber(decimal: $0).doubleValue }
                    ?? (pos.quantity > 0 ? NSDecimalNumber(decimal: pos.brokerValuation / pos.quantity).doubleValue : 0.0)
                let sym = Self.symbol(for: pos.isin, displayName: pos.displayName)
                let shares = NSDecimalNumber(decimal: pos.quantity).doubleValue
                let isFresh = pos.qualityStatus.uppercased() == "FRESH" || pos.qualityStatus.uppercased() == "LIVE"
                return PinnedAsset(
                    id: sym,
                    symbol: sym,
                    isin: pos.isin,
                    name: pos.displayName,
                    priceEur: price,
                    changePct: nil,
                    shares: shares,
                    isFresh: isFresh
                )
            }

            if positions.first(where: { $0.qualityStatus.uppercased() == "FRESH" || $0.qualityStatus.uppercased() == "LIVE" }) != nil {
                self.dataFreshnessText = "Live"
            } else if positions.first(where: { $0.qualityStatus.uppercased() == "AGED" || $0.qualityStatus.uppercased() == "OUTDATED" }) != nil {
                self.dataFreshnessText = "Delayed"
            } else if positions.first(where: { $0.qualityStatus.uppercased() == "OFF_HOURS" }) != nil {
                self.dataFreshnessText = "Closed"
            } else {
                self.dataFreshnessText = "No Quotes"
            }
        } catch {
            CockpitLogger.shared.warning("Failed to load pinned assets: \(error.localizedDescription)")
            self.pinnedAssets = []
            self.dataFreshnessText = "No Quotes"
        }
    }

    public func loadBrokerSession() async {
        do {
            let res = try await cliRunner.runCommand(arguments: ["giris", "--json"])
            if res.isSuccess, let data = res.stdout.data(using: .utf8) {
                struct SessionJSON: Decodable {
                    let active: Bool?
                    let session_ok: Bool?
                }
                if let sess = try? JSONDecoder().decode(SessionJSON.self, from: data) {
                    self.brokerSessionActive = sess.active ?? sess.session_ok
                    return
                }
            }
            self.brokerSessionActive = nil
        } catch {
            self.brokerSessionActive = nil
        }
    }

    public func loadMarketStatus() async {
        do {
            let res = try await cliRunner.runCommand(arguments: ["durum", "--json"])
            if res.isSuccess, let data = res.stdout.data(using: .utf8) {
                struct DurumIntegrity: Decodable {
                    let schema_version: Int?
                    let trigger_count: Int?
                    let snapshots: Int?
                    let audit_events: Int?
                    let chain_tip_status: String?
                    let ok: Bool?
                }
                struct DurumJSON: Decodable {
                    let integrity: DurumIntegrity?
                    let market_status: String?
                    let is_market_open: Bool?
                }
                if let durum = try? JSONDecoder().decode(DurumJSON.self, from: data) {
                    if let integ = durum.integrity {
                        self.schemaVersion = integ.schema_version
                        self.triggerCount = integ.trigger_count
                        self.snapshotCount = integ.snapshots
                        self.auditEventCount = integ.audit_events
                        self.chainTipStatus = integ.chain_tip_status
                        if integ.ok == true {
                            self.auditStatusText = (integ.chain_tip_status == nil || integ.chain_tip_status == "UNKNOWN") ? "MATCH_SEALED" : (integ.chain_tip_status ?? "MATCH_SEALED")
                            self.auditStatusLevel = (integ.chain_tip_status == "MATCH_SEALED" || integ.chain_tip_status == "AHEAD_OF_SEALED") ? .success : .warning
                        } else {
                            self.auditStatusText = "INTEGRITY_FAILURE"
                            self.auditStatusLevel = .error
                        }
                    }
                    if let ms = durum.market_status {
                        self.marketStatusText = ms
                    }
                    if let mo = durum.is_market_open {
                        self.isMarketOpen = mo
                    }
                }
            }
        } catch {
            // Keep nil or fallback
        }

        // Deterministic XETR schedule fallback if CLI durum didn't provide market_status
        if self.isMarketOpen == nil {
            var cal = Calendar(identifier: .gregorian)
            if let cetTz = TimeZone(identifier: "Europe/Berlin") {
                cal.timeZone = cetTz
            }
            let now = Date()
            let weekday = cal.component(.weekday, from: now)
            let isWeekend = (weekday == 1 || weekday == 7)
            let hour = cal.component(.hour, from: now)
            let minute = cal.component(.minute, from: now)
            let currentSec = (hour * 3600) + (minute * 60)
            let openSec = 9 * 3600 // 09:00 CET
            let closeSec = (17 * 3600) + (30 * 60) // 17:30 CET

            let isOpen = !isWeekend && (currentSec >= openSec && currentSec <= closeSec)
            self.isMarketOpen = isOpen
            self.marketStatusText = isOpen ? "XETR: Open" : (isWeekend ? "Market Closed (Weekend)" : "XETR: Closed")
        }
    }

    public static func symbol(for isin: String, displayName: String) -> String {
        let known: [String: String] = [
            "IE00B3YLTY66": "SPYI",
            "IE00BKM4GZ66": "IS3N",
            "IE00BP3QZ825": "IS3R",
            "IE00BP3QZB59": "IS3S",
            "IE00B4L5Y983": "EUNL",
            "IE00BK5BQT80": "VWCE",
            "IE00B5BMR087": "SXR8",
            "IE00B4K48X80": "SXR7",
            "IE00BP3QZ601": "IS3Q",
            "IE00BF4RFH31": "IUSN",
            "US0378331005": "AAPL",
            "US5949181045": "MSFT",
            "US67066G1040": "NVDA",
            "US02079K3059": "GOOGL",
            "US0231351067": "AMZN",
            "DE0007164600": "SAP",
            "NL0010273215": "ASML",
            "DE0007236101": "SIE"
        ]
        if let s = known[isin] { return s }
        let tokens = displayName.split(separator: " ")
        if let first = tokens.first, first.count >= 2, first.count <= 5, first.allSatisfy({ $0.isLetter || $0.isNumber }) {
            return String(first).uppercased()
        }
        return String(isin.prefix(4))
    }

    // MARK: - Manual Refresh Current View
    public func refreshCurrentView() async {
        isRefreshing = true
        defer {
            isRefreshing = false
            lastGlobalRefresh = Date()
        }

        await loadInitialData()

        switch selectedItem {
        case .today, .none:
            await todayVM.loadData()
        case .portfolio:
            await portfolioVM.loadData()
        case .forecast:
            await forecastVM.loadData()
        case .evaluation:
            await evaluationVM.loadData()
        case .screener:
            await screenerVM.loadData()
        case .reports:
            await reportsVM.loadReports()
        case .research:
            await researchVM.loadData()
        case .modelRegistry:
            await modelRegistryVM.loadData()
        case .ledger:
            await ledgerVM.loadData()
        case .basket:
            await basketVM.loadData()
        case .thesis:
            await thesisVM.loadData()
        case .integrity:
            await integrityVM.loadData()
        case .scheduler:
            await schedulerVM.loadData()
        case .configuration:
            await configurationVM.loadConfiguration()
        }
    }

    // MARK: - Refresh All Views
    public func refreshAllViews() async {
        isRefreshing = true
        defer {
            isRefreshing = false
            lastGlobalRefresh = Date()
        }

        async let td: () = todayVM.loadData()
        async let p: () = portfolioVM.loadData()
        async let f: () = forecastVM.loadData()
        async let ev: () = evaluationVM.loadData()
        async let sc: () = screenerVM.loadData()
        async let rp: () = reportsVM.loadReports()
        async let r: () = researchVM.loadData()
        async let m: () = modelRegistryVM.loadData()
        async let l: () = ledgerVM.loadData()
        async let b: () = basketVM.loadData()
        async let t: () = thesisVM.loadData()
        async let i: () = integrityVM.loadData()
        async let s: () = schedulerVM.loadData()
        async let c: () = configurationVM.loadConfiguration()
        async let pa: () = loadPinnedAssets()
        async let bs: () = loadBrokerSession()
        async let ms: () = loadMarketStatus()

        _ = await (td, p, f, ev, sc, rp, r, m, l, b, t, i, s, c, pa, bs, ms)
    }
}
