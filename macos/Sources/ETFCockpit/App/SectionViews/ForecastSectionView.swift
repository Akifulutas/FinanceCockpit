import SwiftUI

/// Container view for Forecasts (⌘3), providing native segmented tabs for
/// Forecast & Settlement and Model Scorecard & Registry.
public struct ForecastSectionView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var selectedTab: ForecastTab = .settlement

    public enum ForecastTab: String, CaseIterable, Identifiable {
        case settlement = "Forecast & Settlement"
        case registry = "Model Scorecard & Registry"

        public var id: String { rawValue }

        public var icon: String {
            switch self {
            case .settlement: return "chart.line.uptrend.xyaxis"
            case .registry: return "cpu"
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
                    ForEach(ForecastTab.allCases) { tab in
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
            case .settlement:
                ForecastSettlementView(viewModel: appState.forecastVM)
            case .registry:
                ModelRegistryView(viewModel: appState.modelRegistryVM)
            }
        }
    }
}
