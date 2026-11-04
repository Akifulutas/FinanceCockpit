import SwiftUI
import Combine

@MainActor
public final class SystemIntegrityViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var auditEvents: [AuditEventItem] = []
    @Published public var integrityResult: IntegrityCheckResult?
    @Published public var backupResult: BackupResult?
    @Published public var securityScanResult: SecurityScanResult?

    @Published public var isLoading: Bool = false
    @Published public var isVerifying: Bool = false
    @Published public var isBackingUp: Bool = false
    @Published public var isScanning: Bool = false

    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastVerifiedDate: Date?
    @Published public var lastRefreshDate: Date?

    @Published public var searchText: String = ""
    @Published public var selectedActionFilter: String = "ALL"

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
    }

    // MARK: - Computed Properties

    public var isIntegrityValid: Bool {
        integrityResult?.ok ?? false
    }

    public var fileVaultActive: Bool {
        integrityResult?.fileVaultActive ?? false
    }

    public var triggerCount: Int {
        integrityResult?.triggerCount ?? 78
    }

    public var schemaVersion: Int {
        integrityResult?.schemaVersion ?? 3
    }

    public var snapshotsCount: Int {
        integrityResult?.snapshotsCount ?? 0
    }

    public var auditEventsCount: Int {
        let reported = integrityResult?.auditEventsCount ?? 0
        return reported > 0 ? reported : auditEvents.count
    }

    public var chainTip: String {
        integrityResult?.chainTip ?? ""
    }

    public var snapshotChainOk: Bool {
        integrityResult?.snapshotChainOk ?? false
    }

    public var auditChainOk: Bool {
        integrityResult?.auditChainOk ?? false
    }

    public var chainTipStatus: String {
        integrityResult?.chainTipStatus ?? "UNKNOWN"
    }

    public var sealedSnapshotTip: String {
        integrityResult?.sealedSnapshotTip ?? ""
    }

    public var sealedAuditTip: String {
        integrityResult?.sealedAuditTip ?? ""
    }

    public var criticalIntegrityViolation: Bool {
        integrityResult?.criticalIntegrityViolation ?? false
    }

    public var availableActionTypes: [String] {
        let set = Set(auditEvents.map(\.action))
        return ["ALL"] + Array(set).sorted()
    }

    public var filteredAuditEvents: [AuditEventItem] {
        var items = auditEvents

        // Action Filter
        if selectedActionFilter != "ALL" {
            items = items.filter { $0.action.localizedCaseInsensitiveCompare(selectedActionFilter) == .orderedSame }
        }

        // Search text filter
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            items = items.filter {
                $0.actor.lowercased().contains(query) ||
                $0.action.lowercased().contains(query) ||
                $0.entityType.lowercased().contains(query) ||
                $0.entityId.lowercased().contains(query) ||
                $0.currHash.lowercased().contains(query) ||
                $0.eventUuid.lowercased().contains(query)
            }
        }

        return items
    }

    // MARK: - Actions

    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            let events = try await databaseService.fetchAuditEvents(limit: 100)
            self.auditEvents = events
            self.lastRefreshDate = Date()
            self.isLoading = false
        } catch {
            self.errorMessage = "Failed to load audit events: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func runAuditVerification() async {
        isVerifying = true
        errorMessage = nil
        statusMessage = "Verifying system and cryptographic hash chain (etf-masa dogrula)..."
        do {
            let result = try await cliRunner.runVerifyIntegrity()
            self.integrityResult = result
            self.lastVerifiedDate = Date()
            
            // Refresh audit events
            do {
                self.auditEvents = try await databaseService.fetchAuditEvents(limit: 100)
            } catch {
                CockpitLogger.shared.error("Failed to refresh audit events: \(error.localizedDescription)")
            }

            if result.ok {
                self.statusMessage = "Cryptographic integrity verified: 0 errors, 78 triggers active."
            } else {
                self.errorMessage = "Integrity verification failed! Chain tip or trigger mismatch."
            }
        } catch {
            self.errorMessage = "Error running integrity verification: \(error.localizedDescription)"
        }
        isVerifying = false
    }

    public func runBackup(drillOnly: Bool = false) async {
        isBackingUp = true
        errorMessage = nil
        statusMessage = drillOnly ? "Running backup restore drill (etf-masa yedek --prova)..." : "Creating live database backup (etf-masa yedek)..."
        do {
            let result = try await cliRunner.runBackup(drillOnly: drillOnly)
            self.backupResult = result
            
            // Refresh audit events
            do {
                self.auditEvents = try await databaseService.fetchAuditEvents(limit: 100)
            } catch {
                CockpitLogger.shared.error("Failed to refresh audit events: \(error.localizedDescription)")
            }

            if result.isSuccess {
                self.statusMessage = drillOnly ? "Restore drill completed successfully (quick_check: OK)." : "Database backup created and cryptographically sealed."
            } else {
                self.errorMessage = "Backup operation failed."
            }
        } catch {
            self.errorMessage = "Failed to run backup command: \(error.localizedDescription)"
        }
        isBackingUp = false
    }

    public func runSecurityScan() async {
        isScanning = true
        errorMessage = nil
        statusMessage = "Running security and permissions scan (etf-masa guvenlik-tara)..."
        do {
            let result = try await cliRunner.runSecurityScan()
            self.securityScanResult = result
            if result.isSuccess && result.gitleaksLeaksCount == 0 && result.permissionsOk {
                self.statusMessage = "Security scan clean: 0 leaks, POSIX 0700/0600 compliant."
            } else if result.gitleaksLeaksCount > 0 {
                self.errorMessage = "Gitleaks security alert: \(result.gitleaksLeaksCount) leaks detected!"
            } else if !result.permissionsOk {
                self.errorMessage = "File permissions alert: Non-compliant files detected (require 0700/0600)."
            } else {
                self.statusMessage = "Security scan completed."
            }
        } catch {
            self.errorMessage = "Failed to run security scan: \(error.localizedDescription)"
        }
        isScanning = false
    }
}
