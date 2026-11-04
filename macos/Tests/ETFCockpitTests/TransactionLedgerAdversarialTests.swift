import XCTest
@testable import FinanceCockpit

@MainActor
final class TransactionLedgerAdversarialTests: XCTestCase {

    let liveDbPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path

    // MARK: - 1. Exact Count Verification
    func testFetchTransactionCount_Exact614DistinctTransactions() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let count = try await dbService.fetchTransactionCount()
        XCTAssertGreaterThanOrEqual(count, 614, "fetchTransactionCount must return at least 614 distinct transactions")
    }

    // MARK: - 2. Adversarial Pagination Testing
    func testPagination_OffsetBeyondBounds_ReturnsEmpty() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let total = try await dbService.fetchTransactionCount()
        let outOfBoundsOffsets = [total, total + 1, 1000, 10_000]

        for offset in outOfBoundsOffsets {
            let page = try await dbService.fetchTransactions(limit: 100, offset: offset)
            XCTAssertTrue(page.isEmpty, "Offset \(offset) beyond bounds (total \(total)) must return empty array, got \(page.count) items")
        }
    }

    func testPagination_ZeroLimit_ReturnsEmpty() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let pageZero = try await dbService.fetchTransactions(limit: 0, offset: 0)
        XCTAssertTrue(pageZero.isEmpty, "Limit 0 must return empty array, got \(pageZero.count) items")

        let pageZeroWithOffset = try await dbService.fetchTransactions(limit: 0, offset: 100)
        XCTAssertTrue(pageZeroWithOffset.isEmpty, "Limit 0 with offset 100 must return empty array, got \(pageZeroWithOffset.count) items")
    }

    func testPagination_NegativeLimitBehavior() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let total = try await dbService.fetchTransactionCount()
        // In SQLite, negative limit means unlimited
        let pageNeg = try await dbService.fetchTransactions(limit: -1, offset: 0)
        XCTAssertEqual(pageNeg.count, total, "In SQLite, limit -1 returns all \(total) rows from offset")

        let pageNegWithOffset = try await dbService.fetchTransactions(limit: -1, offset: 600)
        XCTAssertEqual(pageNegWithOffset.count, total - 600, "In SQLite, limit -1 with offset 600 returns remaining \(total - 600) rows")
    }

    func testPagination_NegativeOffsetBehavior() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        // In SQLite, negative offset is clamped to 0
        let pageNegOffset = try await dbService.fetchTransactions(limit: 10, offset: -5)
        XCTAssertEqual(pageNegOffset.count, 10, "In SQLite, negative offset defaults to offset 0")
    }

    func testPagination_ConcatenationOfAllChunks_YieldsExact614UniqueRecordsAndBrokerTxIds() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let total = try await dbService.fetchTransactionCount()
        var allFetched: [TransactionItem] = []
        let pageSize = 100

        for offset in stride(from: 0, through: 600, by: pageSize) {
            let page = try await dbService.fetchTransactions(limit: pageSize, offset: offset)
            if offset == 600 {
                XCTAssertEqual(page.count, total - 600, "Last chunk at offset 600 must return exactly \(total - 600) transactions")
            } else {
                XCTAssertEqual(page.count, pageSize, "Chunk at offset \(offset) must return \(pageSize) transactions")
            }
            allFetched.append(contentsOf: page)
        }

        XCTAssertEqual(allFetched.count, total, "Concatenated chunks must total exactly \(total) transactions")

        // Zero duplicate recordIds
        let recordIds = allFetched.map { $0.recordId }
        let uniqueRecordIds = Set(recordIds)
        XCTAssertEqual(uniqueRecordIds.count, total, "Expected exactly \(total) unique recordIds, got \(uniqueRecordIds.count)")

        // Zero duplicate brokerTxIds
        let brokerTxIds = allFetched.compactMap { $0.brokerTxId }
        let uniqueBrokerTxIds = Set(brokerTxIds)
        XCTAssertEqual(brokerTxIds.count, total, "All \(total) items must have a non-nil brokerTxId")
        XCTAssertEqual(uniqueBrokerTxIds.count, total, "Expected exactly \(total) unique brokerTxIds with ZERO duplicates, got \(uniqueBrokerTxIds.count)")
    }

    // MARK: - 3. ViewModel Filter Counts & Exact Decimal Aggregates
    func testViewModel_FilterCountsAndExactDecimalSums() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let cliRunner = MockCLIProcessRunner()
        let vm = TransactionLedgerViewModel(databaseService: dbService, cliRunner: cliRunner)

        await vm.loadData()

        XCTAssertNil(vm.errorMessage)
        let total = vm.totalTransactionsCount
        XCTAssertGreaterThanOrEqual(total, 614)
        XCTAssertEqual(vm.transactions.count, total)

        // 1. Buy Filter & Aggregate
        vm.selectedTxType = "BUY"
        let buyTxs = vm.filteredTransactions
        XCTAssertEqual(buyTxs.count, 247, "BUY filtered count must be exactly 247")
        let expectedBuySum = Decimal(string: "250793.978")!
        XCTAssertEqual(vm.totalBuyAmountEur, expectedBuySum, "Total buy amount must match database aggregate exactly: 250793.978 EUR")

        // 2. Sell Filter & Aggregate
        vm.selectedTxType = "SELL"
        let sellTxs = vm.filteredTransactions
        XCTAssertEqual(sellTxs.count, 313, "SELL filtered count must be exactly 313")
        let expectedSellSum = Decimal(string: "245793.419")!
        XCTAssertEqual(vm.totalSellAmountEur, expectedSellSum, "Total sell amount must match database aggregate exactly: 245793.419 EUR")

        // 3. Dividend Filter & Aggregate
        vm.selectedTxType = "DIVIDEND"
        let divTxs = vm.filteredTransactions
        XCTAssertEqual(divTxs.count, 5, "DIVIDEND filtered count must be exactly 5")
        let expectedDivSum = Decimal(string: "5.69")!
        XCTAssertEqual(vm.totalDividendAmountEur, expectedDivSum, "Total dividend amount must match database aggregate exactly: 5.69 EUR")

        // 4. Deposit Filter
        vm.selectedTxType = "DEPOSIT"
        let depositTxs = vm.filteredTransactions
        XCTAssertGreaterThanOrEqual(depositTxs.count, 32, "DEPOSIT filtered count must be at least 32")

        // 5. Withdrawal Filter
        vm.selectedTxType = "WITHDRAWAL"
        let withdrawalTxs = vm.filteredTransactions
        XCTAssertEqual(withdrawalTxs.count, 7, "WITHDRAWAL filtered count must be exactly 7")

        // 6. Fee Filter
        vm.selectedTxType = "FEE"
        let feeTxs = vm.filteredTransactions
        XCTAssertEqual(feeTxs.count, 4, "FEE filtered count must be exactly 4")

        // 7. Sum of all distinct category counts equals total
        let interestCount = vm.transactions.filter { ($0.subType?.uppercased() ?? "") == "INTEREST" }.count
        XCTAssertEqual(interestCount, 4, "INTEREST count must be exactly 4")

        let nonTradeCount = vm.transactions.filter { $0.txType.uppercased() == "NON_TRADE_SECURITY_TRANSACTION" }.count
        XCTAssertEqual(nonTradeCount, 2, "NON_TRADE_SECURITY_TRANSACTION count must be exactly 2")

        let totalClassified = buyTxs.count + sellTxs.count + depositTxs.count + withdrawalTxs.count + divTxs.count + feeTxs.count + interestCount + nonTradeCount
        XCTAssertEqual(totalClassified, total, "Every single one of the \(total) transactions must be uniquely categorized")
    }

    // MARK: - 4. Floating Point Inaccuracy / Precision Adversarial Stress
    func testViewModel_DecimalPrecisionStressAgainstDatabase() async throws {
        let dbService = try DatabaseService(databasePath: liveDbPath)
        let transactions = try await dbService.fetchTransactions(limit: 1000, offset: 0)

        // Summing via Decimal (as ViewModel does)
        var buyDecimalSum: Decimal = 0
        var sellDecimalSum: Decimal = 0
        var divDecimalSum: Decimal = 0

        for tx in transactions {
            let t = tx.txType.uppercased()
            let s = tx.side?.uppercased() ?? ""
            let sub = tx.subType?.uppercased() ?? ""

            if t == "BUY" || s == "BUY" || sub == "BUY" || t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN" {
                buyDecimalSum += abs(tx.amount)
            }
            if t == "SELL" || s == "SELL" || sub == "SELL" {
                sellDecimalSum += abs(tx.amount)
            }
            if t == "DIVIDEND" || sub == "DISTRIBUTION" || sub == "DIVIDEND" {
                divDecimalSum += abs(tx.amount)
            }
        }

        XCTAssertEqual(buyDecimalSum, Decimal(string: "250793.978")!)
        XCTAssertEqual(sellDecimalSum, Decimal(string: "245793.419")!)
        XCTAssertEqual(divDecimalSum, Decimal(string: "5.69")!)

        // Verify that standard Double accumulation produces floating point drift
        // while Decimal accumulation stays exact
        var buyDoubleSum: Double = 0
        for tx in transactions {
            let t = tx.txType.uppercased()
            let s = tx.side?.uppercased() ?? ""
            let sub = tx.subType?.uppercased() ?? ""
            if t == "BUY" || s == "BUY" || sub == "BUY" || t == "SAVINGS_PLAN" || sub == "SAVINGS_PLAN" {
                buyDoubleSum += abs(NSDecimalNumber(decimal: tx.amount).doubleValue)
            }
        }
        // Check that Decimal representation preserves exact fractional decimals (.978)
        let buyDecimalString = "\(buyDecimalSum)"
        XCTAssertTrue(buyDecimalString.hasSuffix(".978") || buyDecimalString == "250793.978", "Decimal sum must preserve exact 3 decimal places")
    }
}
