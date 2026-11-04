import SwiftUI

/// Container view for System (⌘6), providing native segmented tabs for
/// Integrity & Health, Scheduler & Automation, and System Configuration.
public struct SystemSectionView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var selectedTab: SystemTab = .integrity

    public enum SystemTab: String, CaseIterable, Identifiable {
        case integrity = "Integrity & Health"
        case scheduler = "Scheduler & Automation"
        case configuration = "System Configuration"

        public var id: String { rawValue }

        public var icon: String {
            switch self {
            case .integrity: return "lock.shield.fill"
            case .scheduler: return "clock.badge.checkmark"
            case .configuration: return "gearshape.2.fill"
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
                    ForEach(SystemTab.allCases) { tab in
                        Label(tab.rawValue, systemImage: tab.icon).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 460)

                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 10)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            switch selectedTab {
            case .integrity:
                SystemIntegrityView(viewModel: appState.integrityVM)
            case .scheduler:
                SchedulerAutomationView(viewModel: appState.schedulerVM)
            case .configuration:
                SystemConfigurationView(viewModel: appState.configurationVM)
            }
        }
    }
}
