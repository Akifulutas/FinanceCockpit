import SwiftUI

/// View for the "Fırsat Taraması" (Opportunity Screener) screen (E3).
public struct ScreenerView: View {
    @ObservedObject public var viewModel: ScreenerViewModel

    public init(viewModel: ScreenerViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        VStack(spacing: 0) {
            headerBar
                .padding(20)

            Divider()

            if viewModel.isLoading {
                ProgressView("Loading opportunity screener data...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error = viewModel.errorMessage {
                errorBanner(error)
                    .padding(20)
                Spacer()
            } else if viewModel.candidates.isEmpty {
                emptyState
            } else {
                contentSplitView
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            await viewModel.loadData()
        }
        .sheet(isPresented: $viewModel.showPoolEditor) {
            poolEditorSheet
        }
    }

    // MARK: - Header Bar
    private var headerBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Opportunity Screener")
                    .font(.system(size: 24, weight: .bold))
                Text("Quantitative scoring and rule evaluation for candidate pool instruments")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Pool Count Pill
            HStack(spacing: 5) {
                Image(systemName: "circle.grid.2x2.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(.blue)
                Text("\(viewModel.poolCount) Instruments in Pool")
                    .font(.system(size: 11, weight: .medium))
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Color(nsColor: .controlBackgroundColor))
            .cornerRadius(12)

            // Pool Editor Button
            Button {
                Task {
                    await viewModel.openPoolEditor()
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "slider.horizontal.3")
                    Text("Edit Pool")
                }
            }
            .buttonStyle(.bordered)
            .help("Edit candidate instrument ISIN pool")

            // Live Scan Button
            Button {
                Task {
                    await viewModel.triggerLiveScan()
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "bolt.fill")
                    Text("Scan Now")
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.blue)
            .disabled(viewModel.isLoading)
            .help("Executes full screener run using live market quotes and historical series.")

            // Refresh Button
            Button {
                Task {
                    await viewModel.loadData()
                }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .disabled(viewModel.isLoading)
            .help("Reloads latest sealed scan from database.")
        }
    }

    // MARK: - Content Split View (List + Detail Drawer)
    private var contentSplitView: some View {
        HSplitView {
            // Candidates Table
            VStack(alignment: .leading, spacing: 0) {
                List(viewModel.candidates, selection: $viewModel.selectedCandidate) { candidate in
                    candidateRow(for: candidate)
                        .tag(candidate)
                }
                .listStyle(.inset)
            }
            .frame(minWidth: 400, maxWidth: .infinity)

            // Detail Drawer
            VStack(alignment: .leading, spacing: 16) {
                if let selected = viewModel.selectedCandidate {
                    candidateDetailView(for: selected)
                } else {
                    Text("Select a candidate to view details")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .padding(16)
            .frame(minWidth: 300, idealWidth: 350, maxWidth: 450)
            .background(Color(nsColor: .controlBackgroundColor))
        }
    }

    private func candidateRow(for item: TaramaCandidateDTO) -> some View {
        HStack(spacing: 12) {
            // Score circle
            ZStack {
                Circle()
                    .fill(scoreColor(item.score).opacity(0.15))
                    .frame(width: 38, height: 38)
                Text(item.score != nil ? String(format: "%.1f", item.score!) : "—")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(scoreColor(item.score))
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(item.name)
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(1)
                Text(item.isin)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Tag Pill
            Text(displayLabel(for: item.label))
                .font(.system(size: 10, weight: .bold))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(labelColor(item.label).opacity(0.15))
                .foregroundStyle(labelColor(item.label))
                .cornerRadius(4)
        }
        .padding(.vertical, 4)
    }

    private func candidateDetailView(for item: TaramaCandidateDTO) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name)
                        .font(.system(size: 16, weight: .bold))
                    Text(item.isin)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(displayLabel(for: item.label))
                    .font(.system(size: 12, weight: .bold))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(labelColor(item.label).opacity(0.15))
                    .foregroundStyle(labelColor(item.label))
                    .cornerRadius(6)
            }

            Divider()

            HStack {
                Text("Screener Score:")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(item.score != nil ? String(format: "%.2f / 10.0", item.score!) : "Not Calculated")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(scoreColor(item.score))
            }

            Divider()

            VStack(alignment: .leading, spacing: 8) {
                Text("SCREENING & SELECTION RATIONALE")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.secondary)

                if item.reasons.isEmpty {
                    Text("No specific rationale recorded.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(item.reasons.indices, id: \.self) { idx in
                        HStack(alignment: .top, spacing: 6) {
                            Text("•")
                                .foregroundStyle(.secondary)
                            Text(item.reasons[idx])
                                .font(.system(size: 12))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }

            Spacer()

            // Safe Decision-Support Disclaimer
            Text("Note: Decision support only; the system never places automated broker orders.")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    // MARK: - Pool Editor Sheet
    private var poolEditorSheet: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Edit Screener Pool")
                    .font(.system(size: 18, weight: .bold))
                Spacer()
                Button("Close") {
                    viewModel.showPoolEditor = false
                }
            }

            Text("Enter one candidate ETF or equity ISIN per line. Each ISIN is verified via the Luhn checksum algorithm.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)

            TextEditor(text: $viewModel.poolISINsText)
                .font(.system(size: 12, design: .monospaced))
                .frame(minHeight: 200)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.3), lineWidth: 1))

            if let valMsg = viewModel.poolEditorValidationMessage {
                Text(valMsg)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
            }

            HStack {
                Spacer()
                Button("Cancel") {
                    viewModel.showPoolEditor = false
                }
                .buttonStyle(.bordered)

                Button {
                    Task {
                        _ = await viewModel.savePool()
                    }
                } label: {
                    if viewModel.isSavingPool {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Save Pool")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isSavingPool)
            }
        }
        .padding(20)
        .frame(minWidth: 480, minHeight: 380)
    }

    // MARK: - Helpers
    private func scoreColor(_ score: Double?) -> Color {
        guard let s = score else { return .secondary }
        if s >= 7.0 { return .green }
        if s >= 5.0 { return .blue }
        return .orange
    }

    // Labels are CLI data values from masa/scanner.py (ARAŞTIRMAYA DEĞER / İZLE / ELENDİ); mapped to English for display only.
    private func labelColor(_ label: String) -> Color {
        switch label.uppercased() {
        case "EKLE", "ADD", "ARAŞTIRMAYA DEĞER", "WORTH_RESEARCHING": return .green
        case "AZALT", "REDUCE": return .red
        case "IZLE", "İZLE", "WATCH": return .purple
        case "ELENDİ", "ELENDI", "EXCLUDED": return .secondary
        default: return .blue
        }
    }

    private func displayLabel(for label: String) -> String {
        switch label.uppercased() {
        case "EKLE", "ADD": return "ADD"
        case "AZALT", "REDUCE": return "REDUCE"
        case "TUT", "HOLD": return "HOLD"
        case "IZLE", "İZLE", "WATCH": return "WATCH"
        case "ARAŞTIRMAYA DEĞER", "WORTH_RESEARCHING": return "WORTH RESEARCHING"
        case "ELENDİ", "ELENDI", "EXCLUDED": return "EXCLUDED"
        default: return label.uppercased()
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text("No Screener Results Found")
                .font(.system(size: 16, weight: .semibold))
            Text("No screened instruments in pool yet. Add candidate instruments using the 'Edit Pool' button.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func errorBanner(_ message: String) -> some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
            Text(message)
                .font(.system(size: 12))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.1))
        .cornerRadius(8)
    }
}
