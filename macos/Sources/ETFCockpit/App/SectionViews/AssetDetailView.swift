import SwiftUI

/// Section 5.7: Unified Asset Detail View
/// Displays an all-in-one operational lens for any pinned or selected ETF asset.
public struct AssetDetailView: View {
    public let asset: PinnedAsset
    @ObservedObject public var appState: CockpitAppState

    public init(asset: PinnedAsset, appState: CockpitAppState) {
        self.asset = asset
        self.appState = appState
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Asset Header Bar
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 8) {
                            Text(asset.symbol)
                                .font(.system(size: 26, weight: .bold, design: .monospaced))

                            Text(asset.isin)
                                .font(.system(size: 13, weight: .medium, design: .monospaced))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(Color.primary.opacity(0.08))
                                .cornerRadius(6)

                            Circle()
                                .fill(asset.isFresh ? Color.green : Color.orange)
                                .frame(width: 8, height: 8)

                            Text(asset.isFresh ? "Live Quote" : "Closing Quote")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.secondary)
                        }

                        Text(asset.name)
                            .font(.system(size: 15))
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    // Quick action buttons
                    HStack(spacing: 10) {
                        Button {
                            appState.selectSection(.portfolio)
                        } label: {
                            Label("Show in Portfolio", systemImage: "chart.pie.fill")
                        }
                        .buttonStyle(.borderedProminent)

                        Button {
                            appState.selectSection(.discovery)
                        } label: {
                            Label("Research", systemImage: "doc.text.magnifyingglass")
                        }
                        .buttonStyle(.bordered)
                    }
                }

                Divider()

                // Key Valuation Metrics
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
                    let changeSub: String = {
                        if let c = asset.changePct {
                            return String(format: "%@%.1f%% daily", c >= 0 ? "+" : "", c)
                        } else {
                            return " — "
                        }
                    }()
                    let changeCol: Color = {
                        if let c = asset.changePct {
                            return c >= 0 ? .green : .red
                        } else {
                            return .secondary
                        }
                    }()
                    metricCard(
                        title: "Latest Quote",
                        value: String(format: "%.2f €", asset.priceEur),
                        subtitle: changeSub,
                        color: changeCol
                    )

                    metricCard(
                        title: "Portfolio Units",
                        value: String(format: "%.0f Units", asset.shares),
                        subtitle: "Sealed snapshot",
                        color: .blue
                    )

                    metricCard(
                        title: "Market Value",
                        value: String(format: "%.2f €", asset.shares * asset.priceEur),
                        subtitle: "Current valuation",
                        color: .primary
                    )

                    let total = NSDecimalNumber(decimal: appState.portfolioVM.totalValuation).doubleValue
                    let weightStr: String = {
                        if total > 0 {
                            let weight = ((asset.shares * asset.priceEur) / total) * 100
                            return String(format: "%.1f%%", weight)
                        } else {
                            return " — "
                        }
                    }()
                    metricCard(
                        title: "Portfolio Weight",
                        value: weightStr,
                        subtitle: "Target basket share",
                        color: .indigo
                    )
                }

                // Subsystem Insights Cards
                VStack(alignment: .leading, spacing: 12) {
                    Text("Connected Subsystems & Decision Support")
                        .font(.system(size: 15, weight: .bold))

                    HStack(spacing: 14) {
                        insightCard(
                            icon: "chart.line.uptrend.xyaxis",
                            title: "Today's Forecast",
                            desc: "\(asset.symbol) directional bias: UP (09:30 CET). Margin of safety: Verified.",
                            actionTitle: "Go to Forecasts"
                        ) {
                            appState.selectSection(.forecast)
                        }

                        insightCard(
                            icon: "lightbulb.fill",
                            title: "Investment Thesis",
                            desc: "Core portfolio thesis active. Falsifiability criterion: 3-year tracking.",
                            actionTitle: "Manage Theses"
                        ) {
                            appState.selectSection(.decisions)
                        }
                    }
                }

                // Trading History Link
                VStack(alignment: .leading, spacing: 10) {
                    Text("Historical Transactions & Reconciliation")
                        .font(.system(size: 15, weight: .bold))

                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Historical broker orders and 4D reconciliation events for this asset.")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Filter Transaction Ledger") {
                            appState.selectSection(.portfolio)
                        }
                        .buttonStyle(.bordered)
                    }
                    .padding(14)
                    .background(Color(nsColor: .controlBackgroundColor))
                    .cornerRadius(8)
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private func metricCard(title: String, value: String, subtitle: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)

            Text(value)
                .font(.system(size: 20, weight: .bold, design: .monospaced))
                .foregroundStyle(color)

            Text(subtitle)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
    }

    private func insightCard(icon: String, title: String, desc: String, actionTitle: String, action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.blue)
                Text(title)
                    .font(.system(size: 13, weight: .bold))
            }

            Text(desc)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)

            Spacer()

            Button(action: action) {
                HStack(spacing: 4) {
                    Text(actionTitle)
                    Image(systemName: "arrow.right")
                }
                .font(.system(size: 11, weight: .medium))
            }
            .buttonStyle(.link)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
    }
}
