import SwiftUI

public enum TrendDirection: Sendable, Equatable, Hashable {
    case up
    case down
    case neutral

    public var iconName: String {
        switch self {
        case .up: return "arrow.up.right"
        case .down: return "arrow.down.right"
        case .neutral: return "arrow.right"
        }
    }

    public var color: Color {
        switch self {
        case .up: return Color(red: 0.1, green: 0.75, blue: 0.4)
        case .down: return Color.red
        case .neutral: return Color.secondary
        }
    }
}

public struct MetricCardView: View {
    public let title: String
    public let value: String
    public let subtitle: String?
    public let trend: TrendDirection?
    public let trendValue: String?
    public let badge: String?
    public let badgeColor: Color?

    @State private var isHovered = false

    public init(
        title: String,
        value: String,
        subtitle: String? = nil,
        trend: TrendDirection? = nil,
        trendValue: String? = nil,
        badge: String? = nil,
        badgeColor: Color? = nil
    ) {
        self.title = title
        self.value = value
        self.subtitle = subtitle
        self.trend = trend
        self.trendValue = trendValue
        self.badge = badge
        self.badgeColor = badgeColor
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Header Row: Title & Optional Badge
            HStack(alignment: .top) {
                Text(title)
                    .font(.system(size: 11, weight: .semibold, design: .default))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                Spacer(minLength: 4)

                if let badge = badge {
                    Text(badge)
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(badgeColor ?? .blue)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            Capsule()
                                .fill((badgeColor ?? .blue).opacity(0.12))
                        )
                }
            }

            // Main Metric Value
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)

            // Footer Row: Subtitle and / or Trend
            HStack(spacing: 6) {
                if let trend = trend {
                    HStack(spacing: 3) {
                        Image(systemName: trend.iconName)
                            .font(.system(size: 10, weight: .bold))
                        if let trendValue = trendValue {
                            Text(trendValue)
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        }
                    }
                    .foregroundStyle(trend.color)
                }

                if let subtitle = subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.system(size: 11, weight: .regular))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .padding(14)
        .frame(minWidth: 160, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(isHovered ? Color.accentColor.opacity(0.4) : Color.primary.opacity(0.08), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(isHovered ? 0.08 : 0.03), radius: isHovered ? 6 : 2, x: 0, y: isHovered ? 3 : 1)
        .onHover { hovering in
            withAnimation(.easeInOut(duration: 0.15)) {
                isHovered = hovering
            }
        }
    }
}

#Preview {
    HStack(spacing: 12) {
        MetricCardView(
            title: "Total Portfolio Value",
            value: "€1,826.01",
            subtitle: "10 Assets",
            trend: .up,
            trendValue: "+1.24%",
            badge: "LIVE"
        )
        MetricCardView(
            title: "Cash Balance",
            value: "€54.20",
            subtitle: "Buying Power: €54.20",
            trend: .neutral,
            badge: "EUR"
        )
    }
    .padding()
}
