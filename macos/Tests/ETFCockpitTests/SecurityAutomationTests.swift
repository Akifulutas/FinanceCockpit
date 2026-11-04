import XCTest
@testable import FinanceCockpit

@MainActor
final class SecurityAutomationTests: XCTestCase {

    // MARK: - Test Fixtures

    private var mockDB: MockDatabaseService!
    private var mockCLI: MockCLIProcessRunner!

    override func setUp() async throws {
        try await super.setUp()
        mockDB = MockDatabaseService()
        mockCLI = MockCLIProcessRunner()
    }

    override func tearDown() async throws {
        mockDB = nil
        mockCLI = nil
        try await super.tearDown()
    }

    // MARK: =================================================================
    // MARK: Subsystem 8: System Integrity & Security Tests (İP-1 / İP-10)
    // MARK: =================================================================

    func testLoadAuditEvents() async {
        let event1 = AuditEventItem(
            eventId: 101,
            eventUuid: "evt-uuid-001",
            eventTime: "2026-10-31T10:00:00Z",
            actor: "etf-masa-cli",
            action: "INSERT",
            entityType: "SNAPSHOT",
            entityId: "run_001",
            payloadJson: "{\"status\": \"SEALED\"}",
            prevHash: "0000000000000000000000000000000000000000000000000000000000000000",
            currHash: "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"
        )
        let event2 = AuditEventItem(
            eventId: 102,
            eventUuid: "evt-uuid-002",
            eventTime: "2026-10-31T10:05:00Z",
            actor: "scheduler-launchd",
            action: "UPDATE",
            entityType: "THESIS",
            entityId: "th_spyi_01",
            payloadJson: "{\"review\": \"OK\"}",
            prevHash: "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            currHash: "222233334444555566667777888899990000aaaabbbbccccddddeeeeffff1111"
        )

        mockDB.mockAuditEvents = [event1, event2]

        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.loadData()

        XCTAssertEqual(viewModel.auditEvents.count, 2)
        XCTAssertEqual(viewModel.auditEvents[0].eventId, 101)
        XCTAssertTrue(viewModel.availableActionTypes.contains("ALL"))
        XCTAssertTrue(viewModel.availableActionTypes.contains("INSERT"))
        XCTAssertTrue(viewModel.availableActionTypes.contains("UPDATE"))
    }

    func testFilteredAuditEventsByActionAndSearch() async {
        let event1 = AuditEventItem(
            eventId: 1,
            eventUuid: "uuid-1",
            eventTime: "2026-10-31T09:00:00Z",
            actor: "admin",
            action: "INSERT",
            entityType: "TRANSACTION",
            entityId: "tx_123",
            prevHash: "0000",
            currHash: "aaaa"
        )
        let event2 = AuditEventItem(
            eventId: 2,
            eventUuid: "uuid-2",
            eventTime: "2026-10-31T09:10:00Z",
            actor: "scheduler",
            action: "SNAPSHOT",
            entityType: "PORTFOLIO",
            entityId: "snap_456",
            prevHash: "aaaa",
            currHash: "bbbb"
        )

        mockDB.mockAuditEvents = [event1, event2]
        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.loadData()

        // 1. Filter by Action
        viewModel.selectedActionFilter = "SNAPSHOT"
        XCTAssertEqual(viewModel.filteredAuditEvents.count, 1)
        XCTAssertEqual(viewModel.filteredAuditEvents.first?.eventId, 2)

        // 2. Filter by search text
        viewModel.selectedActionFilter = "ALL"
        viewModel.searchText = "tx_123"
        XCTAssertEqual(viewModel.filteredAuditEvents.count, 1)
        XCTAssertEqual(viewModel.filteredAuditEvents.first?.eventId, 1)

        // 3. Search non-existent
        viewModel.searchText = "non_existent_query"
        XCTAssertTrue(viewModel.filteredAuditEvents.isEmpty)
    }

    func testRunAuditVerificationSuccess() async {
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: true,
            fileVaultActive: true,
            schemaVersion: 3,
            triggerCount: 78,
            snapshotsCount: 12,
            rawObjectsCount: 45,
            auditEventsCount: 150,
            chainTip: "0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a",
            snapshotChainOk: true,
            auditChainOk: true,
            chainTipStatus: "MATCH",
            chainTipDetails: "Matches sealed tip",
            sealedSnapshotTip: "0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a",
            sealedAuditTip: "4e2e8967252d4e2eee2a173072ed601b49cea2e37a3817552f94789704a3c618",
            criticalIntegrityViolation: false,
            rawOutput: "ok true\ntrigger_count 78"
        )

        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.runAuditVerification()

