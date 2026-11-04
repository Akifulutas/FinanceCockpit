import SwiftUI

/// Container view for Portfolio (⌘2), providing native segmented tabs for
/// Positions, Transaction Ledger, and Allocation & Overlap.
public struct PortfolioSectionView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var selectedTab: PortfolioTab = .positions

    public enum PortfolioTab: String, CaseIterable, Identifiable {
        case positions = "Positions"
        case ledger = "Transaction Ledger"
        case basket = "Allocation & Overlap"

        public var id: String { rawValue }

        public var icon: String {
            switch self {
            case .positions: return "chart.pie.fill"
            case .ledger: return "list.bullet.rectangle.portrait"
            case .basket: return "square.grid.2x2"
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
                    ForEach(PortfolioTab.allCases) { tab in
                        Label(tab.rawValue, systemImage: tab.icon).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 420)

                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 10)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            // Sub-screen content
            switch selectedTab {
            case .positions:
                PortfolioView(viewModel: appState.portfolioVM)
            case .ledger:
                TransactionLedgerView(viewModel: appState.ledgerVM)
            case .basket:
                TargetBasketOverlapView(viewModel: appState.basketVM)
            }
        }
    }
}
