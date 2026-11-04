import SwiftUI

public struct ResearchEvidenceView: View {
    @ObservedObject public var viewModel: ResearchEvidenceViewModel

    public init(viewModel: ResearchEvidenceViewModel) {
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

                // MARK: - Evidence Bundle Horizontal Selector
                bundleSelectorSection

                // MARK: - Tab Picker
                tabPickerSection

                // MARK: - Tab Content
                switch viewModel.selectedTab {
                case .claims:
                    claimsTabContent
                case .metrics:
                    metricsTabContent
                case .sources:
                    sourcesTabContent
                case .critic:
                    criticTabContent
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .sheet(isPresented: $viewModel.isShowingResearchSheet) {
            researchLauncherSheet
        }
        .task {
            if viewModel.evidenceBundles.isEmpty {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Sourced Research & Evidence Seal")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.totalClaimsCount) Claims Sealed",
                        level: .neutral,
                        icon: "doc.text.magnifyingglass"
                    )
                }

                Text("Verbatim Primary Quote Verification, Financial Metrics & Red-Team Critic Audit")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                    viewModel.isShowingResearchSheet = true
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "sparkles")
                        Text("Start Research")
                    }
                }
                .buttonStyle(.borderedProminent)

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
                title: "Evidence Bundles",
                value: "\(viewModel.evidenceBundles.count)",
                subtitle: viewModel.selectedBundle != nil ? "Active: \(viewModel.selectedBundle?.isin ?? "")" : "No bundle selected",
                trend: .neutral,
                badge: "SEALED"
            )

            MetricCardView(
                title: "Total Claims",
                value: "\(viewModel.totalClaimsCount)",
                subtitle: "\(viewModel.verifiedClaimsCount) Verified / \(viewModel.unverifiedClaimsCount) Pending",
                trend: viewModel.verifiedClaimsCount > 0 ? .up : .neutral,
                trendValue: viewModel.verificationRatePct != nil ? String(format: "%.1f%%", viewModel.verificationRatePct!) : "—",
                badge: "CLAIMS"
            )

            MetricCardView(
                title: "Verified Metrics",
                value: "\(viewModel.totalMetricsCount)",
                subtitle: "TER, Sharpe, Balance Sheet",
                trend: .neutral,
                badge: "METRICS"
            )

            MetricCardView(
                title: "Red-Team Critic Status",
                value: viewModel.criticReportStatus == .notRun ? "Not Run" : viewModel.criticReportStatus.rawValue,
                subtitle: viewModel.criticScorePct != nil ? String(format: "Audit Score: %.1f%%", viewModel.criticScorePct!) : "Not evaluated yet",
                trend: viewModel.criticReportStatus == .pass ? .up : (viewModel.criticReportStatus == .notRun ? .neutral : .down),
                trendValue: viewModel.criticReportStatus == .pass ? "✓ PASS" : (viewModel.criticReportStatus == .notRun ? "—" : "ALERT"),
                badge: "AUDIT",
                badgeColor: viewModel.criticReportStatus == .pass ? .green : (viewModel.criticReportStatus == .notRun ? .secondary : .orange)
            )
        }
    }

    private var bundleSelectorSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Sealed Evidence Bundles")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.secondary)

            if viewModel.evidenceBundles.isEmpty {
                HStack {
                    Image(systemName: "tray")
                        .foregroundStyle(.secondary)
                    Text("No sealed evidence bundles found yet. You can launch a new research run.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(viewModel.evidenceBundles) { bundle in
                            Button {
                                viewModel.selectBundle(bundle: bundle)
                            } label: {
                                HStack(spacing: 8) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(bundle.isin)
                                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                                        if let name = bundle.instrumentName {
                                            Text(name)
                                                .font(.system(size: 10))
                                                .foregroundStyle(.secondary)
                                                .lineLimit(1)
                                        }
                                        Text("Date: \(bundle.asOfDate)")
                                            .font(.system(size: 9))
                                            .foregroundStyle(.secondary)
                                    }

                                    StatusPillView(
                                        text: "\(bundle.claimsCount) Claims",
                                        level: .info,
                                        icon: "doc.text",
                                        showIcon: false
                                    )
                                }
                                .padding(10)
                                .background(
                                    RoundedRectangle(cornerRadius: 8)
                                        .fill(viewModel.selectedBundle?.bundleId == bundle.bundleId ? Color.accentColor.opacity(0.15) : Color(nsColor: .controlBackgroundColor))
                                )
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .strokeBorder(viewModel.selectedBundle?.bundleId == bundle.bundleId ? Color.accentColor : Color.primary.opacity(0.1), lineWidth: 1)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var tabPickerSection: some View {
        HStack {
            Picker("View", selection: $viewModel.selectedTab) {
                ForEach(ResearchTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 550)

            Spacer()

            if viewModel.selectedTab == .claims || viewModel.selectedTab == .metrics || viewModel.selectedTab == .sources {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search...", text: $viewModel.searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 160)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
            }
        }
    }

    // MARK: - Claims Tab

    private var claimsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            // Filter Bars
            HStack(spacing: 12) {
                HStack(spacing: 6) {
                    Text("Type:")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                    Picker("", selection: $viewModel.selectedClaimTypeFilter) {
                        ForEach(ClaimTypeFilter.allCases) { type in
                            Text(type.displayTitle).tag(type)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 140)
                }

                HStack(spacing: 6) {
                    Text("Verification:")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                    Picker("", selection: $viewModel.selectedVerificationFilter) {
                        ForEach(VerificationFilter.allCases) { v in
                            Text(v.displayTitle).tag(v)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 140)
                }

                Spacer()

                Text("\(viewModel.filteredClaims.count) claims listed")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            if viewModel.filteredClaims.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "doc.text.magnifyingglass")
                            .font(.system(size: 30))
                            .foregroundStyle(.secondary)
                        Text("No matching evidence claims found.")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    .padding(30)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ForEach(viewModel.filteredClaims) { claim in
                    claimCard(claim: claim)
                }
            }
        }
    }

    private func claimCard(claim: ClaimItem) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                // Semantic Claim Pill
                claimTypeBadge(claim.claimType)

                // Verification Status Pill
                claimVerificationBadge(claim.verificationStatus)

                Spacer()

                if let publisher = claim.publisher {
                    Text(publisher)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }

            // Claim Text
            Text(claim.claimText)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.primary)

            // Verbatim Quote Callout Box
            if let quote = claim.quoteVerbatim, !quote.isEmpty {
                verbatimQuoteCallout(quote: quote)
            }

            // Source Footer
            if let title = claim.sourceTitle {
                HStack(spacing: 4) {
                    Image(systemName: "link")
                        .font(.system(size: 9))
                    Text("Source: \(title)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    private func verbatimQuoteCallout(quote: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "quote.opening")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Color.accentColor)
                Text("Official Document Verbatim Quote")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.secondary)
            }

            Text("\"\(quote)\"")
                .font(.system(size: 11, design: .serif))
                .italic()
                .foregroundStyle(.primary.opacity(0.85))
                .padding(.leading, 4)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.06)))
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.accentColor.opacity(0.2), lineWidth: 1))
    }

    private func claimTypeBadge(_ type: String) -> some View {
        let (title, color): (String, Color) = {
            switch type.lowercased() {
            case "fact": return ("FACT", .blue)
            case "sourced_estimate": return ("SOURCED ESTIMATE", .purple)
            case "computation": return ("COMPUTATION", .teal)
            case "inference": return ("INFERENCE", .orange)
            default: return (type.uppercased(), .gray)
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

    private func claimVerificationBadge(_ status: String) -> some View {
        let (title, level): (String, StatusLevel) = {
            switch status.uppercased() {
            case "VERIFIED": return ("VERIFIED", .success)
            case "UNVERIFIED": return ("UNVERIFIED", .warning)
            case "CONTRADICTED": return ("CONTRADICTED", .error)
            default: return (status, .neutral)
            }
        }()

        return StatusPillView(text: title, level: level, showIcon: true)
    }

    // MARK: - Metrics Tab

    private var metricsTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.filteredMetrics.isEmpty {
                HStack {
                    Spacer()
                    Text("No financial metrics found.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .padding(20)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                Table(viewModel.filteredMetrics) {
                    TableColumn("Metric Name") { metric in
                        Text(metric.metricName)
                            .font(.system(size: 12, weight: .semibold))
                    }
                    TableColumn("Value") { metric in
                        Text(metric.value)
                            .font(.system(size: 12, weight: .bold, design: .monospaced))
                    }
                    TableColumn("Unit") { metric in
                        Text(metric.unit ?? "—")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    TableColumn("Period") { metric in
                        if let start = metric.periodStart, let end = metric.periodEnd {
                            Text("\(start) → \(end)")
                                .font(.system(size: 11, design: .monospaced))
                        } else {
                            Text("—")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(minHeight: 250)
            }
        }
    }

    // MARK: - Sources Tab

    private var sourcesTabContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.filteredSources.isEmpty {
                HStack {
                    Spacer()
                    Text("No official source documents found.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .padding(20)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                ForEach(viewModel.filteredSources) { source in
                    sourceRow(source: source)
                }
            }
        }
    }

    private func sourceRow(source: SourceItem) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "doc.fill")
                .font(.system(size: 20))
                .foregroundStyle(.blue)

            VStack(alignment: .leading, spacing: 3) {
                Text(source.title)
                    .font(.system(size: 12, weight: .semibold))

                HStack(spacing: 8) {
                    if let pub = source.publisher {
                        Text("Publisher: \(pub)")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                    }
                    Text("Type: \(source.sourceType)")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    if let date = source.publicationDate {
                        Text("Date: \(date)")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                    }
                }

                if let hash = source.contentSha256 {
                    HStack(spacing: 4) {
                        Text("SHA-256:")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.secondary)
                        Text(Formatters.formatTruncatedHash(hash))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer()

            StatusPillView(text: source.sourceType, level: .neutral, showIcon: false)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    // MARK: - Critic Tab

    private var criticTabContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            // Auditor Scorecard Card
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Red-Team Critic Auditor Panel")
                            .font(.system(size: 15, weight: .bold))
                        Text("Deterministic Mathematical & Semantic Document Audit Engine (SPEC-PROMPT-CRITIC-001)")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    StatusPillView(
                        text: viewModel.criticReportStatus.title,
                        level: viewModel.criticReportStatus.statusLevel,
                        icon: "shield.checkerboard"
                    )
                }

                Divider()

                HStack(spacing: 20) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Audit Accuracy Score")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                        if let score = viewModel.criticScorePct {
                            Text(String(format: "%.1f%%", score))
                                .font(.system(size: 24, weight: .bold, design: .rounded))
                                .foregroundStyle(score >= 90 ? .green : .orange)
                        } else {
                            Text("—")
                                .font(.system(size: 24, weight: .bold, design: .rounded))
                                .foregroundStyle(.secondary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Verified Claims")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                        if viewModel.totalClaimsCount > 0 {
                            Text("\(viewModel.verifiedClaimsCount) / \(viewModel.totalClaimsCount)")
                                .font(.system(size: 14, weight: .semibold, design: .rounded))
                        } else {
                            Text("No data")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Audit Status")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                        Text(viewModel.criticReportStatus.title)
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(viewModel.criticReportStatus == .pass ? .green : (viewModel.criticReportStatus == .notRun ? .secondary : .orange))
                    }
                }
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))

            // Audit Check Items
            Text("Mathematical & Logical Audit Criteria")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.secondary)

            if viewModel.criticFindings.isEmpty {
                HStack(spacing: 12) {
                    Image(systemName: "shield.slash")
                        .font(.system(size: 24))
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Not evaluated yet")
                            .font(.system(size: 13, weight: .bold))
                        Text("Red-Team Critic audit has not yet run for this instrument or evidence bundle. Findings will be listed here after verification.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            } else {
                ForEach(viewModel.criticFindings) { finding in
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: finding.isPassed ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .font(.system(size: 16))
                            .foregroundStyle(finding.isPassed ? .green : .orange)

                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(finding.name)
                                    .font(.system(size: 12, weight: .bold))
                                Spacer()
                                StatusPillView(
                                    text: finding.isPassed ? "PASS" : "REVIEW",
                                    level: finding.isPassed ? .success : .warning,
                                    showIcon: false
                                )
                            }

                            Text(finding.description)
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)

                            if let detail = finding.detail {
                                Text("Result: \(detail)")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(.primary.opacity(0.8))
                            }
                        }
                    }
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                }
            }
        }
    }

    // MARK: - Research Launcher Sheet

    private var researchLauncherSheet: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Launch Deep Sourced Research")
                .font(.system(size: 16, weight: .bold))

            Text("Scans official SEC/factsheet filings, extracts claims, and produces a Born-Sealed evidence bundle.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                Text("Instrument / Ticker / ISIN")
                    .font(.system(size: 11, weight: .semibold))
                TextField("e.g. IE00B3YLTY66 or SPYI.DE", text: $viewModel.researchTargetTickerOrIsin)
                    .textFieldStyle(.roundedBorder)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Analytical Horizon")
                    .font(.system(size: 11, weight: .semibold))
                Picker("Horizon", selection: $viewModel.researchHorizon) {
                    Text("Long Term (Strategic)").tag("uzun")
                    Text("Medium Term (Tactical)").tag("orta")
                    Text("Short Term (Opportunity)").tag("firsat")
                }
                .pickerStyle(.radioGroup)
            }

            HStack {
                Spacer()

                Button("Cancel") {
                    viewModel.isShowingResearchSheet = false
                }
                .buttonStyle(.bordered)

                Button {
                    let isin = viewModel.researchTargetTickerOrIsin
                    let horizon = viewModel.researchHorizon
                    viewModel.isShowingResearchSheet = false
                    Task {
                        await viewModel.triggerResearch(isin: isin, horizon: horizon)
                    }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "sparkles")
                        Text("Start Research")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.researchTargetTickerOrIsin.isEmpty || viewModel.isExecutingAction)
            }
        }
        .padding(24)
        .frame(width: 440)
    }
}
