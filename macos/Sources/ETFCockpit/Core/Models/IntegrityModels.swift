import Foundation

public struct AuditEventItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: Int64 { eventId }
    public let eventId: Int64
    public let eventUuid: String
    public let eventTime: String
    public let actor: String
    public let action: String
    public let entityType: String
    public let entityId: String
    public let payloadJson: String?
    public let prevHash: String
    public let currHash: String

    public init(
        eventId: Int64,
        eventUuid: String,
        eventTime: String,
        actor: String,
        action: String,
        entityType: String,
        entityId: String,
        payloadJson: String? = nil,
        prevHash: String,
        currHash: String
    ) {
        self.eventId = eventId
        self.eventUuid = eventUuid
        self.eventTime = eventTime
        self.actor = actor
        self.action = action
        self.entityType = entityType
        self.entityId = entityId
        self.payloadJson = payloadJson
        self.prevHash = prevHash
        self.currHash = currHash
    }
}

public struct IntegrityCheckResult: Sendable, Equatable {
    public let ok: Bool
    public let fileVaultActive: Bool
    public let schemaVersion: Int
    public let triggerCount: Int
    public let snapshotsCount: Int
    public let rawObjectsCount: Int
    public let auditEventsCount: Int
    public let chainTip: String
    public let snapshotChainOk: Bool
    public let auditChainOk: Bool
    public let chainTipStatus: String
    public let chainTipDetails: String
    public let sealedSnapshotTip: String
    public let sealedAuditTip: String
    public let criticalIntegrityViolation: Bool
    public let rawOutput: String

    public init(
        ok: Bool,
        fileVaultActive: Bool = false,
        schemaVersion: Int = 3,
        triggerCount: Int = 78,
        snapshotsCount: Int = 0,
        rawObjectsCount: Int = 0,
        auditEventsCount: Int = 0,
        chainTip: String = "",
        snapshotChainOk: Bool = false,
        auditChainOk: Bool = false,
        chainTipStatus: String = "UNKNOWN",
        chainTipDetails: String = "",
        sealedSnapshotTip: String = "",
        sealedAuditTip: String = "",
        criticalIntegrityViolation: Bool = false,
        rawOutput: String = ""
    ) {
        self.ok = ok
        self.fileVaultActive = fileVaultActive
        self.schemaVersion = schemaVersion
        self.triggerCount = triggerCount
        self.snapshotsCount = snapshotsCount
        self.rawObjectsCount = rawObjectsCount
        self.auditEventsCount = auditEventsCount
        self.chainTip = chainTip
        self.snapshotChainOk = snapshotChainOk
        self.auditChainOk = auditChainOk
        self.chainTipStatus = chainTipStatus
        self.chainTipDetails = chainTipDetails
        self.sealedSnapshotTip = sealedSnapshotTip
        self.sealedAuditTip = sealedAuditTip
        self.criticalIntegrityViolation = criticalIntegrityViolation
        self.rawOutput = rawOutput
    }
}

public struct BackupResult: Sendable, Equatable {
    public let isSuccess: Bool
    public let backupFilePath: String?
    public let fileSizeBytes: Int64?
    public let sha256: String?
    public let snapshotTip: String?
    public let auditTip: String?
    public let manifestPath: String?
    public let restoreDrillOk: Bool
    public let rawOutput: String

    public init(
        isSuccess: Bool,
        backupFilePath: String? = nil,
        fileSizeBytes: Int64? = nil,
        sha256: String? = nil,
        snapshotTip: String? = nil,
        auditTip: String? = nil,
        manifestPath: String? = nil,
        restoreDrillOk: Bool = false,
        rawOutput: String = ""
    ) {
        self.isSuccess = isSuccess
        self.backupFilePath = backupFilePath
        self.fileSizeBytes = fileSizeBytes
        self.sha256 = sha256
        self.snapshotTip = snapshotTip
        self.auditTip = auditTip
        self.manifestPath = manifestPath
        self.restoreDrillOk = restoreDrillOk
        self.rawOutput = rawOutput
    }
}

public struct SecurityScanResult: Sendable, Equatable {
    public let isSuccess: Bool
    public let permissionsOk: Bool
    public let gitleaksLeaksCount: Int
    public let rawOutput: String

    public init(
        isSuccess: Bool,
        permissionsOk: Bool = true,
        gitleaksLeaksCount: Int = 0,
        rawOutput: String = ""
    ) {
        self.isSuccess = isSuccess
        self.permissionsOk = permissionsOk
        self.gitleaksLeaksCount = gitleaksLeaksCount
        self.rawOutput = rawOutput
    }
}
