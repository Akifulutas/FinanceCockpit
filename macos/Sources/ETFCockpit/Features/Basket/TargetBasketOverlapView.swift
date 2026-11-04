import SwiftUI

public struct TargetBasketOverlapView: View {
    @ObservedObject public var viewModel: TargetBasketOverlapViewModel

    public init(viewModel: TargetBasketOverlapViewModel) {
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

                // MARK: - UCITS Limit Violation Alert Banner
                if viewModel.ucitsStatus.isEvaluated && !viewModel.ucitsStatus.isCompliant {
                    ucitsViolationBanner
                }

                // MARK: - Overlap & Concentration KPI Row
                kpiSection

                // MARK: - Tab Picker
                tabPickerSection

                // MARK: - Tab Content
                switch viewModel.selectedTab {
                case .overlapMatrix:
                    overlapMatrixTabContent
                case .topConsolidated:
                    topConsolidatedTabContent
                case .driftRebalance:
                    driftRebalanceTabContent
                case .holdingsSets:
                    holdingsSetsTabContent
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.holdingsSets.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Target Basket & Overlap Analysis")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? "UCITS 5/10/40 Compliant" : "Limit Violation") : "Not Evaluated",
                        level: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? .success : .error) : .neutral,
                        icon: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? "checkmark.shield.fill" : "exclamationmark.shield.fill") : "questionmark.circle"
                    )
                }

                Text("ETF Pairwise Overlap Matrix, Consolidated Company Exposure & Rebalancing Plan")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.triggerRebalancePlan() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isExecutingAction {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "slider.horizontal.3")
                        }
                        Text("Calculate Rebalancing Plan")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!viewModel.hasTargetWeights || viewModel.isExecutingAction)
                .help(!viewModel.hasTargetWeights ? "No targets defined — configure in Configuration" : "Calculate rebalancing plan")

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

    private var ucitsViolationBanner: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.octagon.fill")
                    .foregroundStyle(.red)
                Text("UCITS 5/10/40 Portfolio Limit Violation Detected!")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.red)
            }

            ForEach(viewModel.ucitsStatus.violations, id: \.self) { v in
                Text("• \(v)")
                    .font(.system(size: 11))
                    .foregroundStyle(.primary)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.red.opacity(0.12)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.red.opacity(0.3), lineWidth: 1))
    }

    private var kpiSection: some View {
        HStack(spacing: 14) {
            MetricCardView(
                title: "Max Pairwise Overlap",
                value: viewModel.holdingsSets.isEmpty ? "Not Evaluated" : String(format: "%.1f%%", viewModel.maxOverlapPct),
                subtitle: viewModel.holdingsSets.isEmpty ? "Baskets not loaded" : "Inter-fund shared weight",
                trend: viewModel.holdingsSets.isEmpty ? .neutral : (viewModel.maxOverlapPct > 30 ? .down : .up),
                trendValue: viewModel.holdingsSets.isEmpty ? "—" : (viewModel.maxOverlapPct > 30 ? "HIGH" : "LOW"),
                badge: "OVERLAP",
                badgeColor: viewModel.holdingsSets.isEmpty ? .secondary : (viewModel.maxOverlapPct > 30 ? .orange : .green)
            )

            MetricCardView(
                title: "Highest Issuer Exposure",
                value: viewModel.ucitsStatus.isEvaluated ? String(format: "%.2f%%", viewModel.ucitsStatus.maxSingleWeightPct) : "Not Evaluated",
                subtitle: viewModel.ucitsStatus.isEvaluated ? (viewModel.highestConsolidatedHolding?.constituentName ?? "No data") : "No data",
                trend: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.maxSingleWeightPct > 10.0 ? .down : .neutral) : .neutral,
                trendValue: viewModel.ucitsStatus.isEvaluated ? "Limit: 10%" : "—",
                badge: "CONSOLIDATED"
            )

            MetricCardView(
                title: "UCITS 5/10/40 Status",
                value: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? "Compliant" : "Violation") : "Not Evaluated",
                subtitle: viewModel.ucitsStatus.isEvaluated ? String(format: "5-10%% group: %.1f%% / 40%%", viewModel.ucitsStatus.groupBetween5and10Pct) : "No data",
                trend: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? .up : .down) : .neutral,
                trendValue: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? "OK" : "ALERT") : "—",
                badge: "UCITS",
                badgeColor: viewModel.ucitsStatus.isEvaluated ? (viewModel.ucitsStatus.isCompliant ? .green : .red) : .secondary
            )

            MetricCardView(
                title: "Portfolio Balance State",
                value: !viewModel.hasTargetWeights ? "No Targets" : (viewModel.hasDriftWarning ? "Drifting" : "Balanced"),
                subtitle: !viewModel.hasTargetWeights ? "Target basket not configured" : "Tolerance: ±5% absolute / ±25% relative",
                trend: !viewModel.hasTargetWeights ? .neutral : (viewModel.hasDriftWarning ? .down : .up),
                trendValue: !viewModel.hasTargetWeights ? "—" : (viewModel.hasDriftWarning ? "DRIFT" : "ON TARGET"),
                badge: "DRIFT",
                badgeColor: !viewModel.hasTargetWeights ? .secondary : (viewModel.hasDriftWarning ? .orange : .green)
            )
        }
    }

    private var tabPickerSection: some View {
        HStack {
            Picker("View", selection: $viewModel.selectedTab) {
                ForEach(BasketTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 580)

            Spacer()

            if viewModel.selectedTab == .topConsolidated && !viewModel.holdingsSets.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search company or ticker...", text: $viewModel.searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 190)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
            }
        }
    }

    // MARK: - Overlap Matrix Tab

    private var overlapMatrixTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.holdingsSets.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "square.grid.3x3.topleft.filled")
                        .font(.system(size: 32))
                        .foregroundStyle(.secondary)
                    Text("No Fund Baskets Loaded")
                        .font(.system(size: 14, weight: .bold))
                    Text("Fund basket data must be loaded to compare constituents and analyze pairwise overlap.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 440)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("To import basket files via terminal:")
                            .font(.system(size: 11, weight: .semibold))
                        Text("./etf-masa sepet yukle --dosya <path> --isin <ISIN>")
                            .font(.system(size: 11, design: .monospaced))
                            .padding(6)
                            .background(Color.primary.opacity(0.05))
                            .cornerRadius(4)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(30)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            } else {
                let matrix = viewModel.overlapData.overlapMatrix
                let isins = Array(matrix.keys).sorted()

                VStack(alignment: .leading, spacing: 10) {
                    Text("Inter-Fund Pairwise Overlap Heatmap")
                        .font(.system(size: 13, weight: .bold))

                    Text("Values: ∑ min(w_A, w_B). Sum of minimum weights for identical companies held across two funds.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)

                    // Matrix Table
                    VStack(spacing: 6) {
                        // Header Row
                        HStack(spacing: 6) {
                            Text("ETF / Fund")
                                .font(.system(size: 11, weight: .bold))
                                .frame(width: 130, alignment: .leading)

                            ForEach(isins, id: \.self) { isin in
                                Text(isin.suffix(6))
                                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                                    .frame(width: 70)
                            }
                        }

                        Divider()

                        ForEach(isins, id: \.self) { isinA in
                            HStack(spacing: 6) {
                                Text(isinA.suffix(6))
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                    .frame(width: 130, alignment: .leading)

                                ForEach(isins, id: \.self) { isinB in
                                    let val = matrix[isinA]?[isinB] ?? 0.0
                                    matrixCell(val: val, isSelf: isinA == isinB)
                                }
                            }
                        }
                    }
                    .padding(14)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                }
            }
        }
    }

    private func matrixCell(val: Double, isSelf: Bool) -> some View {
        let bgColor: Color = {
            if isSelf { return Color.primary.opacity(0.04) }
            if val == 0 { return Color.clear }
            if val > 50 { return Color.red.opacity(0.25) }
            if val > 30 { return Color.orange.opacity(0.2) }
            if val > 15 { return Color.yellow.opacity(0.18) }
            return Color.blue.opacity(0.1)
        }()

        return Text(String(format: "%.1f%%", val))
            .font(.system(size: 11, weight: isSelf ? .regular : .semibold, design: .monospaced))
            .foregroundStyle(isSelf ? .secondary : .primary)
            .frame(width: 70, height: 32)
            .background(RoundedRectangle(cornerRadius: 4).fill(bgColor))
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color.primary.opacity(0.05), lineWidth: 1))
    }

    // MARK: - Top 25 Consolidated Tab

    private var topConsolidatedTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.holdingsSets.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "list.bullet.rectangle")
                        .font(.system(size: 32))
                        .foregroundStyle(.secondary)
                    Text("No Consolidated Holdings Found")
                        .font(.system(size: 14, weight: .bold))
                    Text("Consolidated company exposures cannot be calculated because no fund baskets have been loaded. Please run `./etf-masa sepet yukle`.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 440)
                }
                .frame(maxWidth: .infinity)
                .padding(30)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            } else if viewModel.filteredTopHoldings.isEmpty {
                HStack {
                    Spacer()
                    Text("No holdings match the search query.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .padding(24)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                Table(viewModel.filteredTopHoldings) {
                    TableColumn("Company") { item in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.constituentName)
                                .font(.system(size: 12, weight: .semibold))
                            if let isin = item.constituentIsin {
                                Text(isin)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    TableColumn("Ticker") { item in
                        Text(item.ticker ?? "—")
                            .font(.system(size: 11, design: .monospaced))
                    }
                    TableColumn("Consolidated Weight") { item in
                        HStack(spacing: 6) {
                            Text(String(format: "%.2f%%", item.consolidatedWeightPct))
                                .font(.system(size: 12, weight: .bold, design: .monospaced))

                            if item.consolidatedWeightPct > 5.0 {
                                StatusPillView(text: "HIGH", level: .warning, showIcon: false)
                            }
                        }
                    }
                    TableColumn("Sector") { item in
                        Text(item.sector ?? "—")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    TableColumn("Country") { item in
                        Text(item.country ?? "—")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    TableColumn("Contributing Funds") { item in
                        HStack(spacing: 4) {
                            ForEach(item.contributingFunds, id: \.self) { fund in
                                Text(fund.suffix(6))
                                    .font(.system(size: 9, design: .monospaced))
                                    .padding(.horizontal, 4)
                                    .padding(.vertical, 1)
                                    .background(Capsule().fill(Color.blue.opacity(0.12)))
                            }
                        }
                    }
                }
                .frame(minHeight: 380)
            }
        }
    }

    // MARK: - Drift & Rebalance Tab

    private var driftRebalanceTabContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !viewModel.hasTargetWeights {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("No targets defined — configure in Configuration")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.orange)
                        Text("Portfolio target weights have not been configured; drift bars and rebalancing calculations are disabled.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.1)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
            } else {
                // Cash Injection Simulator Card
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Cash-Inflow Sell-Free Rebalancing Simulator")
                                .font(.system(size: 13, weight: .bold))
                            Text("Reach target allocations by directing new incoming cash without selling existing holdings, avoiding taxes and transaction fees.")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        HStack(spacing: 8) {
                            cashPresetButton(amount: 500)
                            cashPresetButton(amount: 1000)
                            cashPresetButton(amount: 2500)
                            cashPresetButton(amount: 5000)
                        }
                    }

                    Divider()

                    HStack {
                        Text("Simulated New Cash Injection:")
                            .font(.system(size: 12, weight: .medium))

                        Text(Formatters.formatCurrency(Decimal(viewModel.simulatedCashEur)))
                            .font(.system(size: 16, weight: .bold, design: .rounded))
                            .foregroundStyle(Color.accentColor)

                        Spacer()
                    }
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))

                // Drift Comparison Table
                Text("Target vs Live Allocation & Recommended Buy Orders")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.secondary)

                ForEach(viewModel.drifts) { drift in
                    driftRow(drift: drift)
                }
            }
        }
    }

    private func cashPresetButton(amount: Double) -> some View {
        Button {
            viewModel.updateSimulatedCash(cash: amount)
        } label: {
            Text("+\(Int(amount)) €")
                .font(.system(size: 11, weight: .medium))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    Capsule().fill(viewModel.simulatedCashEur == amount ? Color.accentColor.opacity(0.2) : Color.primary.opacity(0.06))
                )
                .overlay(
                    Capsule().strokeBorder(viewModel.simulatedCashEur == amount ? Color.accentColor : Color.primary.opacity(0.1), lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }

    private func driftRow(drift: RebalanceDriftItem) -> some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text(drift.name)
                    .font(.system(size: 12, weight: .semibold))
                Text(drift.isin)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            .frame(width: 170, alignment: .leading)

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text("Target: \(String(format: "%.1f%%", drift.targetWeightPct))")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("Live: \(String(format: "%.1f%%", drift.liveWeightPct))")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                }

                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 3)
                            .fill(Color.primary.opacity(0.06))

                        RoundedRectangle(cornerRadius: 3)
                            .fill(drift.isDrifting ? Color.orange : Color.green)
                            .frame(width: min(geo.size.width, geo.size.width * CGFloat(drift.liveWeightPct / 100.0)))
                    }
                }
                .frame(height: 6)
            }
            .frame(maxWidth: .infinity)

            HStack(spacing: 4) {
                Image(systemName: drift.driftPct > 0 ? "arrow.up.right" : (drift.driftPct < 0 ? "arrow.down.right" : "equal"))
                    .font(.system(size: 10, weight: .bold))
                Text(String(format: "%+.1f%%", drift.driftPct))
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
            }
            .foregroundStyle(drift.isDrifting ? Color.orange : Color.secondary)
            .frame(width: 70, alignment: .trailing)

            VStack(alignment: .trailing, spacing: 2) {
                Text(Formatters.formatCurrency(Decimal(drift.suggestedOrderEur)))
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .foregroundStyle(drift.suggestedOrderEur > 0 ? Color.accentColor : Color.secondary)
                Text("Recommended Buy")
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
            }
            .frame(width: 110, alignment: .trailing)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(drift.isDrifting ? Color.orange.opacity(0.3) : Color.primary.opacity(0.05), lineWidth: 1))
    }

    // MARK: - Holdings Sets Tab

    private var holdingsSetsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.holdingsSets.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "folder.badge.questionmark")
                        .font(.system(size: 32))
                        .foregroundStyle(.secondary)
                    Text("No Fund Baskets Loaded")
                        .font(.system(size: 14, weight: .bold))
                    Text("No fund baskets have been loaded into the system yet. Run `./etf-masa sepet yukle` from the terminal to import basket files.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 440)
                }
                .frame(maxWidth: .infinity)
                .padding(30)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            } else {
                HStack(spacing: 14) {
                    // Left: Sets List
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Loaded Fund Baskets")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(.secondary)

                        ForEach(viewModel.holdingsSets) { s in
                            Button {
                                viewModel.selectedSetId = s.setId
                                Task { await viewModel.loadConstituents(setId: s.setId) }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(s.fundName ?? s.isin)
                                            .font(.system(size: 11, weight: .semibold))
                                        Text("\(s.totalRecords) holdings • \(s.asOfDate)")
                                            .font(.system(size: 10))
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if viewModel.selectedSetId == s.setId {
                                        Image(systemName: "checkmark")
                                            .font(.system(size: 10, weight: .bold))
                                            .foregroundStyle(Color.accentColor)
                                    }
                                }
                                .padding(10)
                                .background(RoundedRectangle(cornerRadius: 6).fill(viewModel.selectedSetId == s.setId ? Color.accentColor.opacity(0.1) : Color(nsColor: .controlBackgroundColor)))
                                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(viewModel.selectedSetId == s.setId ? Color.accentColor.opacity(0.4) : Color.primary.opacity(0.06), lineWidth: 1))
                            }
                            .buttonStyle(.plain)
                        }

                        Spacer()
                    }
                    .frame(width: 250)

                    // Right: Constituents Table
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Constituents of Selected Fund")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(.secondary)

                        Table(viewModel.selectedConstituents) {
                            TableColumn("Rank") { c in
                                Text("#\(c.itemOrder)")
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                            TableColumn("Holding Name") { c in
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(c.constituentName)
                                        .font(.system(size: 11, weight: .semibold))
                                    if let isin = c.constituentIsin {
                                        Text(isin)
                                            .font(.system(size: 9, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                            TableColumn("Weight") { c in
                                Text(Formatters.formatPercentage(c.weightPct, decimalPlaces: 2))
                                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                            }
                            TableColumn("Sector") { c in
                                Text(c.sector ?? "—")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                            }
                            TableColumn("Country") { c in
                                Text(c.country ?? "—")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .frame(minHeight: 400)
            }
        }
    }
}
