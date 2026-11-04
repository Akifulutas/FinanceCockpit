import SwiftUI

/// Container view for Discovery (⌘5), providing native segmented tabs for
/// Opportunity Screener and Sourced Research.
public struct DiscoverySectionView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var selectedTab: DiscoveryTab = .screener

    public enum DiscoveryTab: String, CaseIterable, Identifiable {
        case screener = "Opportunity Screener"
        case research = "Sourced Research"

        public var id: String { rawValue }

        public var icon: String {
            switch self {
            case .screener: return "slider.horizontal.3"
            case .research: return "doc.text.magnifyingglass"
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
                    ForEach(DiscoveryTab.allCases) { tab in
                        Label(tab.rawValue, systemImage: tab.icon).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 380)

                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 10)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            switch selectedTab {
            case .screener:
                ScreenerView(viewModel: appState.screenerVM)
            case .research:
                ResearchEvidenceView(viewModel: appState.researchVM)
            }
        }
    }
}
