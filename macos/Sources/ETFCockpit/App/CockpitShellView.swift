import SwiftUI

/// Main macOS Cockpit shell layout for FinanceCockpit v2.
/// Features a streamlined 6-section sidebar + pinned ETF assets,
/// unified toolbar Status Capsule, containerized sub-screens with segmented navigation,
/// and privacy-sanitized bottom activity status bar.
public struct CockpitShellView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    public init(appState: CockpitAppState) {
        self.appState = appState
    }

    public var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            sidebarContent
        } detail: {
            detailContent
        }
        .navigationTitle(currentNavigationTitle)
        .toolbar {
            cockpitToolbarContent
        }
        .task {
            await appState.loadInitialData()
        }
    }

    // MARK: - Sidebar Content (6 Sections + Pinned Assets)

    private var sidebarContent: some View {
        List {
            Section("MAIN SECTIONS") {
                ForEach(CockpitSection.allCases) { section in
                    Button {
                        appState.selectSection(section)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: section.icon)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(section.accentColor)
                                .frame(width: 20, alignment: .center)

                            Text(section.rawValue)
                                .font(.system(size: 13, weight: appState.selectedSection == section && appState.selectedPinnedAsset == nil ? .bold : .medium))
                                .foregroundStyle(appState.selectedSection == section && appState.selectedPinnedAsset == nil ? Color.accentColor : Color.primary)

                            Spacer()

                            Text("⌘\(section.shortcutNumber)")
                                .font(.system(size: 10, weight: .medium, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }

            Section("HOLDINGS") {
                if appState.pinnedAssets.isEmpty {
                    Text("No holdings available")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 4)
                } else {
                    ForEach(appState.pinnedAssets) { asset in
                        Button {
                            appState.selectPinnedAsset(asset)
                        } label: {
                            HStack(spacing: 8) {
                                Text(asset.symbol)
                                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                                    .frame(width: 44, alignment: .leading)
                                    .foregroundStyle(appState.selectedPinnedAsset?.id == asset.id ? Color.accentColor : Color.primary)

                                Text(String(format: "%.2f €", asset.priceEur))
                                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                                    .foregroundStyle(.secondary)

                                Spacer()

                                if let change = asset.changePct {
                                    HStack(spacing: 2) {
                                        Text(change >= 0 ? "▲" : "▼")
                                            .font(.system(size: 8))
                                        Text(String(format: "%.1f%%", abs(change)))
                                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                    }
                                    .foregroundStyle(change >= 0 ? Color.green : Color.red)
                                } else {
                                    Text(" — ")
                                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                }

                                Circle()
                                    .fill(asset.isFresh ? Color.green : Color.orange)
                                    .frame(width: 6, height: 6)
                            }
                            .padding(.vertical, 3)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .navigationSplitViewColumnWidth(min: 220, ideal: 245, max: 290)
    }

    // MARK: - Detail Content (Section Routing + Activity Bar)

    private var detailContent: some View {
        VStack(spacing: 0) {
            mainSectionView
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            bottomStatusBar
        }
    }

    @ViewBuilder
    private var mainSectionView: some View {
        if let asset = appState.selectedPinnedAsset {
            AssetDetailView(asset: asset, appState: appState)
        } else {
            switch appState.selectedSection {
            case .today:
                TodayDashboardView(viewModel: appState.todayVM)
            case .portfolio:
                PortfolioSectionView(appState: appState)
            case .forecast:
                ForecastSectionView(appState: appState)
            case .decisions:
                DecisionsSectionView(appState: appState)
            case .discovery:
                DiscoverySectionView(appState: appState)
            case .system:
                SystemSectionView(appState: appState)
            }
        }
    }

    // MARK: - Backwards-compatible Destination View Method (for unit tests)

    @ViewBuilder
    public func destinationView(for item: CockpitNavigationItem?) -> some View {
        switch item {
        case .today, .none:
            TodayDashboardView(viewModel: appState.todayVM)
        case .portfolio:
            PortfolioView(viewModel: appState.portfolioVM)
        case .forecast:
            ForecastSettlementView(viewModel: appState.forecastVM)
        case .evaluation:
            EvaluationView(viewModel: appState.evaluationVM)
        case .screener:
            ScreenerView(viewModel: appState.screenerVM)
        case .reports:
            ReportsView(viewModel: appState.reportsVM)
        case .research:
            ResearchEvidenceView(viewModel: appState.researchVM)
        case .modelRegistry:
            ModelRegistryView(viewModel: appState.modelRegistryVM)
        case .ledger:
            TransactionLedgerView(viewModel: appState.ledgerVM)
        case .basket:
            TargetBasketOverlapView(viewModel: appState.basketVM)
        case .thesis:
            ThesisManagementView(viewModel: appState.thesisVM)
        case .integrity:
            SystemIntegrityView(viewModel: appState.integrityVM)
        case .scheduler:
            SchedulerAutomationView(viewModel: appState.schedulerVM)
        case .configuration:
            SystemConfigurationView(viewModel: appState.configurationVM)
        }
    }

    // MARK: - Unified Cockpit Toolbar

    @ToolbarContentBuilder
    private var cockpitToolbarContent: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            // Manual Refresh button
            Button {
                Task {
                    await appState.refreshCurrentView()
                }
            } label: {
                if appState.isRefreshing {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 12, weight: .semibold))
                }
            }
            .disabled(appState.isRefreshing)
            .keyboardShortcut("r", modifiers: .command)
            .help("Refresh active view data (⌘R)")
        }
    }

    // MARK: - Bottom Status Bar (Section 4.2 Sanitized Activity Bar)

    private var bottomStatusBar: some View {
        let schemaStr = appState.schemaVersion.map { "v\($0)" } ?? "?"
        let triggerStr = appState.triggerCount.map { "\($0)" } ?? "?"
        let snapshotStr = appState.snapshotCount.map { "\($0)" } ?? "?"
        let isDbReady = appState.schemaVersion != nil && appState.triggerCount != nil

        let isSealed = appState.chainTipStatus == "MATCH_SEALED" || appState.chainTipStatus == "AHEAD_OF_SEALED"
        let isUnknown = (appState.chainTipStatus == nil || appState.chainTipStatus == "UNKNOWN") && appState.auditStatusLevel == .unknown
        let auditCountStr = appState.auditEventCount.map { "\($0)" } ?? "?"

        return HStack(spacing: 16) {
            // SQLite Database & Schema status (Privacy-sanitized, no user file paths)
            HStack(spacing: 5) {
                Circle()
                    .fill(isDbReady ? Color.green : Color.secondary)
                    .frame(width: 7, height: 7)
                Text("Masa.db (Schema \(schemaStr) · \(triggerStr) Triggers · \(snapshotStr) Seals)")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(.primary)
            }
            .help("SQLite Schema: Read-only direct C-API access with append-only triggers")

            Divider()
                .frame(height: 12)

            // SHA-256 Chain Seal Status
            HStack(spacing: 5) {
                if isSealed {
                    Image(systemName: "checkmark.shield.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(.green)
                    let sealLabel = appState.chainTipStatus == "MATCH_SEALED" ? "Sealed" : "Verified"
                    Text("SHA-256 Chain: \(sealLabel) (\(auditCountStr) Events)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                } else if isUnknown {
                    Image(systemName: "questionmark.shield")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text("SHA-256 Chain: Unverified (\(auditCountStr) Events)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                } else {
                    Image(systemName: "exclamationmark.shield.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(.red)
                    Text("SHA-256 Chain: \(appState.auditStatusText) (\(auditCountStr) Events)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            // Last refresh timestamp
            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                Text("Last Refresh: \(appState.formattedLastRefresh)")
                    .font(.system(size: 11, weight: .regular))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    // MARK: - Helper Actions

    private var currentNavigationTitle: String {
        if let asset = appState.selectedPinnedAsset {
            return "\(asset.symbol) — \(asset.name)"
        }
        return appState.selectedSection.rawValue
    }

    private func toggleSidebar() {
        #if os(macOS)
        NSApp.keyWindow?.firstResponder?.tryToPerform(#selector(NSSplitViewController.toggleSidebar(_:)), with: nil)
        #endif
    }
}
