import SwiftUI

public struct SystemConfigurationView: View {
    @ObservedObject public var viewModel: SystemConfigurationViewModel

    public init(viewModel: SystemConfigurationViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header
                headerSection

                // MARK: - Feedback Banners
                feedbackBannersSection

                // MARK: - Segmented Tab Picker
                Picker("Configuration Tab", selection: $viewModel.selectedTab) {
                    ForEach(ConfigSectionTab.allCases) { tab in
                        Text(tab.rawValue).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 550)

                // MARK: - Tab Content
                switch viewModel.selectedTab {
                case .portfolio:
                    portfolioTargetsTab
                case .policy:
                    investmentPolicyTab
                case .modelAccess:
                    modelAccessTab
                case .notifications:
                    notificationsTab
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            await viewModel.loadConfiguration()
        }
        .alert("Confirm Investment Policy", isPresented: $viewModel.showPolicyApprovalDialog) {
            Button("Confirm & Save", role: .none) {
                Task { _ = await viewModel.saveInvestmentPolicies(confirmed: true) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Are you sure you want to approve these thresholds as your active investment policy? An approved policy binds the parameters to the automated evaluation engine.")
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("System Configuration & Settings")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: (viewModel.policyApprovalStatus == "ONAYLANDI" || viewModel.policyApprovalStatus == "APPROVED") ? "Policy Approved" : "Draft Status",
                        level: (viewModel.policyApprovalStatus == "ONAYLANDI" || viewModel.policyApprovalStatus == "APPROVED") ? .success : .warning,
                        icon: (viewModel.policyApprovalStatus == "ONAYLANDI" || viewModel.policyApprovalStatus == "APPROVED") ? "checkmark.circle.fill" : "pencil.circle"
                    )
                }

                Text("portfoy.json, politika.json and model access configuration")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button("Reset to Defaults") {
                viewModel.resetToDefaults()
            }
            .buttonStyle(.bordered)
        }
    }

    private var feedbackBannersSection: some View {
        Group {
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
        }
    }

    // MARK: - Tab 1: Portfolio Targets

    private var portfolioTargetsTab: some View {
        VStack(alignment: .leading, spacing: 16) {
            // Summary KPI
            let sum = viewModel.totalTargetWeightPct
            let isValid = viewModel.isTargetWeightSumValid
            let diff = 100.0 - NSDecimalNumber(decimal: sum).doubleValue

            HStack(spacing: 16) {
                MetricCardView(
                    title: "Total Target Weight",
                    value: Formatters.formatPercentage(sum, decimalPlaces: 1),
                    subtitle: isValid ? (viewModel.targetWeightItems.isEmpty ? "No targets defined" : "Remaining Cash Buffer: \(String(format: "%.1f%%", max(0, diff)))") : "Error: Exceeds 100%!",
                    trend: isValid ? .neutral : .down,
                    badge: isValid ? (viewModel.targetWeightItems.isEmpty ? "EMPTY" : "VALID") : "BREACH",
                    badgeColor: isValid ? (viewModel.targetWeightItems.isEmpty ? .secondary : .green) : .red
                )

                MetricCardView(
                    title: "Minimum Order Size",
                    value: Formatters.formatCurrency(viewModel.minTradeEur),
                    subtitle: "Single execution floor",
                    trend: nil,
                    badge: "EUR"
                )

                MetricCardView(
                    title: "Target Cash Buffer",
                    value: Formatters.formatPercentage(viewModel.targetCashRatio * 100, decimalPlaces: 1),
                    subtitle: "Strategic liquidity reserve",
                    trend: nil,
                    badge: "CASH"
                )
            }

            if viewModel.targetWeightItems.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "tray")
                        .font(.system(size: 32))
                        .foregroundStyle(.secondary)
                    Text("Target basket not defined")
                        .font(.system(size: 14, weight: .bold))
                    Text(viewModel.targetStatusMessage ?? "Portfolio target weights not defined yet. Click below to populate known instruments with 0% initial weight and save your desired allocations.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 420)
                    Button("Populate Known Instruments") {
                        viewModel.populateFromKnownInstruments()
                    }
                    .buttonStyle(.bordered)
                }
                .frame(maxWidth: .infinity)
                .padding(30)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            } else {
                // Target Weights Table
                VStack(alignment: .leading, spacing: 10) {
                    Text("Asset Allocation Targets (portfoy.json)")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.secondary)

                    VStack(spacing: 0) {
                        HStack(spacing: 12) {
                            Text("ISIN / Security")
                                .frame(minWidth: 220, alignment: .leading)
                            Text("Role / Strategy")
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Text("Target Weight (%)")
                                .frame(width: 140, alignment: .trailing)
                        }
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(Color.primary.opacity(0.03))

                        Divider()

                        ForEach(viewModel.targetWeightItems) { item in
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.name)
                                        .font(.system(size: 12, weight: .semibold))
                                    Text(item.isin)
                                        .font(.system(size: 10, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                }
                                .frame(minWidth: 220, alignment: .leading)

                                Text(item.role)
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .leading)

                                HStack(spacing: 8) {
                                    Text(Formatters.formatPercentage(item.weightPct, decimalPlaces: 1))
                                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                                        .frame(width: 55, alignment: .trailing)

                                    Stepper("", value: Binding(
                                        get: { NSDecimalNumber(decimal: item.weightPct).doubleValue },
                                        set: { viewModel.updateWeight(for: item.isin, newWeight: Decimal($0)) }
                                    ), in: 0...100, step: 5)
                                    .labelsHidden()
                                }
                                .frame(width: 140, alignment: .trailing)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)

                            Divider()
                        }
                    }
                    .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                }

                // Save Controls
                HStack {
                    Spacer()

                    Button {
                        Task { _ = await viewModel.savePortfolioTargets() }
                    } label: {
                        HStack(spacing: 6) {
                            if viewModel.isSaving {
                                ProgressView().controlSize(.small)
                            } else {
                                Image(systemName: "checkmark.circle.fill")
                            }
                            Text("Save Target Basket")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.isTargetWeightSumValid || viewModel.isSaving)
                }
            }
        }
    }

    // MARK: - Tab 2: Investment Policies

    private var investmentPolicyTab: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Rebalancing & Risk Policy Limits (politika.json)")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.secondary)

            VStack(spacing: 14) {
                // Absolute Tolerance
                policySettingRow(
                    title: "Absolute Tolerance Band",
                    subtitle: "Permitted absolute deviation from target weight (e.g. ±5%)",
                    control: HStack {
                        Text(Formatters.formatPercentage(viewModel.absoluteTolerance * 100, decimalPlaces: 1))
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(width: 50, alignment: .trailing)
                        Stepper("", value: Binding(
                            get: { NSDecimalNumber(decimal: viewModel.absoluteTolerance * 100).doubleValue },
                            set: { viewModel.absoluteTolerance = Decimal($0) / 100.0 }
                        ), in: 1...20, step: 1)
                        .labelsHidden()
                    }
                )

                Divider()

                // Relative Tolerance
                policySettingRow(
                    title: "Relative Tolerance Band",
                    subtitle: "Permitted relative deviation relative to target weight (e.g. ±25%)",
                    control: HStack {
                        Text(Formatters.formatPercentage(viewModel.relativeTolerance * 100, decimalPlaces: 1))
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(width: 50, alignment: .trailing)
                        Stepper("", value: Binding(
                            get: { NSDecimalNumber(decimal: viewModel.relativeTolerance * 100).doubleValue },
                            set: { viewModel.relativeTolerance = Decimal($0) / 100.0 }
                        ), in: 5...50, step: 5)
                        .labelsHidden()
                    }
                )

                Divider()

                // UCITS 5/10/40 Enforcement
                policySettingRow(
                    title: "EU UCITS 5/10/40 Concentration Rules",
                    subtitle: "Enforce strict single-company concentration bounds under UCITS rules",
                    control: Toggle("", isOn: $viewModel.ucitsEnforcement).labelsHidden()
                )

                Divider()

                // Trend Warning
                policySettingRow(
                    title: "Downside Trend Warning Threshold",
                    subtitle: "Threshold to trigger portfolio trend alert (e.g. -5%)",
                    control: HStack {
                        Text(Formatters.formatPercentage(viewModel.trendAlertThreshold * 100, includeSign: true, decimalPlaces: 1))
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(width: 60, alignment: .trailing)
                        Stepper("", value: Binding(
                            get: { NSDecimalNumber(decimal: viewModel.trendAlertThreshold * 100).doubleValue },
                            set: { viewModel.trendAlertThreshold = Decimal($0) / 100.0 }
                        ), in: -30 ... -1, step: 1)
                        .labelsHidden()
                    }
                )

                Divider()

                // Drawdown Review
                policySettingRow(
                    title: "Maximum Drawdown Review Trigger",
                    subtitle: "Portfolio drawdown threshold triggering mandatory thesis review (e.g. -20%)",
                    control: HStack {
                        Text(Formatters.formatPercentage(viewModel.drawdownReviewThreshold * 100, includeSign: true, decimalPlaces: 1))
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(width: 60, alignment: .trailing)
                        Stepper("", value: Binding(
                            get: { NSDecimalNumber(decimal: viewModel.drawdownReviewThreshold * 100).doubleValue },
                            set: { viewModel.drawdownReviewThreshold = Decimal($0) / 100.0 }
                        ), in: -50 ... -5, step: 5)
                        .labelsHidden()
                    }
                )

                Divider()

                // Spread Warning Limit
                policySettingRow(
                    title: "Bid/Ask Spread Warning Threshold",
                    subtitle: "Maximum acceptable market spread on quotes (e.g. 1.00%)",
                    control: HStack {
                        Text(Formatters.formatPercentage(viewModel.spreadWarningPct, decimalPlaces: 2))
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .frame(width: 60, alignment: .trailing)
                        Stepper("", value: Binding(
                            get: { NSDecimalNumber(decimal: viewModel.spreadWarningPct).doubleValue },
                            set: { viewModel.spreadWarningPct = Decimal($0) }
                        ), in: 0.2 ... 5.0, step: 0.1)
                        .labelsHidden()
                    }
                )

                Divider()

                // Policy Approval Status
                policySettingRow(
                    title: "Policy Governance Status",
                    subtitle: "When APPROVED, rules are strictly enforced by evaluation engine",
                    control: Picker("", selection: $viewModel.policyApprovalStatus) {
                        Text("DRAFT").tag("TASLAK")
                        Text("APPROVED").tag("ONAYLANDI")
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 160)
                )
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

            HStack {
                Spacer()
                Button {
                    Task { _ = await viewModel.saveInvestmentPolicies() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "shield.checkmark.fill")
                        Text("Save Policy")
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    private func policySettingRow(title: String, subtitle: String, control: some View) -> some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                Text(subtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            control
        }
    }

    // MARK: - Tab 3: Model Access & Broker (Read-Only)

    private var modelAccessTab: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Broker & AI Model Access Status")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.secondary)

            // Scalable Capital Broker Card
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "building.columns.circle.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(.blue)
                    Text("Scalable Capital Broker CLI")
                        .font(.system(size: 13, weight: .bold))
                    Spacer()
                    StatusPillView(
                        text: viewModel.brokerCliExists ? "Installed" : "Not Found",
                        level: viewModel.brokerCliExists ? .success : .warning
                    )
                }

                Divider()

                HStack {
                    Text("CLI Path:")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 140, alignment: .leading)
                    Text(viewModel.brokerCliPath)
                        .font(.system(size: 11, design: .monospaced))
                }

                HStack {
                    Text("Account ID (Masked):")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 140, alignment: .leading)
                    Text(viewModel.brokerAccountIdMasked)
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(.primary)
                }

                Text("The application does not manage broker credentials directly; an isolated read-only terminal session is used (`sc login --local-read-only`).")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

            // TradingAgents & AI Models Card
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Image(systemName: "brain.head.profile")
                        .font(.system(size: 16))
                        .foregroundStyle(.purple)
                    Text("TradingAgents & AI Model Providers")
                        .font(.system(size: 13, weight: .bold))
                    Spacer()
                    StatusPillView(
                        text: viewModel.chatgptAuthExists ? "ChatGPT Active" : "ChatGPT Login Pending",
                        level: viewModel.chatgptAuthExists ? .success : .info
                    )
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Active Provider & Model Routing:")
                        .font(.system(size: 11, weight: .semibold))

                    if viewModel.modelProviders.isEmpty {
                        Text("Loading model routing info...")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.modelProviders, id: \.self) { line in
                            HStack(alignment: .top, spacing: 6) {
                                Text("•")
                                    .foregroundStyle(.secondary)
                                Text(line)
                                    .font(.system(size: 11))
                            }
                        }
                    }
                }

                Divider()

                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("ChatGPT Session File:")
                            .font(.system(size: 11, weight: .semibold))
                        Text(viewModel.chatgptAuthPath)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusPillView(
                        text: viewModel.chatgptAuthExists ? "Session Present" : "File Missing",
                        level: viewModel.chatgptAuthExists ? .success : .warning
                    )
                }

                Divider()

                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Google Model:")
                            .font(.system(size: 11, weight: .semibold))
                        Text(viewModel.googleModel)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusPillView(text: "Free Tier", level: .info)
                }

                Text("Model API keys are stored in TradingAgents' isolated environment. ETFCockpit never reads, stores, or logs raw credentials.")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    // MARK: - Tab 4: Notifications & Timeframes

    private var notificationsTab: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("macOS Notification Preferences & Cadence")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.secondary)

            VStack(spacing: 14) {
                policySettingRow(
                    title: "Morning Forecast Alerts (09:30 CET)",
                    subtitle: "Send system notification when morning forecasts are generated",
                    control: Toggle("", isOn: $viewModel.notifications.morningForecastAlerts).labelsHidden()
                )

                Divider()

                policySettingRow(
                    title: "Evening Settlement Alerts (17:40 CET)",
                    subtitle: "Send system notification when closing prices settle and scorecard is updated",
                    control: Toggle("", isOn: $viewModel.notifications.eveningSettlementAlerts).labelsHidden()
                )

                Divider()

                policySettingRow(
                    title: "Session Expiry Alerts (WAITING_AUTH)",
                    subtitle: "Trigger alert if the broker session expires or requires interactive authentication",
                    control: Toggle("", isOn: $viewModel.notifications.waitingAuthAlerts).labelsHidden()
                )

                Divider()

                policySettingRow(
                    title: "Sound Effects",
                    subtitle: "Play system auditory chime on critical alerts and completions",
                    control: Toggle("", isOn: $viewModel.notifications.soundEnabled).labelsHidden()
                )

                Divider()

                policySettingRow(
                    title: "Default Chart Timeframe",
                    subtitle: "Default time window for performance and asset charts",
                    control: Picker("", selection: $viewModel.notifications.defaultTimeframe) {
                        ForEach(viewModel.availableTimeframes, id: \.self) { tf in
                            Text(tf).tag(tf)
                        }
                    }
                    .frame(width: 100)
                )
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }
}
