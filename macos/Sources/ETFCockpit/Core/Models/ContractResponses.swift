import Foundation

// MARK: - Contract Response Models (Schema Version 1.0.0)

public struct GirisResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let active: Bool
    public let sessionOk: Bool
    public let readerPath: String
    public let accountInfo: GirisAccountInfo?

    public init(
        schemaVersion: String = "1.0.0",
        active: Bool = false,
        sessionOk: Bool = false,
        readerPath: String = "",
        accountInfo: GirisAccountInfo? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.active = active
        self.sessionOk = sessionOk
        self.readerPath = readerPath
        self.accountInfo = accountInfo
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case active
        case sessionOk = "session_ok"
        case readerPath = "reader_path"
        case accountInfo = "account_info"
    }
}

public struct GirisAccountInfo: Codable, Sendable, Equatable {
    public let accountId: String?
    public let email: String?

    public init(accountId: String? = nil, email: String? = nil) {
        self.accountId = accountId
        self.email = email
    }

    enum CodingKeys: String, CodingKey {
        case accountId = "account_id"
        case email
    }
}

public struct DurumResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let ok: Bool
    public let databasePath: String
    public let integrity: DurumIntegrity
    public let capabilities: DurumCapabilities?
    public let queue: DurumQueue

    public init(
        schemaVersion: String = "1.0.0",
        ok: Bool,
        databasePath: String,
        integrity: DurumIntegrity,
        capabilities: DurumCapabilities? = nil,
        queue: DurumQueue
    ) {
        self.schemaVersion = schemaVersion
        self.ok = ok
        self.databasePath = databasePath
        self.integrity = integrity
        self.capabilities = capabilities
        self.queue = queue
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case ok
        case databasePath = "database_path"
        case integrity
        case capabilities
        case queue
    }
}

public struct DurumCapabilities: Codable, Sendable, Equatable {
    public let version: String?
    public let commandCount: Int?
    public let driftLevel: String?
    public let criticalIssues: [String]?
    public let warnings: [String]?

    public init(
        version: String? = nil,
        commandCount: Int? = nil,
        driftLevel: String? = nil,
        criticalIssues: [String]? = nil,
        warnings: [String]? = nil
    ) {
        self.version = version
        self.commandCount = commandCount
        self.driftLevel = driftLevel
        self.criticalIssues = criticalIssues
        self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case version
        case commandCount = "command_count"
        case driftLevel = "drift_level"
        case criticalIssues = "critical_issues"
        case warnings
    }
}

public struct DurumIntegrity: Codable, Sendable, Equatable {
    public let schemaVersion: Int
    public let triggerCount: Int
    public let snapshots: Int
    public let auditEvents: Int?
    public let chainTipStatus: String
    public let ok: Bool

    public init(
        schemaVersion: Int,
        triggerCount: Int,
        snapshots: Int,
        auditEvents: Int? = nil,
        chainTipStatus: String,
        ok: Bool
    ) {
        self.schemaVersion = schemaVersion
        self.triggerCount = triggerCount
        self.snapshots = snapshots
        self.auditEvents = auditEvents
        self.chainTipStatus = chainTipStatus
        self.ok = ok
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case triggerCount = "trigger_count"
        case snapshots
        case auditEvents = "audit_events"
        case chainTipStatus = "chain_tip_status"
        case ok
    }
}

public struct DurumQueue: Codable, Sendable, Equatable {
    public let pendingCount: Int
    public let recentJobs: [DurumJobSummary]?

    public init(pendingCount: Int, recentJobs: [DurumJobSummary]? = nil) {
        self.pendingCount = pendingCount
        self.recentJobs = recentJobs
    }

    enum CodingKeys: String, CodingKey {
        case pendingCount = "pending_count"
        case recentJobs = "recent_jobs"
    }
}

public struct DurumJobSummary: Codable, Sendable, Equatable, Identifiable, Hashable {
    public var id: String { jobType }
    public let jobType: String
    public let state: String
    public let count: Int?

    public init(jobType: String, state: String, count: Int? = nil) {
        self.jobType = jobType
        self.state = state
        self.count = count
    }

    enum CodingKeys: String, CodingKey {
        case jobType = "job_type"
        case state
        case count
    }
}

public struct PortfoyResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let runId: String?
    public let completedAt: String?
    public let positionsCount: Int
    public let cashEur: Double
    public let totalEur: Double
    public let warning: String?
    public let positions: [PortfoyPositionDTO]

    public init(
        schemaVersion: String = "1.0.0",
        runId: String? = nil,
        completedAt: String? = nil,
        positionsCount: Int,
        cashEur: Double,
        totalEur: Double,
        warning: String? = nil,
        positions: [PortfoyPositionDTO]
    ) {
        self.schemaVersion = schemaVersion
        self.runId = runId
        self.completedAt = completedAt
        self.positionsCount = positionsCount
        self.cashEur = cashEur
        self.totalEur = totalEur
        self.warning = warning
        self.positions = positions
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case runId = "run_id"
        case completedAt = "completed_at"
        case positionsCount = "positions_count"
        case cashEur = "cash_eur"
        case totalEur = "total_eur"
        case warning
        case positions
    }
}

