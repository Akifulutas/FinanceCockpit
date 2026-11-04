import SwiftUI

/// View for the "Rapor ve Yorum" (Reports & Commentary) screen (E4).
public struct ReportsView: View {
    @ObservedObject public var viewModel: ReportsViewModel

    public init(viewModel: ReportsViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        VStack(spacing: 0) {
            headerBar
                .padding(20)

            Divider()

            if let feedback = viewModel.actionFeedbackMessage {
                HStack(spacing: 8) {
                    Image(systemName: feedback.contains("✓") ? "checkmark.circle.fill" : "info.circle.fill")
                        .foregroundStyle(feedback.contains("✓") ? .green : .blue)
                    Text(feedback)
                        .font(.system(size: 11, weight: .medium))
                    Spacer()
                    Button("Close") {
                        viewModel.actionFeedbackMessage = nil
                    }
                    .font(.system(size: 10))
                    .buttonStyle(.plain)
                }
                .padding(10)
                .background(feedback.contains("✓") ? Color.green.opacity(0.1) : Color.blue.opacity(0.1))
            }

            if viewModel.isLoading {
                ProgressView("Scanning reports...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if viewModel.reports.isEmpty {
                emptyState
            } else {
                reportsSplitView
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            await viewModel.loadReports()
        }
    }

    // MARK: - Header Bar
    private var headerBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Reports & Commentary")
                    .font(.system(size: 24, weight: .bold))
                Text("Locally generated status reports, TradingAgents analysis, and commentary digests")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Generate Report Button
            Button {
                Task {
                    await viewModel.generateNewReport()
                }
            } label: {
                HStack(spacing: 6) {
                    if viewModel.isGeneratingReport {
                        ProgressView().controlSize(.small)
                        Text("Compiling...")
                    } else {
                        Image(systemName: "doc.badge.plus")
                        Text("Create Status Report")
                    }
                }
            }
            .buttonStyle(.bordered)
            .disabled(viewModel.isGeneratingReport)
            .help("Compiles portfolio status report (masa rapor)")

            // Generate Commentary Button
            Button {
                Task {
                    await viewModel.generateCommentaryPackage()
                }
            } label: {
                HStack(spacing: 6) {
                    if viewModel.isGeneratingCommentary {
                        ProgressView().controlSize(.small)
                        Text("Generating...")
                    } else {
                        Image(systemName: "bubble.left.and.bubble.right.fill")
                        Text("Generate Commentary")
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.purple)
            .disabled(viewModel.isGeneratingCommentary)
            .help("Generates multi-model consolidated commentary package (masa yorum)")

            // Refresh List Button
            Button {
                Task {
                    await viewModel.loadReports()
                }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
        }
    }

    // MARK: - Reports Split View
    private var reportsSplitView: some View {
        HSplitView {
            // Report Files List
            List(viewModel.reports, selection: $viewModel.selectedReport) { report in
                reportRow(for: report)
                    .tag(report)
            }
            .listStyle(.inset)
            .frame(minWidth: 260, idealWidth: 300, maxWidth: 360)

            // Document Preview
            VStack(alignment: .leading, spacing: 12) {
                if let selected = viewModel.selectedReport {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(selected.fileName)
                                .font(.system(size: 14, weight: .bold))
                            Text(formatDate(selected.modifiedDate))
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        reportTypePill(for: selected.reportType)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 14)

                    Divider()

                    ScrollView {
                        Text(viewModel.reportContent)
                            .font(.system(size: 12, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(16)
                    }
                } else {
                    Text("Select a report from the list on the left to view")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .background(Color(nsColor: .controlBackgroundColor))
        }
        .onChange(of: viewModel.selectedReport) { _, newReport in
            if let newReport {
                Task {
                    await viewModel.selectReport(newReport)
                }
            }
        }
    }

    private func reportRow(for item: ReportFileItem) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(item.title)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
                Spacer()
                reportTypePill(for: item.reportType)
            }
            Text(item.fileName)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Text(formatDate(item.modifiedDate))
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    private func reportTypePill(for type: String) -> some View {
        let color: Color
        switch type {
        case "COMMENTARY": color = .purple
        case "AGENT": color = .blue
        case "RESEARCH": color = .teal
        default: color = .indigo
        }

        return Text(type)
            .font(.system(size: 9, weight: .bold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .cornerRadius(4)
    }

    private func formatDate(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.string(from: date)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "doc.text")
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text("No Reports Found")
                .font(.system(size: 16, weight: .semibold))
            Text("No compiled markdown reports available yet. Use the buttons above to generate a new status report or commentary digest.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
