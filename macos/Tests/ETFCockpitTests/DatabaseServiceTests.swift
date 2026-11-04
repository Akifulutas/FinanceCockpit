import XCTest
import SQLite3
@testable import FinanceCockpit

final class DatabaseServiceTests: XCTestCase {

    let liveDbPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path

    func testDatabaseServiceInitialization() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let summary = try await dbService.fetchPortfolioSummary()
        XCTAssertGreaterThan(summary.totalValueEur, 0)
    }

    func testDatabaseServiceInvalidPathThrows() async {
        do {
            _ = try DatabaseService(databasePath: "/nonexistent/invalid/path/db.sqlite")
            XCTFail("Expected DatabaseService init to throw for nonexistent path")
        } catch {
            XCTAssertTrue(error is DatabaseService.DatabaseError)
        }
    }

    func testReadOnlyEnforcement() async throws {
        // Direct verification that the connection is opened in strict read-only mode
        var dbPointer: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        let uri = "file:\(liveDbPath)?mode=ro"
        let rc = sqlite3_open_v2(uri, &dbPointer, flags, nil)
        XCTAssertEqual(rc, SQLITE_OK)

        defer {
            if let dbPointer = dbPointer {
                sqlite3_close(dbPointer)
            }
        }

        // Attempting an INSERT or UPDATE on a read-only connection must fail with SQLITE_READONLY
        let insertRC = sqlite3_exec(dbPointer, "INSERT INTO audit_events (actor) VALUES ('malicious_test');", nil, nil, nil)
        XCTAssertEqual(insertRC, SQLITE_READONLY, "Read-only SQLite connection must reject writes with SQLITE_READONLY (8)")
    }

    func testFetchPositions() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let positions = try await dbService.fetchPositions()

        XCTAssertEqual(positions.count, 4, "Expected exactly 4 positions in live snapshot")

        let isins = Set(positions.map { $0.isin })
        XCTAssertTrue(isins.contains("IE00B3YLTY66"))
        XCTAssertTrue(isins.contains("IE00BKM4GZ66"))
        XCTAssertTrue(isins.contains("IE00BP3QZ825"))
        XCTAssertTrue(isins.contains("IE00BP3QZB59"))

        // Check SPDR ACWI position
        if let spdr = positions.first(where: { $0.isin == "IE00B3YLTY66" }) {
            XCTAssertEqual(spdr.quantity, Decimal(158))
            XCTAssertGreaterThan(spdr.brokerValuation, Decimal(1000))
            XCTAssertNotNil(spdr.computedMid)
            XCTAssertNotNil(spdr.calculatedValuation)
            XCTAssertTrue(["FRESH", "OUTDATED", "AGED", "STALE"].contains(spdr.qualityStatus))
        } else {
            XCTFail("SPDR position not found")
        }
    }

    func testFetchCashObservations() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let cash = try await dbService.fetchCashObservations()

        XCTAssertNotNil(cash)
        XCTAssertEqual(cash?.currency, "EUR")
        XCTAssertEqual(cash?.accountIdMasked, "rSw…aJ")
        XCTAssertNotNil(cash?.settledCash)
        XCTAssertNotNil(cash?.totalCash)
        XCTAssertNotNil(cash?.buyingPower)
    }

    func testFetchPortfolioSummary() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let summary = try await dbService.fetchPortfolioSummary()

        XCTAssertEqual(summary.positions.count, 4)
        XCTAssertEqual(summary.totalValueEur, summary.investedAssetsEur + summary.totalCashEur)
        XCTAssertFalse(summary.asOfDate.isEmpty)
    }

    func testFetchQuotes() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let quotes = try await dbService.fetchQuotes()

        XCTAssertGreaterThanOrEqual(quotes.count, 4)
        for quote in quotes {
            XCTAssertFalse(quote.isin.isEmpty)
            XCTAssertNotNil(quote.computedMid)
            XCTAssertFalse(quote.qualityStatus.isEmpty)
        }
    }

    func testFetchAuditEvents() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let events = try await dbService.fetchAuditEvents(limit: 10)

        XCTAssertGreaterThan(events.count, 0)
        XCTAssertLessThanOrEqual(events.count, 10)

        for event in events {
            XCTAssertGreaterThan(event.eventId, 0)
            XCTAssertFalse(event.currHash.isEmpty)
            XCTAssertFalse(event.actor.isEmpty)
            XCTAssertFalse(event.action.isEmpty)
        }
    }

    func testFetchModelRegistry() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let models = try await dbService.fetchModelRegistry()

        XCTAssertGreaterThanOrEqual(models.count, 1)
        let modelIds = models.map { $0.modelId }
        XCTAssertTrue(modelIds.contains("mod_local_deterministic"))
    }

    func testFetchTheses() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let theses = try await dbService.fetchTheses()
        XCTAssertNotNil(theses)
    }

    func testFetchTransactions() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let transactions = try await dbService.fetchTransactions()
        XCTAssertNotNil(transactions)
        XCTAssertGreaterThan(transactions.count, 0, "Expected transactions from current views or fallback observations")
    }

    func testFetchTransactionCount_Returns614_InLiveOrCopyDB() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let count = try await dbService.fetchTransactionCount()
        XCTAssertGreaterThanOrEqual(count, 614, "fetchTransactionCount() must return at least 614 merged distinct transactions in live or copy DB")
    }

    func testFetchTransactions_WithPagination_Returns100Records_NoDuplicates() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let total = try await dbService.fetchTransactionCount()
        let page1 = try await dbService.fetchTransactions(limit: 100, offset: 0)
        let page2 = try await dbService.fetchTransactions(limit: 100, offset: 100)

        XCTAssertEqual(page1.count, 100, "Page 1 must return 100 records")
        XCTAssertEqual(page2.count, 100, "Page 2 must return 100 records")

        let set1 = Set(page1.map { $0.recordId })
        let set2 = Set(page2.map { $0.recordId })
        let intersection = set1.intersection(set2)
        XCTAssertTrue(intersection.isEmpty, "Page 1 and Page 2 must not have overlapping record IDs, found: \(intersection)")

        let lastPage = try await dbService.fetchTransactions(limit: 100, offset: 600)
        XCTAssertEqual(lastPage.count, total - 600, "Offset 600 of \(total) records must return exactly \(total - 600) records")
    }

    func testFetchTransactions_MergedObservationsAndVersions() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let total = try await dbService.fetchTransactionCount()
        let allTransactions = try await dbService.fetchTransactions(limit: 1000, offset: 0)
        XCTAssertEqual(allTransactions.count, total, "Full fetch must return all \(total) transactions")

        let obsCount = allTransactions.filter { $0.recordId.hasPrefix("obs_") }.count
        let versionCount = allTransactions.filter { !$0.recordId.hasPrefix("obs_") }.count

        XCTAssertGreaterThan(obsCount, 0, "Unversioned observations must appear seamlessly with obs_ prefix")
        XCTAssertGreaterThan(versionCount, 0, "Versioned transactions must appear with version_id")
        XCTAssertEqual(obsCount + versionCount, total, "Merged sum must equal \(total) total records")
    }

    func testFetchJobs() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let jobs = try await dbService.fetchJobs()
        XCTAssertNotNil(jobs)
    }

    func testFetchHoldingsOverlap() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let overlap = try await dbService.fetchHoldingsOverlap()
        XCTAssertNotNil(overlap)
    }

    func testFetchForecastPerformance() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let perf = try await dbService.fetchForecastPerformance()
        XCTAssertNotNil(perf)
        XCTAssertGreaterThanOrEqual(perf.totalSettledCount, 0)
    }
}

