import XCTest
@testable import FinanceCockpit

@MainActor
final class LoginURLEdgeCaseAdversarialTests: XCTestCase {

    private var mockDB: MockDatabaseService!

    override func setUp() async throws {
        try await super.setUp()
        mockDB = MockDatabaseService()
    }

    override func tearDown() async throws {
        mockDB = nil
        try await super.tearDown()
    }

    // MARK: - 1. URL-Encoded Query String Variations

    func testQueryString_URLEncodedAmpersand_AcceptedAndPreserved() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Lütfen adrese gidin: https://secure.scalable.capital/activate?code=foo%26bar\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=foo%26bar")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate?code=foo%26bar")
        XCTAssertNil(vm.loginPromptMessage?.range(of: "Unexpected link"))
    }

    func testQueryString_MultipleEncodedParameters_AcceptedAndPreserved() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Adres: https://secure.scalable.capital/activate?code=test%20code&action=verify%2Bconfirm\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=test%20code&action=verify%2Bconfirm")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate?code=test%20code&action=verify%2Bconfirm")
    }

    func testQueryString_EncodedTraversalInsideQueryValue_AcceptedBecausePathIsClean() async {
        let runner = ChunkStreamingMockRunner()
        // Encoded dot-dot in query parameter value, but path itself is clean /activate
        runner.chunksToYield = [
            .stdout("Adres: https://secure.scalable.capital/activate?return_path=%2e%2e%2fhome\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?return_path=%2e%2e%2fhome")
    }

    // MARK: - 2. Empty Query Variations

    func testEmptyQuery_NoQueryString_Accepted() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Giriş bağlantısı: https://secure.scalable.capital/activate\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate")
        XCTAssertNil(vm.loginPromptMessage?.range(of: "Unexpected link"))
    }

    func testEmptyQuery_TrailingQuestionMark_Accepted() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Giriş bağlantısı: https://secure.scalable.capital/activate?\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate?")
    }

    func testEmptyQuery_EmptyParameterValue_Accepted() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("Giriş bağlantısı: https://secure.scalable.capital/activate?code=\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=")
    }

    // MARK: - 3. Multiple Sequential Logins & State Isolation

    func testMultipleSequentialLogins_FirstBlocked_SecondSucceeds() async {
        let runner = ChunkStreamingMockRunner()
        // Attempt 1: Malicious URL
        runner.chunksToYield = [
            .stdout("https://evil.com/activate?code=sample_code_1\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)

        // Attempt 2: Valid Scalable URL
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?code=sample_code_recovery\n")
        ]

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=sample_code_recovery")
        XCTAssertEqual(vm.activationURL, "https://secure.scalable.capital/activate?code=sample_code_recovery")
    }

    func testMultipleSequentialLogins_ConsecutiveSuccessfulLoginsUpdateState() async {
        let runner = ChunkStreamingMockRunner()
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        // Attempt 1
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?code=sample_code_alpha\n")
        ]
        await vm.runLoginStream()
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=sample_code_alpha")

        // Attempt 2
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?code=sample_code_beta\n")
        ]
        await vm.runLoginStream()
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=sample_code_beta")
    }

    func testMultipleSequentialLogins_SuccessFollowedByBlockedUrl_ResetsState() async {
        let runner = ChunkStreamingMockRunner()
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        // Attempt 1: Success
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate?code=sample_code_valid\n")
        ]
        await vm.runLoginStream()
        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate?code=sample_code_valid")

        // Attempt 2: Malicious URL
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate/../api/v1/steal\n")
        ]
        await vm.runLoginStream()
        XCTAssertNil(vm.loginAuthURL)
        XCTAssertNil(vm.activationURL)
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    // MARK: - 4. Additional Adversarial Encodings & Boundaries

    func testPathTraversal_UppercaseURLEncodedDots_ShouldBeBlocked() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate/%2E%2E/api/v1/steal\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertNil(vm.loginAuthURL, "Uppercase URL-encoded dot-dot path traversal (%2E%2E) escaping /activate must be blocked")
        XCTAssertTrue(vm.loginPromptMessage?.contains("Unexpected link") == true)
    }

    func testPath_ValidSubpathWithTrailingSlash_Accepted() async {
        let runner = ChunkStreamingMockRunner()
        runner.chunksToYield = [
            .stdout("https://secure.scalable.capital/activate/\n")
        ]
        let vm = TodayDashboardViewModel(databaseService: mockDB, cliRunner: runner)

        await vm.runLoginStream()

        XCTAssertEqual(vm.loginAuthURL, "https://secure.scalable.capital/activate/")
    }
}
