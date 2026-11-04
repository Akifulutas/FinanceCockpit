import SwiftUI

/// Section 4.1: Unified Status Capsule (Durum Kapsülü) for ETFCockpit v2.
/// Replaces fragmented pills with a single, cohesive, clickable toolbar element.
public struct StatusCapsuleView: View {
    @ObservedObject public var appState: CockpitAppState
    @State private var isShowingPopover: Bool = false

    private var marketStatusText: String {
        if let text = appState.marketStatusText {
            return text
        }
        if let isOpen = appState.isMarketOpen {
            return isOpen ? "XETR: Open" : "XETR: Closed"
        }
        return "XETR: ?"
    }

    private var isMarketOpen: Bool {
        appState.isMarketOpen ?? false
    }

    private var marketColor: Color {
        guard let open = appState.isMarketOpen else { return .secondary }
        return open ? .green : .secondary
    }

    private var brokerSessionText: String {
        switch appState.brokerSessionActive {
        case .some(true): return "Scalable: Active"
        case .some(false): return "Scalable: Inactive"
        case .none: return "Scalable: Unknown"
        }
    }

    private var brokerSessionColor: Color {
        switch appState.brokerSessionActive {
        case .some(true): return .green
        case .some(false): return .orange
        case .none: return .secondary
        }
    }

    private var freshnessText: String {
        if let text = appState.dataFreshnessText {
            return "Data: \(text)"
        }
        return "Data: No Quotes"
    }

    private var freshnessColor: Color {
        switch appState.dataFreshnessText {
        case "Live": return .green
        case "Delayed": return .orange
        case "Stale": return .red
        default: return .secondary
        }
    }

    private var freshnessIcon: String {
        switch appState.dataFreshnessText {
        case "Live": return "bolt.fill"
        case "Delayed": return "clock"
        case "Stale": return "exclamationmark.triangle"
        default: return "questionmark.circle"
        }
    }

    public init(appState: CockpitAppState) {
        self.appState = appState
    }

    public var body: some View {
        Button {
            isShowingPopover.toggle()
        } label: {
            HStack(spacing: 8) {
                // 1. Market Status
                HStack(spacing: 4) {
                    Circle()
                        .fill(marketColor)
                        .frame(width: 6, height: 6)
                    Text(marketStatusText)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(appState.isMarketOpen == true ? Color.primary : Color.secondary)
                }

                Text("│")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)

                // 2. Broker Session
                HStack(spacing: 4) {
                    Circle()
                        .fill(brokerSessionColor)
                        .frame(width: 6, height: 6)
                    Text(brokerSessionText)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(appState.brokerSessionActive == true ? Color.primary : Color.secondary)
                }

                Text("│")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)

                // 3. Data Freshness
                HStack(spacing: 4) {
                    Image(systemName: freshnessIcon)
                        .font(.system(size: 10))
                        .foregroundStyle(freshnessColor)
                    Text(freshnessText)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(freshnessColor == .green ? Color.primary : Color.secondary)
                }

                Text("│")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)

                // 4. Cryptographic Seal
                HStack(spacing: 4) {
                    Image(systemName: appState.auditStatusLevel.defaultIcon)
                        .font(.system(size: 10))
                        .foregroundStyle(appState.auditStatusLevel.color)
                    Text(appState.auditStatusText)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(appState.auditStatusLevel.color)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                Capsule()
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
            .overlay(
                Capsule()
                    .strokeBorder(Color.primary.opacity(0.12), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .popover(isPresented: $isShowingPopover) {
            popoverDiagnosticDetails
        }
    }

    private var popoverDiagnosticDetails: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Cockpit System Status & Diagnostics")
                    .font(.system(size: 14, weight: .bold))
                Spacer()
                Image(systemName: "shield.lefthalf.filled.badge.checkmark")
                    .foregroundStyle(appState.auditStatusLevel.color)
            }

            Divider()

            // 1. Market Details
            VStack(alignment: .leading, spacing: 4) {
                Label("Market Session: Xetra (Frankfurt)", systemImage: "clock")
                    .font(.system(size: 12, weight: .semibold))
                Text("Open 09:00–17:30 CET · Morning forecast: 09:30 CET · Evening settlement: 17:40 CET")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            // 2. Broker Session Details
            VStack(alignment: .leading, spacing: 4) {
                Label("Broker Session: Scalable Capital", systemImage: "lock.shield")
                    .font(.system(size: 12, weight: .semibold))
                let sessionDesc = appState.brokerSessionActive == true ? "Read-only local session active. CLI and Safari 2FA verified." : "Broker session inactive or verification pending."
                Text(sessionDesc)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            // 3. Database & Cryptographic Seal
            VStack(alignment: .leading, spacing: 4) {
                Label("Cryptographic Integrity (SHA-256)", systemImage: "link.badge.plus")
                    .font(.system(size: 12, weight: .semibold))
                let snaps = appState.snapshotCount.map { "\($0)" } ?? "?"
                let events = appState.auditEventCount.map { "\($0)" } ?? "?"
                let triggers = appState.triggerCount.map { "\($0)" } ?? "?"
                Text("\(snaps) sealed snapshots · \(events) audit events · \(triggers) SQLite triggers active.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Divider()

            // Quick Audit Action
            HStack {
                Button {
                    Task {
                        await appState.runQuickAudit()
                    }
                } label: {
                    HStack(spacing: 5) {
                        if appState.isRunningQuickAudit {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "checkmark.shield.fill")
                        }
                        Text("Verify Integrity Now")
                    }
                }
                .disabled(appState.isRunningQuickAudit)
                .buttonStyle(.borderedProminent)

                Spacer()

                Button("Close") {
                    isShowingPopover = false
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(16)
        .frame(width: 380)
    }
}
