import XCTest
@testable import FinanceCockpit

final class FormattersTests: XCTestCase {

    func testCurrencyFormattingEUR() {
        let decimal = Decimal(string: "1826.01")
        let formatted = Formatters.formatCurrency(decimal, currency: "EUR")
        XCTAssertTrue(formatted.contains("1.826,01"), "Expected German currency grouping: \(formatted)")
        XCTAssertTrue(formatted.contains("€"), "Expected Euro symbol: \(formatted)")

        XCTAssertEqual(Formatters.formatCurrency(nil), "—")
    }

    func testCurrencyFormattingUSDandTRY() {
        let decimal = Decimal(string: "1826.01")
        let formattedUSD = Formatters.formatCurrency(decimal, currency: "USD")
        XCTAssertTrue(formattedUSD.contains("1,826.01"), "Expected US currency grouping: \(formattedUSD)")
        XCTAssertTrue(formattedUSD.contains("$"), "Expected Dollar symbol: \(formattedUSD)")

        let formattedTRY = Formatters.formatCurrency(decimal, currency: "TRY")
        XCTAssertTrue(formattedTRY.contains("1.826,01"), "Expected Turkish currency grouping: \(formattedTRY)")
        XCTAssertTrue(formattedTRY.contains("₺"), "Expected Lira symbol: \(formattedTRY)")
    }

    func testQuantityFormatting() {
        let intQty = Decimal(158)
        let formattedInt = Formatters.formatQuantity(intQty)
        XCTAssertEqual(formattedInt, "158")

        let fracQty = Decimal(string: "22.4500")
        let formattedFrac = Formatters.formatQuantity(fracQty)
        XCTAssertEqual(formattedFrac, "22,45")

        XCTAssertEqual(Formatters.formatQuantity(nil), "—")
    }

    func testPriceFormatting() {
        let price = Decimal(string: "11.557")
        let formatted = Formatters.formatPrice(price, currency: "EUR")
        XCTAssertTrue(formatted.contains("11,557"), "Expected 3 decimals: \(formatted)")
        XCTAssertTrue(formatted.contains("€"), "Expected Euro symbol: \(formatted)")

        XCTAssertEqual(Formatters.formatPrice(nil), "—")
    }

    func testPercentageFormatting() {
        let positive = Decimal(string: "12.45")
        XCTAssertEqual(Formatters.formatPercentage(positive, includeSign: true), "+12,45%")
        XCTAssertEqual(Formatters.formatPercentage(positive, includeSign: false), "12,45%")

        let negative = Decimal(string: "-3.10")
        XCTAssertEqual(Formatters.formatPercentage(negative, includeSign: true), "-3,10%")

        XCTAssertEqual(Formatters.formatPercentage(nil as Decimal?), "—")
    }

    // MARK: - Empirical Confidence Rule (N < 30 Rule) Tests

    func testEmpiricalConfidenceSuppression() {
        // N < 30 MUST be suppressed as "—"
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 0, hitRatePct: 65.5), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 1, hitRatePct: 100.0), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 15, hitRatePct: 53.3), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 29, hitRatePct: 58.6), "—")

        // N >= 30 displays Hit Rate %
        let formatted30 = Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: 60.0)
        XCTAssertEqual(formatted30, "60,0%")

        let formatted100 = Formatters.formatEmpiricalConfidence(observationCount: 100, hitRatePct: 72.5)
        XCTAssertEqual(formatted100, "72,5%")

        // Nil hit rate with N >= 30 returns "—"
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 35, hitRatePct: nil), "—")
    }

    func testStatisticalReliabilityHelper() {
        XCTAssertFalse(Formatters.isEmpiricallyReliable(observationCount: 0))
        XCTAssertFalse(Formatters.isEmpiricallyReliable(observationCount: 29))
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 30))
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 100))

        XCTAssertTrue(Formatters.confidenceStatusMessage(observationCount: 25).contains("Small Sample Size"))
        XCTAssertTrue(Formatters.confidenceStatusMessage(observationCount: 35).contains("Statistically Reliable"))
    }

    // MARK: - Deadband Direction Classification Tests

    func testDeadbandClassification() {
        // |return| < 0.10% is FLAT
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "0.00")!), .flat)
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "0.05")!), .flat)
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "-0.09")!), .flat)

        // return >= 0.10% is UP
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "0.10")!), .up)
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "1.25")!), .up)

        // return <= -0.10% is DOWN
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "-0.10")!), .down)
        XCTAssertEqual(Formatters.classifyDirection(returnPct: Decimal(string: "-2.50")!), .down)
    }

    // MARK: - Decimal Parsing Tests

    func testDecimalParsing() {
        // Single quotes stripping (SQLite textual decimal representation)
        XCTAssertEqual(Formatters.parseDecimal(from: "'1826.01'"), Decimal(string: "1826.01"))
        XCTAssertEqual(Formatters.parseDecimal(from: "'158'"), Decimal(158))
        XCTAssertEqual(Formatters.parseDecimal(from: "'0.1557497620489746473998442502'"), Decimal(string: "0.1557497620489746473998442502"))

        // Whitespace and clean numbers
        XCTAssertEqual(Formatters.parseDecimal(from: "  44.5575  "), Decimal(string: "44.5575"))
        XCTAssertEqual(Formatters.parseDecimal(from: "10"), Decimal(10))

        // Nil and null inputs
        XCTAssertNil(Formatters.parseDecimal(from: nil))
        XCTAssertNil(Formatters.parseDecimal(from: ""))
        XCTAssertNil(Formatters.parseDecimal(from: "NULL"))
        XCTAssertNil(Formatters.parseDecimal(from: "None"))
    }

    // MARK: - Hash and Date Formatting Tests

    func testTruncatedHash() {
        let fullHash = "0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a"
        let truncated = Formatters.formatTruncatedHash(fullHash)
        XCTAssertEqual(truncated, "0a92cf40...9c0cef8a")

        let short = "short"
        XCTAssertEqual(Formatters.formatTruncatedHash(short), "short")
    }

    func testISO8601DateFormatting() {
        let isoWithMillis = "2026-10-30T18:22:29.883000+00:00"
        let formatted = Formatters.formatISO8601(isoWithMillis)
        XCTAssertFalse(formatted.isEmpty)
        XCTAssertNotEqual(formatted, "—")

        XCTAssertEqual(Formatters.formatISO8601(nil), "—")
        XCTAssertEqual(Formatters.formatISO8601(""), "—")
    }
}
