import SwiftUI

/// Root SwiftUI App for FinanceCockpit macOS application.
/// Configures window sizing constraints (min: 1100x750, default: 1300x850) and native menu shortcuts.
public struct FinanceCockpitApp: App {
    @StateObject private var appState: CockpitAppState

    public init() {
        _appState = StateObject(wrappedValue: CockpitAppState())
    }

    public init(appState: CockpitAppState) {
        _appState = StateObject(wrappedValue: appState)
    }

    public var body: some Scene {
        WindowGroup {
            CockpitShellView(appState: appState)
                .frame(minWidth: 1100, minHeight: 750)
        }
        .defaultSize(width: 1300, height: 850)
        .commands {
            CommandGroup(replacing: .newItem) {}

            CommandMenu("Navigate") {
                Button("Refresh") {
                    Task {
                        await appState.refreshCurrentView()
                    }
                }
                .keyboardShortcut("r", modifiers: .command)

                Divider()

                Button("Today") {
                    appState.selectSection(.today)
                }
                .keyboardShortcut("1", modifiers: .command)

                Button("Portfolio") {
                    appState.selectSection(.portfolio)
                }
                .keyboardShortcut("2", modifiers: .command)

                Button("Forecasts") {
                    appState.selectSection(.forecast)
                }
                .keyboardShortcut("3", modifiers: .command)

                Button("Decisions") {
                    appState.selectSection(.decisions)
                }
                .keyboardShortcut("4", modifiers: .command)

                Button("Discovery") {
                    appState.selectSection(.discovery)
                }
                .keyboardShortcut("5", modifiers: .command)

                Button("System") {
                    appState.selectSection(.system)
                }
                .keyboardShortcut("6", modifiers: .command)
            }
        }
    }
}

public typealias ETFCockpitApp = FinanceCockpitApp
