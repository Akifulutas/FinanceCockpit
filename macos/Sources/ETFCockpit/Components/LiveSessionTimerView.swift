import SwiftUI
import Combine

public struct LiveSessionTimerView: View {
    public let referenceDate: Date?

    @State private var currentDate: Date = Date()
    @State private var timer = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()

    public init(referenceDate: Date? = nil) {
        self.referenceDate = referenceDate
    }

    private var effectiveDate: Date {
        referenceDate ?? currentDate
    }

    private var calendar: Calendar {
        var cal = Calendar(identifier: .gregorian)
        if let cetZone = TimeZone(identifier: "Europe/Berlin") {
            cal.timeZone = cetZone
        }
        return cal
    }

    public var isWeekend: Bool {
        let weekday = calendar.component(.weekday, from: effectiveDate)
        // 1 = Sunday, 7 = Saturday
        return weekday == 1 || weekday == 7
    }

    public var currentHourMinute: (hour: Int, minute: Int, second: Int) {
        let h = calendar.component(.hour, from: effectiveDate)
        let m = calendar.component(.minute, from: effectiveDate)
        let s = calendar.component(.second, from: effectiveDate)
        return (h, m, s)
    }

    /// Total seconds since midnight CET
    public var currentSecondsSinceMidnight: Int {
        let (h, m, s) = currentHourMinute
        return (h * 3600) + (m * 60) + s
    }

    public var morningForecastSeconds: Int {
        (9 * 3600) + (30 * 60) // 09:30 CET = 34200s
    }

    public var xetrOpenSeconds: Int {
        (9 * 3600) // 09:00 CET
    }

    public var xetrCloseSeconds: Int {
        (17 * 3600) + (30 * 60) // 17:30 CET
    }

    public var eveningSettlementSeconds: Int {
        (17 * 3600) + (40 * 60) // 17:40 CET = 63600s
    }

    public var isMarketOpen: Bool {
        guard !isWeekend else { return false }
        let nowSec = currentSecondsSinceMidnight
        return nowSec >= xetrOpenSeconds && nowSec <= xetrCloseSeconds
    }

    public var nextEventInfo: (name: String, remainingText: String, isPastToday: Bool) {
        if isWeekend {
            return ("Market Closed (Weekend)", "Awaiting Monday 09:30 CET", true)
        }

        let nowSec = currentSecondsSinceMidnight

        if nowSec < morningForecastSeconds {
            let diff = morningForecastSeconds - nowSec
            let hours = diff / 3600
            let mins = (diff % 3600) / 60
            let secs = diff % 60
            let timeStr = hours > 0 ? "\(hours)h \(mins)m" : "\(mins)m \(secs)s"
            return ("Morning Forecast (09:30 CET)", "Remaining: \(timeStr)", false)
        } else if nowSec < eveningSettlementSeconds {
            let diff = eveningSettlementSeconds - nowSec
            let hours = diff / 3600
            let mins = (diff % 3600) / 60
            let secs = diff % 60
            let timeStr = hours > 0 ? "\(hours)h \(mins)m" : "\(mins)m \(secs)s"
            return ("Evening Settlement (17:40 CET)", "Remaining: \(timeStr)", false)
        } else {
            return ("Trading Day Complete", "Awaiting Tomorrow 09:30 CET", true)
        }
    }

    public var body: some View {
        HStack(spacing: 12) {
            // Market Status Indicator
            HStack(spacing: 6) {
                Circle()
                    .fill(isMarketOpen ? Color.green : Color.secondary)
                    .frame(width: 8, height: 8)

                Text(isMarketOpen ? "XETR Open" : (isWeekend ? "Market Closed" : "XETR Closed"))
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(isMarketOpen ? Color.primary : Color.secondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(isMarketOpen ? Color.green.opacity(0.12) : Color.primary.opacity(0.06))
            )

            Divider()
                .frame(height: 16)

            // Next Session Event
            HStack(spacing: 6) {
                Image(systemName: "clock.badge")
                    .font(.system(size: 11))
                    .foregroundStyle(.blue)

                Text(nextEventInfo.name)
                    .font(.system(size: 11, weight: .semibold))

                Text("•")
                    .foregroundStyle(.secondary)

                Text(nextEventInfo.remainingText)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(nextEventInfo.isPastToday ? Color.secondary : Color.blue)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
        .onReceive(timer) { newDate in
            if referenceDate == nil {
                currentDate = newDate
            }
        }
    }
}

#Preview {
    VStack(spacing: 12) {
        LiveSessionTimerView()
    }
    .padding()
}
