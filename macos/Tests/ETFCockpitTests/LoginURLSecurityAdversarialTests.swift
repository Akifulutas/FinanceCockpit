import XCTest
@testable import FinanceCockpit

@MainActor
final class LoginURLSecurityAdversarialTests: XCTestCase {

    private var mockDB: MockDatabaseService!

    override func setUp() async throws {
        try await super.setUp()
        mockDB = MockDatabaseService()
    }

    override func tearDown() async throws {
        mockDB = nil
        try await super.tearDown()
    }

    // MARK: - 1. URL Spoofing & Injection Tests

    func testSubdomainSpoofing_EvilDomainSuffix_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Lütfen adrese gidin: https://secure.scalable.capital.evil.com/activate?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Subdomain spoofing evil.com must be blocked")
        XCTAssertNil(vm.activationURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
        XCTAssertFalse(vm.isSessionActive ?? true)
    }

    func testSubdomainSpoofing_PrefixEvilDomain_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://evil-secure.scalable.capital/activate?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Prefix evil domain must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testUserinfoUserInfoSpoofing_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital@attacker.com/activate?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "UserInfo auth spoofing attacker.com must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testSchemeDowngrade_Http_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("http://secure.scalable.capital/activate?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Plain http scheme must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testPathTraversal_WrongPath_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/api/v1/steal?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Path /api/v1/steal must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testOpenRedirect_QueryParamTarget_Blocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://evil.com/?target=secure.scalable.capital/activate\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Open redirect query param to evil.com must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testJavascriptScheme_IgnoredAndNotOpened() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("javascript:alert(1)\n"),
            .stdout("javascript://secure.scalable.capital/activate\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "javascript: scheme must never be captured or opened")
    }

    func testInvalidUriCharacters_HandledSafely() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?token=123%00evil\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()
        // If parsed, host/path must strictly match; if invalid, must not crash
        if let captured = vm.loginAuthURL {
            XCTAssertTrue(captured.hasPrefix("https://secure.scalable.capital/activate"))
        }
    }

    // MARK: - 2. Chunk Fragmentation & Buffer Stress Tests

    func testChunkSplitAcrossDomain_ReassembledCorrectly() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://sec"),
            .stdout("ure.scalable.ca"),
            .stdout("pital/activate?token=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?token=123")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate?token=123")
    }

    func testChunkSplitAcrossMultipleComponents_ReassembledCorrectly() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Lütfen tarayıcıda "),
            .stdout("şu linki açın: h"),
            .stdout("ttps://secure."),
            .stdout("scalable.capital"),
            .stdout("/activate?user_code=SPLIT-MULTI-999\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?user_code=SPLIT-MULTI-999")
    }

    func testSingleChunkContainingMultipleLines_MixOfValidAndInvalid() async {
        let runner = ChunkStreamingMockRunner()
        // Line 1 is evil, Line 2 is valid
        runner.chunksToYield = [
            .stdout("Log 1: https://evil.com/steal\nLog 2: https://secure.scalable.capital/activate?user_code=ABCD-1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        print("DEBUG: mixOfValidAndInvalid promptMessage=\(String(describing: vm.loginPromptMessage))")
        print("DEBUG: mixOfValidAndInvalid loginAuthURL=\(String(describing: vm.loginAuthURL))")
        print("DEBUG: mixOfValidAndInvalid isSessionActive=\(String(describing: vm.isSessionActive))")

        // Finding: When Line 1 is evil and Line 2 is valid, Line 2 overwrites loginPromptMessage
        // and sets loginAuthURL, defeating the blockedUrl defense during streaming!
    }

    func testPathTraversal_DotDotPath_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate/../api/v1/steal\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        // Critical Security Check: A path traversal escaping /activate must NOT be accepted as a valid activation URL
        XCTAssertNil(vm.loginAuthURL, "Path traversal escaping /activate via /../ must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testSubpath_ActivateEvilPrefix_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activateevil?code=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        // Path /activateevil is not /activate
        XCTAssertNil(vm.loginAuthURL, "Path /activateevil without slash or exact match must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testSingleChunkContainingMultipleLines_EvilThenValid_WarningMustNotBeOverwritten() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Log 1: https://evil.com/steal\nLog 2: https://secure.scalable.capital/activate?user_code=ABCD-1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        // If an untrusted URL is detected, the warning MUST NOT be overwritten by a subsequent URL!
        // The auth URL must be blocked or reset!
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true, "Security warning must not be overwritten by subsequent valid line")
        XCTAssertNil(vm.loginAuthURL, "Login URL must be invalidated if stream contained untrusted URL")
    }

    func testChunksWithoutTrailingNewlinesFollowedByExitEOF_ShouldBeProcessedAtEOF() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?token=EOF-TEST-123")
            // No trailing newline before stream end
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        // When process exits without trailing newline, buffer should be flushed so URL is captured
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?token=EOF-TEST-123", "Buffer remaining at EOF must be processed and URL captured")
    }

    func testExtremelyLargeChunk_100KBLine_HandledWithoutCrashOrOOM() async {
        let runner = ChunkStreamingMockRunner()
        let largeNoise = String(repeating: "A", count: 100_000)
        runner.chunksToYield = [
            .stdout("NOISE: \(largeNoise)\n"),
            .stdout("https://secure.scalable.capital/activate?testtoken=sample_chunk_123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?testtoken=sample_chunk_123")
    }

    func testDeviceCodeCapture_AcrossChunkBoundaries() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?code=123\n"),
            .stdout("kod: "),
            .stdout("ABCD-"),
            .stdout("WXYZ-1234\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=123")
        XCTAssertEqual(vm.activationCode, "ABCD-WXYZ-1234")
    }

    // MARK: - 3. Additional Boundary & Bypass Tests (Milestone Rem-3 R6 Verification)

    func testPathTraversal_URLEncodedDots_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate/%2e%2e/api/v1/steal\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "URL-encoded dot-dot path traversal (%2e%2e) escaping /activate must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testDoubleSlash_LeadingDoubleSlash_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital//activate?code=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Leading double slash path (//activate) must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testPortManipulation_NonStandardPort_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital:8080/activate?code=123\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Non-standard port (:8080) must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testFragmentInjection_FragmentInActivationURL_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate#bad\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Fragment injection in activation URL must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }
}

