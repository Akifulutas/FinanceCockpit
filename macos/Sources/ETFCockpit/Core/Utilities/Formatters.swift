import Foundation

public enum Formatters {
    // MARK: - Thread-safe cached formatters

    private static let currencyFormatterEUR: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "EUR"
        formatter.currencySymbol = "€"
        formatter.locale = Locale(identifier: "de_DE")
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    private static let currencyFormatterUSD: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.currencySymbol = "$"
        formatter.locale = Locale(identifier: "en_US")
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    private static let currencyFormatterTRY: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "TRY"
        formatter.currencySymbol = "₺"
        formatter.locale = Locale(identifier: "tr_TR")
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    private static let decimalFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "de_DE")
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        return formatter
    }()

    private static let priceFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "de_DE")
        formatter.minimumFractionDigits = 3
        formatter.maximumFractionDigits = 3
        return formatter
    }()

    private static let quantityFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "de_DE")
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 4
        return formatter
    }()

    nonisolated(unsafe) private static let iso8601FormatterWithMillis: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    nonisolated(unsafe) private static let iso8601FormatterStandard: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let displayDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "tr_TR")
        formatter.dateFormat = "dd.MM.yyyy HH:mm"
        return formatter
    }()

    private static let shortDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "tr_TR")
        formatter.dateFormat = "dd.MM.yyyy"
        return formatter
    }()

    // MARK: - Currency Formatting

    /// Formats decimal monetary amounts into European currency formats (e.g. 1.826,01 €).
    public static func formatCurrency(_ value: Decimal?, currency: String = "EUR") -> String {
        guard let value = value else { return "—" }
        let number = NSDecimalNumber(decimal: value)
        let formatter: NumberFormatter
        switch currency.uppercased() {
        case "USD":
            formatter = currencyFormatterUSD
        case "TRY":
            formatter = currencyFormatterTRY
        default:
            formatter = currencyFormatterEUR
        }
        return formatter.string(from: number) ?? "\(value) \(currency)"
    }

    // MARK: - Quantity & Price Formatting

    /// Formats share quantity with up to 4 decimal places, omitting trailing zeros for integer quantities (e.g. 158 or 22,45).
    public static func formatQuantity(_ quantity: Decimal?) -> String {
        guard let quantity = quantity else { return "—" }
        let number = NSDecimalNumber(decimal: quantity)
        return quantityFormatter.string(from: number) ?? "\(quantity)"
    }

    /// Formats unit price with 3 decimal places (e.g. 11,557 €).
    public static func formatPrice(_ price: Decimal?, currency: String = "EUR") -> String {
        guard let price = price else { return "—" }
        let number = NSDecimalNumber(decimal: price)
        let numStr = priceFormatter.string(from: number) ?? "\(price)"
        let symbol = currency.uppercased() == "USD" ? "$" : (currency.uppercased() == "TRY" ? "₺" : "€")
        return "\(numStr) \(symbol)"
    }

    // MARK: - Percentage Formatting

    /// Formats percentages with customizable decimal places and sign (e.g. +12,45% or -3,10%).
    public static func formatPercentage(_ pct: Decimal?, includeSign: Bool = false, decimalPlaces: Int = 2) -> String {
        guard let pct = pct else { return "—" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "de_DE")
        formatter.minimumFractionDigits = decimalPlaces
        formatter.maximumFractionDigits = decimalPlaces
        if includeSign && pct > 0 {
            formatter.positivePrefix = "+"
        }
        let number = NSDecimalNumber(decimal: pct)
        let str = formatter.string(from: number) ?? "\(pct)"
        return "\(str)%"
    }

    public static func formatPercentage(_ pct: Double?, includeSign: Bool = false, decimalPlaces: Int = 2) -> String {
        guard let pct = pct else { return "—" }
        return formatPercentage(Decimal(pct), includeSign: includeSign, decimalPlaces: decimalPlaces)
    }

    // MARK: - Empirical Confidence Rule (N < 30 Rule)

    /// Mandatory empirical confidence rule:
    /// If observationCount N < 30: returns strictly "—" (em-dash).
    /// If observationCount N >= 30: returns formatted Hit Rate % (e.g. "58.3%").
    public static func formatEmpiricalConfidence(observationCount: Int, hitRatePct: Double?) -> String {
        guard observationCount >= 30, let hitRate = hitRatePct else {
            return "—"
        }
        return formatPercentage(hitRate, includeSign: false, decimalPlaces: 1)
    }

    /// Returns true if sample size meets the statistical significance cutoff N >= 30.
    public static func isEmpiricallyReliable(observationCount: Int) -> Bool {
        return observationCount >= 30
    }

    /// Status message for statistical reliability of the sample size.
    public static func confidenceStatusMessage(observationCount: Int) -> String {
        if observationCount < 30 {
            return "Small Sample Size (N < 30) — Statistically Suppressed"
        } else {
            return "Statistically Reliable (N ≥ 30)"
        }
    }

    // MARK: - Deadband Direction Classification (0.10% Deadband)

    /// Evaluates forecast direction with a 0.10% deadband.
    /// Absolute return < 0.10% (0.0010) is classified as FLAT.
    public static func classifyDirection(returnPct: Decimal) -> ForecastDirection {
        let deadband: Decimal = 0.10 // 0.10%
        if abs(returnPct) < deadband {
            return .flat
        } else if returnPct > 0 {
            return .up
        } else {
            return .down
        }
    }

    // MARK: - Decimal Parsing (Handling surrounding single quotes & whitespace)

    /// Safely parses a string that may contain single quotes (e.g. "'1826.01'") into a Decimal.
    public static func parseDecimal(from raw: String?) -> Decimal? {
        guard let raw = raw else { return nil }
        let cleaned = raw.trimmingCharacters(in: CharacterSet(charactersIn: "'\" \t\r\n"))
        if cleaned.isEmpty || cleaned.uppercased() == "NULL" || cleaned.uppercased() == "NONE" {
            return nil
        }
        // Normalize commas to dots if European notation is entered without standard decimal point
        let normalized = cleaned.replacingOccurrences(of: ",", with: ".")
        return Decimal(string: normalized)
    }

    // MARK: - Date & Hash Formatting

    /// Parses ISO8601 string and returns formatted date e.g. "30.10.2026 21:22".
    public static func formatISO8601(_ dateString: String?) -> String {
        guard let dateString = dateString, !dateString.isEmpty else { return "—" }
        if let date = iso8601FormatterWithMillis.date(from: dateString) ?? iso8601FormatterStandard.date(from: dateString) {
            return displayDateFormatter.string(from: date)
        }
        // Fallback: If date string has at least 10 chars (YYYY-MM-DD), extract it
        if dateString.count >= 10 {
            return String(dateString.prefix(10))
        }
        return dateString
    }

    /// Truncates a 64-character SHA-256 hash to "0a92cf40...9c0cef8a".
    public static func formatTruncatedHash(_ hash: String) -> String {
        guard hash.count >= 16 else { return hash }
        let prefix = hash.prefix(8)
        let suffix = hash.suffix(8)
        return "\(prefix)...\(suffix)"
    }
}
