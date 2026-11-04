import Foundation

public struct JobQueueItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { jobId }
    public let jobId: String
    public let jobType: String
    public let status: String
    public let dedupKey: String?
    public let paramsJson: String?
    public let resultJson: String?
    public let errorMessage: String?
    public let retryCount: Int
    public let createdAt: String
    public let startedAt: String?
    public let completedAt: String?

    public init(
        jobId: String,
        jobType: String,
        status: String,
        dedupKey: String? = nil,
        paramsJson: String? = nil,
        resultJson: String? = nil,
        errorMessage: String? = nil,
        retryCount: Int = 0,
        createdAt: String,
        startedAt: String? = nil,
        completedAt: String? = nil
    ) {
        self.jobId = jobId
        self.jobType = jobType
        self.status = status
        self.dedupKey = dedupKey
        self.paramsJson = paramsJson
        self.resultJson = resultJson
        self.errorMessage = errorMessage
        self.retryCount = retryCount
        self.createdAt = createdAt
        self.startedAt = startedAt
        self.completedAt = completedAt
    }
}

public struct SchedulerStatusResponse: Sendable, Equatable, Hashable, Codable {
    public let schemaVersion: String
    public let agents: [LaunchdAgentItem]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case agents
    }

    public init(schemaVersion: String = "1.0.0", agents: [LaunchdAgentItem] = []) {
        self.schemaVersion = schemaVersion
        self.agents = agents
    }
}

public struct LaunchdAgentItem: Identifiable, Sendable, Equatable, Hashable, Codable {
    public var id: String { label }
    public let label: String
    public let description: String
    public let schedule: String
    public let isInstalled: Bool
    public let isActive: Bool
    public let lastExitCode: Int?
    public let plistPath: String?
    public let logLines: [String]

    enum CodingKeys: String, CodingKey {
        case label
        case description
        case schedule
        case isInstalled = "installed"
        case isActive = "loaded"
        case lastExitCode = "last_exit_code"
        case plistPath = "plist_path"
        case logLines = "log_lines"
    }

    public init(
        label: String,
        description: String,
        schedule: String,
        isInstalled: Bool = false,
        isActive: Bool = false,
        lastExitCode: Int? = nil,
        plistPath: String? = nil,
        logLines: [String] = []
    ) {
        self.label = label
        self.description = description
        self.schedule = schedule
        self.isInstalled = isInstalled
        self.isActive = isActive
        self.lastExitCode = lastExitCode
        self.plistPath = plistPath
        self.logLines = logLines
    }
}
