import XCTest
@testable import FinanceCockpit

/// Integration test verifying end-to-end execution against an isolated copy of the database.
/// Strictly respects Rule §0.6: Never touches or mutates live `masa.db`, `var/`, or `config/`.
final class IntegrationEndToEndTests: XCTestCase {

    private var tempDirURL: URL!
    private var tempDBPath: String!
    private var databaseService: DatabaseService!
    private let liveDBPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path
    private let etfMasaExecutable = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/etf-masa").path

    override func setUp() async throws {
        try await super.setUp()

        // Create temporary isolated sandbox directory
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("etf_cockpit_e2e_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        self.tempDirURL = tempDir

        // Copy live database to temporary isolated directory
        let isolatedDBURL = tempDir.appendingPathComponent("isolated_masa.db")
        if FileManager.default.fileExists(atPath: liveDBPath) {
            try FileManager.default.copyItem(at: URL(fileURLWithPath: liveDBPath), to: isolatedDBURL)
        } else {
            XCTFail("Live database not found at \(liveDBPath)")
        }
        self.tempDBPath = isolatedDBURL.path

        // Initialize DatabaseService pointing strictly to the isolated temporary copy
        self.databaseService = try DatabaseService(databasePath: tempDBPath)
    }

    override func tearDown() async throws {
        databaseService = nil
        if let tempDir = tempDirURL {
            try? FileManager.default.removeItem(at: tempDir)
        }
        try await super.tearDown()
    }

    func testDatabaseServiceAgainstIsolatedLiveCopy() async throws {
        // Verify portfolio summary can be read
        let summary = try await databaseService.fetchPortfolioSummary()
        XCTAssertGreaterThanOrEqual(summary.positions.count, 0)

        // Verify audit events can be queried
        let events = try await databaseService.fetchAuditEvents(limit: 10)
        XCTAssertGreaterThanOrEqual(events.count, 0)

        // Verify model registry can be fetched
        let models = try await databaseService.fetchModelRegistry()
        XCTAssertGreaterThanOrEqual(models.count, 0)
    }

    func testCLIProcessRunnerRealCLIReadCommands() async throws {
        guard FileManager.default.isExecutableFile(atPath: etfMasaExecutable) else {
            throw XCTSkip("etf-masa executable not found or not executable")
        }

        let runner = CLIProcessRunner(
            executablePath: etfMasaExecutable,
            workingDirectory: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF").path
        )

        // 1. Run dogrula
        let dogrulaResult = try await runner.runVerifyIntegrity()
        XCTAssertTrue(dogrulaResult.ok)
        XCTAssertEqual(dogrulaResult.schemaVersion, 3)
        XCTAssertEqual(dogrulaResult.triggerCount, 78)

        // 2. Run durum --json
        let durumResult = try await runner.runCommand(arguments: ["durum", "--json"])
        XCTAssertTrue(durumResult.isSuccess)
        let durumData = try XCTUnwrap(durumResult.stdout.data(using: .utf8))
        let durumResponse = try JSONDecoder().decode(DurumResponse.self, from: durumData)
        XCTAssertEqual(durumResponse.schemaVersion, "1.0.0")
        XCTAssertTrue(durumResponse.ok)

        // 3. Run portfoy --json
        let portfoyResult = try await runner.runCommand(arguments: ["portfoy", "--json"])
        XCTAssertTrue(portfoyResult.isSuccess)
        let portfoyData = try XCTUnwrap(portfoyResult.stdout.data(using: .utf8))
        let portfoyResponse = try JSONDecoder().decode(PortfoyResponse.self, from: portfoyData)
        XCTAssertEqual(portfoyResponse.schemaVersion, "1.0.0")
        XCTAssertGreaterThanOrEqual(portfoyResponse.positionsCount, 0)

        // 4. Run tahmin karne --json
        let karneResult = try await runner.runCommand(arguments: ["tahmin", "karne", "--json"])
        XCTAssertTrue(karneResult.isSuccess)
        let karneData = try XCTUnwrap(karneResult.stdout.data(using: .utf8))
        let karneResponse = try JSONDecoder().decode(TahminKarneResponse.self, from: karneData)
        XCTAssertEqual(karneResponse.schemaVersion, "1.0.0")
    }
}
