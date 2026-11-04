import SwiftUI

public enum QuoteQualityStatus: String, Sendable, Equatable, Hashable, CaseIterable {
    case fresh = "FRESH"
    case outdated = "OUTDATED"
    case stale = "STALE"
    case unknown = "UNKNOWN"

    public var title: String {
        switch self {
        case .fresh: return "LIVE (FRESH)"
        case .outdated: return "DELAYED (OUTDATED)"
        case .stale: return "STALE"
        case .unknown: return "UNKNOWN"
        }
    }

    public var color: Color {
        switch self {
        case .fresh: return Color(red: 0.05, green: 0.75, blue: 0.45) // Emerald green
        case .outdated: return Color.orange
        case .stale: return Color.red
        case .unknown: return Color.secondary
        }
    }

    public var iconName: String {
        switch self {
        case .fresh: return "bolt.fill"
        case .outdated: return "clock.badge.exclamationmark"
        case .stale: return "exclamationmark.octagon.fill"
        case .unknown: return "questionmark.circle"
        }
    }

    public static func from(string: String) -> QuoteQualityStatus {
        let normalized = string.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        return QuoteQualityStatus(rawValue: normalized) ?? .unknown
    }
}

public struct FreshnessPillView: View {
    public let status: QuoteQualityStatus
    public let ageText: String?
    public let showIcon: Bool

    public init(
        status: QuoteQualityStatus,
        ageText: String? = nil,
        showIcon: Bool = true
    ) {
        self.status = status
        self.ageText = ageText
        self.showIcon = showIcon
    }

    public init(
        statusString: String,
        ageText: String? = nil,
        showIcon: Bool = true
    ) {
        self.init(
            status: QuoteQualityStatus.from(string: statusString),
            ageText: ageText,
            showIcon: showIcon
        )
    }

    public var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(status.color)
                .frame(width: 6, height: 6)

            Text(status.rawValue)
                .font(.system(size: 10, weight: .bold, design: .monospaced))

            if let age = ageText, !age.isEmpty {
                Text("(\(age))")
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(status.color)
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(status.color.opacity(0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .strokeBorder(status.color.opacity(0.3), lineWidth: 1)
        )
        .help(status.title)
    }
}

#Preview {
    VStack(spacing: 12) {
        FreshnessPillView(status: .fresh, ageText: "12s")
        FreshnessPillView(status: .outdated, ageText: "4m")
        FreshnessPillView(status: .stale, ageText: "2d")
        FreshnessPillView(status: .unknown)
    }
    .padding()
}