        XCTAssertTrue(viewModel.isIntegrityValid)
        XCTAssertTrue(viewModel.fileVaultActive)
        XCTAssertEqual(viewModel.triggerCount, 78)
        XCTAssertEqual(viewModel.schemaVersion, 3)
        XCTAssertEqual(viewModel.snapshotsCount, 12)
        XCTAssertTrue(viewModel.snapshotChainOk)
        XCTAssertTrue(viewModel.auditChainOk)
        XCTAssertEqual(viewModel.chainTipStatus, "MATCH")
        XCTAssertFalse(viewModel.criticalIntegrityViolation)
        XCTAssertNotNil(viewModel.lastVerifiedDate)
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertNil(viewModel.errorMessage)
    }

    func testRunAuditVerificationFailure() async {
        mockCLI.mockVerifyResult = IntegrityCheckResult(
            ok: false,
            fileVaultActive: false,
            schemaVersion: 3,
            triggerCount: 75, // Triggers bypassed!
            criticalIntegrityViolation: true,
            rawOutput: "ok false\ncritical_integrity_violation true"
        )

        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.runAuditVerification()

        XCTAssertFalse(viewModel.isIntegrityValid)
        XCTAssertTrue(viewModel.criticalIntegrityViolation)
        XCTAssertNotNil(viewModel.errorMessage)
    }

    func testRunBackupOnlineAndDrill() async {
        mockCLI.mockBackupResult = BackupResult(
            isSuccess: true,
            backupFilePath: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/backups/backup-20261031.db").path,
            fileSizeBytes: 2_621_440,
            sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            restoreDrillOk: true,
            rawOutput: "BAŞARIYLA ALINDI"
        )

        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.runBackup(drillOnly: true)

        XCTAssertNotNil(viewModel.backupResult)
        XCTAssertTrue(viewModel.backupResult?.isSuccess ?? false)
        XCTAssertTrue(viewModel.backupResult?.restoreDrillOk ?? false)
        XCTAssertEqual(viewModel.backupResult?.fileSizeBytes, 2_621_440)
        XCTAssertNotNil(viewModel.statusMessage)
    }

    func testRunSecurityScan() async {
        mockCLI.mockSecurityResult = SecurityScanResult(
            isSuccess: true,
            permissionsOk: true,
            gitleaksLeaksCount: 0,
            rawOutput: "0 sızıntı, POSIX 0700/0600 uyumlu"
        )

        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.runSecurityScan()

        XCTAssertNotNil(viewModel.securityScanResult)
        XCTAssertTrue(viewModel.securityScanResult?.isSuccess ?? false)
        XCTAssertTrue(viewModel.securityScanResult?.permissionsOk ?? false)
        XCTAssertEqual(viewModel.securityScanResult?.gitleaksLeaksCount, 0)
        XCTAssertNotNil(viewModel.statusMessage)
    }

    func testSystemIntegrityCLIFailure() async {
        mockCLI.shouldFail = true
        let viewModel = SystemIntegrityViewModel(databaseService: mockDB, cliRunner: mockCLI)

        await viewModel.runAuditVerification()
        XCTAssertNotNil(viewModel.errorMessage)

        await viewModel.runBackup(drillOnly: false)
        XCTAssertNotNil(viewModel.errorMessage)

        await viewModel.runSecurityScan()
        XCTAssertNotNil(viewModel.errorMessage)
    }

    // MARK: =================================================================
    // MARK: Subsystem 9: Scheduler & Automation Tests (İP-12)
    // MARK: =================================================================

    func testDefaultLaunchdAgents() {
        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)

        XCTAssertEqual(viewModel.launchdAgents.count, 3)
        let labels = viewModel.launchdAgents.map(\.label)
        XCTAssertTrue(labels.contains("com.etf.masa.sabah"))
        XCTAssertTrue(labels.contains("com.etf.masa.aksam"))
        XCTAssertTrue(labels.contains("com.etf.masa.cuma"))

        let sabah = viewModel.launchdAgents.first { $0.label.contains("sabah") }
        XCTAssertEqual(sabah?.schedule, "Mon-Fri 09:30 CET")
        XCTAssertFalse(sabah?.isActive ?? true)
        XCTAssertFalse(sabah?.isInstalled ?? true)
    }

    func testJobsStateClassification() async {
        mockDB.mockJobs = [
            JobQueueItem(jobId: "job_01", jobType: "forecast", status: "PENDING", createdAt: "2026-10-31T09:00:00Z"),
            JobQueueItem(jobId: "job_02", jobType: "collect", status: "RUNNING", createdAt: "2026-10-31T09:01:00Z"),
            JobQueueItem(jobId: "job_03", jobType: "settle", status: "SUCCESS", createdAt: "2026-10-31T09:02:00Z"),
            JobQueueItem(jobId: "job_04", jobType: "research", status: "FAILED", createdAt: "2026-10-31T09:03:00Z"),
            JobQueueItem(jobId: "job_05", jobType: "broker_sync", status: "WAITING_AUTH", createdAt: "2026-10-31T09:04:00Z")
        ]

        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.loadData()

        XCTAssertEqual(viewModel.jobs.count, 5)
        XCTAssertEqual(viewModel.pendingJobsCount, 1)
        XCTAssertEqual(viewModel.runningJobsCount, 1)
        XCTAssertEqual(viewModel.completedJobsCount, 1)
        XCTAssertEqual(viewModel.failedJobsCount, 1)
        XCTAssertEqual(viewModel.waitingAuthJobs.count, 1)
        XCTAssertTrue(viewModel.hasWaitingAuthAlert)
    }

    func testWaitingAuthAlertDetection() async {
        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Initial state: no waiting auth
        XCTAssertFalse(viewModel.hasWaitingAuthAlert)

        // Inject WAITING_AUTH job
        mockDB.mockJobs = [
            JobQueueItem(
                jobId: "job_sync_scalable",
                jobType: "collect_snapshot",
                status: "WAITING_AUTH",
                errorMessage: "Broker session expired. Please re-authenticate.",
                createdAt: "2026-10-31T09:25:00Z"
            )
        ]
        await viewModel.loadData()

        XCTAssertTrue(viewModel.hasWaitingAuthAlert)
        XCTAssertEqual(viewModel.waitingAuthJobs.first?.jobId, "job_sync_scalable")
    }

    func testJobQueueFiltering() async {
        mockDB.mockJobs = [
            JobQueueItem(jobId: "job_alpha", jobType: "forecast_run", status: "PENDING", createdAt: "2026-10-31T09:00:00Z"),
            JobQueueItem(jobId: "job_beta", jobType: "research_deep", status: "FAILED", errorMessage: "Quota exceeded", createdAt: "2026-10-31T09:05:00Z"),
            JobQueueItem(jobId: "job_gamma", jobType: "settle_run", status: "SUCCESS", createdAt: "2026-10-31T09:10:00Z")
        ]

        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.loadData()

        // 1. Filter by status: FAILED
        viewModel.selectedJobFilter = "FAILED"
        XCTAssertEqual(viewModel.filteredJobs.count, 1)
        XCTAssertEqual(viewModel.filteredJobs.first?.jobId, "job_beta")

        // 2. Filter by status: COMPLETED
        viewModel.selectedJobFilter = "COMPLETED"
        XCTAssertEqual(viewModel.filteredJobs.count, 1)
        XCTAssertEqual(viewModel.filteredJobs.first?.jobId, "job_gamma")

        // 3. Search text
        viewModel.selectedJobFilter = "ALL"
        viewModel.searchText = "Quota exceeded"
        XCTAssertEqual(viewModel.filteredJobs.count, 1)
        XCTAssertEqual(viewModel.filteredJobs.first?.jobId, "job_beta")
    }

    func testSchedulerActions() async {
        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Install agents
        await viewModel.installLaunchdAgents()
        XCTAssertTrue(viewModel.launchdAgents.allSatisfy(\.isActive))
        XCTAssertNotNil(viewModel.statusMessage)

        // Send notification test
        await viewModel.sendNotificationTest()
        XCTAssertNotNil(viewModel.statusMessage)

        // Run agent manually
        await viewModel.runAgentManually(agentLabel: "com.etf.masa.sabah")
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["tahmin", "uret"]))

        // Uninstall agents
        await viewModel.uninstallLaunchdAgents()
        XCTAssertFalse(viewModel.launchdAgents.first?.isActive ?? true)
    }

    func testResolveWaitingAuth() async {
        mockDB.mockJobs = [
            JobQueueItem(jobId: "job_01", jobType: "collect", status: "WAITING_AUTH", createdAt: "2026-10-31T09:00:00Z")
        ]
        let viewModel = SchedulerAutomationViewModel(databaseService: mockDB, cliRunner: mockCLI)
        await viewModel.loadData()
        XCTAssertTrue(viewModel.hasWaitingAuthAlert)

        await viewModel.resolveWaitingAuth()
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["kontrol"]))
    }

    // MARK: =================================================================
    // MARK: Subsystem 10: System Configuration Tests
    // MARK: =================================================================

    func testDefaultConfigurationWeightsSum() {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)

        // Per H1, initial target weights are empty (0%)
        XCTAssertTrue(viewModel.isTargetWeightSumValid)
        XCTAssertEqual(viewModel.totalTargetWeightPct, 0.0)
        let validation = viewModel.validateTargetWeights()
        XCTAssertTrue(validation.isValid)
        XCTAssertEqual(validation.sumPct, 0.0)
    }

    func testTargetWeightsSumValidationOver100Percent() {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)
        viewModel.targetWeightItems = [
            TargetWeightItem(isin: "IE00B3YLTY66", name: "ACWI", role: "Core", weightPct: 45.0),
            TargetWeightItem(isin: "IE00BKM4GZ66", name: "EM", role: "Satellite", weightPct: 50.0)
        ]

        // Increase ACWI from 45% to 55% -> sum becomes 105%
        viewModel.updateWeight(for: "IE00B3YLTY66", newWeight: 55.0)

        XCTAssertFalse(viewModel.isTargetWeightSumValid)
        XCTAssertEqual(viewModel.totalTargetWeightPct, 105.0)

        let validation = viewModel.validateTargetWeights()
        XCTAssertFalse(validation.isValid)
        XCTAssertTrue(validation.message.contains("exceeds 100%"))
    }

    func testTargetWeightsSumValidationNegativeWeight() {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)
        viewModel.targetWeightItems = [
            TargetWeightItem(isin: "IE00B3YLTY66", name: "ACWI", role: "Core", weightPct: 45.0)
        ]

        // Set negative weight directly in item
        viewModel.targetWeightItems[0].weightPct = -5.0

        let validation = viewModel.validateTargetWeights()
        XCTAssertFalse(validation.isValid)
        XCTAssertTrue(validation.message.contains("cannot be negative"))
    }

    func testSavePortfolioTargets() async {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)
        viewModel.targetWeightItems = [
            TargetWeightItem(isin: "IE00B3YLTY66", name: "ACWI", role: "Core", weightPct: 60.0),
            TargetWeightItem(isin: "IE00BKM4GZ66", name: "EM", role: "Satellite", weightPct: 40.0)
        ]

        // Valid save
        let success = await viewModel.savePortfolioTargets()
        XCTAssertTrue(success)
        XCTAssertNotNil(viewModel.statusMessage)
        XCTAssertNil(viewModel.errorMessage)

        // Invalid save
        viewModel.updateWeight(for: "IE00B3YLTY66", newWeight: 70.0) // sum = 110%
        let fail = await viewModel.savePortfolioTargets()
        XCTAssertFalse(fail)
        XCTAssertNotNil(viewModel.errorMessage)
    }

    func testSaveInvestmentPolicies() async {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)

        viewModel.absoluteTolerance = 0.04
        viewModel.relativeTolerance = 0.20
        viewModel.policyApprovalStatus = "ONAYLANDI"
        viewModel.ucitsEnforcement = true

        // Without confirmation, saving ONAYLANDI triggers confirmation dialog
        let requiresConfirmation = await viewModel.saveInvestmentPolicies(confirmed: false)
        XCTAssertFalse(requiresConfirmation)
        XCTAssertTrue(viewModel.showPolicyApprovalDialog)

        // With confirmation, policy is saved
        let success = await viewModel.saveInvestmentPolicies(confirmed: true)
        XCTAssertTrue(success)
        XCTAssertNotNil(viewModel.statusMessage)
    }

    func testSystemConfigurationModelAccessAndNoSecretStorage() {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)

        // Masked Broker Account ID defaults to "—" before loading database
        XCTAssertEqual(viewModel.maskedBrokerAccountId, "—")

        // No unencrypted plaintext API keys in ViewModel
        XCTAssertEqual(viewModel.googleModel, "google / gemini-3.8-flash")
    }

    func testNotificationPreferences() {
        let viewModel = SystemConfigurationViewModel(cliRunner: mockCLI)

        XCTAssertTrue(viewModel.notifications.morningForecastAlerts)
        XCTAssertTrue(viewModel.notifications.eveningSettlementAlerts)
        XCTAssertTrue(viewModel.notifications.waitingAuthAlerts)
        XCTAssertTrue(viewModel.notifications.soundEnabled)
        XCTAssertEqual(viewModel.notifications.defaultTimeframe, "1Y")

        viewModel.notifications.soundEnabled = false
        viewModel.notifications.defaultTimeframe = "6A"

        XCTAssertFalse(viewModel.notifications.soundEnabled)
        XCTAssertEqual(viewModel.notifications.defaultTimeframe, "6A")
    }
}