public struct PortfoyPositionDTO: Codable, Sendable, Equatable, Identifiable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let name: String
    public let role: String
    public let quantity: Double
    public let midEur: Double
    public let valueEur: Double
    public let weightPct: Double
    public let quality: String
    public let fifoPriceEur: Double?

    public init(
        isin: String,
        name: String,
        role: String,
        quantity: Double,
        midEur: Double,
        valueEur: Double,
        weightPct: Double,
        quality: String,
        fifoPriceEur: Double? = nil
    ) {
        self.isin = isin
        self.name = name
        self.role = role
        self.quantity = quantity
        self.midEur = midEur
        self.valueEur = valueEur
        self.weightPct = weightPct
        self.quality = quality
        self.fifoPriceEur = fifoPriceEur
    }

    enum CodingKeys: String, CodingKey {
        case isin
        case name
        case role
        case quantity
        case midEur = "mid_eur"
        case valueEur = "value_eur"
        case weightPct = "weight_pct"
        case quality
        case fifoPriceEur = "fifo_price_eur"
    }
}

public struct DegerlendirResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let runId: String?
    public let warning: String?
    public let assessments: [DegerlendirAssessmentDTO]

    public init(
        schemaVersion: String = "1.0.0",
        runId: String? = nil,
        warning: String? = nil,
        assessments: [DegerlendirAssessmentDTO]
    ) {
        self.schemaVersion = schemaVersion
        self.runId = runId
        self.warning = warning
        self.assessments = assessments
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case runId = "run_id"
        case warning
        case assessments
    }
}

public struct DegerlendirAssessmentDTO: Codable, Sendable, Equatable, Identifiable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let name: String
    public let label: String
    public let reasons: [String]
    public let notes: [String]

    public init(
        isin: String,
        name: String,
        label: String,
        reasons: [String],
        notes: [String]
    ) {
        self.isin = isin
        self.name = name
        self.label = label
        self.reasons = reasons
        self.notes = notes
    }
}

public struct TaramaResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let poolCount: Int
    public let warning: String?
    public let candidates: [TaramaCandidateDTO]

    public init(
        schemaVersion: String = "1.0.0",
        poolCount: Int,
        warning: String? = nil,
        candidates: [TaramaCandidateDTO]
    ) {
        self.schemaVersion = schemaVersion
        self.poolCount = poolCount
        self.warning = warning
        self.candidates = candidates
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case poolCount = "pool_count"
        case warning
        case candidates
    }
}

public struct TaramaCandidateDTO: Codable, Sendable, Equatable, Identifiable, Hashable {
    public var id: String { isin }
    public let isin: String
    public let name: String
    public let label: String
    public let score: Double?
    public let reasons: [String]

    public init(
        isin: String,
        name: String,
        label: String,
        score: Double? = nil,
        reasons: [String]
    ) {
        self.isin = isin
        self.name = name
        self.label = label
        self.score = score
        self.reasons = reasons
    }
}

public struct TahminKarneResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let totalForecasts: Int
    public let settledCount: Int
    public let pendingCount: Int
    public let hitRatePct: String
    public let etfHitRatePct: String?
    public let stockHitRatePct: String?
    public let mapePct: String
    public let maeEur: String
    public let mpePct: String
    public let isSmallSample: Bool
    public let warningMessage: String?
    public let baselineFlatHitRatePct: String?
    public let baselineYesterdayHitRatePct: String?
    public let beatsBaselines: Bool?
    public let baselineWarning: String?

    public init(
        schemaVersion: String = "1.0.0",
        totalForecasts: Int,
        settledCount: Int,
        pendingCount: Int,
        hitRatePct: String,
        etfHitRatePct: String? = nil,
        stockHitRatePct: String? = nil,
        mapePct: String,
        maeEur: String,
        mpePct: String,
        isSmallSample: Bool,
        warningMessage: String? = nil,
        baselineFlatHitRatePct: String? = nil,
        baselineYesterdayHitRatePct: String? = nil,
        beatsBaselines: Bool? = nil,
        baselineWarning: String? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.totalForecasts = totalForecasts
        self.settledCount = settledCount
        self.pendingCount = pendingCount
        self.hitRatePct = hitRatePct
        self.etfHitRatePct = etfHitRatePct
        self.stockHitRatePct = stockHitRatePct
        self.mapePct = mapePct
        self.maeEur = maeEur
        self.mpePct = mpePct
        self.isSmallSample = isSmallSample
        self.warningMessage = warningMessage
        self.baselineFlatHitRatePct = baselineFlatHitRatePct
        self.baselineYesterdayHitRatePct = baselineYesterdayHitRatePct
        self.beatsBaselines = beatsBaselines
        self.baselineWarning = baselineWarning
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case totalForecasts = "total_forecasts"
        case settledCount = "settled_count"
        case pendingCount = "pending_count"
        case hitRatePct = "hit_rate_pct"
        case etfHitRatePct = "etf_hit_rate_pct"
        case stockHitRatePct = "stock_hit_rate_pct"
        case mapePct = "mape_pct"
        case maeEur = "mae_eur"
        case mpePct = "mpe_pct"
        case isSmallSample = "is_small_sample"
        case warningMessage = "warning_message"
        case baselineFlatHitRatePct = "baseline_flat_hit_rate_pct"
        case baselineYesterdayHitRatePct = "baseline_yesterday_hit_rate_pct"
        case beatsBaselines = "beats_baselines"
        case baselineWarning = "baseline_warning"
    }
}
