import SwiftUI

public enum StatusLevel: String, Sendable, Equatable, Hashable, CaseIterable {
    case success
    case warning
    case error
    case neutral
    case info
    case unknown

    public var color: Color {
        switch self {
        case .success: return .green
        case .warning: return .orange
        case .error: return .red
        case .neutral: return .secondary
        case .info: return .blue
        case .unknown: return .secondary
        }
    }

    public var defaultIcon: String {
        switch self {
        case .success: return "checkmark.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .error: return "xmark.circle.fill"
        case .neutral: return "minus.circle"
        case .info: return "info.circle.fill"
        case .unknown: return "questionmark.circle"
        }
    }
}

public struct StatusPillView: View {
    public let text: String
    public let level: StatusLevel
    public let icon: String?
    public let showIcon: Bool

    public init(
        text: String,
        level: StatusLevel = .neutral,
        icon: String? = nil,
        showIcon: Bool = true
    ) {
        self.text = text
        self.level = level
        self.icon = icon
        self.showIcon = showIcon
    }

    public var body: some View {
        HStack(spacing: 4) {
            if showIcon {
                Image(systemName: icon ?? level.defaultIcon)
                    .font(.system(size: 9, weight: .bold))
            }
            Text(text)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
        }
        .foregroundStyle(level.color)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(
            Capsule()
                .fill(level.color.opacity(0.12))
        )
        .overlay(
            Capsule()
                .strokeBorder(level.color.opacity(0.3), lineWidth: 1)
        )
    }
}

#Preview {
    HStack {
        StatusPillView(text: "Active", level: .success)
        StatusPillView(text: "Warning", level: .warning)
        StatusPillView(text: "Critical", level: .error)
        StatusPillView(text: "Neutral", level: .neutral)
        StatusPillView(text: "Info", level: .info)
    }
    .padding()
}
