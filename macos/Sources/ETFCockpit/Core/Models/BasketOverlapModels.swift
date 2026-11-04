import Foundation

public struct HoldingsSetItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { setId }
    public let setId: String
    public let isin: String
    public let fundName: String?
    public let asOfDate: String
    public let sourceFile: String
    public let provider: String
    public let totalRecords: Int
    public let totalWeightPct: Decimal
    public let createdAt: String

    public init(
        setId: String,
        isin: String,
        fundName: String? = nil,
        asOfDate: String,
        sourceFile: String,
        provider: String,
        totalRecords: Int,
        totalWeightPct: Decimal,
        createdAt: String
    ) {
        self.setId = setId
        self.isin = isin
        self.fundName = fundName
        self.asOfDate = asOfDate
        self.sourceFile = sourceFile
        self.provider = provider
        self.totalRecords = totalRecords
        self.totalWeightPct = totalWeightPct
        self.createdAt = createdAt
    }
}

public struct HoldingConstituentItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { itemId }
    public let itemId: String
    public let setId: String
    public let constituentIsin: String?
    public let constituentTicker: String?
    public let constituentName: String
    public let weightPct: Decimal
    public let sharesHeld: Decimal?
    public let marketValue: Decimal?
    public let currency: String?
    public let sector: String?
    public let country: String?
    public let assetClass: String?
    public let itemOrder: Int

    public init(
        itemId: String,
        setId: String,
        constituentIsin: String? = nil,
        constituentTicker: String? = nil,
        constituentName: String,
        weightPct: Decimal,
        sharesHeld: Decimal? = nil,
        marketValue: Decimal? = nil,
        currency: String? = nil,
        sector: String? = nil,
        country: String? = nil,
        assetClass: String? = nil,
        itemOrder: Int = 0
    ) {
        self.itemId = itemId
        self.setId = setId
        self.constituentIsin = constituentIsin
        self.constituentTicker = constituentTicker
        self.constituentName = constituentName
        self.weightPct = weightPct
        self.sharesHeld = sharesHeld
        self.marketValue = marketValue
        self.currency = currency
        self.sector = sector
        self.country = country
        self.assetClass = assetClass
        self.itemOrder = itemOrder
    }
}

public struct ConsolidatedHoldingItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { constituentIsin ?? constituentName }
    public let constituentName: String
    public let ticker: String?
    public let constituentIsin: String?
    public let consolidatedWeightPct: Double
    public let sector: String?
    public let country: String?
    public let contributingFunds: [String]

    public init(
        constituentName: String,
        ticker: String? = nil,
        constituentIsin: String? = nil,
        consolidatedWeightPct: Double,
        sector: String? = nil,
        country: String? = nil,
        contributingFunds: [String] = []
    ) {
        self.constituentName = constituentName
        self.ticker = ticker
        self.constituentIsin = constituentIsin
        self.consolidatedWeightPct = consolidatedWeightPct
        self.sector = sector
        self.country = country
        self.contributingFunds = contributingFunds
    }
}

public struct HoldingsOverlapData: Sendable, Equatable {
    public let sets: [HoldingsSetItem]
    public let overlapMatrix: [String: [String: Double]]
    public let topConsolidatedHoldings: [ConsolidatedHoldingItem]

    public init(
        sets: [HoldingsSetItem] = [],
        overlapMatrix: [String: [String: Double]] = [:],
        topConsolidatedHoldings: [ConsolidatedHoldingItem] = []
    ) {
        self.sets = sets
        self.overlapMatrix = overlapMatrix
        self.topConsolidatedHoldings = topConsolidatedHoldings
    }
}

public struct RebalanceDriftItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let name: String
    public let targetWeightPct: Double
    public let liveWeightPct: Double
    public let driftPct: Double
    public let isDrifting: Bool
    public let suggestedOrderEur: Double

    public init(
        isin: String,
        name: String,
        targetWeightPct: Double,
        liveWeightPct: Double,
        driftPct: Double,
        isDrifting: Bool,
        suggestedOrderEur: Double = 0
    ) {
        self.isin = isin
        self.name = name
        self.targetWeightPct = targetWeightPct
        self.liveWeightPct = liveWeightPct
        self.driftPct = driftPct
        self.isDrifting = isDrifting
        self.suggestedOrderEur = suggestedOrderEur
    }
}

public struct UCITSComplianceStatus: Sendable, Equatable {
    public let isCompliant: Bool
    public let maxSingleWeightPct: Double
    public let groupBetween5and10Pct: Double
    public let violations: [String]
    public let isEvaluated: Bool

    public init(
        isCompliant: Bool = true,
        maxSingleWeightPct: Double = 0,
        groupBetween5and10Pct: Double = 0,
        violations: [String] = [],
        isEvaluated: Bool = true
    ) {
        self.isCompliant = isCompliant
        self.maxSingleWeightPct = maxSingleWeightPct
        self.groupBetween5and10Pct = groupBetween5and10Pct
        self.violations = violations
        self.isEvaluated = isEvaluated
    }
}

