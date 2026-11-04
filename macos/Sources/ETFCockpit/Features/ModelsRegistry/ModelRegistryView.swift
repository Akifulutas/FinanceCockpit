import SwiftUI

public struct ModelRegistryView: View {
    @ObservedObject public var viewModel: ModelRegistryViewModel

    public init(viewModel: ModelRegistryViewModel) {
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

                // MARK: - Champions Banner (Top of Screen)
                championsBannerSection

                // MARK: - Tab Picker
                tabPickerSection

                // MARK: - Tab Content
                switch viewModel.selectedTab {
                case .registry:
                    registryTabContent
                case .scorecard:
                    scorecardTabContent
                case .runs:
                    runsTabContent
                case .comparison:
                    comparisonTabContent
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.registeredModels.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Model Registry & Evaluation")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.activeEligibleCount) Active Models",
                        level: .success,
                        icon: "cpu"
                    )
                }

                Text("Task-Based Champion Selection, Benchmark Scorecards & Execution Manifests")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.triggerModelEvaluation() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isExecutingAction {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "crown.fill")
                        }
                        Text("Evaluate Models")
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

    private var kpiSection: some View {
        HStack(spacing: 14) {
            MetricCardView(
                title: "Registered Models",
                value: "\(viewModel.totalModelsCount)",
                subtitle: "\(viewModel.activeEligibleCount) Ready for Use",
                trend: .neutral,
                badge: "REGISTRY"
            )

            MetricCardView(
                title: "Task Champions",
                value: "\(viewModel.championsCount) / 4",
                subtitle: "Critical Failures: 0",
                trend: viewModel.championsCount >= 4 ? .up : .neutral,
                trendValue: "👑 ACTIVE",
                badge: "CHAMPIONS",
                badgeColor: .yellow
            )

            MetricCardView(
                title: "API Cost Policy",
                value: "€0.00",
                subtitle: "Subscription & Local Cap",
                trend: .neutral,
                badge: "ZERO COST",
                badgeColor: .secondary
            )

            MetricCardView(
                title: "Privacy Class",
                value: "Local + EU",
                subtitle: "Confidential data never leaks",
                trend: .up,
                trendValue: "100% SECURE",
                badge: "PRIVACY",
                badgeColor: .blue
            )
        }
    }

    private var championsBannerSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Task Champions (Active 👑)")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.secondary)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                ForEach(ModelRegistryViewModel.benchmarkTasks, id: \.0) { taskKey, taskTitle, icon in
                    championCard(key: taskKey, title: taskTitle, icon: icon)
                }
            }
        }
    }

    private func championCard(key: String, title: String, icon: String) -> some View {
        let champion = viewModel.championForTask(category: key)

        return HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(champion != nil ? Color.yellow.opacity(0.15) : Color.gray.opacity(0.1))
                    .frame(width: 40, height: 40)
                Image(systemName: champion != nil ? "crown.fill" : icon)
                    .font(.system(size: 18))
                    .foregroundStyle(champion != nil ? Color.yellow : Color.secondary)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 12, weight: .bold))

                if let champ = champion {
                    Text(champ.modelName)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.primary)

                    HStack(spacing: 6) {
                        Text(champ.provider.uppercased())
                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                            .foregroundStyle(.secondary)
                        Text("•")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                        Text(String(format: "%.1f%%", NSDecimalNumber(decimal: champ.scorePct).doubleValue))
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundStyle(.green)
                    }
                } else {
                    Text("Awaiting Evaluation")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            if let champ = champion {
                StatusPillView(
                    text: String(format: "%.0f%%", NSDecimalNumber(decimal: champ.scorePct).doubleValue),
                    level: .success,
                    showIcon: false
                )
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(champion != nil ? Color.yellow.opacity(0.3) : Color.primary.opacity(0.08), lineWidth: 1))
    }

    private var tabPickerSection: some View {
        HStack {
            Picker("View", selection: $viewModel.selectedTab) {
                ForEach(ModelRegistryTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 550)

            Spacer()

            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search model or task...", text: $viewModel.searchText)
                    .textFieldStyle(.plain)
                    .frame(width: 170)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
        }
    }

    // MARK: - Registry Tab

    private var registryTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            // Provider Filter Pills
            HStack(spacing: 8) {
                providerFilterButton(title: "All", value: nil)
                providerFilterButton(title: "Local Engine", value: "local")
                providerFilterButton(title: "Google Gemini", value: "google")
                providerFilterButton(title: "ChatGPT", value: "chatgpt")
                providerFilterButton(title: "LM Studio", value: "lmstudio")

                Spacer()

                Text("\(viewModel.filteredModels.count) models listed")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            if viewModel.filteredModels.isEmpty {
                HStack {
                    Spacer()
                    Text("No models match the filter.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .padding(24)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ForEach(viewModel.filteredModels) { model in
                    modelRow(model: model)
                }
            }
        }
    }

    private func providerFilterButton(title: String, value: String?) -> some View {
        Button {
            viewModel.selectedProvider = value
        } label: {
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(
                    Capsule().fill(viewModel.selectedProvider == value ? Color.accentColor.opacity(0.2) : Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    Capsule().strokeBorder(viewModel.selectedProvider == value ? Color.accentColor : Color.primary.opacity(0.1), lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }

    private func modelRow(model: ModelRegistryItem) -> some View {
        HStack(spacing: 12) {
            Image(systemName: model.provider == "local" || model.provider == "lmstudio" ? "desktopcomputer" : "cloud.fill")
                .font(.system(size: 18))
                .foregroundStyle(model.provider == "local" ? .purple : .blue)

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(model.modelName)
                        .font(.system(size: 13, weight: .semibold))

                    Text("(\(model.modelId))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 8) {
                    Text("Provider: \(model.provider.uppercased())")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text("•")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text("Tier: \(model.accessTier)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text("•")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text("Region: \(model.regionCompliance)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }

                if let verified = model.lastVerifiedAt, !verified.isEmpty {
                    Text("Last Verified: \(verified)")
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Unverified")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(.orange)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                let isUnverified = (model.lastVerifiedAt == nil || model.lastVerifiedAt?.isEmpty == true)
                StatusPillView(
                    text: isUnverified ? "UNVERIFIED" : model.status.uppercased(),
                    level: isUnverified ? .warning : (model.status == "eligible" || model.status == "access_verified" ? .success : .warning),
                    showIcon: true
                )

                Text(model.privacyClass == "confidential_anonymized" ? "Confidential/Local" : "Public Data")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    // MARK: - Scorecard Tab

    private var scorecardTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.evaluations.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "chart.bar.doc.horizontal")
                            .font(.system(size: 30))
                            .foregroundStyle(.secondary)
                        Text("No model evaluation scores found yet.")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                        Text("Click 'Evaluate Models' to run the benchmark evaluation suites.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    .padding(24)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                Table(viewModel.filteredEvaluations) {
                    TableColumn("Model") { eval in
                        Text(eval.modelId)
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    }
                    TableColumn("Task Category") { eval in
                        Text(eval.taskCategory)
                            .font(.system(size: 11))
                    }
                    TableColumn("Score") { eval in
                        Text(String(format: "%.2f%%", NSDecimalNumber(decimal: eval.scorePct).doubleValue))
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                    }
                    TableColumn("Critical Error") { eval in
                        StatusPillView(
                            text: eval.criticalErrorPassed ? "PASSED" : "FAILED",
                            level: eval.criticalErrorPassed ? .success : .error,
                            showIcon: false
                        )
                    }
                    TableColumn("Champion") { eval in
                        if eval.isChampion {
                            Text("👑 CHAMPION")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(.yellow)
                        } else {
                            Text("—")
                                .foregroundStyle(.secondary)
                        }
                    }
                    TableColumn("Execution Type") { eval in
                        if eval.isSimulated {
                            StatusPillView(
                                text: "Simulation (No API Call)",
                                level: .warning,
                                showIcon: false
                            )
                        } else {
                            StatusPillView(
                                text: "Live Call",
                                level: .success,
                                showIcon: false
                            )
                        }
                    }
                }
                .frame(minHeight: 280)
            }
        }
    }

    // MARK: - Runs Tab

    private var runsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.filteredRuns.isEmpty {
                HStack {
                    Spacer()
                    Text("No execution manifests found.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .padding(24)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ForEach(viewModel.filteredRuns) { run in
                    runRow(run: run)
                }
            }
        }
    }

    private func runRow(run: ModelRunItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(run.taskName)
                    .font(.system(size: 13, weight: .bold))

                Spacer()

                StatusPillView(
                    text: run.status.uppercased(),
                    level: run.status == "completed" ? .success : .warning,
                    showIcon: true
                )
            }

            HStack(spacing: 12) {
                if let quick = run.quickModelId {
                    Text("Fast: \(quick)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                if let deep = run.deepModelId {
                    Text("Deep: \(deep)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                if let route = run.routeLabel {
                    Text("Route: \(route)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
            }

            if let rationale = run.selectionRationale {
                Text("Selection Rationale: \(rationale)")
                    .font(.system(size: 11))
                    .foregroundStyle(.primary.opacity(0.85))
            }

            if let hash = run.promptHash {
                HStack(spacing: 4) {
                    Text("Prompt Hash:")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.secondary)
                    Text(Formatters.formatTruncatedHash(hash))
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    // MARK: - Local vs LLM Comparison Tab

    private var comparisonTabContent: some View {
        let metrics = viewModel.localVsLLMComparisonMetrics

        return VStack(alignment: .leading, spacing: 16) {
            Text("Local Deterministic Engine vs External Cloud LLM Analysis")
                .font(.system(size: 14, weight: .bold))

            HStack(spacing: 14) {
                comparisonMetricCard(
                    title: "Local Models (Local)",
                    countText: "\(metrics.localModelCount) Models",
                    championsText: "\(metrics.localChampionCount) Champions",
                    privacyText: "100% Confidential Data Compliant",
                    color: .purple
                )

                comparisonMetricCard(
                    title: "Cloud Models (Google/ChatGPT)",
                    countText: "\(metrics.cloudModelCount) Models",
                    championsText: "\(metrics.cloudChampionCount) Champions",
                    privacyText: "Public Data / EU Compliant",
                    color: .blue
                )
            }

            // Rules & Invariants
            VStack(alignment: .leading, spacing: 10) {
                Text("System Security & Cost Principles")
                    .font(.system(size: 12, weight: .bold))

                HStack(spacing: 8) {
                    Image(systemName: "checkmark.shield.fill")
                        .foregroundStyle(.green)
                    Text("Zero External API Cost: Relies strictly on existing Pro subscriptions and local engines.")
                        .font(.system(size: 11))
                }

                HStack(spacing: 8) {
                    Image(systemName: "lock.shield.fill")
                        .foregroundStyle(.blue)
                    Text("Privacy Safeguards: Portfolio balances and account credentials are never transmitted externally.")
                        .font(.system(size: 11))
                }

                HStack(spacing: 8) {
                    Image(systemName: "bolt.shield.fill")
                        .foregroundStyle(.orange)
                    Text("Deterministic Precedence: Tabular and arithmetic calculations executed primarily in local Python.")
                        .font(.system(size: 11))
                }
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    private func comparisonMetricCard(title: String, countText: String, championsText: String, privacyText: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(color)

            Text(countText)
                .font(.system(size: 20, weight: .bold, design: .rounded))

            Text(championsText)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)

            Text(privacyText)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(color.opacity(0.3), lineWidth: 1))
    }
}
