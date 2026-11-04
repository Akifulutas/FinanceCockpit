import SwiftUI

/// View for the "Değerlendirme" (Position Evaluation) screen (E2).
public struct EvaluationView: View {
    @ObservedObject public var viewModel: EvaluationViewModel

    public init(viewModel: EvaluationViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerBar
                disclaimerBanner

                if viewModel.isLoading {
                    ProgressView("Fetching position evaluation data...")
                        .frame(maxWidth: .infinity, minHeight: 200)
                } else if let error = viewModel.errorMessage {
                    errorBanner(error)
                } else if viewModel.assessments.isEmpty {
                    emptyState
                } else {
                    assessmentsList
                }
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            await viewModel.loadData()
        }
        .confirmationDialog(
            "Deep Portfolio Analysis",
            isPresented: $viewModel.showDeepAnalysisConfirmation,
            titleVisibility: .visible
        ) {
            Button("Start Analysis", role: .none) {
                Task {
                    await viewModel.triggerDeepAnalysis()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Deep analysis evaluates current market quotes and deterministic models to generate a decision-support assessment. Do you want to proceed?")
        }
    }

    // MARK: - Header Bar
    private var headerBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Position Decisions")
                    .font(.system(size: 24, weight: .bold))
                Text("Rule-based and model-driven decision support for portfolio positions")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if let runId = viewModel.runId {
                Text("Run: \(runId)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color(nsColor: .controlBackgroundColor))
                    .cornerRadius(6)
            }

            Button {
                viewModel.showDeepAnalysisConfirmation = true
            } label: {
                HStack(spacing: 6) {
                    if viewModel.isRunningDeepAnalysis {
                        ProgressView()
                            .controlSize(.small)
                        Text("Analyzing...")
                    } else {
                        Image(systemName: "sparkles")
                        Text("Run Deep Analysis")
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.indigo)
            .disabled(viewModel.isRunningDeepAnalysis)
        }
    }

    // MARK: - Mandatory Disclaimer Banner
    private var disclaimerBanner: some View {
        HStack(spacing: 12) {
            Image(systemName: "hand.raised.fill")
                .font(.system(size: 16))
                .foregroundStyle(.orange)

            VStack(alignment: .leading, spacing: 2) {
                Text("LEGAL NOTICE & DECISION-SUPPORT MANDATE")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.orange)
                Text("Decision support only; the system never places automated orders. All trades and portfolio rebalancing must be executed manually by the investor via Scalable Capital.")
                    .font(.system(size: 11))
                    .foregroundStyle(.primary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.1))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.orange.opacity(0.3), lineWidth: 1)
        )
    }

    // MARK: - Assessments List
    private var assessmentsList: some View {
        VStack(spacing: 16) {
            ForEach(viewModel.assessments) { item in
                assessmentCard(for: item)
            }
        }
    }

    private func assessmentCard(for item: DegerlendirAssessmentDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name)
                        .font(.system(size: 14, weight: .bold))
                    Text(item.isin)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                // Recommendation Badge
                recommendationBadge(for: item.label)
            }

            Divider()

            // Rationale / Reasons
            if !item.reasons.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("RATIONALE & MODEL ANALYSIS")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.secondary)

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

            // Notes / German Tax Rules
            if !item.notes.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("TAX & POLICY NOTES")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.secondary)

                    ForEach(item.notes.indices, id: \.self) { idx in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 11))
                                .foregroundStyle(.blue)
                            Text(item.notes[idx])
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(8)
                .background(Color(nsColor: .windowBackgroundColor))
                .cornerRadius(6)
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

    private func recommendationBadge(for label: String) -> some View {
        let text = label.uppercased()
        let color: Color
        let icon: String
        let display: String

        switch text {
        case "EKLE", "ADD":
            display = "ADD"
            color = .green
            icon = "plus.circle.fill"
        case "AZALT", "REDUCE":
            display = "REDUCE"
            color = .red
            icon = "minus.circle.fill"
        default: // TUT / HOLD
            display = "HOLD"
            color = .blue
            icon = "pause.circle.fill"
        }

        return HStack(spacing: 5) {
            Image(systemName: icon)
            Text(display)
                .fontWeight(.bold)
        }
        .font(.system(size: 12))
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(color.opacity(0.15))
        .foregroundStyle(color)
        .cornerRadius(6)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "chart.bar.doc.horizontal")
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text("No Evaluations Found")
                .font(.system(size: 16, weight: .semibold))
            Text("No saved evaluation reports found yet. Click 'Run Deep Analysis' to generate an assessment.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 400)
        }
        .frame(maxWidth: .infinity, minHeight: 250)
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
