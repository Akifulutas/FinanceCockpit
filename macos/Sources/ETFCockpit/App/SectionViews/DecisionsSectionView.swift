import SwiftUI

/// Container view for Decisions (⌘4), providing native segmented tabs for
/// Position Decisions, Investment Theses, and Reports & Commentary.
public struct DecisionsSectionView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var selectedTab: DecisionsTab = .evaluation

    public enum DecisionsTab: String, CaseIterable, Identifiable {
        case evaluation = "Position Decisions"
        case thesis = "Investment Theses"
        case reports = "Reports & Commentary"

        public var id: String { rawValue }

        public var icon: String {
            switch self {
            case .evaluation: return "checklist"
            case .thesis: return "lightbulb.fill"
            case .reports: return "newspaper.fill"
            }
        }
    }

    public init(appState: CockpitAppState) {
        self.appState = appState
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Segmented Header
            HStack {
                Picker("", selection: $selectedTab) {
                    ForEach(DecisionsTab.allCases) { tab in
                        Label(tab.rawValue, systemImage: tab.icon).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 440)

                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 10)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            switch selectedTab {
            case .evaluation:
                EvaluationView(viewModel: appState.evaluationVM)
            case .thesis:
                ThesisManagementView(viewModel: appState.thesisVM)
            case .reports:
                ReportsView(viewModel: appState.reportsVM)
            }
        }
    }
}
