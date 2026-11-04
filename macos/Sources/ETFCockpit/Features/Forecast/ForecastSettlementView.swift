import SwiftUI

public struct ForecastSettlementView: View {
    @ObservedObject public var viewModel: ForecastSettlementViewModel
    @State private var isShowingMorningConfirmAlert: Bool = false
    @State private var isShowingEveningConfirmAlert: Bool = false
    @State private var isShowingSimulationConfirmAlert: Bool = false

    public init(viewModel: ForecastSettlementViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header & Live Session Timer
                headerSection

                // MARK: - Error & Status Banners
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

                // MARK: - Scorecard KPI Metric Cards
                kpiSection

                // MARK: - Segment Picker & Filter & Sort
                segmentPickerSection

                // MARK: - Segment Content
                switch viewModel.selectedSegment {
                case .today:
                    todayForecastsSection
                case .ledger:
                    settlementLedgerSection
                case .scorecard:
                    modelScorecardSection
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .alert("Confirm Morning Forecast", isPresented: $isShowingMorningConfirmAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Confirm & Generate") {
                Task { await viewModel.triggerMorningForecast() }
            }
        } message: {
            Text("Deterministic models will execute for 10 instruments (5 ETFs + 5 Equities) and newly generated forecasts will be cryptographically sealed into the database. Do you want to proceed?")
        }
        .alert("Confirm Evening Settlement", isPresented: $isShowingEveningConfirmAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Confirm & Settle") {
                Task { await viewModel.triggerEveningSettlement() }
            }
        } message: {
            Text("End-of-day market closing prices will be fetched, reconciled against morning forecasts, and the accuracy scorecard updated. Do you want to proceed?")
        }
        .alert("Confirm Historical Simulation", isPresented: $isShowingSimulationConfirmAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Confirm & Start") {
                Task { await viewModel.triggerSimulation(days: 30) }
            }
        } message: {
            Text("The last 30 trading days will be simulated walk-forward and the empirical performance scorecard updated. Do you want to proceed?")
        }
        .task {
            if viewModel.forecastEntries.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text("Daily Forecast & Settlement")
                            .font(.system(size: 20, weight: .bold))

                        StatusPillView(
                            text: "\(viewModel.forecastEntries.count) Active Forecasts",
                            level: .neutral,
                            icon: "chart.line.uptrend.xyaxis"
                        )
                    }

                    Text("09:30 CET Morning Forecast & 17:40 CET Evening Settlement Cycle")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                // Action Buttons
                HStack(spacing: 10) {
                    Button {
                        isShowingMorningConfirmAlert = true
                    } label: {
                        HStack(spacing: 6) {
                            if viewModel.isExecutingAction {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "sun.horizon.fill")
                            }
                            Text("Morning Forecast (09:30)")
                        }
                    }
                    .disabled(viewModel.isExecutingAction || viewModel.isLoading)

                    Button {
                        isShowingEveningConfirmAlert = true
                    } label: {
                        HStack(spacing: 6) {
                            if viewModel.isExecutingAction {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "moon.stars.fill")
                            }
                            Text("Evening Settlement (17:40)")
                        }
                    }
                    .disabled(viewModel.isExecutingAction || viewModel.isLoading)

                    Button {
                        isShowingSimulationConfirmAlert = true
                    } label: {
                        HStack(spacing: 6) {
                            if viewModel.isExecutingAction {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "arrow.counterclockwise.circle.fill")
                            }
                            Text("Historical Simulation (30D)")
                        }
                    }
                    .disabled(viewModel.isExecutingAction || viewModel.isLoading)
                    .help("Run 30-day walk-forward simulation and update performance scorecard")

                    Button {
                        Task { await viewModel.loadData() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(viewModel.isLoading || viewModel.isExecutingAction)
                    .help("Reload")
                }
            }

            // Live Session Timer
            LiveSessionTimerView()
        }
    }

    private var kpiSection: some View {
        HStack(spacing: 12) {
            MetricCardView(
                title: "Total Settled (N)",
                value: "\(viewModel.totalSettledCount)",
                subtitle: "Pending: \(viewModel.unsettledCount)",
                trend: nil,
                badge: viewModel.isEmpiricallyReliable ? "N ≥ 30 RELIABLE" : "N < 30 SMALL SAMPLE",
                badgeColor: viewModel.isEmpiricallyReliable ? .green : .orange
            )

            // Hit Rate Card with MANDATORY N < 30 Rule
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Model Hit Rate")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    ConfidenceBadgeView(
                        observationCount: viewModel.totalSettledCount,
                        hitRatePct: viewModel.hitRatePct,
                        compact: true
                    )
                }

                Text(viewModel.empiricalConfidenceDisplay)
                    .font(.system(size: 22, weight: .bold, design: .rounded))
                    .foregroundStyle(.primary)

                Text(viewModel.isEmpiricallyReliable ? "\(viewModel.hitsCount) Hits / \(viewModel.totalSettledCount) Obs" : "Suppressed (N < 30)")
                    .font(.system(size: 11))
                    .foregroundStyle(viewModel.isEmpiricallyReliable ? Color.secondary : Color.orange)
            }
            .padding(14)
            .frame(minWidth: 160, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
            )

            MetricCardView(
                title: "Mean Absolute % Error (MAPE)",
                value: viewModel.mapePct != nil ? Formatters.formatPercentage(viewModel.mapePct, decimalPlaces: 2) : "—",
                subtitle: "Absolute Forecast Deviation",
                trend: nil
            )

            MetricCardView(
                title: "Mean Absolute Error (MAE)",
                value: viewModel.maeEur != nil ? Formatters.formatCurrency(Decimal(viewModel.maeEur!)) : "—",
                subtitle: "Price Deviation",
                trend: nil
            )

            MetricCardView(
                title: "Baseline Benchmark",
                value: viewModel.baselineOutperformance == true ? "Outperforming (+)" : (viewModel.baselineOutperformance == false ? "Underperforming (-)" : "—"),
                subtitle: "vs Martingale & Momentum",
                trend: viewModel.baselineOutperformance == true ? .up : (viewModel.baselineOutperformance == false ? .down : .neutral),
                badge: viewModel.isEmpiricallyReliable ? "VERIFIED" : "PENDING"
            )
        }
    }

    private var segmentPickerSection: some View {
        HStack(spacing: 12) {
            Picker("View", selection: $viewModel.selectedSegment) {
                ForEach(ForecastSegment.allCases) { seg in
                    Text(seg.rawValue).tag(seg)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 380)

            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search by ISIN, Model or Date...", text: $viewModel.searchText)
                    .textFieldStyle(.plain)
                if !viewModel.searchText.isEmpty {
                    Button {
                        viewModel.searchText = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.1), lineWidth: 1))
            .frame(maxWidth: 280)

            // Dedicated Sort Menu Button
            Menu {
                Section("Sort By Field") {
                    ForEach(ForecastSortField.allCases, id: \.self) { field in
                        Button {
                            if viewModel.sortField == field {
                                viewModel.sortOrder.toggle()
                            } else {
                                viewModel.sortField = field
                                viewModel.sortOrder = (field == .isin || field == .model || field == .direction) ? .ascending : .descending
                            }
                        } label: {
                            HStack {
                                Text(field.rawValue)
                                if viewModel.sortField == field {
                                    Image(systemName: "checkmark")
                                }
                            }
                        }
                    }
                }
                Divider()
                Section("Sort Order") {
                    Button {
                        viewModel.sortOrder = .descending
                    } label: {
                        HStack {
                            Text("Descending (High to Low / Z-A)")
                            if viewModel.sortOrder == .descending {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                    Button {
                        viewModel.sortOrder = .ascending
                    } label: {
                        HStack {
                            Text("Ascending (Low to High / A-Z)")
                            if viewModel.sortOrder == .ascending {
                                Image(systemName: "checkmark")
                            }
                        }
                    }
                }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "arrow.up.arrow.down")
                    Text("Sort: \(viewModel.sortField.rawValue)")
                        .font(.system(size: 11, weight: .medium))
                    Image(systemName: viewModel.sortOrder == .ascending ? "chevron.up" : "chevron.down")
                        .font(.system(size: 9, weight: .bold))
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
            }
            .menuStyle(.borderedButton)

            Spacer()
        }
    }

    // MARK: - Segment 1: Today's Forecasts Section

    private func sortableHeaderButton(
        title: String,
        field: ForecastSortField,
        width: CGFloat? = nil,
        minWidth: CGFloat? = nil,
        alignment: Alignment = .leading
    ) -> some View {
        Button {
            viewModel.toggleSort(field: field)
        } label: {
            HStack(spacing: 4) {
                if alignment == .trailing {
                    Spacer(minLength: 0)
                }
                Text(title)
                if viewModel.sortField == field {
                    Image(systemName: viewModel.sortOrder == .ascending ? "chevron.up" : "chevron.down")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(Color.accentColor)
                }
                if alignment == .leading {
                    Spacer(minLength: 0)
                }
            }
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(viewModel.sortField == field ? Color.primary : Color.secondary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .modifier(SortHeaderFrameModifier(width: width, minWidth: minWidth, alignment: alignment))
        .help("Sort by \(title)")
    }

    private var todayForecastsSection: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 12) {
                sortableHeaderButton(title: "ISIN / Instrument", field: .isin, minWidth: 180, alignment: .leading)
                sortableHeaderButton(title: "Model", field: .model, width: 90, alignment: .leading)
                sortableHeaderButton(title: "Direction", field: .direction, width: 120, alignment: .leading)
                sortableHeaderButton(title: "Reference (09:30)", field: .referencePrice, width: 110, alignment: .trailing)
                sortableHeaderButton(title: "Target Close", field: .targetPrice, width: 110, alignment: .trailing)
                sortableHeaderButton(title: "Expected Return", field: .expectedReturn, width: 110, alignment: .trailing)
                sortableHeaderButton(title: "Confidence (N<30 Rule)", field: .confidence, width: 130, alignment: .center)
            }
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.primary.opacity(0.03))

            Divider()

            if viewModel.filteredTodayForecasts.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "chart.bar.xaxis")
                        .font(.system(size: 24))
                        .foregroundStyle(.secondary)
                    Text("No active forecast records found.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 120)
            } else {
                ForEach(viewModel.filteredTodayForecasts) { item in
                    forecastRowView(item: item)
                    Divider()
                }
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private func forecastRowView(item: ForecastEntryItem) -> some View {
        let returnPct = item.expectedReturnPct
        let dirColor: Color = item.direction == .up ? .green : (item.direction == .down ? .red : .secondary)

        return HStack(spacing: 12) {
            // ISIN
            VStack(alignment: .leading, spacing: 2) {
                Text(item.isin)
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                Text(item.targetDate)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 180, alignment: .leading)

            // Model
            Text(item.modelId)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 90, alignment: .leading)

            // Direction Badge
            HStack(spacing: 4) {
                Text(item.direction.symbol)
                    .font(.system(size: 11, weight: .bold))
                Text(item.direction.displayName)
                    .font(.system(size: 10, weight: .bold))
            }
            .foregroundStyle(dirColor)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(Capsule().fill(dirColor.opacity(0.12)))
            .frame(width: 120, alignment: .leading)

            // Reference Price
            Text(Formatters.formatPrice(item.referencePrice))
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 110, alignment: .trailing)

            // Target Price
            Text(Formatters.formatPrice(item.targetPrice))
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .frame(width: 110, alignment: .trailing)

            // Expected Return
            Text(Formatters.formatPercentage(returnPct, includeSign: true, decimalPlaces: 2))
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(dirColor)
                .frame(width: 110, alignment: .trailing)

            // Confidence Badge with STRICT N < 30 RULE
            ConfidenceBadgeView(
                observationCount: viewModel.totalSettledCount,
                confidencePct: item.confidencePct,
                compact: false
            )
            .frame(width: 130, alignment: .center)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }

    // MARK: - Segment 2: Settlement Ledger Section

    private var settlementLedgerSection: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 12) {
                Text("Date / ISIN")
                    .frame(minWidth: 160, alignment: .leading)
                Text("Model")
                    .frame(width: 80, alignment: .leading)
                Text("Direction")
                    .frame(width: 60, alignment: .center)
                Text("Target Price")
                    .frame(width: 95, alignment: .trailing)
                Text("Close Price")
                    .frame(width: 95, alignment: .trailing)
                Text("Error (€)")
                    .frame(width: 90, alignment: .trailing)
                Text("Error (%)")
                    .frame(width: 80, alignment: .trailing)
                Text("Settlement Result")
                    .frame(width: 110, alignment: .center)
            }
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.primary.opacity(0.03))

            Divider()

            if viewModel.filteredLedgerRecords.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "list.clipboard")
                        .font(.system(size: 24))
                        .foregroundStyle(.secondary)
                    Text("No settlement records found.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 120)
            } else {
                ForEach(viewModel.filteredLedgerRecords) { record in
                    settlementRowView(record: record)
                    Divider()
                }
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private func settlementRowView(record: ForecastPerformanceItem) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(record.isin)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                Text(record.targetDate)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 160, alignment: .leading)

            Text(record.modelId)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 80, alignment: .leading)

            Text(record.direction.symbol)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(record.direction == .up ? Color.green : (record.direction == .down ? Color.red : Color.secondary))
                .frame(width: 60, alignment: .center)

            Text(Formatters.formatPrice(record.targetPrice))
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 95, alignment: .trailing)

            Text(record.actualClosePrice != nil ? Formatters.formatPrice(record.actualClosePrice!) : "—")
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .frame(width: 95, alignment: .trailing)

            Text(record.errorEur != nil ? Formatters.formatPrice(record.errorEur!) : "—")
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 90, alignment: .trailing)

            Text(record.errorPct != nil ? Formatters.formatPercentage(record.errorPct!, includeSign: true, decimalPlaces: 2) : "—")
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 80, alignment: .trailing)

            // Hit / Miss Badge
            if let hit = record.directionHit {
                StatusPillView(
                    text: hit ? "✓ HIT" : "✗ MISS",
                    level: hit ? .success : .error,
                    showIcon: false
                )
                .frame(width: 110, alignment: .center)
            } else {
                StatusPillView(
                    text: "PENDING",
                    level: .neutral,
                    showIcon: false
                )
                .frame(width: 110, alignment: .center)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    // MARK: - Segment 3: Model Scorecard Section

    private var modelScorecardSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            // Small sample notice if N < 30
            if !viewModel.isEmpiricallyReliable {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 18))
                        .foregroundStyle(.orange)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Small Sample Warning (N < 30 Rule)")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(.orange)
                        Text("Current settled observation count (\(viewModel.totalSettledCount)) is below the statistical threshold of 30. Empirical confidence percentages are suppressed to '—' to prevent misleading claims. The model cannot claim statistical reliability until at least 30 settled trading days are recorded.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.1)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
            }

            // Baseline Comparison Cards
            VStack(alignment: .leading, spacing: 10) {
                Text("Baseline Model Benchmarks")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                HStack(spacing: 14) {
                    baselineCard(
                        title: "Active Forecast Model",
                        value: viewModel.empiricalConfidenceDisplay,
                        subtitle: "\(viewModel.hitsCount) Hits / \(viewModel.totalSettledCount) Obs",
                        color: .blue,
                        isPrimary: true
                    )

                    baselineCard(
                        title: "Martingale Flat (FLAT)",
                        value: viewModel.martingaleFlatHitRatePct != nil ? Formatters.formatPercentage(viewModel.martingaleFlatHitRatePct!, decimalPlaces: 1) : "—",
                        subtitle: "Zero-drift Flat Baseline",
                        color: .secondary,
                        isPrimary: false
                    )

                    baselineCard(
                        title: "Momentum Baseline",
                        value: viewModel.momentumHitRatePct != nil ? Formatters.formatPercentage(viewModel.momentumHitRatePct!, decimalPlaces: 1) : "—",
                        subtitle: "Prior-day Trend Continuation",
                        color: .secondary,
                        isPrimary: false
                    )
                }
            }

            // Summary Metrics Table
            VStack(alignment: .leading, spacing: 10) {
                Text("Detailed Statistical Error Metrics")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                VStack(spacing: 8) {
                    metricRow(label: "Total Settled Observations (N)", value: "\(viewModel.totalSettledCount)")
                    Divider()
                    metricRow(label: "Successful Directional Hits", value: "\(viewModel.hitsCount)")
                    Divider()
                    metricRow(label: "Mean Absolute Percentage Error (MAPE)", value: viewModel.mapePct != nil ? Formatters.formatPercentage(viewModel.mapePct, decimalPlaces: 2) : "—")
                    Divider()
                    metricRow(label: "Mean Absolute Error (MAE)", value: viewModel.maeEur != nil ? Formatters.formatCurrency(Decimal(viewModel.maeEur!)) : "—")
                    Divider()
                    metricRow(label: "Baseline Superiority", value: viewModel.baselineOutperformance == true ? "Achieved (+)" : (viewModel.baselineOutperformance == false ? "Underperforming (-)" : "Undetermined (N < 30)"))
                }
                .padding(14)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
                )
            }
        }
    }

    private func baselineCard(title: String, value: String, subtitle: String, color: Color, isPrimary: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(isPrimary ? color : .secondary)

            Text(value)
                .font(.system(size: 20, weight: .bold, design: .rounded))
                .foregroundStyle(.primary)

            Text(subtitle)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(isPrimary ? color.opacity(0.3) : Color.primary.opacity(0.08), lineWidth: isPrimary ? 1.5 : 1)
        )
    }

    private func metricRow(label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(.primary)
        }
    }
}

private struct SortHeaderFrameModifier: ViewModifier {
    let width: CGFloat?
    let minWidth: CGFloat?
    let alignment: Alignment

    func body(content: Content) -> some View {
        if let width {
            content.frame(width: width, alignment: alignment)
        } else if let minWidth {
            content.frame(minWidth: minWidth, alignment: alignment)
        } else {
            content.frame(alignment: alignment)
        }
    }
}
