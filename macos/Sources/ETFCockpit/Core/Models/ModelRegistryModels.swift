import Foundation

public struct ModelRegistryItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { modelId }
    public let modelId: String
    public let provider: String
    public let modelName: String
    public let accessTier: String
    public let regionCompliance: String
    public let quotaInfo: String?
    public let privacyClass: String
    public let status: String
    public let lastVerifiedAt: String?
    public let createdAt: String

    public init(
        modelId: String,
        provider: String,
        modelName: String,
        accessTier: String,
        regionCompliance: String = "EU_COMPLIANT",
        quotaInfo: String? = nil,
        privacyClass: String = "confidential_anonymized",
        status: String = "eligible",
        lastVerifiedAt: String? = nil,
        createdAt: String
    ) {
        self.modelId = modelId
        self.provider = provider
        self.modelName = modelName
        self.accessTier = accessTier
        self.regionCompliance = regionCompliance
        self.quotaInfo = quotaInfo
        self.privacyClass = privacyClass
        self.status = status
        self.lastVerifiedAt = lastVerifiedAt
        self.createdAt = createdAt
    }
}

public struct ModelChampionItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { "\(taskCategory)_\(modelId)" }
    public let taskCategory: String
    public let modelId: String
    public let provider: String
    public let modelName: String
    public let accessTier: String
    public let scorePct: Decimal
    public let evalDatasetVersion: String
    public let evaluatedAt: String

    public init(
        taskCategory: String,
        modelId: String,
        provider: String,
        modelName: String,
        accessTier: String,
        scorePct: Decimal,
        evalDatasetVersion: String,
        evaluatedAt: String
    ) {
        self.taskCategory = taskCategory
        self.modelId = modelId
        self.provider = provider
        self.modelName = modelName
        self.accessTier = accessTier
        self.scorePct = scorePct
        self.evalDatasetVersion = evalDatasetVersion
        self.evaluatedAt = evaluatedAt
    }
}

public struct ModelEvaluationItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { evaluationId }
    public let evaluationId: String
    public let modelId: String
    public let taskCategory: String
    public let scorePct: Decimal
    public let criticalErrorPassed: Bool
    public let isChampion: Bool
    public let evalMetricsJson: String?

    public var isSimulated: Bool {
        if let json = evalMetricsJson?.lowercased() {
            if json.contains("\"live\": true") || json.contains("\"is_live\": true") {
                return false
            }
            return json.contains("simulation") || json.contains("simulated") || json.contains("mock") || json.contains("deterministic")
        }
        return true
    }

    public init(
        evaluationId: String,
        modelId: String,
        taskCategory: String,
        scorePct: Decimal,
        criticalErrorPassed: Bool,
        isChampion: Bool,
        evalMetricsJson: String? = nil
    ) {
        self.evaluationId = evaluationId
        self.modelId = modelId
        self.taskCategory = taskCategory
        self.scorePct = scorePct
        self.criticalErrorPassed = criticalErrorPassed
        self.isChampion = isChampion
        self.evalMetricsJson = evalMetricsJson
    }
}

public struct ModelRunItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { runId }
    public let runId: String
    public let taskName: String
    public let quickModelId: String?
    public let deepModelId: String?
    public let routeLabel: String?
    public let promptHash: String?
    public let toolsUsed: String?
    public let selectionRationale: String?
    public let status: String

    public init(
        runId: String,
        taskName: String,
        quickModelId: String? = nil,
        deepModelId: String? = nil,
        routeLabel: String? = nil,
        promptHash: String? = nil,
        toolsUsed: String? = nil,
        selectionRationale: String? = nil,
        status: String
    ) {
        self.runId = runId
        self.taskName = taskName
        self.quickModelId = quickModelId
        self.deepModelId = deepModelId
        self.routeLabel = routeLabel
        self.promptHash = promptHash
        self.toolsUsed = toolsUsed
        self.selectionRationale = selectionRationale
        self.status = status
    }
}
