import XCTest
@testable import FinanceCockpit

final class AdversarialChallengerTests: XCTestCase {

    // MARK: - 1. Empirical Confidence Boundary Verification (N = 0, 29, 30, 31)

    func testEmpiricalConfidenceStrictBoundaries() {
        // Boundary N = -5, -1: Negative counts must be suppressed
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: -5, hitRatePct: 75.0), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: -1, hitRatePct: 75.0), "—")
        XCTAssertFalse(Formatters.isEmpiricallyReliable(observationCount: -1))

        // Boundary N = 0: Zero count must be suppressed
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 0, hitRatePct: 80.0), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 0, hitRatePct: nil), "—")
        XCTAssertFalse(Formatters.isEmpiricallyReliable(observationCount: 0))

        // Intermediate values N < 30
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 1, hitRatePct: 100.0), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 15, hitRatePct: 50.0), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 28, hitRatePct: 71.4), "—")

        // Boundary N = 29: Threshold - 1 MUST be strictly SUPPRESSED
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 29, hitRatePct: 99.9), "—")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 29, hitRatePct: 0.0), "—")
        XCTAssertFalse(Formatters.isEmpiricallyReliable(observationCount: 29))
        XCTAssertTrue(Formatters.confidenceStatusMessage(observationCount: 29).contains("Small Sample Size"))

        // Boundary N = 30: EXACT THRESHOLD -> MUST format actual hit rate
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 30))
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: 70.0), "70,0%")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: 0.0), "0,0%")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: 100.0), "100,0%")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: 58.333), "58,3%")
        XCTAssertTrue(Formatters.confidenceStatusMessage(observationCount: 30).contains("Statistically Reliable"))

        // Boundary N = 30 with nil hitRate -> returns "—"
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 30, hitRatePct: nil), "—")

        // Boundary N = 31: Threshold + 1 -> MUST format actual hit rate
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 31))
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 31, hitRatePct: 67.7), "67,7%")
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 31, hitRatePct: nil), "—")

        // Higher counts N = 100, N = 1000
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 100))
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 100, hitRatePct: 65.4), "65,4%")
        XCTAssertTrue(Formatters.isEmpiricallyReliable(observationCount: 1000))
        XCTAssertEqual(Formatters.formatEmpiricalConfidence(observationCount: 1000, hitRatePct: 83.2), "83,2%")
    }

    @MainActor
    func testConfidenceBadgeViewBoundaries() {
        // N = 0
        let badge0 = ConfidenceBadgeView(observationCount: 0, hitRatePct: 75.0)
        XCTAssertFalse(badge0.isReliable)
        XCTAssertEqual(badge0.displayConfidence, "—")
        XCTAssertTrue(badge0.tooltipText.contains("Small Sample"))
        XCTAssertTrue(badge0.tooltipText.contains("N = 0 < 30"))

        // N = 29
        let badge29 = ConfidenceBadgeView(observationCount: 29, hitRatePct: 65.5)
        XCTAssertFalse(badge29.isReliable)
        XCTAssertEqual(badge29.displayConfidence, "—")
        XCTAssertTrue(badge29.tooltipText.contains("Small Sample"))
        XCTAssertTrue(badge29.tooltipText.contains("N = 29 < 30"))

        // N = 30
        let badge30 = ConfidenceBadgeView(observationCount: 30, hitRatePct: 65.5)
        XCTAssertTrue(badge30.isReliable)
        XCTAssertEqual(badge30.displayConfidence, "65,5%")
        XCTAssertTrue(badge30.tooltipText.contains("Statistically Reliable"))
        XCTAssertTrue(badge30.tooltipText.contains("N = 30 ≥ 30"))

        // N = 31
        let badge31 = ConfidenceBadgeView(observationCount: 31, hitRatePct: 71.0)
        XCTAssertTrue(badge31.isReliable)
        XCTAssertEqual(badge31.displayConfidence, "71,0%")
        XCTAssertTrue(badge31.tooltipText.contains("Statistically Reliable"))
        XCTAssertTrue(badge31.tooltipText.contains("N = 31 ≥ 30"))

        // Decimal initializers at boundaries
        let badgeDecimal29 = ConfidenceBadgeView(observationCount: 29, confidencePct: Decimal(string: "68.4"))
        XCTAssertFalse(badgeDecimal29.isReliable)
        XCTAssertEqual(badgeDecimal29.displayConfidence, "—")

        let badgeDecimal30 = ConfidenceBadgeView(observationCount: 30, confidencePct: Decimal(string: "68.4"))
        XCTAssertTrue(badgeDecimal30.isReliable)
        XCTAssertEqual(badgeDecimal30.displayConfidence, "68,4%")

        let badgeDecimal31 = ConfidenceBadgeView(observationCount: 31, confidencePct: Decimal(string: "68.4"))
        XCTAssertTrue(badgeDecimal31.isReliable)
        XCTAssertEqual(badgeDecimal31.displayConfidence, "68,4%")
    }

    @MainActor
    func testForecastViewModelAtBoundaries() async {
        let mockDb = MockDatabaseService()
        let mockCli = MockCLIProcessRunner()
        let vm = ForecastSettlementViewModel(databaseService: mockDb, cliRunner: mockCli)

        // N = 0
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 0,
            hitsCount: 0,
            hitRatePct: nil
        )
        await vm.loadData()
        XCTAssertFalse(vm.isEmpiricallyReliable)
        XCTAssertEqual(vm.empiricalConfidenceDisplay, "—")

        // N = 29
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 29,
            hitsCount: 22,
            hitRatePct: 75.86
        )
        await vm.loadData()
        XCTAssertFalse(vm.isEmpiricallyReliable)
        XCTAssertEqual(vm.empiricalConfidenceDisplay, "—")

        // N = 30
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 30,
            hitsCount: 21,
            hitRatePct: 70.0
        )
        await vm.loadData()
        XCTAssertTrue(vm.isEmpiricallyReliable)
        XCTAssertEqual(vm.empiricalConfidenceDisplay, "70,0%")

        // N = 31
        mockDb.mockForecastPerformance = ForecastPerformanceSummary(
            totalSettledCount: 31,
            hitsCount: 22,
            hitRatePct: 70.97
        )
        await vm.loadData()
        XCTAssertTrue(vm.isEmpiricallyReliable)
        XCTAssertEqual(vm.empiricalConfidenceDisplay, "71,0%")
    }

    // MARK: - 2. Subprocess Resilience: Timeout and Failure Handling

    func testSubprocessTimeoutHandling() async {
        // Create a temporary shell script that sleeps for 5 seconds
        let tempScript = FileManager.default.temporaryDirectory.appendingPathComponent("test_sleep_\(UUID().uuidString).sh")
        let scriptContent = "#!/bin/sh\nsleep 5\necho 'done'\n"
        try? scriptContent.write(to: tempScript, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: tempScript.path)

        defer {
            try? FileManager.default.removeItem(at: tempScript)
        }

        let runner = CLIProcessRunner(
            executablePath: tempScript.path,
            workingDirectory: FileManager.default.temporaryDirectory.path,
            defaultTimeout: 0.3 // 300 ms timeout
        )

        do {
            _ = try await runner.runCommand(arguments: [], timeoutSeconds: 0.3)
            XCTFail("Expected runCommand to throw ProcessError.timedOut")
        } catch {
            guard case CLIProcessRunner.ProcessError.timedOut(let seconds) = error else {
                XCTFail("Expected ProcessError.timedOut, got: \(error)")
                return
            }
            XCTAssertEqual(seconds, 0.3, accuracy: 0.05)
        }
    }

    func testSubprocessFailureHandlingNonZeroExit() async {
        // Create a temporary shell script that exits with non-zero code and writes to stderr
        let tempScript = FileManager.default.temporaryDirectory.appendingPathComponent("test_fail_\(UUID().uuidString).sh")
        let scriptContent = "#!/bin/sh\necho 'Fatal database locked error' >&2\nexit 42\n"
        try? scriptContent.write(to: tempScript, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: tempScript.path)

        defer {
            try? FileManager.default.removeItem(at: tempScript)
        }

        let runner = CLIProcessRunner(
            executablePath: tempScript.path,
            workingDirectory: FileManager.default.temporaryDirectory.path
        )

        let result = try? await runner.runCommand(arguments: [])
        XCTAssertNotNil(result, "Command execution should return CLIOperationResult without throwing")
        XCTAssertFalse(result!.isSuccess, "isSuccess must be false for exit code 42")
        XCTAssertEqual(result!.exitCode, 42)
        XCTAssertTrue(result!.stderr.contains("Fatal database locked error"))
        XCTAssertTrue(result!.message.contains("Fatal database locked error"))
    }

    func testSubprocessBinaryNotFoundHandling() async {
        let runner = CLIProcessRunner(executablePath: "/nonexistent/invalid/executable/binary")
        do {
            _ = try await runner.runCommand(arguments: [])
            XCTFail("Expected binaryNotFound error")
        } catch {
            guard case CLIProcessRunner.ProcessError.binaryNotFound(let path) = error else {
                XCTFail("Expected ProcessError.binaryNotFound, got: \(error)")
                return
            }
            XCTAssertEqual(path, "/nonexistent/invalid/executable/binary")
        }
    }

    // MARK: - 3. Secret Masking Stress Testing

    func testSecretMaskingIBANVariations() {
        // German IBAN
        let germanIBAN = "DE89" + "370400440532013000"
        let germanMsg = "Broker transfer to account \(germanIBAN) completed."
        let sanitizedGerman = SecretMasker.sanitizeLogMessage(germanMsg)
        XCTAssertFalse(sanitizedGerman.contains(germanIBAN))
        XCTAssertTrue(sanitizedGerman.contains("DE8••••••••000"))

        // Turkish IBAN
        let turkishIBAN = "TR33" + "0006100519786453210987"
        let turkishMsg = "TL çekim hesabı: \(turkishIBAN)"
        let sanitizedTurkish = SecretMasker.sanitizeLogMessage(turkishMsg)
        XCTAssertFalse(sanitizedTurkish.contains(turkishIBAN))
        XCTAssertTrue(sanitizedTurkish.contains("TR3••••••••987"))

        // French IBAN
        let frenchIBAN = "FR14" + "20041010050500013M02606"
        let frenchMsg = "SEPA direct debit: \(frenchIBAN)"
        let sanitizedFrench = SecretMasker.sanitizeLogMessage(frenchMsg)
        XCTAssertFalse(sanitizedFrench.contains(frenchIBAN))
        XCTAssertTrue(sanitizedFrench.contains("FR1••••••••606"))

        // Multiple IBANs on same line
        let multiMsg = "Transferred from \(germanIBAN) to target \(turkishIBAN) via SEPA"
        let sanitizedMulti = SecretMasker.sanitizeLogMessage(multiMsg)
        XCTAssertFalse(sanitizedMulti.contains(germanIBAN))
        XCTAssertFalse(sanitizedMulti.contains(turkishIBAN))
        XCTAssertTrue(sanitizedMulti.contains("DE8••••••••000"))
        XCTAssertTrue(sanitizedMulti.contains("TR3••••••••987"))
    }

    func testSecretMaskingBearerTokens() {
        let dummyJwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0." + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

        // Capitalized 'Bearer'
        let msg1 = "Headers: Authorization: Bearer \(dummyJwt)"
        let s1 = SecretMasker.sanitizeLogMessage(msg1)
        XCTAssertFalse(s1.contains(dummyJwt))
        XCTAssertTrue(s1.contains("eyJ••••••••w5c"))

        // Lowercase 'bearer'
        let msg2 = "header authorization: bearer \(dummyJwt)"
        let s2 = SecretMasker.sanitizeLogMessage(msg2)
        XCTAssertFalse(s2.contains(dummyJwt))
        XCTAssertTrue(s2.contains("eyJ••••••••w5c"))

        // Uppercase 'BEARER'
        let msg3 = "AUTHORIZATION: BEARER \(dummyJwt)"
        let s3 = SecretMasker.sanitizeLogMessage(msg3)
        XCTAssertFalse(s3.contains(dummyJwt))
        XCTAssertTrue(s3.contains("eyJ••••••••w5c"))
    }

    func testSecretMaskingOpenAIAndClaudeAPIKeys() {
        // OpenAI Key format
        let openAIKey = "sk-test-" + "abc123456789xyz9876543210abcdef"
        let msg1 = "Configured OPENAI_API_KEY=\(openAIKey)"
        let s1 = SecretMasker.sanitizeLogMessage(msg1)
        XCTAssertFalse(s1.contains(openAIKey))
        XCTAssertTrue(s1.contains("sk-••••••••def"))

        // Anthropic Claude Key format
        let claudeKey = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz1234567890_ABC"
        let msg2 = "Configured ANTHROPIC_API_KEY=\(claudeKey)"
        let s2 = SecretMasker.sanitizeLogMessage(msg2)
        XCTAssertFalse(s2.contains(claudeKey))
        XCTAssertTrue(s2.contains("sk-••••••••ABC"))

        // Google Gemini Key format
        let geminiKey = "AIzaTest" + "_EXAMPLE_1234567890abcdefghijkl"
        let msg3 = "Gemini initialized with key \(geminiKey)"
        let s3 = SecretMasker.sanitizeLogMessage(msg3)
        XCTAssertFalse(s3.contains(geminiKey))
        XCTAssertTrue(s3.contains("AIz••••••••jkl"))

        // GitHub token format
        let githubToken = "ghp_" + "1234567890abcdefghijklmnopqrstuvwx"
        let msg4 = "GitHub sync with \(githubToken)"
        let s4 = SecretMasker.sanitizeLogMessage(msg4)
        XCTAssertFalse(s4.contains(githubToken))
        XCTAssertTrue(s4.contains("ghp••••••••vwx"))
    }

    func testSecretMaskingKeyValuePairs() {
        // password
        let pwdVal = "superSecret" + "Password123"
        let pwdMsg = "Connecting db with password='\(pwdVal)' at host"
        let sPwd = SecretMasker.sanitizeLogMessage(pwdMsg)
        XCTAssertFalse(sPwd.contains(pwdVal))
        XCTAssertTrue(sPwd.contains("sup••••••••123"))

        // token (clean key: token)
        let tokVal = "session_token" + "_xyz_99887766"
        let tokenMsg = "broker config: token=\"\(tokVal)\""
        let sToken = SecretMasker.sanitizeLogMessage(tokenMsg)
        XCTAssertFalse(sToken.contains(tokVal))
        XCTAssertTrue(sToken.contains("ses••••••••766"))

        // secret
        let secVal = "veryConfidential" + "ClientSecretVal"
        let secMsg = "api config: secret = '\(secVal)'"
        let sSec = SecretMasker.sanitizeLogMessage(secMsg)
        XCTAssertFalse(sSec.contains(secVal))
        XCTAssertTrue(sSec.contains("ver••••••••Val"))
    }

    func testSecretStringGuaranteesNoPlaintextInDescriptions() {
        let confidential = "sk-ant-" + "api03-veryConfidentialValue99887766"
        let secretObj = SecretString(confidential)

        // String interpolation and description must NEVER contain the raw token
        let descriptionStr = "\(secretObj)"
        XCTAssertFalse(descriptionStr.contains("veryConfidentialValue"))
        XCTAssertTrue(descriptionStr.contains("••••••••"))

        let debugStr = String(reflecting: secretObj)
        XCTAssertFalse(debugStr.contains("veryConfidentialValue"))
        XCTAssertTrue(debugStr.contains("••••••••"))

        // Unmasked strictly returns original value
        XCTAssertEqual(secretObj.unmasked, confidential)
    }

    // MARK: - 4. CockpitLogger Zero Leakage Stress Test

    func testCockpitLoggerStressSanitization() {
        let logger = CockpitLogger.shared
        let dummyOpenAI = "sk-test-" + "1234567890abcdef12345678"
        let dummyIBAN = "DE89" + "370400440532013000"
        let dummyPwd = "admin" + "MasterPassword123"
        let dummyBearer = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0"

        let rawSensitiveMessage = """
        CRITICAL ERROR: Failed to authorize user with token: '\(dummyOpenAI)' \
        for IBAN \(dummyIBAN) using password='\(dummyPwd)' \
        and Bearer \(dummyBearer)
        """

        let sanitized = SecretMasker.sanitizeLogMessage(rawSensitiveMessage)

        // Assert all 4 secrets are masked
        XCTAssertFalse(sanitized.contains(dummyOpenAI))
        XCTAssertFalse(sanitized.contains(dummyIBAN))
        XCTAssertFalse(sanitized.contains(dummyPwd))
        XCTAssertFalse(sanitized.contains(dummyBearer))

        // Execute all logger levels with sanitized pipeline
        logger.info(rawSensitiveMessage)
        logger.debug(rawSensitiveMessage)
        logger.warning(rawSensitiveMessage)
        logger.error(rawSensitiveMessage)
    }

    // MARK: - 5. Phase 1 Empirical Adversarial Tests (H1, H2, H3)

    func testCLIProcessRunnerStdinStreamingAndPiping() async throws {
        // Test piping stdin through POSIX /bin/cat
        let runner = CLIProcessRunner(executablePath: "/bin/cat", workingDirectory: "/tmp", defaultTimeout: 10.0)

        // 1. Unicode & Turkish characters in stdin
        let turkishInput = "Çalışma, Gelişme, Şifreleme, Örnekleme, İnovasyon — 2026 🚀"
        let result1 = try await runner.runCommand(arguments: [], stdin: turkishInput)
        XCTAssertTrue(result1.isSuccess)
        XCTAssertEqual(result1.exitCode, 0)
        XCTAssertEqual(result1.stdout, turkishInput)

        // 2. Multiline JSON configuration payload piping
        let jsonPayload = """
        {
          "cekirdek_isin": "IE00B3YLTY66",
          "hedef_agirliklar": {
            "IE00B3YLTY66": 0.60,
            "IE00BKM4GZ66": 0.40
          }
        }
        """
        let result2 = try await runner.runCommand(arguments: [], stdin: jsonPayload)
        XCTAssertTrue(result2.isSuccess)
        XCTAssertEqual(result2.stdout, jsonPayload)

        // 3. Empty stdin string
        let result3 = try await runner.runCommand(arguments: [], stdin: "")
        XCTAssertTrue(result3.isSuccess)
        XCTAssertEqual(result3.stdout, "")
    }

    @MainActor
    func testThesisManagementViewModelPhase1AdversarialStress() async {
        let mockDb = MockDatabaseService()
        let mockCli = MockCLIProcessRunner()
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCli)

        // 1. Initial State must be strictly blank (R3.3)
        XCTAssertEqual(vm.newTitle, "")
        XCTAssertEqual(vm.newIsin, "")
        XCTAssertEqual(vm.newSummary, "")
        XCTAssertEqual(vm.newRationale, "")
        XCTAssertEqual(vm.newEvidencePillarsText, "")
        XCTAssertEqual(vm.newCounterArguments, "")
        XCTAssertEqual(vm.newFalsificationTriggersText, "")
        XCTAssertEqual(vm.newBenchmark, "")
        XCTAssertEqual(vm.newTargetAllocationPct, "")
        XCTAssertEqual(vm.newReviewDate, "")

        // 2. Whitespace-only title must be rejected (< 3 chars after trimming)
        vm.newTitle = "   "
        vm.newIsin = "IE00B3YLTY66"
        vm.newSummary = "Geçerli bir özet metni en az on karakter."
        vm.newRationale = "Geçerli bir ekonomik gerekçe metni en az on karakter."
        vm.newFalsificationTriggersText = "Tetikleyici 1: Koşul A\nTetikleyici 2: Koşul B"
        var val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("at least 3 characters") ?? false)

        // 3. Lowercase valid ISIN should be normalized and accepted
        vm.newTitle = "Global Genişleme Tezi"
        vm.newIsin = "ie00b3ylty66"
        val = vm.validateNewThesis()
        XCTAssertTrue(val.isValid)
        XCTAssertNil(val.error)

        // 4. Invalid Luhn check digit rejected
        vm.newIsin = "IE00B3YLTY65"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("Luhn") ?? false)

        // 5. Triggers: empty lines filtered out, strictly enforcing count >= 2
        vm.newIsin = "IE00B3YLTY66"
        vm.newFalsificationTriggersText = "   \nTek Tetikleyici\n   \n"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("at least 2 falsification triggers") ?? false)

        // 6. Triggers: exactly 2 distinct triggers -> valid
        vm.newFalsificationTriggersText = "Tetikleyici 1: TER artışı > 0.25%\nTetikleyici 2: Takip hatası > 0.50%"
        val = vm.validateNewThesis()
        XCTAssertTrue(val.isValid)

        // 7. Allocation %: negative rejected, >100 rejected, valid normalized
        vm.newTargetAllocationPct = "-10"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)

        vm.newTargetAllocationPct = "105"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)

        vm.newTargetAllocationPct = "40%"
        val = vm.validateNewThesis()
        XCTAssertTrue(val.isValid)

        // 8. Review Date: non-ISO format rejected, ISO valid
        vm.newReviewDate = "31-12-2026"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("YYYY-MM-DD") ?? false)

        vm.newReviewDate = "2026-12-31"
        val = vm.validateNewThesis()
        XCTAssertTrue(val.isValid)

        // 9. CLI Argument Generation Stress
        vm.newCategory = "THEMATIC"
        vm.newHorizon = "MEDIUM_TERM"
        vm.newEvidencePillarsText = "Pillar 1\nPillar 2"
        vm.newCounterArguments = "Risk faktörü"
        vm.newTargetAllocationPct = "40"

        await vm.triggerCreateThesis()
        XCTAssertEqual(mockCli.commandExecutionCount, 1)
        let args = mockCli.lastExecutedArguments
        XCTAssertEqual(args.prefix(2), ["tez", "ekle"])
        XCTAssertTrue(args.contains("--isin"))
        XCTAssertTrue(args.contains("IE00B3YLTY66"))
        XCTAssertTrue(args.contains("--kategori"))
        XCTAssertTrue(args.contains("THEMATIC"))
        XCTAssertTrue(args.contains("--vade"))
        XCTAssertTrue(args.contains("MEDIUM_TERM"))
        XCTAssertTrue(args.contains("--hedef-agirlik"))
        if let idx = args.firstIndex(of: "--hedef-agirlik") {
            XCTAssertEqual(args[idx + 1], "0.40")
        }
        XCTAssertTrue(args.contains("--sonraki-kontrol"))
        XCTAssertTrue(args.contains("2026-12-31"))
    }

    // MARK: - 6. Phase 1 Empirical Adversarial Tests - Instance 1: TargetBasket & ISINValidator

    @MainActor
    func testTargetBasketOverlapViewModelEmptyAndMalformedConfig() {
        let mockDb = MockDatabaseService()
        let mockCli = MockCLIProcessRunner()

        // 1. Non-existent file
        let nonExistentURL = URL(fileURLWithPath: "/tmp/non_existent_config_\(UUID().uuidString).json")
        let vmMissing = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: nonExistentURL)
        vmMissing.loadTargetWeightsFromConfig()
        XCTAssertTrue(vmMissing.targetWeights.isEmpty)
        XCTAssertFalse(vmMissing.hasTargetWeights)

        // 2. Empty JSON object
        let tempDir = FileManager.default.temporaryDirectory
        let emptyConfigURL = tempDir.appendingPathComponent("empty_config_\(UUID().uuidString).json")
        try? "{}".data(using: .utf8)?.write(to: emptyConfigURL)
        defer { try? FileManager.default.removeItem(at: emptyConfigURL) }

        let vmEmpty = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: emptyConfigURL)
        vmEmpty.loadTargetWeightsFromConfig()
        XCTAssertTrue(vmEmpty.targetWeights.isEmpty)
        XCTAssertFalse(vmEmpty.hasTargetWeights)

        // 3. Malformed JSON
        let malformedURL = tempDir.appendingPathComponent("malformed_\(UUID().uuidString).json")
        try? "{ invalid json: true".data(using: .utf8)?.write(to: malformedURL)
        defer { try? FileManager.default.removeItem(at: malformedURL) }

        let vmMalformed = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: malformedURL)
        vmMalformed.loadTargetWeightsFromConfig()
        XCTAssertTrue(vmMalformed.targetWeights.isEmpty)
        XCTAssertFalse(vmMalformed.hasTargetWeights)

        // 4. Non-dictionary JSON root (array)
        let arrayURL = tempDir.appendingPathComponent("array_\(UUID().uuidString).json")
        try? "[1, 2, 3]".data(using: .utf8)?.write(to: arrayURL)
        defer { try? FileManager.default.removeItem(at: arrayURL) }

        let vmArray = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: arrayURL)
        vmArray.loadTargetWeightsFromConfig()
        XCTAssertTrue(vmArray.targetWeights.isEmpty)
        XCTAssertFalse(vmArray.hasTargetWeights)
    }

    @MainActor
    func testTargetBasketOverlapViewModelDecimalVsPercentNormalization() {
        let mockDb = MockDatabaseService()
        let mockCli = MockCLIProcessRunner()
        let tempDir = FileManager.default.temporaryDirectory

        // 1. Decimal format (0.45, 0.20, 0.20, 0.15)
        let decimalConfigURL = tempDir.appendingPathComponent("decimal_\(UUID().uuidString).json")
        let decimalJSON = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 0.45,
                "IE00BKM4GZ66": 0.20,
                "IE00BP3QZ825": 0.20,
                "IE00BP3QZB59": 0.15
            },
            "araclar": {
                "IE00B3YLTY66": {"rol": "Core"},
                "IE00BKM4GZ66": {"rol": "EM"},
                "IE00BP3QZ825": {"rol": "Momentum"},
                "IE00BP3QZB59": {"rol": "Value"}
            }
        }
        """
        try? decimalJSON.data(using: .utf8)?.write(to: decimalConfigURL)
        defer { try? FileManager.default.removeItem(at: decimalConfigURL) }

        let vmDecimal = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: decimalConfigURL)
        vmDecimal.loadTargetWeightsFromConfig()

        XCTAssertEqual(vmDecimal.targetWeights.count, 4)
        let core = vmDecimal.targetWeights.first { $0.isin == "IE00B3YLTY66" }
        XCTAssertEqual(core?.targetWeight, 45.0)

        // 2. Percent format (> 1.0, e.g. 60.0, 40.0)
        let percentConfigURL = tempDir.appendingPathComponent("percent_\(UUID().uuidString).json")
        let percentJSON = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 60.0,
                "IE00BKM4GZ66": 40.0
            }
        }
        """
        try? percentJSON.data(using: .utf8)?.write(to: percentConfigURL)
        defer { try? FileManager.default.removeItem(at: percentConfigURL) }

        let vmPercent = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: percentConfigURL)
        vmPercent.loadTargetWeightsFromConfig()
        let corePct = vmPercent.targetWeights.first { $0.isin == "IE00B3YLTY66" }
        XCTAssertEqual(corePct?.targetWeight, 60.0)

        // 3. Single 100% asset represented as 1.0
        let single100ConfigURL = tempDir.appendingPathComponent("single100_\(UUID().uuidString).json")
        let single100JSON = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 1.0
            }
        }
        """
        try? single100JSON.data(using: .utf8)?.write(to: single100ConfigURL)
        defer { try? FileManager.default.removeItem(at: single100ConfigURL) }

        let vmSingle100 = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: single100ConfigURL)
        vmSingle100.loadTargetWeightsFromConfig()
        let singleCore = vmSingle100.targetWeights.first { $0.isin == "IE00B3YLTY66" }
        XCTAssertEqual(singleCore?.targetWeight, 100.0)

        // 4. String format numbers in JSON
        let strConfigURL = tempDir.appendingPathComponent("str_\(UUID().uuidString).json")
        let strJSON = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": "0.35",
                "IE00BKM4GZ66": "65.0"
            }
        }
        """
        try? strJSON.data(using: .utf8)?.write(to: strConfigURL)
        defer { try? FileManager.default.removeItem(at: strConfigURL) }

        let vmStr = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli, configURL: strConfigURL)
        vmStr.loadTargetWeightsFromConfig()
        let strDec = vmStr.targetWeights.first { $0.isin == "IE00B3YLTY66" }
        let strPct = vmStr.targetWeights.first { $0.isin == "IE00BKM4GZ66" }
        XCTAssertEqual(strDec?.targetWeight, 35.0)
        XCTAssertEqual(strPct?.targetWeight, 65.0)
    }

    @MainActor
    func testTargetBasketOverlapViewModelEmptyHoldingsGuard() async {
        let mockDb = MockDatabaseService()
        let mockCli = MockCLIProcessRunner()

        // Empty holdingsSets
        mockDb.mockHoldingsSets = []
        mockDb.mockHoldingsOverlap = HoldingsOverlapData(sets: [], overlapMatrix: [:], topConsolidatedHoldings: [])

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCli)
        await vm.loadData()

        XCTAssertFalse(vm.ucitsStatus.isEvaluated)
        XCTAssertFalse(vm.ucitsStatus.isCompliant)
        XCTAssertEqual(vm.ucitsStatus.violations.count, 0)
        XCTAssertEqual(vm.ucitsStatus.maxSingleWeightPct, 0)

        // Attempting rebalance plan without targets produces immediate validation error without calling CLI
        await vm.triggerRebalancePlan()
        XCTAssertEqual(mockCli.commandExecutionCount, 0)
        XCTAssertTrue(vm.errorMessage?.contains("No target weights defined") ?? false)
    }

    func testISINValidatorExhaustiveAdversarial() {
        let knownISINs = [
            "US0378331005", // Apple
            "US5949181045", // Microsoft
            "US88160R1014", // Tesla
            "IE00B3YLTY66", // SPDR ACWI IMI
            "IE00BKM4GZ66", // Emerging Markets IMI
            "IE00B4L5Y983", // iShares Core MSCI World
            "DE000BAY0017", // Bayer AG
            "DE0007164600", // SAP SE
            "FR0000120271", // TotalEnergies
            "GB0002374006", // Diageo
            "NL0010273215", // ASML
            "CH0012005267", // Novartis
            "JP3435000009", // Sony
            "AU000000BHP4", // BHP Group
            "CA0679011084"  // Barrick Gold
        ]

        // 1. All valid ISINs pass
        for isin in knownISINs {
            XCTAssertTrue(ISINValidator.isValid(isin), "Valid ISIN should pass: \(isin)")
        }

        // 2. Lowercase normalization check (case-insensitive)
        for isin in knownISINs {
            XCTAssertTrue(ISINValidator.isValid(isin.lowercased()), "Lowercase ISIN should pass: \(isin)")
        }

        // 3. Whitespace trimming
        for isin in knownISINs {
            let padded = "  \(isin) \n\t"
            XCTAssertTrue(ISINValidator.isValid(padded), "Padded ISIN should pass: \(padded)")
        }

        // 4. Invalid Check Digit rejection (100% of mutated check digits must fail)
        for isin in knownISINs {
            let prefix11 = String(isin.prefix(11))
            let actualDigit = Int(String(isin.last!))!
            for otherDigit in 0...9 where otherDigit != actualDigit {
                let mutated = prefix11 + "\(otherDigit)"
                XCTAssertFalse(ISINValidator.isValid(mutated), "Mutated check digit must fail: \(mutated)")
            }
        }

        // 5. Invalid Country Codes (numbers or symbols in first 2 positions)
        XCTAssertFalse(ISINValidator.isValid("120378331005"))
        XCTAssertFalse(ISINValidator.isValid("1E00B3YLTY66"))
        XCTAssertFalse(ISINValidator.isValid("E100B3YLTY66"))
        XCTAssertFalse(ISINValidator.isValid("U_0378331005"))

        // 6. Invalid Lengths
        XCTAssertFalse(ISINValidator.isValid(""))
        XCTAssertFalse(ISINValidator.isValid("US037833100"))   // 11 chars
        XCTAssertFalse(ISINValidator.isValid("US03783310055")) // 13 chars
        XCTAssertFalse(ISINValidator.isValid("A"))

        // 7. Special Characters & Non-Alphanumeric
        XCTAssertFalse(ISINValidator.isValid("US037833100@"))
        XCTAssertFalse(ISINValidator.isValid("IE00-3YLTY66"))
        XCTAssertFalse(ISINValidator.isValid("DE 00BAY0017"))
    }
}
