import SwiftUI

public struct ThesisManagementView: View {
    @ObservedObject public var viewModel: ThesisManagementViewModel

    public init(viewModel: ThesisManagementViewModel) {
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

                // MARK: - KPI Metric Cards
                kpiSection

                // MARK: - Filters Bar
                filtersSection

                // MARK: - Theses Cards Grid
                thesesGridSection
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.theses.isEmpty {
                await viewModel.loadData()
            }
        }
        .sheet(isPresented: $viewModel.isShowingDetailSheet) {
            if let thesis = viewModel.selectedThesis {
                thesisDetailSheet(thesis: thesis)
            }
        }
        .sheet(isPresented: $viewModel.isShowingCreateSheet) {
            createThesisSheet
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Investment Thesis Ledger")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.activeThesesCount) Active Theses",
                        level: .success,
                        icon: "lightbulb.fill"
                    )
                }

                Text("Long-Term Investment Theses, Falsification Triggers & Health Auditing")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                    viewModel.isShowingCreateSheet = true
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "plus")
                        Text("New Thesis")
                    }
                }
                .buttonStyle(.borderedProminent)

                Button {
                    Task { await viewModel.triggerThesisHealthCheck() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isExecutingAction {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "stethoscope")
                        }
                        Text("Run Health Check")
                    }
                }
                .buttonStyle(.bordered)
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
                title: "Active Theses",
                value: viewModel.kpiActiveThesesText,
                subtitle: viewModel.theses.isEmpty ? "No theses recorded yet" : "\(viewModel.totalThesesCount) Total Versions",
                trend: .neutral,
                badge: "ACTIVE"
            )

            MetricCardView(
                title: "Falsification Triggers",
                value: viewModel.kpiFalsificationSummaryText,
                subtitle: viewModel.theses.isEmpty ? "No active theses" : (viewModel.hasBreachedThesis ? "Trigger breach detected" : "Zero trigger breaches"),
                trend: viewModel.theses.isEmpty ? .neutral : (viewModel.hasBreachedThesis ? .down : .up),
                trendValue: viewModel.theses.isEmpty ? nil : (viewModel.hasBreachedThesis ? "BREACH" : "NORMAL"),
                badge: "TRIGGERS",
                badgeColor: viewModel.theses.isEmpty ? .secondary : (viewModel.hasBreachedThesis ? .red : .green)
            )

            MetricCardView(
                title: "Monthly Review Health",
                value: viewModel.kpiHealthSummaryText,
                subtitle: viewModel.theses.isEmpty ? "No reviews scheduled" : (viewModel.hasDelayedReview ? "Overdue review pending" : "On regular cadence"),
                trend: viewModel.theses.isEmpty ? .neutral : (viewModel.hasDelayedReview ? .down : .up),
                badge: "HEALTH",
                badgeColor: viewModel.theses.isEmpty ? .secondary : (viewModel.hasDelayedReview ? .orange : .green)
            )

            MetricCardView(
                title: "Invalidated / Superseded",
                value: "\(viewModel.invalidatedThesesCount)",
                subtitle: "Breached or superseded",
                trend: .neutral,
                badge: "ARCHIVE"
            )
        }
    }

    private var filtersSection: some View {
        HStack(spacing: 12) {
            Picker("Status", selection: $viewModel.selectedStatusFilter) {
                ForEach(ThesisStatusFilter.allCases) { filter in
                    Text(filter.displayTitle).tag(filter)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 360)

            Picker("Category", selection: $viewModel.selectedCategoryFilter) {
                Text("All Categories").tag(String?.none)
                ForEach(ThesisManagementViewModel.categories, id: \.0) { catKey, catTitle, _ in
                    Text(catTitle).tag(String?.some(catKey))
                }
            }
            .pickerStyle(.menu)
            .frame(width: 170)

            Spacer()

            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search thesis title, ISIN, or summary...", text: $viewModel.searchText)
                    .textFieldStyle(.plain)
                    .frame(width: 180)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
        }
    }

    private var thesesGridSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            if viewModel.theses.isEmpty {
                heldPositionsMissingThesesSection
            } else if viewModel.filteredTheses.isEmpty {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
                        Image(systemName: "lightbulb")
                            .font(.system(size: 30))
                            .foregroundStyle(.secondary)
                        Text("No investment theses match your filters.")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                        Text("Click 'New Thesis' to seal your first investment thesis.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    .padding(30)
                    Spacer()
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(nsColor: .controlBackgroundColor)))
            } else {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
                    ForEach(viewModel.filteredTheses) { thesis in
                        thesisCard(thesis: thesis)
                    }
                }
            }
        }
    }

    // MARK: - Held Positions Missing Theses
    private var heldPositionsMissingThesesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(systemName: "lightbulb.slash.fill")
                    .font(.system(size: 20))
                    .foregroundStyle(.orange)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Held Positions (Theses Pending)")
                        .font(.system(size: 14, weight: .bold))
                    Text("The following portfolio positions do not yet have a sealed investment thesis. Long-term discipline requires at least 2 falsification triggers per holding.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }

            VStack(spacing: 8) {
                if viewModel.heldPositions.isEmpty {
                    // Fallback default core positions if positions are empty
                    heldPositionRow(isin: "IE00B3YLTY66", ticker: "SPYI", name: "SPDR MSCI ACWI IMI UCITS ETF")
                    heldPositionRow(isin: "IE00BKM4GZ66", ticker: "IS3N", name: "iShares Core MSCI EM IMI UCITS ETF")
                    heldPositionRow(isin: "IE00BYX2JD69", ticker: "IS3R", name: "iShares Edge MSCI World Multifactor")
                    heldPositionRow(isin: "IE00B3F81409", ticker: "IS3S", name: "iShares Edge MSCI USA Value Factor")
                } else {
                    ForEach(viewModel.heldPositions) { pos in
                        heldPositionRow(
                            isin: pos.isin,
                            ticker: nil,
                            name: !pos.displayName.isEmpty ? pos.displayName : pos.isin,
                            originalPosition: pos
                        )
                    }
                }
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
    }

    private func heldPositionRow(isin: String, ticker: String?, name: String, originalPosition: PositionItem? = nil) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    if let ticker {
                        Text(ticker)
                            .font(.system(size: 12, weight: .bold))
                    }
                    Text(name)
                        .font(.system(size: 12, weight: .medium))
                        .lineLimit(1)
                }

                Text(isin)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // "NO THESIS" badge
            Text("NO THESIS")
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .foregroundStyle(.orange)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Capsule().fill(Color.orange.opacity(0.12)))
                .overlay(Capsule().strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))

            // "Draft Thesis" shortcut button
            Button {
                if let pos = originalPosition {
                    viewModel.openCreateThesis(for: pos)
                } else {
                    viewModel.newIsin = isin
                    viewModel.newTitle = "\(ticker ?? isin) Investment Thesis"
                    viewModel.newCategory = "CORE"
                    viewModel.newHorizon = "LONG_TERM"
                    viewModel.isShowingCreateSheet = true
                }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "square.and.pencil")
                    Text("Draft Thesis")
                        .fontWeight(.semibold)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
            .controlSize(.small)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.orange.opacity(0.04)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.orange.opacity(0.15), lineWidth: 1))
    }

    private func thesisCard(thesis: ThesisItem) -> some View {
        let health = viewModel.healthStatus(for: thesis)
        let falsification = viewModel.falsificationStatus(for: thesis)

        return VStack(alignment: .leading, spacing: 10) {
            // Header Row
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(thesis.title)
                        .font(.system(size: 14, weight: .bold))
                        .lineLimit(2)

                    HStack(spacing: 6) {
                        Text(thesis.isin)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                        if let name = thesis.instrumentName {
                            Text("• \(name)")
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                Spacer()

                StatusPillView(
                    text: health.rawValue,
                    level: health.statusLevel,
                    showIcon: false
                )
            }

            // Summary
            Text(thesis.oneLineSummary)
                .font(.system(size: 12))
                .foregroundStyle(.primary.opacity(0.9))
                .lineLimit(3)

            // Falsification Triggers Box (MANDATORY >= 2)
            falsificationTriggersBox(triggers: thesis.falsificationTriggers, status: falsification)

            Divider()

            // Footer
            HStack {
                HStack(spacing: 6) {
                    categoryBadge(thesis.category)
                    horizonBadge(thesis.horizon)
                }

                Spacer()

                if let alloc = thesis.targetAllocationPct {
                    Text("Target: \(String(format: "%.1f%%", NSDecimalNumber(decimal: alloc).doubleValue))")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.secondary)
                }

                Button("Details") {
                    viewModel.selectedThesis = thesis
                    viewModel.isShowingDetailSheet = true
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    private func falsificationTriggersBox(triggers: [String], status: FalsificationStatus) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.orange)

                Text("Falsification Triggers (\(triggers.count) Defined)")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.orange)

                Spacer()

                Text(status.displayTitle)
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(status.statusLevel.color)
            }

            ForEach(triggers.prefix(2), id: \.self) { trigger in
                HStack(alignment: .top, spacing: 4) {
                    Text("•")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.orange)
                    Text(trigger)
                        .font(.system(size: 10))
                        .foregroundStyle(.primary.opacity(0.85))
                        .lineLimit(2)
                }
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.orange.opacity(0.2), lineWidth: 1))
    }

    private func categoryBadge(_ cat: String) -> some View {
        Text(cat)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Capsule().fill(Color.blue.opacity(0.12)))
            .foregroundStyle(.blue)
    }

    private func horizonBadge(_ hor: String) -> some View {
        Text(hor)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Capsule().fill(Color.secondary.opacity(0.12)))
            .foregroundStyle(.secondary)
    }

    // MARK: - Detail Sheet

    private func thesisDetailSheet(thesis: ThesisItem) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(thesis.title)
                        .font(.system(size: 18, weight: .bold))
                    Text("ISIN: \(thesis.isin) — Version: v\(thesis.versionNumber)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button("Close") {
                    viewModel.isShowingDetailSheet = false
                }
                .buttonStyle(.bordered)
            }

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    // One line summary
                    VStack(alignment: .leading, spacing: 4) {
                        Text("One-Line Thesis Summary")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(.secondary)
                        Text(thesis.oneLineSummary)
                            .font(.system(size: 13, weight: .medium))
                    }

                    // Economic Rationale
                    if !thesis.economicRationale.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Economic & Structural Rationale")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.secondary)
                            Text(thesis.economicRationale)
                                .font(.system(size: 12))
                                .foregroundStyle(.primary.opacity(0.9))
                        }
                    }

                    // Evidence Pillars
                    if !thesis.evidencePillars.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Evidence Pillars")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.secondary)
                            ForEach(thesis.evidencePillars, id: \.self) { pillar in
                                HStack(alignment: .top, spacing: 6) {
                                    Image(systemName: "checkmark.circle.fill")
                                        .font(.system(size: 10))
                                        .foregroundStyle(.green)
                                    Text(pillar)
                                        .font(.system(size: 11))
                                }
                            }
                        }
                    }

                    // Falsification Triggers
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Falsification Triggers")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(.orange)
                        ForEach(thesis.falsificationTriggers, id: \.self) { trigger in
                            HStack(alignment: .top, spacing: 6) {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.orange)
                                Text(trigger)
                                    .font(.system(size: 11))
                            }
                        }
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.08)))

                    // Benchmark & Review Date
                    HStack(spacing: 20) {
                        if let bench = thesis.benchmarkReference {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Benchmark Reference:")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                                Text(bench)
                                    .font(.system(size: 11, weight: .semibold))
                            }
                        }

                        if let review = thesis.nextReviewDate {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Next Review Date:")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                                Text(review)
                                    .font(.system(size: 11, weight: .semibold))
                            }
                        }
                    }
                }
            }
        }
        .padding(24)
        .frame(minWidth: 500, minHeight: 450)
    }

    // MARK: - Create Thesis Sheet

    private var createThesisSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Create New Investment Thesis")
                .font(.system(size: 16, weight: .bold))

            Text("Formulate verifiable hypotheses and at least 2 falsification triggers before sealing the thesis.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Thesis Title")
                            .font(.system(size: 11, weight: .semibold))
                        TextField("e.g. Global Equity Core Accumulation Thesis", text: $viewModel.newTitle)
                            .textFieldStyle(.roundedBorder)
                    }

                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("ISIN")
                                .font(.system(size: 11, weight: .semibold))
                            TextField("IE00B3YLTY66", text: $viewModel.newIsin)
                                .textFieldStyle(.roundedBorder)
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text("Category")
                                .font(.system(size: 11, weight: .semibold))
                            Picker("", selection: $viewModel.newCategory) {
                                ForEach(ThesisManagementViewModel.categories, id: \.0) { key, title, _ in
                                    Text(title).tag(key)
                                }
                            }
                            .pickerStyle(.menu)
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text("Investment Horizon")
                                .font(.system(size: 11, weight: .semibold))
                            Picker("", selection: $viewModel.newHorizon) {
                                ForEach(ThesisManagementViewModel.horizons, id: \.0) { key, title in
                                    Text(title).tag(key)
                                }
                            }
                            .pickerStyle(.menu)
                        }
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("One-Line Thesis Summary")
                            .font(.system(size: 11, weight: .semibold))
                        TextField("Single sentence defining the core investment hypothesis", text: $viewModel.newSummary)
                            .textFieldStyle(.roundedBorder)
                    }

                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Target Allocation (%)")
                                .font(.system(size: 11, weight: .semibold))
                            TextField("e.g. 25.0 or 0.25 (Optional)", text: $viewModel.newTargetAllocationPct)
                                .textFieldStyle(.roundedBorder)
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text("Next Review Date")
                                .font(.system(size: 11, weight: .semibold))
                            TextField("YYYY-MM-DD (e.g. 2026-12-01)", text: $viewModel.newReviewDate)
                                .textFieldStyle(.roundedBorder)
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text("Benchmark Reference")
                                .font(.system(size: 11, weight: .semibold))
                            TextField("e.g. MSCI World (Optional)", text: $viewModel.newBenchmark)
                                .textFieldStyle(.roundedBorder)
                        }
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text("Falsification Triggers (One per line — Minimum 2 mandatory)")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.orange)
                            Spacer()
                            let count = viewModel.newFalsificationTriggersText
                                .components(separatedBy: .newlines)
                                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                                .filter { !$0.isEmpty }.count
                            Text("\(count) / 2 Min")
                                .font(.system(size: 10, weight: .bold, design: .monospaced))
                                .foregroundStyle(count >= 2 ? .green : .orange)
                        }

                        TextEditor(text: $viewModel.newFalsificationTriggersText)
                            .frame(height: 60)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.orange.opacity(0.3), lineWidth: 1))
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Economic Rationale")
                            .font(.system(size: 11, weight: .semibold))
                        TextEditor(text: $viewModel.newRationale)
                            .frame(height: 60)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Evidence Pillars (One per line, optional)")
                            .font(.system(size: 11, weight: .semibold))
                        TextEditor(text: $viewModel.newEvidencePillarsText)
                            .frame(height: 50)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Counter-Arguments & Bear Cases (Optional)")
                            .font(.system(size: 11, weight: .semibold))
                        TextEditor(text: $viewModel.newCounterArguments)
                            .frame(height: 50)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
                    }
                }
            }

            HStack {
                Spacer()

                Button("Cancel") {
                    viewModel.isShowingCreateSheet = false
                }
                .buttonStyle(.bordered)

                Button {
                    Task { await viewModel.triggerCreateThesis() }
                } label: {
                    Text("Seal Investment Thesis")
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(24)
        .frame(minWidth: 540, minHeight: 640)
    }
}
