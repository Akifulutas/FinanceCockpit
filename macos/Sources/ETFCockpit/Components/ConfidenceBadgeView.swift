import SwiftUI

public struct ConfidenceBadgeView: View {
    public let observationCount: Int
    public let hitRatePct: Double?
    public let compact: Bool

    public init(
        observationCount: Int,
        hitRatePct: Double?,
        compact: Bool = false
    ) {
        self.observationCount = observationCount
        self.hitRatePct = hitRatePct
        self.compact = compact
    }

    public init(
        observationCount: Int,
        confidencePct: Decimal?,
        compact: Bool = false
    ) {
        let hitRate = confidencePct != nil ? NSDecimalNumber(decimal: confidencePct!).doubleValue : nil
        self.init(observationCount: observationCount, hitRatePct: hitRate, compact: compact)
    }

    public var isReliable: Bool {
        observationCount >= 30
    }

    public var displayConfidence: String {
        Formatters.formatEmpiricalConfidence(observationCount: observationCount, hitRatePct: hitRatePct)
    }

    public var tooltipText: String {
        if isReliable {
            return "Statistically Reliable (N = \(observationCount) ≥ 30)"
        } else {
            return "Small Sample (N = \(observationCount) < 30) — Statistically suppressed"
        }
    }

    public var body: some View {
        HStack(spacing: 5) {
            if !isReliable {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.orange)

                Text(displayConfidence) // "—"
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)

                if !compact {
                    Text("(N=\(observationCount))")
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .foregroundStyle(.orange)
                }
            } else {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.green)

                Text(displayConfidence)
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(.primary)

                if !compact {
                    Text("(N=\(observationCount))")
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(isReliable ? Color.green.opacity(0.10) : Color.orange.opacity(0.10))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .strokeBorder(isReliable ? Color.green.opacity(0.25) : Color.orange.opacity(0.25), lineWidth: 1)
        )
        .help(tooltipText)
    }
}

#Preview {
    VStack(spacing: 12) {
        ConfidenceBadgeView(observationCount: 12, hitRatePct: 65.4)
        ConfidenceBadgeView(observationCount: 29, hitRatePct: 58.0)
        ConfidenceBadgeView(observationCount: 30, hitRatePct: 68.4)
        ConfidenceBadgeView(observationCount: 150, hitRatePct: 72.1)
    }
    .padding()
}
