import XCTest
@testable import FinanceCockpit

@MainActor
final class TransactionLedgerViewModelTests: XCTestCase {

    let liveDbPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path

    func testTransactionLedgerViewModel_LoadsFull614Transactions_FromLiveDb() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let cliRunner = MockCLIProcessRunner()
        let viewModel = TransactionLedgerViewModel(databaseService: dbService, cliRunner: cliRunner)
        let expectedCount = try await dbService.fetchTransactionCount()

        await viewModel.loadData()

        XCTAssertNil(viewModel.errorMessage, "Loading data should succeed without error: \(viewModel.errorMessage ?? "")")
        XCTAssertGreaterThanOrEqual(expectedCount, 614)
        XCTAssertEqual(viewModel.totalTransactionsCount, expectedCount, "ViewModel must reflect the complete transaction count")
        XCTAssertEqual(viewModel.transactions.count, expectedCount, "ViewModel transactions collection must contain all items")
        XCTAssertEqual(viewModel.filteredTransactions.count, expectedCount, "Default filter (all) must list all items")

        // Check financial totals are calculated from the full dataset
        XCTAssertGreaterThan(viewModel.totalBuyAmountEur, 0, "Total buy amount should be greater than 0")
        XCTAssertNotNil(viewModel.lastRefreshDate)
    }

    func testTransactionLedgerViewModel_FilteringByTypeAndSearch() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let cliRunner = MockCLIProcessRunner()
        let viewModel = TransactionLedgerViewModel(databaseService: dbService, cliRunner: cliRunner)
        let expectedCount = try await dbService.fetchTransactionCount()

        await viewModel.loadData()
        XCTAssertEqual(viewModel.transactions.count, expectedCount)

        // Filter by BUY
        viewModel.selectedTxType = "BUY"
        let buyTxs = viewModel.filteredTransactions
        XCTAssertFalse(buyTxs.isEmpty, "There should be BUY transactions in the history")
        for tx in buyTxs {
            let isBuy = tx.txType.uppercased() == "BUY" || tx.side?.uppercased() == "BUY" || tx.subType?.uppercased() == "BUY"
            XCTAssertTrue(isBuy, "Filtered transaction must be a BUY transaction")
        }


        // Reset and test search filter
        viewModel.selectedTxType = nil
        viewModel.searchText = "IE00B3YLTY66"
        let spdrTxs = viewModel.filteredTransactions
        XCTAssertFalse(spdrTxs.isEmpty, "Should find transactions for SPDR ACWI")
        for tx in spdrTxs {
            let matches = (tx.isin?.contains("IE00B3YLTY66") ?? false) ||
                          (tx.description?.contains("IE00B3YLTY66") ?? false)
            XCTAssertTrue(matches)
        }

        // Search for non-existent item
        viewModel.searchText = "NON_EXISTENT_ISIN_XYZ"
        XCTAssertTrue(viewModel.filteredTransactions.isEmpty, "Non-existent search should yield empty results")
    }

    func testTransactionLedgerViewModel_ErrorHandlingGraceful() async {
        let mockDB = MockDatabaseService()
        mockDB.shouldThrowError = true
        let cliRunner = MockCLIProcessRunner()
        let viewModel = TransactionLedgerViewModel(databaseService: mockDB, cliRunner: cliRunner)

        await viewModel.loadData()

        XCTAssertNotNil(viewModel.errorMessage, "Expected error message when database fails")
        XCTAssertFalse(viewModel.isLoading, "Loading state must be reset on failure")
        XCTAssertEqual(viewModel.transactions.count, 0)
    }

    func testTransactionLedgerViewModel_ReconciliationTrigger() async {
        let mockDB = MockDatabaseService()
        let cliRunner = MockCLIProcessRunner()
        cliRunner.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "Mutabakat başarılı",
            stderr: "",
            message: "Mutabakat tamamlandı."
        )

        let viewModel = TransactionLedgerViewModel(databaseService: mockDB, cliRunner: cliRunner)
        await viewModel.triggerReconciliation()


        XCTAssertEqual(cliRunner.commandExecutionCount, 1)
        XCTAssertEqual(viewModel.statusMessage, "Reconciliation completed.")
        XCTAssertNil(viewModel.errorMessage)
    }
}
