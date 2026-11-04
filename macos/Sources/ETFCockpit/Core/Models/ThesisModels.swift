import Foundation

public struct ThesisItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { versionId }
    public let versionId: String
    public let thesisId: String
    public let versionNumber: Int
    public let isin: String
    public let instrumentName: String?
    public let category: String
    public let horizon: String
    public let status: String
    public let title: String
    public let oneLineSummary: String
    public let economicRationale: String
    public let evidencePillars: [String]
    public let counterArguments: String?
    public let falsificationTriggers: [String]
    public let benchmarkReference: String?
    public let sources: [String]
    public let targetAllocationPct: Decimal?
    public let nextReviewDate: String?
    public let revisionRationale: String?
    public let author: String?
    public let createdAt: String

    public init(
        versionId: String,
        thesisId: String,
        versionNumber: Int = 1,
        isin: String,
        instrumentName: String? = nil,
        category: String = "CORE",
        horizon: String = "LONG_TERM",
        status: String = "ACTIVE",
        title: String,
        oneLineSummary: String,
        economicRationale: String = "",
        evidencePillars: [String] = [],
        counterArguments: String? = nil,
        falsificationTriggers: [String] = [],
        benchmarkReference: String? = nil,
        sources: [String] = [],
        targetAllocationPct: Decimal? = nil,
        nextReviewDate: String? = nil,
        revisionRationale: String? = nil,
        author: String? = nil,
        createdAt: String
    ) {
        self.versionId = versionId
        self.thesisId = thesisId
        self.versionNumber = versionNumber
        self.isin = isin
        self.instrumentName = instrumentName
        self.category = category
        self.horizon = horizon
        self.status = status
        self.title = title
        self.oneLineSummary = oneLineSummary
        self.economicRationale = economicRationale
        self.evidencePillars = evidencePillars
        self.counterArguments = counterArguments
        self.falsificationTriggers = falsificationTriggers
        self.benchmarkReference = benchmarkReference
        self.sources = sources
        self.targetAllocationPct = targetAllocationPct
        self.nextReviewDate = nextReviewDate
        self.revisionRationale = revisionRationale
        self.author = author
        self.createdAt = createdAt
    }
}

public enum ThesisHealthStatus: String, Sendable, Equatable, Hashable, CaseIterable {
    case guncel = "CURRENT"
    case incelemeGunu = "DUE TODAY"
    case gecikmis = "OVERDUE"
    case tarihsiz = "UNDATED"

    public var statusLevel: StatusLevel {
        switch self {
        case .guncel: return .success
        case .incelemeGunu: return .warning
        case .gecikmis: return .error
        case .tarihsiz: return .neutral
        }
    }
}

public enum FalsificationStatus: String, Sendable, Equatable, Hashable, CaseIterable {
    case green = "GREEN"
    case warning = "WARNING"
    case breached = "BREACHED"

    public var displayTitle: String {
        switch self {
        case .green: return "NORMAL (GREEN)"
        case .warning: return "WATCHLIST (WARNING)"
        case .breached: return "BREACHED"
        }
    }

    public var statusLevel: StatusLevel {
        switch self {
        case .green: return .success
        case .warning: return .warning
        case .breached: return .error
        }
    }
}
