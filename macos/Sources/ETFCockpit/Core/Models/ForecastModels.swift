import Foundation

public enum ForecastDirection: String, Sendable, Equatable, Hashable, CaseIterable {
    case up = "UP"
    case down = "DOWN"
    case flat = "FLAT"
    case unknown = "UNKNOWN"

    public var displayName: String {
        switch self {
        case .up: return "UP"
        case .down: return "DOWN"
        case .flat: return "FLAT"
        case .unknown: return "UNKNOWN"
        }
    }

    public var symbol: String {
        switch self {
        case .up: return "▲"
        case .down: return "▼"
        case .flat: return "—"
        case .unknown: return "?"
        }
    }
}

public struct ForecastEntryItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { forecastId }
    public let forecastId: String
    public let isin: String
    public let targetDate: String
    public let forecastType: String
    public let direction: ForecastDirection
    public let referencePrice: Decimal
    public let targetPrice: Decimal
    public let confidencePct: Decimal?
    public let modelId: String
    public let createdAt: String

    public init(
        forecastId: String,
        isin: String,
        targetDate: String,
        forecastType: String = "DAILY_CLOSE",
        direction: ForecastDirection,
        referencePrice: Decimal,
        targetPrice: Decimal,
        confidencePct: Decimal? = nil,
        modelId: String,
        createdAt: String
    ) {
        self.forecastId = forecastId
        self.isin = isin
        self.targetDate = targetDate
        self.forecastType = forecastType
        self.direction = direction
        self.referencePrice = referencePrice
        self.targetPrice = targetPrice
        self.confidencePct = confidencePct
        self.modelId = modelId
        self.createdAt = createdAt
    }

    /// Expected return percentage: (targetPrice - referencePrice) / referencePrice * 100
    public var expectedReturnPct: Decimal? {
        guard referencePrice > 0 else { return nil }
        return ((targetPrice - referencePrice) / referencePrice) * 100
    }
}

public struct SettlementItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { settlementId }
    public let settlementId: String
    public let forecastId: String
    public let isin: String
    public let settlementDate: String
    public let actualClosePrice: Decimal
    public let errorEur: Decimal
    public let errorPct: Decimal
    public let directionHit: Bool
    public let settledAt: String

    public init(
        settlementId: String,
        forecastId: String,
        isin: String,
        settlementDate: String,
        actualClosePrice: Decimal,
        errorEur: Decimal,
        errorPct: Decimal,
        directionHit: Bool,
        settledAt: String
    ) {
        self.settlementId = settlementId
        self.forecastId = forecastId
        self.isin = isin
        self.settlementDate = settlementDate
        self.actualClosePrice = actualClosePrice
        self.errorEur = errorEur
        self.errorPct = errorPct
        self.directionHit = directionHit
        self.settledAt = settledAt
    }
}

public struct ForecastPerformanceItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { forecastId }
    public let forecastId: String
    public let isin: String
    public let targetDate: String
    public let direction: ForecastDirection
    public let referencePrice: Decimal
    public let targetPrice: Decimal
    public let confidencePct: Decimal?
    public let modelId: String
    public let settlementDate: String?
    public let actualClosePrice: Decimal?
    public let errorEur: Decimal?
    public let errorPct: Decimal?
    public let directionHit: Bool?
    public let settledAt: String?

    public init(
        forecastId: String,
        isin: String,
        targetDate: String,
        direction: ForecastDirection,
        referencePrice: Decimal,
        targetPrice: Decimal,
        confidencePct: Decimal? = nil,
        modelId: String,
        settlementDate: String? = nil,
        actualClosePrice: Decimal? = nil,
        errorEur: Decimal? = nil,
        errorPct: Decimal? = nil,
        directionHit: Bool? = nil,
        settledAt: String? = nil
    ) {
        self.forecastId = forecastId
        self.isin = isin
        self.targetDate = targetDate
        self.direction = direction
        self.referencePrice = referencePrice
        self.targetPrice = targetPrice
        self.confidencePct = confidencePct
        self.modelId = modelId
        self.settlementDate = settlementDate
        self.actualClosePrice = actualClosePrice
        self.errorEur = errorEur
        self.errorPct = errorPct
        self.directionHit = directionHit
        self.settledAt = settledAt
    }
}

public struct ForecastPerformanceSummary: Sendable, Equatable {
    public let totalSettledCount: Int
    public let hitsCount: Int
    public let hitRatePct: Double?
    public let mapePct: Double?
    public let maeEur: Double?
    public let martingaleFlatHitRatePct: Double?
    public let momentumHitRatePct: Double?
    public let baselineOutperformance: Bool?
    public let unsettledCount: Int
    public let recentRecords: [ForecastPerformanceItem]

    public init(
        totalSettledCount: Int,
        hitsCount: Int,
        hitRatePct: Double? = nil,
        mapePct: Double? = nil,
        maeEur: Double? = nil,
        martingaleFlatHitRatePct: Double? = nil,
        momentumHitRatePct: Double? = nil,
        baselineOutperformance: Bool? = nil,
        unsettledCount: Int = 0,
        recentRecords: [ForecastPerformanceItem] = []
    ) {
        self.totalSettledCount = totalSettledCount
        self.hitsCount = hitsCount
        self.hitRatePct = hitRatePct
        self.mapePct = mapePct
        self.maeEur = maeEur
        self.martingaleFlatHitRatePct = martingaleFlatHitRatePct
        self.momentumHitRatePct = momentumHitRatePct
        self.baselineOutperformance = baselineOutperformance
        self.unsettledCount = unsettledCount
        self.recentRecords = recentRecords
    }
}
