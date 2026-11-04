import SwiftUI

public struct TransactionLedgerView: View {
    @ObservedObject public var viewModel: TransactionLedgerViewModel

    public init(viewModel: TransactionLedgerViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header
                headerSection

                // MARK: - Banners
                if let error = viewModel.errorMessage {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                        Text(error)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.red)
                        Spacer()
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.red.opacity(0.1)))
                }

                if let status = viewModel.statusMessage {
                    HStack(spacing: 8) {
                        Image(systemName: "info.circle.fill")
                            .foregroundStyle(.blue)
                        Text(status)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.blue)
                        Spacer()
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.blue.opacity(0.1)))
                }

                // MARK: - Cash Gap Alert Banner (if any)
                if viewModel.hasCashGapAlert, let gap = viewModel.cashGapEur {
                    cashGapAlertBanner(gap: gap)
                }

                // MARK: - Unreconciled Warning Banner
                if viewModel.reconciliations.isEmpty {
                    unreconciledBanner
                }

                // MARK: - 4-Way Reconciliation Status KPI Row
                reconciliationKpiSection

                // MARK: - Financial Volume KPI Row
                volumeKpiSection

                // MARK: - Tab Picker
                tabPickerSection

                // MARK: - Tab Content
                switch viewModel.selectedTab {
                case .transactions:
                    transactionsTabContent
                case .corporateActions:
                    corporateActionsTabContent
                case .reconciliations:
                    reconciliationsTabContent
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.transactions.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Transaction Ledger & Corporate Actions")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.totalTransactionsCount) Transactions Recorded",
                        level: .neutral,
                        icon: "list.bullet.rectangle"
                    )
                }

                Text("Versioned Transaction Ledger, Corporate Actions & 4D Reconciliation Engine")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.triggerFetchTransactions() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isExecutingAction {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text("Fetch Transactions (Scalable)")
                    }
                }
                .buttonStyle(.bordered)
                .disabled(viewModel.isExecutingAction)

                Button {
                    Task { await viewModel.triggerReconciliation() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark.seal.fill")
                        Text("Run Reconciliation")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isExecutingAction)

                Button {
                    Task { await viewModel.loadData() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .help("Reload")
            }
        }
    }

    private func cashGapAlertBanner(gap: Decimal) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "exclamationmark.octagon.fill")
                .font(.system(size: 22))
                .foregroundStyle(.red)

            VStack(alignment: .leading, spacing: 2) {
                Text("Unexplained Cash Discrepancy (Cash Gap Alert)!")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.red)

                Text("An unexplained discrepancy of \(Formatters.formatCurrency(gap)) was detected between broker cash balance and ledger sum.")
                    .font(.system(size: 11))
                    .foregroundStyle(.primary.opacity(0.85))
            }

            Spacer()

            Button("Inspect Reconciliation Details") {
                viewModel.selectedTab = .reconciliations
            }
            .buttonStyle(.bordered)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.red.opacity(0.12)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.red.opacity(0.3), lineWidth: 1))
    }

    private var unreconciledBanner: some View {
        HStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 24))
                .foregroundStyle(.orange)

            VStack(alignment: .leading, spacing: 3) {
                Text("⚠️ Transaction ledger has never been reconciled")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.primary)

                Text("No reconciliation has been executed yet between broker balance/positions and the local SQLite ledger.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button {
                Task { await viewModel.triggerReconciliation() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.seal.fill")
                    Text("Run Reconciliation")
                        .fontWeight(.semibold)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .disabled(viewModel.isExecutingAction)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.1)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
    }

    private var reconciliationKpiSection: some View {
        let rec = viewModel.latestReconciliation

        return HStack(spacing: 14) {
            MetricCardView(
                title: "1. Shares Count Reconciliation",
                value: rec?.sharesMatch ?? true ? "Matched" : "Mismatch",
                subtitle: "All position quantities",
                trend: rec?.sharesMatch ?? true ? .up : .down,
                trendValue: rec?.sharesMatch ?? true ? "100%" : "GAP",
                badge: "SHARES",
                badgeColor: rec?.sharesMatch ?? true ? .green : .red
            )

            MetricCardView(
                title: "2. Cash Balance Reconciliation",
                value: rec?.cashMatch ?? true ? "Matched" : "Discrepancy",
                subtitle: "Cash gap: \(Formatters.formatCurrency(rec?.cashGapEur ?? 0))",
                trend: rec?.cashMatch ?? true ? .up : .down,
                trendValue: rec?.cashMatch ?? true ? "0 € GAP" : "ALERT",
                badge: "CASH",
                badgeColor: rec?.cashMatch ?? true ? .green : .red
            )

            MetricCardView(
                title: "3. Valuation Reconciliation",
                value: rec?.valuationMatch ?? true ? "Matched" : "Mismatch",
                subtitle: "Broker vs Independent Mid",
                trend: rec?.valuationMatch ?? true ? .up : .down,
                trendValue: rec?.valuationMatch ?? true ? "OK" : "GAP",
                badge: "VALUATION",
                badgeColor: rec?.valuationMatch ?? true ? .green : .red
            )

            MetricCardView(
                title: "4. Cost Basis Reconciliation",
                value: rec?.costBasisMatch ?? true ? "Matched" : "Mismatch",
                subtitle: "WAC / FIFO computation",
                trend: rec?.costBasisMatch ?? true ? .up : .down,
                trendValue: rec?.costBasisMatch ?? true ? "OK" : "GAP",
                badge: "COST BASIS",
                badgeColor: rec?.costBasisMatch ?? true ? .green : .red
            )
        }
    }

    private var volumeKpiSection: some View {
        HStack(spacing: 14) {
            MetricCardView(
                title: "Total Capital Invested (Buy)",
                value: Formatters.formatCurrency(viewModel.totalBuyAmountEur),
                subtitle: "Buys & Savings Plans",
                trend: .up,
                badge: "BUY"
            )

            MetricCardView(
                title: "Total Sell Volume",
                value: Formatters.formatCurrency(viewModel.totalSellAmountEur),
                subtitle: "Realized Disposals",
                trend: .neutral,
                badge: "SELL"
            )

            MetricCardView(
                title: "Gross Dividend Income",
                value: Formatters.formatCurrency(viewModel.totalDividendAmountEur),
                subtitle: "Cash Distributions",
                trend: .up,
                badge: "DIVIDEND",
                badgeColor: .green
            )

            MetricCardView(
                title: "Tax Withheld",
                value: Formatters.formatCurrency(viewModel.totalTaxWithheldEur),
                subtitle: "German/EU Source Withholding",
                trend: .neutral,
                badge: "TAX",
                badgeColor: .orange
            )
        }
    }

    private var tabPickerSection: some View {
        HStack {
            Picker("View", selection: $viewModel.selectedTab) {
                ForEach(LedgerTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 480)

            Spacer()

            if viewModel.selectedTab == .transactions {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search by ISIN, description...", text: $viewModel.searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 200)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
            }
        }
    }

    // MARK: - Transactions Tab

    private var transactionsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            // Filters
            HStack(spacing: 12) {
                HStack(spacing: 6) {
                    Text("Transaction Type:")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)

                    Picker("", selection: $viewModel.selectedTxType) {
                        Text("All").tag(String?.none)
                        ForEach(TransactionLedgerViewModel.transactionTypes, id: \.0) { typeKey, typeTitle, _ in
                            Text(typeTitle).tag(String?.some(typeKey))
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 140)
                }

                HStack(spacing: 6) {
                    Text("Date Range:")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)

                    Picker("", selection: $viewModel.selectedDateRange) {
                        ForEach(DateRangeFilter.allCases) { range in
                            Text(range.rawValue).tag(range)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 150)
                }

                Spacer()

                Text("\(viewModel.filteredTransactions.count) transactions listed")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            if viewModel.filteredTransactions.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "list.bullet.rectangle")
                            .font(.system(size: 30))
                            .foregroundStyle(.secondary)
                        Text("No transactions match the selected filters.")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    .padding(30)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                Table(viewModel.filteredTransactions) {
                    TableColumn("Date") { tx in
                        Text(tx.eventTime)
                            .font(.system(size: 11, design: .monospaced))
                    }
                    TableColumn("Type") { tx in
                        txTypeBadge(tx)
                    }
                    TableColumn("ISIN / Description") { tx in
                        VStack(alignment: .leading, spacing: 2) {
                            if let isin = tx.isin {
                                Text(isin)
                                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                            }
                            if let desc = tx.description {
                                Text(desc)
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                    }
                    TableColumn("Units") { tx in
                        if let qty = tx.quantity {
                            Text(Formatters.formatQuantity(qty))
                                .font(.system(size: 11, design: .monospaced))
                        } else {
                            Text("—")
                                .foregroundStyle(.secondary)
                        }
                    }
                    TableColumn("Unit Price") { tx in
                        if let price = tx.limitPrice {
                            Text(Formatters.formatPrice(price))
                                .font(.system(size: 11, design: .monospaced))
                        } else {
                            Text("—")
                                .foregroundStyle(.secondary)
                        }
                    }
                    TableColumn("Amount") { tx in
                        Text(Formatters.formatCurrency(tx.amount))
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(tx.amount >= 0 ? .green : .primary)
                    }
                    TableColumn("Flow Class") { tx in
                        StatusPillView(
                            text: tx.flowClassification,
                            level: tx.flowClassification == "INTERNAL" ? .neutral : .info,
                            showIcon: false
                        )
                    }
                    TableColumn("Status") { tx in
                        StatusPillView(
                            text: tx.status,
                            level: tx.status == "SETTLED" ? .success : .warning,
                            showIcon: false
                        )
                    }
                }
                .frame(minHeight: 380)
            }
        }
    }

    private func txTypeBadge(_ tx: TransactionItem) -> some View {
        let (title, color): (String, Color) = {
            let t = tx.txType.uppercased()
            let s = tx.side?.uppercased() ?? ""
            let sub = tx.subType?.uppercased() ?? ""

            if t == "BUY" || s == "BUY" || sub == "BUY" {
                return ("BUY", .blue)
            } else if t == "SELL" || s == "SELL" || sub == "SELL" {
                return ("SELL", .purple)
            } else if t == "DIVIDEND" || sub == "DISTRIBUTION" || sub == "DIVIDEND" {
                return ("DIVIDEND", .green)
            } else if t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN" {
                return ("SAVINGS", .teal)
            } else if t == "DEPOSIT" || sub == "DEPOSIT" || sub.contains("TRANSFER_IN") {
                return ("DEPOSIT", .green)
            } else if t == "WITHDRAWAL" || sub == "WITHDRAWAL" || sub.contains("TRANSFER_OUT") {
                return ("WITHDRAW", .red)
            } else if t == "TAX" || sub.contains("TAX") {
                return ("TAX", .orange)
            } else if t == "FEE" || sub.contains("FEE") {
                return ("FEE", .gray)
            } else if sub == "INTEREST" {
                return ("INTEREST", .teal)
            } else {
                return (sub.isEmpty ? t : sub, .secondary)
            }
        }()

        return Text(title)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Capsule().fill(color.opacity(0.12)))
            .overlay(Capsule().strokeBorder(color.opacity(0.3), lineWidth: 1))
    }

    // MARK: - Corporate Actions Tab

    private var corporateActionsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.corporateActions.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "arrow.triangle.branch")
                            .font(.system(size: 30))
                            .foregroundStyle(.secondary)
                        Text("No corporate action records (splits, mergers, etc.) found.")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    .padding(30)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ForEach(viewModel.corporateActions) { action in
                    corporateActionRow(action: action)
                }
            }
        }
    }

    private func corporateActionRow(action: CorporateActionItem) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.triangle.branch")
                .font(.system(size: 20))
                .foregroundStyle(.purple)

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(action.actionType.uppercased())
                        .font(.system(size: 12, weight: .bold))

                    Text("Ratio: \(action.ratio)")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.accentColor)

                    Text("ISIN: \(action.isin)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                if let desc = action.description {
                    Text(desc)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 8) {
                    Text("Effective: \(action.effectiveDate)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)

                    if let newIsin = action.newIsin {
                        Text("New ISIN: \(newIsin)")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }

                    if let approver = action.approvedBy {
                        Text("Approval: \(approver)")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer()

            StatusPillView(text: "APPROVED", level: .success, showIcon: false)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    // MARK: - Reconciliations Tab

    private var reconciliationsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.reconciliations.isEmpty {
                VStack(spacing: 12) {
                    HStack(spacing: 14) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.system(size: 26))
                            .foregroundStyle(.orange)

                        VStack(alignment: .leading, spacing: 3) {
                            Text("⚠️ Transaction ledger has never been reconciled")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(.primary)

                            Text("No reconciliation has been executed yet between broker balance/positions and the local SQLite ledger.")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Button {
                            Task { await viewModel.triggerReconciliation() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "checkmark.seal.fill")
                                Text("Run Reconciliation")
                                    .fontWeight(.semibold)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.orange)
                        .disabled(viewModel.isExecutingAction)
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.1)))
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
                }
            } else {
                ForEach(viewModel.reconciliations) { rec in
                    reconciliationRow(rec: rec)
                }
            }
        }
    }

    private func reconciliationRow(rec: ReconciliationItem) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Session: \(rec.runId)")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                    Text("Time: \(rec.reconciliationTime)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                StatusPillView(
                    text: rec.status.uppercased(),
                    level: rec.isFullyReconciled ? .success : .error,
                    showIcon: true
                )
            }

            Divider()

            HStack(spacing: 16) {
                checkFlagItem(title: "Shares", isPassed: rec.sharesMatch)
                checkFlagItem(title: "Cash", isPassed: rec.cashMatch)
                checkFlagItem(title: "Valuation", isPassed: rec.valuationMatch)
                checkFlagItem(title: "Cost Basis", isPassed: rec.costBasisMatch)

                Spacer()

                if let gap = rec.cashGapEur {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("Cash Gap")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                        Text(Formatters.formatCurrency(gap))
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(gap == 0 ? .green : .red)
                    }
                }
            }

            if let notes = rec.notes, !notes.isEmpty {
                Text("Notes: \(notes)")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    private func checkFlagItem(title: String, isPassed: Bool) -> some View {
        HStack(spacing: 4) {
            Image(systemName: isPassed ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(isPassed ? .green : .red)
            Text(title)
                .font(.system(size: 11, weight: .medium))
        }
    }
}
