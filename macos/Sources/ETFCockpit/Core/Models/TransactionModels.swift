import Foundation

public struct TransactionItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { recordId }
    public let recordId: String
    public let brokerTxId: String?
    public let txType: String
    public let subType: String?
    public let side: String?
    public let isin: String?
    public let description: String?
    public let amount: Decimal
    public let currency: String
    public let quantity: Decimal?
    public let limitPrice: Decimal?
    public let status: String
    public let eventTime: String
    public let settlementDate: String?
    public let flowClassification: String
    public let costImpact: Decimal?

    public init(
        recordId: String,
        brokerTxId: String? = nil,
        txType: String,
        subType: String? = nil,
        side: String? = nil,
        isin: String? = nil,
        description: String? = nil,
        amount: Decimal,
        currency: String = "EUR",
        quantity: Decimal? = nil,
        limitPrice: Decimal? = nil,
        status: String = "SETTLED",
        eventTime: String,
        settlementDate: String? = nil,
        flowClassification: String = "INTERNAL",
        costImpact: Decimal? = nil
    ) {
        self.recordId = recordId
        self.brokerTxId = brokerTxId
        self.txType = txType
        self.subType = subType
        self.side = side
        self.isin = isin
        self.description = description
        self.amount = amount
        self.currency = currency
        self.quantity = quantity
        self.limitPrice = limitPrice
        self.status = status
        self.eventTime = eventTime
        self.settlementDate = settlementDate
        self.flowClassification = flowClassification
        self.costImpact = costImpact
    }
}

public struct CorporateActionItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { actionId }
    public let actionId: String
    public let isin: String
    public let actionType: String
    public let ratio: String
    public let newIsin: String?
    public let newTicker: String?
    public let effectiveDate: String
    public let announcementDate: String?
    public let description: String?
    public let source: String?
    public let approvedBy: String?
    public let approvedAt: String?
    public let createdAt: String

    public init(
        actionId: String,
        isin: String,
        actionType: String,
        ratio: String,
        newIsin: String? = nil,
        newTicker: String? = nil,
        effectiveDate: String,
        announcementDate: String? = nil,
        description: String? = nil,
        source: String? = nil,
        approvedBy: String? = nil,
        approvedAt: String? = nil,
        createdAt: String
    ) {
        self.actionId = actionId
        self.isin = isin
        self.actionType = actionType
        self.ratio = ratio
        self.newIsin = newIsin
        self.newTicker = newTicker
        self.effectiveDate = effectiveDate
        self.announcementDate = announcementDate
        self.description = description
        self.source = source
        self.approvedBy = approvedBy
        self.approvedAt = approvedAt
        self.createdAt = createdAt
    }
}

public struct ReconciliationItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { reconciliationId }
    public let reconciliationId: String
    public let runId: String
    public let reconciliationTime: String
    public let reconciliationType: String
    public let status: String
    public let sharesMatch: Bool
    public let cashMatch: Bool
    public let valuationMatch: Bool
    public let costBasisMatch: Bool
    public let cashGapEur: Decimal?
    public let observationLagSeconds: Int?
    public let discrepanciesCount: Int
    public let discrepanciesJson: String?
    public let notes: String?

    public init(
        reconciliationId: String,
        runId: String,
        reconciliationTime: String,
        reconciliationType: String = "4WAY",
        status: String,
        sharesMatch: Bool,
        cashMatch: Bool,
        valuationMatch: Bool,
        costBasisMatch: Bool,
        cashGapEur: Decimal? = nil,
        observationLagSeconds: Int? = nil,
        discrepanciesCount: Int = 0,
        discrepanciesJson: String? = nil,
        notes: String? = nil
    ) {
        self.reconciliationId = reconciliationId
        self.runId = runId
        self.reconciliationTime = reconciliationTime
        self.reconciliationType = reconciliationType
        self.status = status
        self.sharesMatch = sharesMatch
        self.cashMatch = cashMatch
        self.valuationMatch = valuationMatch
        self.costBasisMatch = costBasisMatch
        self.cashGapEur = cashGapEur
        self.observationLagSeconds = observationLagSeconds
        self.discrepanciesCount = discrepanciesCount
        self.discrepanciesJson = discrepanciesJson
        self.notes = notes
    }

    public var isFullyReconciled: Bool {
        sharesMatch && cashMatch && valuationMatch && costBasisMatch && (cashGapEur == nil || cashGapEur == 0)
    }
}
