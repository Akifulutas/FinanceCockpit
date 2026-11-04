import Foundation

public struct PositionItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let displayName: String
    public let securityType: String
    public let quantity: Decimal
    public let brokerValuation: Decimal
    public let brokerCostBasis: Decimal?
    public let bid: Decimal?
    public let ask: Decimal?
    public let computedMid: Decimal?
    public let spreadPct: Decimal?
    public let qualityStatus: String
    public let quoteTimestamp: String?
    public let asOfTime: String?

    public init(
        isin: String,
        displayName: String,
        securityType: String = "ETF",
        quantity: Decimal,
        brokerValuation: Decimal,
        brokerCostBasis: Decimal? = nil,
        bid: Decimal? = nil,
        ask: Decimal? = nil,
        computedMid: Decimal? = nil,
        spreadPct: Decimal? = nil,
        qualityStatus: String = "UNKNOWN",
        quoteTimestamp: String? = nil,
        asOfTime: String? = nil
    ) {
        self.isin = isin
        self.displayName = displayName
        self.securityType = securityType
        self.quantity = quantity
        self.brokerValuation = brokerValuation
        self.brokerCostBasis = brokerCostBasis
        self.bid = bid
        self.ask = ask
        self.computedMid = computedMid
        self.spreadPct = spreadPct
        self.qualityStatus = qualityStatus
        self.quoteTimestamp = quoteTimestamp
        self.asOfTime = asOfTime
    }

    /// Calculated valuation based on live mid-quote: quantity * computedMid
    public var calculatedValuation: Decimal? {
        guard let mid = computedMid else { return nil }
        return quantity * mid
    }

    /// Total cost basis: quantity * brokerCostBasis
    public var totalCostBasis: Decimal? {
        guard let cost = brokerCostBasis else { return nil }
        return quantity * cost
    }

    /// Unrealized profit/loss in EUR
    public var unrealizedPnLEur: Decimal? {
        guard let cost = totalCostBasis, cost > 0 else { return nil }
        return brokerValuation - cost
    }

    /// Unrealized profit/loss percentage
    public var unrealizedPnLPct: Decimal? {
        guard let cost = totalCostBasis, cost > 0 else { return nil }
        return ((brokerValuation - cost) / cost) * 100
    }
}

public struct CashObservation: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { observedAt }
    public let accountIdMasked: String
    public let currency: String
    public let settledCash: Decimal
    public let unsettledCash: Decimal?
    public let accruedCash: Decimal?
    public let totalCash: Decimal
    public let buyingPower: Decimal
    public let pendingBuyOrdersAmount: Decimal?
    public let possibleTaxes: Decimal?
    public let observedAt: String

    public init(
        accountIdMasked: String,
        currency: String = "EUR",
        settledCash: Decimal,
        unsettledCash: Decimal? = nil,
        accruedCash: Decimal? = nil,
        totalCash: Decimal,
        buyingPower: Decimal,
        pendingBuyOrdersAmount: Decimal? = nil,
        possibleTaxes: Decimal? = nil,
        observedAt: String
    ) {
        self.accountIdMasked = accountIdMasked
        self.currency = currency
        self.settledCash = settledCash
        self.unsettledCash = unsettledCash
        self.accruedCash = accruedCash
        self.totalCash = totalCash
        self.buyingPower = buyingPower
        self.pendingBuyOrdersAmount = pendingBuyOrdersAmount
        self.possibleTaxes = possibleTaxes
        self.observedAt = observedAt
    }
}

public struct QuoteItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let bid: Decimal?
    public let ask: Decimal?
    public let computedMid: Decimal?
    public let spreadPct: Decimal?
    public let qualityStatus: String
    public let quoteTimestamp: String

    public init(
        isin: String,
        bid: Decimal? = nil,
        ask: Decimal? = nil,
        computedMid: Decimal? = nil,
        spreadPct: Decimal? = nil,
        qualityStatus: String,
        quoteTimestamp: String
    ) {
        self.isin = isin
        self.bid = bid
        self.ask = ask
        self.computedMid = computedMid
        self.spreadPct = spreadPct
        self.qualityStatus = qualityStatus
        self.quoteTimestamp = quoteTimestamp
    }
}

public struct PortfolioSummary: Sendable, Equatable {
    public let totalValueEur: Decimal
    public let investedAssetsEur: Decimal
    public let totalCashEur: Decimal
    public let settledCashEur: Decimal
    public let buyingPowerEur: Decimal
    public let positions: [PositionItem]
    public let cash: CashObservation?
    public let asOfDate: String

    public init(
        totalValueEur: Decimal,
        investedAssetsEur: Decimal,
        totalCashEur: Decimal,
        settledCashEur: Decimal,
        buyingPowerEur: Decimal,
        positions: [PositionItem],
        cash: CashObservation?,
        asOfDate: String
    ) {
        self.totalValueEur = totalValueEur
        self.investedAssetsEur = investedAssetsEur
        self.totalCashEur = totalCashEur
        self.settledCashEur = settledCashEur
        self.buyingPowerEur = buyingPowerEur
        self.positions = positions
        self.cash = cash
        self.asOfDate = asOfDate
    }
}
