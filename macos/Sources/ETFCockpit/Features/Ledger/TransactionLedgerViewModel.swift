import SwiftUI
import Combine

public enum LedgerTab: String, CaseIterable, Identifiable, Sendable {
    case transactions = "Transaction Ledger"
    case corporateActions = "Corporate Actions"
    case reconciliations = "4D Reconciliation"

    public var id: String { rawValue }
}

public enum DateRangeFilter: String, CaseIterable, Identifiable, Sendable {
    case all = "All"
    case last30Days = "Last 30 Days"
    case last90Days = "Last 90 Days"
    case yearToDate = "Year to Date"

    public var id: String { rawValue }
}

@MainActor
public final class TransactionLedgerViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var transactions: [TransactionItem] = []
    @Published public var corporateActions: [CorporateActionItem] = []
    @Published public var reconciliations: [ReconciliationItem] = []

    @Published public var selectedTab: LedgerTab = .transactions
    @Published public var selectedTxType: String? = nil
    @Published public var selectedDateRange: DateRangeFilter = .all
    @Published public var searchText: String = ""
    @Published public var selectedTransaction: TransactionItem? = nil

    @Published public var totalTransactionCount: Int = 0
    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    public static let transactionTypes = [
        ("BUY", "Buy", "cart.badge.plus"),
        ("SELL", "Sell", "cart.badge.minus"),
        ("DIVIDEND", "Dividend", "dollarsign.circle"),
        ("SAVINGS_PLAN", "Savings Plan", "calendar.badge.clock"),
        ("DEPOSIT", "Deposit", "arrow.down.left"),
        ("WITHDRAWAL", "Withdrawal", "arrow.up.right"),
        ("TAX", "Tax Withholding", "percent"),
        ("FEE", "Fee / Commission", "tag")
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
            async let countTask = databaseService.fetchTransactionCount()
            async let caTask = databaseService.fetchCorporateActions()
            async let recTask = databaseService.fetchReconciliations()

            let totalCount = try await countTask
            let (actions, recs) = try await (caTask, recTask)

            var allTxs: [TransactionItem] = []
            let pageSize = 100
            var offset = 0
            while offset < totalCount {
                let page = try await databaseService.fetchTransactions(limit: pageSize, offset: offset)
                if page.isEmpty { break }
                allTxs.append(contentsOf: page)
                offset += page.count
            }

            if allTxs.isEmpty && totalCount == 0 {
                allTxs = try await databaseService.fetchTransactions()
            }

            self.totalTransactionCount = totalCount > 0 ? totalCount : allTxs.count
            self.transactions = allTxs
            self.corporateActions = actions
            self.reconciliations = recs

            if selectedTransaction == nil || !allTxs.contains(where: { $0.id == selectedTransaction?.id }) {
                self.selectedTransaction = allTxs.first
            }

            lastRefreshDate = Date()
            isLoading = false
        } catch {
            CockpitLogger.shared.error("TransactionLedgerViewModel.loadData failed: \(error.localizedDescription)")
            self.errorMessage = "Failed to load transaction ledger: \(error.localizedDescription)"
            self.isLoading = false
        }
    }


    // MARK: - Filtered Views

    public var filteredTransactions: [TransactionItem] {
        var result = transactions

        if let type = selectedTxType, !type.isEmpty {
            let target = type.uppercased()
            result = result.filter { tx in
                let t = tx.txType.uppercased()
                let s = tx.side?.uppercased() ?? ""
                let sub = tx.subType?.uppercased() ?? ""

                switch target {
                case "BUY":
                    return t == "BUY" || s == "BUY" || sub == "BUY" || t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN"
                case "SELL":
                    return t == "SELL" || s == "SELL" || sub == "SELL"
                case "DIVIDEND":
                    return t == "DIVIDEND" || sub == "DISTRIBUTION" || sub == "DIVIDEND"
                case "SAVINGS_PLAN":
                    return t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN"
                case "DEPOSIT":
                    return t == "DEPOSIT" || sub == "DEPOSIT" || sub.contains("TRANSFER_IN")
                case "WITHDRAWAL":
                    return t == "WITHDRAWAL" || sub == "WITHDRAWAL" || sub.contains("TRANSFER_OUT")
                case "TAX":
                    return t == "TAX" || sub.contains("TAX")
                case "FEE":
                    return t == "FEE" || sub.contains("FEE")
                default:
                    return t == target || s == target || sub == target
                }
            }
        }

        // Date range filter
        let now = Date()
        let calendar = Calendar.current
        switch selectedDateRange {
        case .all:
            break
        case .last30Days:
            if let cutoff = calendar.date(byAdding: .day, value: -30, to: now) {
                let formatter = ISO8601DateFormatter()
                let cutoffStr = formatter.string(from: cutoff)
                result = result.filter { $0.eventTime >= cutoffStr }
            }
        case .last90Days:
            if let cutoff = calendar.date(byAdding: .day, value: -90, to: now) {
                let formatter = ISO8601DateFormatter()
                let cutoffStr = formatter.string(from: cutoff)
                result = result.filter { $0.eventTime >= cutoffStr }
            }
        case .yearToDate:
            let year = calendar.component(.year, from: now)
            let ytdPrefix = "\(year)-01-01"
            result = result.filter { $0.eventTime >= ytdPrefix }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            result = result.filter {
                ($0.isin?.lowercased().contains(query) ?? false) ||
                ($0.description?.lowercased().contains(query) ?? false) ||
                $0.txType.lowercased().contains(query) ||
                ($0.subType?.lowercased().contains(query) ?? false) ||
                ($0.side?.lowercased().contains(query) ?? false) ||
                ($0.brokerTxId?.lowercased().contains(query) ?? false)
            }
        }

        return result
    }

    // MARK: - Computed Totals & Reconciliations

    public var totalTransactionsCount: Int {
        totalTransactionCount > 0 ? totalTransactionCount : transactions.count
    }

    public var totalBuyAmountEur: Decimal {
        transactions
            .filter {
                let t = $0.txType.uppercased()
                let s = $0.side?.uppercased() ?? ""
                let sub = $0.subType?.uppercased() ?? ""
                return t == "BUY" || s == "BUY" || sub == "BUY" || t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN"
            }
            .reduce(Decimal(0)) { $0 + abs($1.amount) }
    }

    public var totalSellAmountEur: Decimal {
        transactions
            .filter {
                let t = $0.txType.uppercased()
                let s = $0.side?.uppercased() ?? ""
                let sub = $0.subType?.uppercased() ?? ""
                return t == "SELL" || s == "SELL" || sub == "SELL"
            }
            .reduce(Decimal(0)) { $0 + abs($1.amount) }
    }

    public var totalDividendAmountEur: Decimal {
        transactions
            .filter {
                let t = $0.txType.uppercased()
                let sub = $0.subType?.uppercased() ?? ""
                return t == "DIVIDEND" || sub == "DISTRIBUTION" || sub == "DIVIDEND"
            }
            .reduce(Decimal(0)) { $0 + abs($1.amount) }
    }

    public var totalTaxWithheldEur: Decimal {
        transactions
            .filter {
                let t = $0.txType.uppercased()
                let sub = $0.subType?.uppercased() ?? ""
                return t == "TAX" || sub.contains("TAX")
            }
            .reduce(Decimal(0)) { $0 + abs($1.amount) }
    }


    public var latestReconciliation: ReconciliationItem? {
        reconciliations.first
    }

    public var isFullyReconciled: Bool {
        guard let latest = latestReconciliation else { return true }
        return latest.isFullyReconciled
    }

    public var cashGapEur: Decimal? {
        latestReconciliation?.cashGapEur
    }

    public var hasCashGapAlert: Bool {
        guard let gap = cashGapEur else { return false }
        return abs(NSDecimalNumber(decimal: gap).doubleValue) > 0.01
    }

    // MARK: - Actions

    public func triggerFetchTransactions() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Fetching transaction history from Scalable Capital..."

        do {
            let result = try await cliRunner.runCommand(arguments: ["islemler", "cek"])
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Transactions updated successfully."
                await loadData()
            } else {
                errorMessage = "Failed to fetch transactions: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Command error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }

    public func triggerReconciliation() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Running 4-dimensional reconciliation (Shares, Cash, Valuation, Cost Basis)..."

        do {
            let result = try await cliRunner.runCommand(arguments: ["mutabakat", "--detay"])
            lastActionResult = result

            if result.isSuccess {
                statusMessage = "Reconciliation completed."
                await loadData()
            } else {
                errorMessage = "Reconciliation failed: \(result.stderr.isEmpty ? result.message : result.stderr)"
            }
        } catch {
            errorMessage = "Reconciliation error: \(error.localizedDescription)"
        }

        isExecutingAction = false
    }

    public func runReconciliation() async {
        await triggerReconciliation()
    }
}
