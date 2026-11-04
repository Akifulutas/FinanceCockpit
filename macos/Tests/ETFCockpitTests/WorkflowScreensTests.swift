import XCTest
@testable import FinanceCockpit

@MainActor
final class WorkflowScreensTests: XCTestCase {

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

    // MARK: - E1: Today Dashboard Tests

    func testTodayDashboardSessionActive() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock active session response
        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": true,
              "session_ok": true,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": {
                "account_id": "ACC_VERIFIED_999",
                "email": "user@test.de"
              }
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.loadData()

        XCTAssertEqual(vm.isSessionActive, true)
        XCTAssertEqual(vm.accountInfo?.accountId, "ACC_VERIFIED_999")
        XCTAssertFalse(vm.hasWaitingAuthAlert)
    }

    func testTodayDashboardSessionInactiveAndSafariPrompt() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock inactive session response
        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": false,
              "session_ok": false,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": null
            }
            """,
            stderr: "",
            message: "Session expired"
        )

        await vm.loadData()

        XCTAssertEqual(vm.isSessionActive, false)
        XCTAssertNotNil(vm.loginPromptMessage)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Scalable Capital") ?? false)

        // Trigger Safari Login flow
        await vm.runLoginStream()
        XCTAssertNotNil(vm.loginPromptMessage)
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["giris", "--login"]))

        // Simulate successful login and verify
        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": true,
              "session_ok": true,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": {
                "account_id": "ACC_VERIFIED_999"
              }
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.verifySessionAfterLogin()
        XCTAssertEqual(vm.isSessionActive, true)
        XCTAssertTrue(vm.loginPromptMessage?.contains("✓") ?? false)
    }

    func testTodayDashboardInitialStartupSequenceEndToEnd() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `giris --json` initially returns inactive session
        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": false,
              "session_ok": false,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": null
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.runInitialStartupSequence()

        // Verify that:
        // 1. Session check happened
        // 2. giris --login was executed
        // 3. Data pipeline (veri + gecmis) ran automatically
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["giris", "--login"]))
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["veri"]))
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["gecmis"]))
        XCTAssertEqual(vm.isSessionActive, true)
        XCTAssertTrue(vm.loginPromptMessage?.contains("✓") ?? false)
    }

    // MARK: - İP-1: Honest Exit Code Tests
    func testIP1_LoginFailsOnNonZeroExit() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `giris --login` failing with exit code 1
        mockCLI.customCommandResults[["giris", "--login"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "Oturum açma iptal edildi.\n",
            stderr: "Login authorization rejected",
            message: "Failed"
        )

        await vm.runLoginStream()

        XCTAssertFalse(vm.isSessionActive ?? false, "Session must NOT be active when CLI exits with code 1")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Login failed") ?? false)
    }

    func testIP1_LoginFailsIfActiveFalseAfterExitZero() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `giris --login` exiting with 0
        mockCLI.customCommandResults[["giris", "--login"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "Giriş işlemi tamamlandı.\n",
            stderr: "",
            message: "Success"
        )

        // But verification `giris --json` returns active = false
        mockCLI.customCommandResults[["giris", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": false,
              "session_ok": false,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": null
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.runLoginStream()

        XCTAssertFalse(vm.isSessionActive ?? true, "Session must remain false if verification check active is false")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Login incomplete") ?? false)
    }

    // MARK: - İP-7: 6-Step Morning Sequence Unit Tests
    func testMorningFlow_Step1SessionFailureHaltsFlow() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `giris --json` returns active: false
        mockCLI.customCommandResults[["giris", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "active": false,
              "session_ok": false,
              "reader_path": "/opt/homebrew/bin/sc",
              "account_info": null
            }
            """,
            stderr: "",
            message: "Session Inactive"
        )

        // Mock `giris --login` fails with exit code 1
        mockCLI.customCommandResults[["giris", "--login"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "Giriş yetkilendirmesi reddedildi.\n",
            stderr: "Rejected",
            message: "Failed"
        )

        await vm.runFullMorningFlow()

        // Step 1 must be failed
        let step1 = vm.morningFlowSteps.first(where: { $0.step == .session })
        if case .failed(let code, _) = step1?.status {
            XCTAssertEqual(code, 1)
        } else {
            XCTFail("Step 1 must be marked failed when login fails")
        }

        // Steps 2-6 must be cancelled
        for step in vm.morningFlowSteps where step.step != .session {
            XCTAssertEqual(step.status, .cancelled, "Step \(step.step.rawValue) must be cancelled after step 1 failure")
        }

        XCTAssertNil(vm.morningFlowSummary, "Summary must be nil when flow halts")
    }

    func testMorningFlow_Step2VeriExit1HaltsFlow() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true

        // Mock `veri` returning exit code 1
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "Oturum süresi dolmuş.",
            stderr: "Auth required",
            message: "Auth error"
        )

        await vm.runFullMorningFlow()

        // Step 1 succeeded
        let step1 = vm.morningFlowSteps.first(where: { $0.step == .session })
        XCTAssertEqual(step1?.exitCode, 0)

        // Step 2 failed
        let step2 = vm.morningFlowSteps.first(where: { $0.step == .data })
        if case .failed(let code, _) = step2?.status {
            XCTAssertEqual(code, 1)
        } else {
            XCTFail("Step 2 must be failed with exit code 1")
        }

        // Steps 3-6 cancelled
        for step in vm.morningFlowSteps where step.step.rawValue > 2 {
            XCTAssertEqual(step.status, .cancelled)
        }
    }

    func testMorningFlow_Step3GecmisSkippedWhenRecent() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true

        // Set last history snapshot to 1 hour ago (within 24h)
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)

        // Mock `veri` exit 0
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "Veri mühürlendi", stderr: "", message: "Success")

        await vm.runFullMorningFlow()

        let step3 = vm.morningFlowSteps.first(where: { $0.step == .history })
        if case .skipped(let reason) = step3?.status {
            XCTAssertTrue(reason.contains("24 hours"))
        } else {
            XCTFail("Step 3 must be marked skipped when last history run was within 24h")
        }

        // Flow should have proceeded past step 3
        XCTAssertFalse(mockCLI.executedCommandsHistory.contains(["gecmis"]), "CLI gecmis should NOT have been invoked when skipped")
    }

    func testMorningFlow_Step4DegerlendirExit1HaltsFlow() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "Veri mühürlendi", stderr: "", message: "Success")

        // Mock `degerlendir --json` failing with exit code 1
        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "Değerlendirme motoru hatası",
            message: "Failed"
        )

        await vm.runFullMorningFlow()

        let step4 = vm.morningFlowSteps.first(where: { $0.step == .evaluation })
        if case .failed(let code, _) = step4?.status {
            XCTAssertEqual(code, 1)
        } else {
            XCTFail("Step 4 must be marked failed when degerlendir fails")
        }

        // Steps 5-6 cancelled
        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        let step6 = vm.morningFlowSteps.first(where: { $0.step == .scan })
        XCTAssertEqual(step5?.status, .cancelled)
        XCTAssertEqual(step6?.status, .cancelled)
    }

    func testMorningFlow_Step5YorumDegradedDoesNotHaltFlow() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "Veri mühürlendi", stderr: "", message: "Success")

        // Mock `yorum` failing (e.g. quota limit / 429)
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "Model kotası aşıldı (429)",
            message: "Quota error"
        )

        await vm.runFullMorningFlow()

        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        if case .degraded(let code, _) = step5?.status {
            XCTAssertEqual(code, 1)
        } else {
            XCTFail("Step 5 must be marked degraded when model quota is exceeded")
        }

        // Step 6 should still have run!
        let step6 = vm.morningFlowSteps.first(where: { $0.step == .scan })
        XCTAssertNotEqual(step6?.status, .cancelled, "Step 6 should run even if Step 5 commentary degraded")
    }

    func testMorningFlow_Step6TaramaCompletesFullMorningFlow() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "Veri mühürlendi", stderr: "", message: "Success")
        mockDB.mockLastHistorySnapshotTimestamp = Date().addingTimeInterval(-3600)

        mockCLI.customCommandResults[["degerlendir", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "run_id": "eval_test_01",
              "warning": null,
              "assessments": [
                { "isin": "IE00B3YLTY66", "name": "SPDR ACWI", "label": "TUT", "reasons": ["Hedef bandında"], "notes": [] },
                { "isin": "IE00BKM4GZ66", "name": "iShares EM", "label": "TUT", "reasons": ["Hedef bandında"], "notes": [] },
                { "isin": "IE00BYX2JD69", "name": "iShares Multi", "label": "TUT", "reasons": ["Hedef bandında"], "notes": [] },
                { "isin": "IE00B3F81409", "name": "iShares Value", "label": "TUT", "reasons": ["Hedef bandında"], "notes": [] }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        mockCLI.customCommandResults[["tarama", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "pool_count": 17,
              "warning": null,
              "candidates": [
                {
                  "isin": "IE00B3YLTY66",
                  "name": "SPDR MSCI Europe Small Cap Value",
                  "label": "ARAŞTIRMAYA DEĞER",
                  "score": 8.5,
                  "reasons": ["Sharpe 1.2", "Düşük korelasyon"]
                }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.runFullMorningFlow()

        // Check that all 6 steps completed (none failed or cancelled)
        for step in vm.morningFlowSteps {
            switch step.status {
            case .failed, .cancelled, .pending, .running:
                XCTFail("Step \(step.step.rawValue) did not finish cleanly: \(step.status)")
            case .success, .skipped, .degraded:
                break
            }
        }

        let step6 = vm.morningFlowSteps.first(where: { $0.step == .scan })
        if case .success(let code) = step6?.status {
            XCTAssertEqual(code, 0)
        } else {
            XCTFail("Step 6 must be marked success")
        }

        // Summary card populated
        XCTAssertNotNil(vm.morningFlowSummary)
        XCTAssertTrue(vm.morningFlowSummary?.isComplete ?? false)
        XCTAssertEqual(vm.morningFlowSummary?.evaluatedPositionsCount, 4)
        XCTAssertEqual(vm.morningFlowSummary?.opportunityCandidatesCount, 1)
        XCTAssertTrue(vm.morningFlowSummary?.summaryMessage.contains("4 positions evaluated") ?? false)
    }

    // Explicit 6 test names matching requirement specification
    func testMorningFlow_Step1_SessionFailureStopsFlow() async {
        await testMorningFlow_Step1SessionFailureHaltsFlow()
    }

    func testMorningFlow_Step2_VeriExit1StopsFlow() async {
        await testMorningFlow_Step2VeriExit1HaltsFlow()
    }

    func testMorningFlow_Step3_HistorySkippedWithin24Hours() async {
        await testMorningFlow_Step3GecmisSkippedWhenRecent()
    }

    func testMorningFlow_Step4_DegerlendirExit1StopsFlow() async {
        await testMorningFlow_Step4DegerlendirExit1HaltsFlow()
    }

    func testMorningFlow_Step5_Yorum429DegradedContinuesFlow() async {
        await testMorningFlow_Step5YorumDegradedDoesNotHaltFlow()
    }

    func testMorningFlow_Step6_TaramaSuccessCompletesAllSteps() async {
        await testMorningFlow_Step6TaramaCompletesFullMorningFlow()
    }

    func testIP1_RefreshDataStopsOnVeriExitOne() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `veri` returning exit code 1 (session error)
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "Scalable oturumu bulunamadı.",
            stderr: "Auth required",
            message: "Auth error"
        )

        await vm.refreshData()

        XCTAssertTrue(vm.loginPromptMessage?.contains("session required") ?? false)
        XCTAssertFalse(mockCLI.executedCommandsHistory.contains(["gecmis"]), "gecmis must NOT run when veri fails with auth error")
    }

    func testIP1_RefreshDataHandlesVeriExitTwoDegraded() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        // Mock `veri` returning exit code 2 (DEGRADED)
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 2,
            stdout: "Çalışma: run_test · kalite DEGRADED",
            stderr: "",
            message: "Degraded"
        )

        // Mock `gecmis` returning exit code 0
        mockCLI.customCommandResults[["gecmis"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "Geçmiş mühürlendi",
            stderr: "",
            message: "Success"
        )

        await vm.refreshData()

        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["gecmis"]), "gecmis should run even if quotes were degraded")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Partial data") ?? false)
    }

    func testTodayDashboardWaitingAuthDetection() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)

        mockDB.mockJobs = [
            JobQueueItem(jobId: "job_01", jobType: "SCRAPE", status: "WAITING_AUTH", createdAt: "2026-11-01T10:00:00Z")
        ]

        await vm.loadData()
        XCTAssertTrue(vm.hasWaitingAuthAlert)
    }

    func testXetraHoursCalculationBerlinTimezone() {
        // Monday 10:00 Berlin time -> Should be Open
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Berlin")!

        var components = DateComponents()
        components.year = 2026
        components.month = 11
        components.day = 2 // Monday
        components.hour = 10
        components.minute = 0
        let openDate = calendar.date(from: components)!

        let openStatus = TodayDashboardViewModel.checkIsXetraOpen(at: openDate)
        XCTAssertTrue(openStatus.isOpen)
        XCTAssertTrue(openStatus.text.contains("Open"))

        // Monday 20:00 Berlin time -> Should be Closed
        components.hour = 20
        let closedDate = calendar.date(from: components)!
        let closedStatus = TodayDashboardViewModel.checkIsXetraOpen(at: closedDate)
        XCTAssertFalse(closedStatus.isOpen)
        XCTAssertTrue(closedStatus.text.contains("Closed"))

        // Sunday 14:00 Berlin time -> Should be Closed (Weekend)
        components.day = 1 // Sunday
        components.hour = 14
        let weekendDate = calendar.date(from: components)!
        let weekendStatus = TodayDashboardViewModel.checkIsXetraOpen(at: weekendDate)
        XCTAssertFalse(weekendStatus.isOpen)
        XCTAssertTrue(weekendStatus.text.contains("Weekend"))
    }

    // MARK: - E2: Evaluation Tests

    func testEvaluationLoadDataAndDisclaimer() async {
        let vm = EvaluationViewModel(cliRunner: mockCLI)

        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "run_id": "eval_test_777",
              "warning": null,
              "assessments": [
                {
                  "isin": "IE00B4L5Y983",
                  "name": "iShares Core MSCI World",
                  "label": "TUT",
                  "reasons": ["Hedef ağırlık dengede"],
                  "notes": ["Teilfreistellung %30", "Karar desteğidir; sistem işlem yapmaz."]
                },
                {
                  "isin": "IE00B3YLTY66",
                  "name": "SPDR MSCI Europe Small Cap Value",
                  "label": "EKLE",
                  "reasons": ["Düşük değerleme", "Yüksek faktör maruziyeti"],
                  "notes": ["Karar desteğidir; sistem işlem yapmaz."]
                }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.loadData()

        XCTAssertEqual(vm.runId, "eval_test_777")
        XCTAssertEqual(vm.assessments.count, 2)
        XCTAssertEqual(vm.assessments[0].label, "TUT")
        XCTAssertEqual(vm.assessments[1].label, "EKLE")
        XCTAssertTrue(vm.assessments[0].notes.contains(where: { $0.contains("Karar desteğidir") }))
    }

    func testEvaluationDeepAnalysisTrigger() async {
        let vm = EvaluationViewModel(cliRunner: mockCLI)

        await vm.triggerDeepAnalysis()

        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["degerlendir"]))
        XCTAssertFalse(vm.isRunningDeepAnalysis)
    }

    // MARK: - E3: Screener & Pool Editor Tests

    func testScreenerLoadCandidates() async {
        let vm = ScreenerViewModel(cliRunner: mockCLI)

        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "pool_count": 8,
              "warning": null,
              "candidates": [
                {
                  "isin": "IE00B3YLTY66",
                  "name": "SPDR MSCI Europe Small Cap Value",
                  "label": "EKLE",
                  "score": 9.1,
                  "reasons": ["Sharpe 1.45"]
                }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.loadData()

        XCTAssertEqual(mockCLI.lastExecutedArguments, ["tarama", "--son", "--json"])
        XCTAssertEqual(vm.poolCount, 8)
        XCTAssertEqual(vm.candidates.count, 1)
        XCTAssertEqual(vm.candidates[0].score, 9.1)
        XCTAssertEqual(vm.selectedCandidate?.isin, "IE00B3YLTY66")
    }

    func testIP4_ScreenerTriggerLiveScanGuardsInactiveSession() async {
        let vm = ScreenerViewModel(cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = false

        await vm.triggerLiveScan()

        XCTAssertFalse(vm.isLoading)
        XCTAssertEqual(vm.errorMessage, "Active broker session required for screener. Please log in first.")
        XCTAssertFalse(mockCLI.executedCommandsHistory.contains(["tarama", "--json"]))
    }

    func testIP4_ScreenerTriggerLiveScanSucceedsWhenActive() async {
        let vm = ScreenerViewModel(cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "pool_count": 5,
              "warning": null,
              "candidates": [
                {
                  "isin": "US0378331005",
                  "name": "Apple",
                  "label": "ARAŞTIRMAYA DEĞER",
                  "score": 1.17,
                  "reasons": ["Trend üstünde"]
                }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )

        await vm.triggerLiveScan()

        XCTAssertFalse(vm.isLoading)
        XCTAssertNil(vm.errorMessage)
        XCTAssertEqual(vm.poolCount, 5)
        XCTAssertEqual(vm.candidates.count, 1)
        XCTAssertEqual(vm.candidates.first?.isin, "US0378331005")
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["tarama", "--json"]))
    }

    func testScreenerPoolEditorValidation() async {
        let vm = ScreenerViewModel(cliRunner: mockCLI)

        // Invalid ISIN check (Bad Luhn check digit or invalid format)
        vm.poolISINsText = "INVALID_ISIN_123"
        let successInvalid = await vm.savePool()
        XCTAssertFalse(successInvalid, "Invalid ISIN must be rejected by Luhn validation")
        XCTAssertNotNil(vm.poolEditorValidationMessage)
        XCTAssertTrue(vm.poolEditorValidationMessage?.contains("Invalid ISIN") ?? false)

        // Valid ISINs
        vm.poolISINsText = "IE00B4L5Y983\nIE00B3YLTY66"
        let successValid = await vm.savePool()
        XCTAssertTrue(successValid, "Valid ISINs must pass Luhn validation and trigger ayar yaz")
        XCTAssertNil(vm.poolEditorValidationMessage)
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["ayar", "yaz", "--dosya", "havuz", "--json", "-"]))
    }

    // MARK: - E4: Reports & Commentary Tests

    func testReportsLoadAndCategorization() async {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        // Create sample markdown reports
        let raporFile = tempDir.appendingPathComponent("masa-rapor-2026-11-01.md")
        try? "# Masa Raporu\nİçerik".write(to: raporFile, atomically: true, encoding: .utf8)

        let yorumFile = tempDir.appendingPathComponent("yorum-paketi-2026-11-01.md")
        try? "# Yorum Paketi\nModel görüşleri".write(to: yorumFile, atomically: true, encoding: .utf8)

        let vm = ReportsViewModel(reportsDirectory: tempDir.path, cliRunner: mockCLI)
        await vm.loadReports()

        XCTAssertEqual(vm.reports.count, 2)
        let types = Set(vm.reports.map(\.reportType))
        XCTAssertTrue(types.contains("REPORT"))
        XCTAssertTrue(types.contains("COMMENTARY"))
        XCTAssertFalse(vm.reportContent.isEmpty)

        // Action tests
        await vm.generateNewReport()
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["rapor"]))

        await vm.generateCommentaryPackage()
        XCTAssertTrue(mockCLI.executedCommandsHistory.contains(["yorum"]))
    }

    // MARK: - R6 (İP-5): Login URL Validation & Security Hardening Tests

    func testLoginStream_URLCapturedOnlyOnCompletedLines() async {
        let streamer = ChunkStreamingMockRunner()
        streamer.chunksToYield = [
            .stdout("Lütfen tarayıcıda açın: https://secure.scalable."),
            .stdout("capital/activate?user_code=SPLIT-1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: streamer)
        await vm.runLoginStream()
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?user_code=SPLIT-1234")
    }

    func testLoginStream_StrictScalableHostValidation_Success() async {
        let streamer = ChunkStreamingMockRunner()
        streamer.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?user_code=ABCD-1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: streamer)
        await vm.runLoginStream()
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?user_code=ABCD-1234")
    }

    func testLoginStream_SpoofedHost_BlockedWithWarning() async {
        let streamer = ChunkStreamingMockRunner()
        streamer.chunksToYield = [
            .stdout("https://secure.scalable.capital.evil.com/activate?code=1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: streamer)
        await vm.runLoginStream()
        XCTAssertNil(vm.loginAuthURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testLoginStream_InvalidPath_BlockedWithWarning() async {
        let streamer = ChunkStreamingMockRunner()
        streamer.chunksToYield = [
            .stdout("https://secure.scalable.capital/phishing-login\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: streamer)
        await vm.runLoginStream()
        XCTAssertNil(vm.loginAuthURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testLoginStream_NonHttpsScheme_BlockedWithWarning() async {
        let streamer = ChunkStreamingMockRunner()
        streamer.chunksToYield = [
            .stdout("http://secure.scalable.capital/activate?code=1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: streamer)
        await vm.runLoginStream()
        XCTAssertNil(vm.loginAuthURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    // MARK: - R7 (İP-6): Morning Flow Honesty & Error Reporting Tests

    func testMorningFlow_Step5YorumNonQuotaError_ShowsFirstLineOfStderr() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "FileNotFoundError: config/prompts/yorum.md bulunamadı\nTraceback (most recent call last):\n  File 'masa/cli.py'...",
            message: "Error"
        )
        await vm.runFullMorningFlow()
        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        XCTAssertEqual(step5?.detailText, "FileNotFoundError: config/prompts/yorum.md bulunamadı")
        XCTAssertFalse(step5?.detailText?.contains("Model kotası doldu") == true)
    }

    func testMorningFlow_Step5YorumQuotaError_ShowsModelKotasiDoldu() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(
            isSuccess: false,
            exitCode: 1,
            stdout: "",
            stderr: "GoogleGenerativeAIError: 429 Resource exhausted (quota exceeded)",
            message: "Error"
        )
        await vm.runFullMorningFlow()
        let step5 = vm.morningFlowSteps.first(where: { $0.step == .commentary })
        XCTAssertEqual(step5?.detailText, "Model quota exhausted, deterministic evaluation valid.")
    }

    func testMorningFlow_Step6EmptyCandidates_ShowsZeroWithScannedCount() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockCLI.customCommandResults[["tarama", "--json"]] = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: """
            {
              "schema_version": "1.0.0",
              "pool_count": 17,
              "warning": null,
              "candidates": [
                { "isin": "IE00B3YLTY66", "name": "ETF 1", "label": "NÖTR", "score": 5.0, "reasons": [] },
                { "isin": "IE00BKM4GZ66", "name": "ETF 2", "label": "İZLE", "score": 4.5, "reasons": [] }
              ]
            }
            """,
            stderr: "",
            message: "Success"
        )
        await vm.runFullMorningFlow()
        let step6 = vm.morningFlowSteps.first(where: { $0.step == .scan })
        XCTAssertEqual(step6?.detailText, "0 opportunities (2 assets scanned)")
        XCTAssertEqual(vm.morningFlowSummary?.opportunityCandidatesCount, 0)
    }

    func testMorningFlow_MissingQuotes_ShowsKotasyonYok() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        mockDB.mockQuotes = []
        await vm.runFullMorningFlow()
        XCTAssertEqual(vm.morningFlowSummary?.lastQuoteTimestamp, "no quotes")
    }

    func testMorningFlow_SummaryMessage_ReflectsWarningsAndErrors() async {
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: mockCLI)
        mockCLI.isScalableSessionActive = true
        mockCLI.customCommandResults[["veri"]] = CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "OK", stderr: "", message: "")
        // Step 5 degraded with 429
        mockCLI.customCommandResults[["yorum"]] = CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "429 quota", message: "")
        await vm.runFullMorningFlow()
        XCTAssertTrue(vm.morningFlowSummary?.summaryMessage.contains("Completed · 1 warning(s)") == true)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Completed · 1 warning(s)") == true)
    }
}

// MARK: - Test Helper Mock Runner for Streaming Chunks
final class ChunkStreamingMockRunner: CLIProcessRunnerProtocol, @unchecked Sendable {
    var chunksToYield: [CLIStreamChunk] = []

    func runCommand(
        arguments: [String],
        timeoutSeconds: TimeInterval? = nil,
        stdin: String? = nil,
        onStdoutChunk: (@Sendable (String) -> Void)? = nil,
        onStderrChunk: (@Sendable (String) -> Void)? = nil
    ) async throws -> CLIOperationResult {
        if arguments == ["giris", "--login"] {
            for chunk in chunksToYield {
                switch chunk {
                case .stdout(let text):
                    onStdoutChunk?(text)
                case .stderr(let text):
                    onStderrChunk?(text)
                case .exit:
                    break
                }
            }
            return CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
        }
        return CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }

    func runStream(
        arguments: [String],
        timeoutSeconds: TimeInterval?,
        stdin: String?
    ) -> AsyncThrowingStream<CLIStreamChunk, Error> {
        let chunks = self.chunksToYield
        return AsyncThrowingStream { continuation in
            for chunk in chunks {
                continuation.yield(chunk)
            }
            continuation.yield(.exit(0))
            continuation.finish()
        }
    }

    func runVerifyIntegrity() async throws -> IntegrityCheckResult {
        IntegrityCheckResult(ok: true)
    }
    func runBackup(drillOnly: Bool) async throws -> BackupResult {
        BackupResult(isSuccess: true, backupFilePath: "", fileSizeBytes: 0, sha256: "", restoreDrillOk: false)
    }
    func runSecurityScan() async throws -> SecurityScanResult {
        SecurityScanResult(isSuccess: true, permissionsOk: true, gitleaksLeaksCount: 0)
    }
    func runForecastMorning() async throws -> CLIOperationResult {
        CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }
    func runSettleEvening() async throws -> CLIOperationResult {
        CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }
    func runResearch(isin: String, horizon: String?) async throws -> CLIOperationResult {
        CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }
    func runResearch(query: String?, ticker: String?) async throws -> CLIOperationResult {
        CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }
    func runSchedulerAction(agent: String, action: String) async throws -> CLIOperationResult {
        CLIOperationResult(isSuccess: true, exitCode: 0, stdout: "", stderr: "", message: "")
    }
}
