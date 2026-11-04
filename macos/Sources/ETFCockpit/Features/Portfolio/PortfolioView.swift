import SwiftUI

public struct PortfolioView: View {
    @ObservedObject public var viewModel: PortfolioViewModel
    @State private var selectedPosition: PositionItem?

    public init(viewModel: PortfolioViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header
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

                // MARK: - KPI Metric Cards
                kpiSection

                // MARK: - Cash Breakdown Section
                cashBreakdownSection

                // MARK: - Visual Allocations
                allocationsSection

                // MARK: - Positions & Holdings Table
                positionsTableSection
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.positions.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Portfolio & Holdings")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.positions.count) Positions",
                        level: .neutral,
                        icon: "briefcase.fill"
                    )
                }

                if let summary = viewModel.summary, !summary.asOfDate.isEmpty {
                    Text("Last Close / Valuation: \(Formatters.formatISO8601(summary.asOfDate))")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            // Action Buttons
            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.refreshLiveQuotes() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isRefreshing {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text("Fetch Live Quotes")
                    }
                }
                .disabled(viewModel.isRefreshing || viewModel.isLoading)

                Button {
                    Task { await viewModel.loadData() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(viewModel.isLoading || viewModel.isRefreshing)
                .help("Reload")
            }
        }
    }

    private var kpiSection: some View {
        let pnlEur = viewModel.totalUnrealizedPnLEur
        let pnlPct = viewModel.totalUnrealizedPnLPct
        let pnlTrend: TrendDirection = pnlEur > 0 ? .up : (pnlEur < 0 ? .down : .neutral)
        let pnlFormatted = Formatters.formatPercentage(pnlPct, includeSign: true, decimalPlaces: 2)

        return HStack(spacing: 12) {
            MetricCardView(
                title: "Total Portfolio Value",
                value: Formatters.formatCurrency(viewModel.totalValuation),
                subtitle: "Net Asset Value",
                trend: nil,
                badge: "EUR"
            )

            MetricCardView(
                title: "Invested Securities",
                value: Formatters.formatCurrency(viewModel.investedAssets),
                subtitle: "\(viewModel.positions.count) Securities",
                trend: nil
            )

            MetricCardView(
                title: "Cash Balance",
                value: Formatters.formatCurrency(viewModel.totalCash),
                subtitle: "Including In-flight Cash",
                trend: nil
            )

            MetricCardView(
                title: "Buying Power",
                value: Formatters.formatCurrency(viewModel.buyingPower),
                subtitle: "Available Liquidity",
                trend: nil
            )

            MetricCardView(
                title: "Unrealized P&L",
                value: Formatters.formatCurrency(pnlEur),
                subtitle: "Relative to Cost Basis",
                trend: pnlTrend,
                trendValue: pnlPct != nil ? pnlFormatted : nil
            )
        }
    }

    private var cashBreakdownSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Cash & Liquidity Breakdown")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.secondary)

            HStack(spacing: 16) {
                cashDetailItem(
                    title: "Settled Cash",
                    value: Formatters.formatCurrency(viewModel.settledCash),
                    icon: "checkmark.circle.fill",
                    color: .green
                )
                cashDetailItem(
                    title: "Unsettled Cash (T+2)",
                    value: Formatters.formatCurrency(viewModel.unsettledCash),
                    icon: "clock.arrow.circlepath",
                    color: .blue
                )
                cashDetailItem(
                    title: "Accrued Cash",
                    value: Formatters.formatCurrency(viewModel.accruedCash),
                    icon: "chart.line.uptrend.xyaxis",
                    color: .orange
                )
                cashDetailItem(
                    title: "Pending Buy Orders",
                    value: Formatters.formatCurrency(viewModel.pendingBuyOrders),
                    icon: "hourglass",
                    color: .secondary
                )
                cashDetailItem(
                    title: "Estimated Tax",
                    value: Formatters.formatCurrency(viewModel.possibleTaxes),
                    icon: "building.columns.fill",
                    color: .red
                )
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

    private func cashDetailItem(title: String, value: String, icon: String, color: Color) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundStyle(color)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var allocationsSection: some View {
        HStack(alignment: .top, spacing: 16) {
            // Asset Class Allocation
            VStack(alignment: .leading, spacing: 10) {
                Text("Asset Allocation")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                VStack(spacing: 8) {
                    // Segmented visual bar
                    GeometryReader { geo in
                        HStack(spacing: 2) {
                            ForEach(viewModel.assetAllocationBreakdown) { slice in
                                Rectangle()
                                    .fill(slice.color)
                                    .frame(width: max(2, geo.size.width * CGFloat(slice.percentage / 100.0)))
                            }
                        }
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    .frame(height: 12)

                    // Breakdown legend
                    VStack(spacing: 6) {
                        ForEach(viewModel.assetAllocationBreakdown) { slice in
                            HStack {
                                Circle()
                                    .fill(slice.color)
                                    .frame(width: 8, height: 8)
                                Text(slice.name)
                                    .font(.system(size: 11, weight: .medium))
                                Spacer()
                                Text(Formatters.formatCurrency(Decimal(slice.value)))
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(.secondary)
                                Text(Formatters.formatPercentage(Decimal(slice.percentage), decimalPlaces: 1))
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                    .frame(width: 45, alignment: .trailing)
                            }
                        }
                    }
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
            .frame(maxWidth: .infinity)

            // Domicile / Geographic Exposure
            VStack(alignment: .leading, spacing: 10) {
                Text("Geographic & Domicile Breakdown")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                VStack(spacing: 6) {
                    ForEach(viewModel.geographicExposureBreakdown) { slice in
                        HStack {
                            Text(slice.title)
                                .font(.system(size: 11, weight: .medium))
                            Spacer()
                            Text(Formatters.formatCurrency(Decimal(slice.value)))
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(.secondary)
                            Text(Formatters.formatPercentage(Decimal(slice.percentage), decimalPlaces: 1))
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .frame(width: 45, alignment: .trailing)
                        }
                    }
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
            .frame(maxWidth: .infinity)
        }
    }

    private var positionsTableSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Filters and Search Bar
            HStack(spacing: 12) {
                // Category Picker
                Picker("Filter", selection: $viewModel.selectedFilter) {
                    ForEach(PositionFilter.allCases) { filter in
                        Text(filter.rawValue).tag(filter)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 220)

                // Search Field
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search by ISIN or security name...", text: $viewModel.searchText)
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

                Spacer()

                // Sort Field Picker
                Picker("Sort", selection: $viewModel.sortField) {
                    ForEach(PositionSortField.allCases) { field in
                        Text(field.rawValue).tag(field)
                    }
                }
                .frame(width: 150)

                Button {
                    viewModel.sortAscending.toggle()
                } label: {
                    Image(systemName: viewModel.sortAscending ? "arrow.up" : "arrow.down")
                }
                .help("Toggle Sort Direction")
            }

            // Positions Table View
            VStack(spacing: 0) {
                // Table Header
                tableHeaderView

                Divider()

                if viewModel.filteredPositions.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "tray")
                            .font(.system(size: 24))
                            .foregroundStyle(.secondary)
                        Text("No positions found to display.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ForEach(viewModel.filteredPositions) { position in
                        positionRowView(position: position)
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
    }

    private var tableHeaderView: some View {
        HStack(spacing: 12) {
            Text("Security / ISIN")
                .frame(minWidth: 200, alignment: .leading)
            Text("Type")
                .frame(width: 50, alignment: .center)
            Text("Units")
                .frame(width: 70, alignment: .trailing)
            Text("Market Price")
                .frame(width: 90, alignment: .trailing)
            Text("Valuation (€)")
                .frame(width: 100, alignment: .trailing)
            Text("Weight")
                .frame(width: 60, alignment: .trailing)
            Text("Profit / Loss")
                .frame(width: 110, alignment: .trailing)
            Text("Freshness")
                .frame(width: 80, alignment: .center)
        }
        .font(.system(size: 11, weight: .bold))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.primary.opacity(0.03))
    }

    private func positionRowView(position: PositionItem) -> some View {
        let weight = viewModel.weight(for: position)
        let pnlEur = position.unrealizedPnLEur
        let pnlPct = position.unrealizedPnLPct
        let pnlColor: Color = (pnlEur ?? 0) > 0 ? .green : ((pnlEur ?? 0) < 0 ? .red : .secondary)

        return HStack(spacing: 12) {
            // ISIN & Name
            VStack(alignment: .leading, spacing: 2) {
                Text(position.displayName)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
                Text(position.isin)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 200, alignment: .leading)

            // Security Type Badge
            Text(position.securityType)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .padding(.horizontal, 5)
                .padding(.vertical, 2)
                .background(
                    Capsule().fill(position.securityType.contains("ETF") ? Color.blue.opacity(0.12) : Color.purple.opacity(0.12))
                )
                .foregroundStyle(position.securityType.contains("ETF") ? Color.blue : Color.purple)
                .frame(width: 50, alignment: .center)

            // Quantity
            Text(Formatters.formatQuantity(position.quantity))
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 70, alignment: .trailing)

            // Mid Price
            Text(Formatters.formatPrice(position.computedMid ?? position.bid))
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 90, alignment: .trailing)

            // Valuation
            Text(Formatters.formatCurrency(position.brokerValuation))
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .frame(width: 100, alignment: .trailing)

            // Portfolio Weight %
            Text(Formatters.formatPercentage(weight, decimalPlaces: 1))
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 60, alignment: .trailing)

            // PnL (€ and %)
            VStack(alignment: .trailing, spacing: 1) {
                if let pnl = pnlEur {
                    Text(Formatters.formatCurrency(pnl))
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(pnlColor)
                    if let pct = pnlPct {
                        Text(Formatters.formatPercentage(pct, includeSign: true, decimalPlaces: 1))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(pnlColor)
                    }
                } else {
                    Text("—")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: 110, alignment: .trailing)

            // Freshness Pill
            FreshnessPillView(statusString: position.qualityStatus)
                .frame(width: 80, alignment: .center)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }
}
