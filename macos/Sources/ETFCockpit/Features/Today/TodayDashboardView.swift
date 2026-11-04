import SwiftUI

/// View for the "Bugün" (Today) overview dashboard (E1) in FinanceCockpit.
/// Implements Apple Design Award (ADA) macOS HIG standards, 6-step Morning Flow (İP-7),
/// and uninstalled scheduler warning (İP-10).
public struct TodayDashboardView: View {
    @ObservedObject public var viewModel: TodayDashboardViewModel
    @State private var isShowingSchedulerConfirmAlert: Bool = false

    public init(viewModel: TodayDashboardViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerBar

                // İP-10: Scheduler Warning Banner
                if viewModel.hasUninstalledSchedulerWarning {
                    schedulerWarningBanner
                }

                // İP-7: 6-Step Morning Sequence
                morningFlowCard

                // Scalable Capital Session Status Card
                sessionStatusCard

                // Portfolio Summary KPIs
                portfolioSummaryCards

                // Mevcut Portföy Varlıkları Tablosu
                positionsOverviewCard

                // Manual Data Refresh & Terminal Stream
                dataRefreshCard
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .alert("Scheduler Setup", isPresented: $isShowingSchedulerConfirmAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Install") {
                Task {
                    _ = await viewModel.installScheduler(confirm: true)
                }
            }
        } message: {
            Text("Launchd background schedulers will be installed for automatic forecast evaluation and data fetch after market close. Do you wish to continue?")
        }
        .task {
            await viewModel.loadData()
        }
    }

    // MARK: - Header Bar
    private var headerBar: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Today")
                    .font(.system(size: 24, weight: .bold))
                Text("FinanceCockpit — Daily operational status, 6-step morning flow, and live data pipeline")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Refresh Button
            Button {
                Task {
                    await viewModel.loadData()
                }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Refresh")
                        .font(.system(size: 11, weight: .medium))
                }
            }
            .help("Refresh Status (⌘R)")
        }
    }

    // MARK: - İP-10: User-Approval Controlled Mode Banner
    private var schedulerWarningBanner: some View {
        HStack(spacing: 14) {
            Image(systemName: "checkmark.shield.fill")
                .font(.system(size: 22))
                .foregroundStyle(.blue)

            VStack(alignment: .leading, spacing: 3) {
                Text("User-Confirmed Safe Mode Active")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.primary)

                Text("Morning 09:30 and evening 17:40 forecast cycles will not run in the background without your explicit confirmation. Every action requires your approval.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            StatusPillView(
                text: "APPROVAL REQUIRED",
                level: .neutral,
                icon: "lock.shield"
            )
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.blue.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.blue.opacity(0.2), lineWidth: 1))
    }

    // MARK: - İP-7: 6-Step Morning Sequence Card
    private var morningFlowCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Image(systemName: "sunrise.fill")
                            .foregroundStyle(.blue)
                            .font(.system(size: 16))
                        Text("Morning Sequence (6 Steps)")
                            .font(.system(size: 14, weight: .bold))
                    }
                    Text("1. Session → 2. Live Data → 3. History → 4. Evaluation → 5. Analysis → 6. Screener")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                if viewModel.isMorningFlowRunning {
                    Button(role: .destructive) {
                        viewModel.cancelMorningFlow()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "xmark.circle.fill")
                            Text("Cancel (SIGINT)")
                        }
                    }
                    .buttonStyle(.bordered)
                } else {
                    Button {
                        viewModel.startMorningFlow()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "play.circle.fill")
                            Text("Run Morning Flow")
                                .fontWeight(.semibold)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.blue)
                }
            }

            // 6-Step Flow Items Grid
            VStack(spacing: 8) {
                ForEach(viewModel.morningFlowSteps) { step in
                    morningFlowStepRow(step: step)
                }
            }

            // Waiting auth / login helper (Step 1 active and login process running)
            if viewModel.isLoginProcessRunning || viewModel.currentStartupStep == .phoneApproval {
                HStack(spacing: 14) {
                    Image(systemName: "iphone.radiowaves.left.and.right")
                        .font(.system(size: 26))
                        .foregroundStyle(.blue)

                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text("Scalable Capital Login & 2FA Phone Approval")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(.blue)
                            ProgressView()
                                .controlSize(.small)
                        }
                        Text("Please confirm your login on the opened Safari page and approve the prompt on your mobile phone.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)

                        if let code = viewModel.activationCode, !code.isEmpty {
                            HStack(spacing: 6) {
                                Text("Approval Code:")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(.secondary)
                                Text(code)
                                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                                    .foregroundStyle(.blue)
                            }
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(RoundedRectangle(cornerRadius: 4).fill(Color.blue.opacity(0.12)))
                        }
                    }

                    Spacer()

                    if let urlStr = viewModel.loginAuthURL ?? viewModel.activationURL, !urlStr.isEmpty {
                        Button {
                            viewModel.openActivationURLInSafari()
                        } label: {
                            Label("Open in Safari", systemImage: "safari")
                        }
                        .buttonStyle(.bordered)
                    }

                    Button("Cancel") {
                        viewModel.cancelMorningFlow()
                    }
                    .buttonStyle(.bordered)
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.blue.opacity(0.1)))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.blue.opacity(0.3), lineWidth: 1))
            }

            // Summary Card (When flow completes)
            if let summary = viewModel.morningFlowSummary {
                HStack(spacing: 14) {
                    Image(systemName: "checkmark.seal.fill")
                        .font(.system(size: 26))
                        .foregroundStyle(.green)

                    VStack(alignment: .leading, spacing: 3) {
                        Text("✓ Morning Sequence Completed Successfully")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(.green)

                        Text("\(summary.evaluatedPositionsCount) positions evaluated, \(summary.opportunityCandidatesCount) candidates found, data freshness: \(summary.lastQuoteTimestamp ?? "Current")")
                            .font(.system(size: 11))
                            .foregroundStyle(.primary.opacity(0.85))
                    }

                    Spacer()
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.green.opacity(0.1)))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.green.opacity(0.3), lineWidth: 1))
            }
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private func morningFlowStepRow(step: TodayDashboardViewModel.MorningFlowStepItem) -> some View {
        HStack(spacing: 12) {
            // Status Icon / Number
            ZStack {
                Circle()
                    .fill(stepBadgeColor(for: step.status).opacity(0.15))
                    .frame(width: 26, height: 26)

                switch step.status {
                case .pending:
                    Text("\(step.step.rawValue)")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.secondary)
                case .running:
                    ProgressView()
                        .controlSize(.small)
                case .success:
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.green)
                case .degraded:
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.orange)
                case .failed:
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.red)
                case .skipped:
                    Image(systemName: "arrow.right")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.secondary)
                case .cancelled:
                    Image(systemName: "slash.circle")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(step.step.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(step.status == .cancelled ? .secondary : .primary)

                if let detail = step.detailText, !detail.isEmpty {
                    Text(detail)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer()

            // Exit Code & Duration Badge
            HStack(spacing: 8) {
                if let duration = step.durationSeconds {
                    Text(String(format: "%.1fs", duration))
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                if let code = step.exitCode {
                    Text("Code: \(code)")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundStyle(code == 0 ? .green : (code == 2 ? .orange : .red))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill((code == 0 ? Color.green : (code == 2 ? Color.orange : Color.red)).opacity(0.12)))
                } else if case .skipped = step.status {
                    Text("SKIPPED")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(Color.secondary.opacity(0.12)))
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(stepRowBgColor(for: step.status)))
    }

    private func stepBadgeColor(for status: TodayDashboardViewModel.MorningStepStatus) -> Color {
        switch status {
        case .pending: return .secondary
        case .running: return .blue
        case .success: return .green
        case .degraded: return .orange
        case .failed: return .red
        case .skipped, .cancelled: return .gray
        }
    }

    private func stepRowBgColor(for status: TodayDashboardViewModel.MorningStepStatus) -> Color {
        switch status {
        case .running: return Color.blue.opacity(0.06)
        case .success: return Color.green.opacity(0.04)
        case .degraded: return Color.orange.opacity(0.05)
        case .failed: return Color.red.opacity(0.06)
        default: return Color(nsColor: .controlBackgroundColor)
        }
    }

    // MARK: - Scalable Capital Session Status Card
    private var sessionStatusCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: sessionCardIcon)
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(sessionCardColor)

                VStack(alignment: .leading, spacing: 2) {
                    Text(sessionCardTitle)
                        .font(.system(size: 14, weight: .bold))
                    Text(sessionCardSubtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                if viewModel.isCheckingSession || viewModel.isVerifyingSession {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if let prompt = viewModel.loginPromptMessage {
                HStack(spacing: 8) {
                    Image(systemName: prompt.contains("✓") ? "checkmark.circle.fill" : (viewModel.isLoginProcessRunning ? "hourglass" : "info.circle.fill"))
                        .foregroundStyle(prompt.contains("✓") ? .green : (viewModel.isLoginProcessRunning ? .blue : .orange))
                    Text(prompt)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(prompt.contains("✓") ? .green : .primary)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(prompt.contains("✓") ? Color.green.opacity(0.1) : (viewModel.isLoginProcessRunning ? Color.blue.opacity(0.1) : Color.orange.opacity(0.1)))
                .cornerRadius(8)
            }

            // Action Buttons
            HStack(spacing: 12) {
                if viewModel.isLoginProcessRunning {
                    ProgressView()
                        .controlSize(.small)
                    Text("Waiting for phone 2FA confirmation...")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.blue)

                    Spacer()

                    if let urlStr = viewModel.loginAuthURL ?? viewModel.activationURL, !urlStr.isEmpty {
                        Button {
                            viewModel.openSafariLoginURL()
                        } label: {
                            HStack(spacing: 4) {
                                Image(systemName: "safari")
                                Text("Open in Safari")
                            }
                        }
                        .buttonStyle(.bordered)
                    }

                    Button("Cancel") {
                        viewModel.cancelMorningFlow()
                    }
                    .buttonStyle(.bordered)
                } else if viewModel.isSessionActive != true {
                    Button {
                        viewModel.startCLILogin()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "safari.fill")
                            Text("Sign In (CLI & Safari)")
                                .fontWeight(.semibold)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.blue)
                    .help("Starts Scalable login flow, opens Safari verification and waits for mobile 2FA prompt")

                    Button {
                        Task {
                            await viewModel.checkSession()
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.clockwise")
                            Text("Check Session")
                        }
                    }
                    .buttonStyle(.bordered)
                } else {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.system(size: 13))
                        Text("Session Active: \(viewModel.accountInfo?.accountId ?? "Connected")")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Button {
                        Task {
                            await viewModel.checkSession()
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.clockwise")
                            Text("Verify Session")
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(sessionCardBorderColor, lineWidth: 1)
        )
    }

    // MARK: - Portfolio Summary Cards
    private var portfolioSummaryCards: some View {
        HStack(spacing: 14) {
            MetricCardView(
                title: "Total Portfolio Value",
                value: formatEUR(viewModel.totalEur),
                subtitle: viewModel.totalEur == nil ? "Not calculated" : "Sealed live valuation",
                trend: .neutral,
                badge: "EUR"
            )

            MetricCardView(
                title: "Cash Balance",
                value: formatEUR(viewModel.cashEur),
                subtitle: viewModel.cashEur == nil ? "Not calculated" : "Uninvested cash reserve",
                trend: .neutral,
                badge: "CASH"
            )

            MetricCardView(
                title: "Position Count",
                value: "\(viewModel.positionsCount) ETF",
                subtitle: "Core assets held",
                trend: .neutral,
                badge: "PORTFOLIO"
            )

            MetricCardView(
                title: "Last Sealed",
                value: viewModel.lastUpdatedDateText,
                subtitle: "SQLite snapshot timestamp",
                trend: .neutral,
                badge: "FRESHNESS",
                badgeColor: viewModel.isSessionActive == true ? .green : .secondary
            )
        }
    }

    // MARK: - Current Portfolio Holdings Table
    private var positionsOverviewCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Current Portfolio Holdings")
                        .font(.system(size: 14, weight: .bold))
                    Text("Core ETF positions from the latest SQLite sealed snapshot")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                StatusPillView(
                    text: "\(viewModel.positions.count) Positions",
                    level: .neutral,
                    icon: "chart.pie.fill"
                )
            }

            if viewModel.positions.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "tray")
                            .font(.system(size: 28))
                            .foregroundStyle(.secondary)
                        Text("No sealed positions found yet")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.secondary)
                        Text("Fetch portfolio by running the morning flow or 'Refresh Market Data'.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.vertical, 24)
                    Spacer()
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(viewModel.positions) { pos in
                        HStack(spacing: 12) {
                            Circle()
                                .fill(Color.blue.opacity(0.8))
                                .frame(width: 8, height: 8)

                            VStack(alignment: .leading, spacing: 2) {
                                Text(pos.displayName)
                                    .font(.system(size: 12, weight: .semibold))
                                    .lineLimit(1)
                                Text(pos.isin)
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }

                            Spacer()

                            VStack(alignment: .trailing, spacing: 2) {
                                Text("\(pos.quantity) Shares")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                                if let mid = pos.computedMid {
                                    Text("\(NSDecimalNumber(decimal: mid).doubleValue, specifier: "%.2f") €")
                                        .font(.system(size: 10, design: .monospaced))
                                        .foregroundStyle(.tertiary)
                                }
                            }

                            VStack(alignment: .trailing, spacing: 2) {
                                Text("\(NSDecimalNumber(decimal: pos.brokerValuation).doubleValue, specifier: "%.2f") €")
                                    .font(.system(size: 12, weight: .bold, design: .monospaced))

                                if let total = viewModel.totalEur, total > 0 {
                                    let weight = (NSDecimalNumber(decimal: pos.brokerValuation).doubleValue / total) * 100
                                    Text("\(weight, specifier: "%.1f")%")
                                        .font(.system(size: 10, weight: .medium))
                                        .foregroundStyle(.blue)
                                }
                            }
                            .frame(minWidth: 90, alignment: .trailing)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.5))
                        .cornerRadius(6)
                    }
                }
            }
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 1)
        )
    }

    // MARK: - Data Refresh & Terminal Stream
    private var dataRefreshCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Live Market Data")
                        .font(.system(size: 14, weight: .bold))
                    Text("Fetches positions, live quotes, and cash balance directly from broker")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button {
                    Task {
                        await viewModel.refreshData()
                    }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isRefreshingData {
                            ProgressView()
                                .controlSize(.small)
                            Text("Fetching Data...")
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                            Text("Refresh Market Data (masa veri)")
                                .fontWeight(.semibold)
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(.indigo)
                .disabled(viewModel.isRefreshingData || viewModel.isSessionActive == false)
                .help(viewModel.isSessionActive == false ? "Scalable Capital session must be active before fetching data" : "Seals live quotes and historical price series into database")
            }

            if !viewModel.streamingLogs.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Terminal Output:")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button("Clear") {
                            viewModel.streamingLogs.removeAll()
                        }
                        .font(.system(size: 10))
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                    }

                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(viewModel.streamingLogs.indices, id: \.self) { index in
                                Text(viewModel.streamingLogs[index])
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(viewModel.streamingLogs[index].contains("HATA") || viewModel.streamingLogs[index].contains("ERROR") ? Color.red : Color.primary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .padding(8)
                    }
                    .frame(height: 120)
                    .background(Color.black.opacity(0.1))
                    .cornerRadius(6)
                }
            }
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 1)
        )
    }

    // MARK: - Helpers
    private var sessionCardTitle: String {
        if viewModel.isSessionActive == true {
            return "Scalable Capital Session Active"
        } else if viewModel.isSessionActive == false {
            return "Scalable Capital Sign-In Required"
        } else {
            return "Checking Session Status..."
        }
    }

    private var sessionCardSubtitle: String {
        if viewModel.isSessionActive == true {
            return "Read-only data reader ready. Data fetch and portfolio updates available."
        } else if viewModel.isSessionActive == false {
            return "To fetch live market data, please complete sign-in via Safari and 2FA approval on your mobile phone."
        } else {
            return "System startup session verification is executing."
        }
    }

    private var sessionCardIcon: String {
        if viewModel.isSessionActive == true {
            return "lock.shield.fill"
        } else if viewModel.isSessionActive == false {
            return "exclamationmark.triangle.fill"
        } else {
            return "clock.fill"
        }
    }

    private var sessionCardColor: Color {
        if viewModel.isSessionActive == true {
            return .green
        } else if viewModel.isSessionActive == false {
            return .orange
        } else {
            return .secondary
        }
    }

    private var sessionCardBorderColor: Color {
        if viewModel.isSessionActive == true {
            return Color.green.opacity(0.3)
        } else if viewModel.isSessionActive == false {
            return Color.orange.opacity(0.5)
        } else {
            return Color.secondary.opacity(0.2)
        }
    }

    private func formatEUR(_ value: Double?) -> String {
        guard let value = value else { return "Not calculated" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "EUR"
        formatter.locale = Locale(identifier: "en_IE")
        return formatter.string(from: NSNumber(value: value)) ?? "\(value) €"
    }
}
