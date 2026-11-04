import Foundation

public struct ClaimItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { claimId }
    public let claimId: String
    public let bundleId: String
    public let instrumentId: String
    public let claimText: String
    public let claimType: String
    public let quoteVerbatim: String?
    public let verificationStatus: String
    public let sourceId: String?
    public let sourceType: String?
    public let sourceTitle: String?
    public let publisher: String?
    public let urlOrPath: String?

    public init(
        claimId: String,
        bundleId: String,
        instrumentId: String,
        claimText: String,
        claimType: String = "fact",
        quoteVerbatim: String? = nil,
        verificationStatus: String = "VERIFIED",
        sourceId: String? = nil,
        sourceType: String? = nil,
        sourceTitle: String? = nil,
        publisher: String? = nil,
        urlOrPath: String? = nil
    ) {
        self.claimId = claimId
        self.bundleId = bundleId
        self.instrumentId = instrumentId
        self.claimText = claimText
        self.claimType = claimType
        self.quoteVerbatim = quoteVerbatim
        self.verificationStatus = verificationStatus
        self.sourceId = sourceId
        self.sourceType = sourceType
        self.sourceTitle = sourceTitle
        self.publisher = publisher
        self.urlOrPath = urlOrPath
    }
}

public struct MetricItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { metricId }
    public let metricId: String
    public let bundleId: String
    public let instrumentId: String
    public let metricName: String
    public let value: String
    public let unit: String?
    public let periodStart: String?
    public let periodEnd: String?

    public init(
        metricId: String,
        bundleId: String,
        instrumentId: String,
        metricName: String,
        value: String,
        unit: String? = nil,
        periodStart: String? = nil,
        periodEnd: String? = nil
    ) {
        self.metricId = metricId
        self.bundleId = bundleId
        self.instrumentId = instrumentId
        self.metricName = metricName
        self.value = value
        self.unit = unit
        self.periodStart = periodStart
        self.periodEnd = periodEnd
    }
}

public struct SourceItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { sourceId }
    public let sourceId: String
    public let sourceType: String
    public let title: String
    public let urlOrPath: String?
    public let publisher: String?
    public let publicationDate: String?
    public let contentSha256: String?

    public init(
        sourceId: String,
        sourceType: String,
        title: String,
        urlOrPath: String? = nil,
        publisher: String? = nil,
        publicationDate: String? = nil,
        contentSha256: String? = nil
    ) {
        self.sourceId = sourceId
        self.sourceType = sourceType
        self.title = title
        self.urlOrPath = urlOrPath
        self.publisher = publisher
        self.publicationDate = publicationDate
        self.contentSha256 = contentSha256
    }
}

public struct EvidenceBundleItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { bundleId }
    public let bundleId: String
    public let instrumentId: String
    public let isin: String
    public let instrumentName: String?
    public let asOfDate: String
    public let claimsCount: Int
    public let metricsCount: Int
    public let claims: [ClaimItem]

    public init(
        bundleId: String,
        instrumentId: String,
        isin: String,
        instrumentName: String? = nil,
        asOfDate: String,
        claimsCount: Int = 0,
        metricsCount: Int = 0,
        claims: [ClaimItem] = []
    ) {
        self.bundleId = bundleId
        self.instrumentId = instrumentId
        self.isin = isin
        self.instrumentName = instrumentName
        self.asOfDate = asOfDate
        self.claimsCount = claimsCount
        self.metricsCount = metricsCount
        self.claims = claims
    }
}

public enum CriticVerdict: String, Sendable, Equatable, Hashable, CaseIterable {
    case notRun = "NOT_RUN"
    case pass = "PASS"
    case needsReview = "NEEDS_REVIEW"
    case materialWarning = "MATERIAL_WARNING"
    case fatalDefect = "FATAL_DEFECT"

    public var title: String {
        switch self {
        case .notRun: return "Not yet verified"
        case .pass: return "VERIFIED (PASS)"
        case .needsReview: return "REVIEW REQUIRED (NEEDS_REVIEW)"
        case .materialWarning: return "MATERIAL WARNING"
        case .fatalDefect: return "CRITICAL DEFECT (FATAL_DEFECT)"
        }
    }

    public var statusLevel: StatusLevel {
        switch self {
        case .notRun: return .neutral
        case .pass: return .success
        case .needsReview: return .warning
        case .materialWarning: return .warning
        case .fatalDefect: return .error
        }
    }
}

public struct CriticFindingItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { name }
    public let name: String
    public let description: String
    public let isPassed: Bool
    public let detail: String?

    public init(name: String, description: String, isPassed: Bool, detail: String? = nil) {
        self.name = name
        self.description = description
        self.isPassed = isPassed
        self.detail = detail
    }
}
