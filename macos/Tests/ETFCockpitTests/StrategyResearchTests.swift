import XCTest
@testable import FinanceCockpit

@MainActor
final class StrategyResearchTests: XCTestCase {

    var mockDb: MockDatabaseService!
    var mockCLI: MockCLIProcessRunner!

    override func setUp() async throws {
        try await super.setUp()
        mockDb = MockDatabaseService()
        mockCLI = MockCLIProcessRunner()
    }

    override func tearDown() async throws {
        mockDb = nil
        mockCLI = nil
        try await super.tearDown()
    }

    // MARK: - 1. ResearchEvidenceViewModel Tests (Subsystem 3)

    func testResearchLoadDataPopulatesBundlesAndSources() async {
        let bundle = EvidenceBundleItem(
            bundleId: "bnd_001",
            instrumentId: "inst_01",
            isin: "IE00B3YLTY66",
            instrumentName: "SPDR MSCI ACWI IMI",
            asOfDate: "2026-10-31",
            claimsCount: 2,
            metricsCount: 1,
            claims: [
                ClaimItem(claimId: "cl_1", bundleId: "bnd_001", instrumentId: "inst_01", claimText: "TER is 0.17%", claimType: "fact", quoteVerbatim: "Total Expense Ratio is 0.17% p.a.", verificationStatus: "VERIFIED"),
                ClaimItem(claimId: "cl_2", bundleId: "bnd_001", instrumentId: "inst_01", claimText: "Projected dividend growth", claimType: "inference", verificationStatus: "UNVERIFIED")
            ]
        )
        let source = SourceItem(sourceId: "src_1", sourceType: "FACTSHEET", title: "SPDR Factsheet", publisher: "SSGA", contentSha256: "abcdef1234567890abcdef1234567890")
        let metric = MetricItem(metricId: "met_1", bundleId: "bnd_001", instrumentId: "inst_01", metricName: "TER", value: "0.17", unit: "%")

        mockDb.mockEvidenceBundles = [bundle]
        mockDb.mockSources = [source]
        mockDb.mockMetrics = [metric]

        let vm = ResearchEvidenceViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertEqual(vm.evidenceBundles.count, 1)
        XCTAssertEqual(vm.selectedBundle?.bundleId, "bnd_001")
        XCTAssertEqual(vm.sources.count, 1)
        XCTAssertEqual(vm.metrics.count, 1)
        XCTAssertEqual(vm.totalClaimsCount, 2)
        XCTAssertEqual(vm.verifiedClaimsCount, 1)
        XCTAssertEqual(vm.unverifiedClaimsCount, 1)
        XCTAssertEqual(vm.verificationRatePct, 50.0)
    }

    func testResearchClaimFiltering() async {
        let claims = [
            ClaimItem(claimId: "c1", bundleId: "b1", instrumentId: "i1", claimText: "Fact Alpha", claimType: "fact", verificationStatus: "VERIFIED"),
            ClaimItem(claimId: "c2", bundleId: "b1", instrumentId: "i1", claimText: "Estimate Beta", claimType: "sourced_estimate", verificationStatus: "VERIFIED"),
            ClaimItem(claimId: "c3", bundleId: "b1", instrumentId: "i1", claimText: "Inference Gamma", claimType: "inference", verificationStatus: "UNVERIFIED")
        ]
        let bundle = EvidenceBundleItem(bundleId: "b1", instrumentId: "i1", isin: "IE00B3YLTY66", asOfDate: "2026-10-31", claims: claims)
        mockDb.mockEvidenceBundles = [bundle]

        let vm = ResearchEvidenceViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        // Filter by claim type
        vm.selectedClaimTypeFilter = .fact
        XCTAssertEqual(vm.filteredClaims.count, 1)
        XCTAssertEqual(vm.filteredClaims.first?.claimText, "Fact Alpha")

        vm.selectedClaimTypeFilter = .all
        vm.selectedVerificationFilter = .unverified
        XCTAssertEqual(vm.filteredClaims.count, 1)
        XCTAssertEqual(vm.filteredClaims.first?.claimId, "c3")

        // Search text filtering
        vm.selectedVerificationFilter = .all
        vm.searchText = "Beta"
        XCTAssertEqual(vm.filteredClaims.count, 1)
        XCTAssertEqual(vm.filteredClaims.first?.claimId, "c2")
    }

    func testResearchCriticEvaluation() async {
        let bundle = EvidenceBundleItem(
            bundleId: "b1",
            instrumentId: "i1",
            isin: "IE00B3YLTY66",
            asOfDate: "2026-10-31",
            claims: [
                ClaimItem(claimId: "c1", bundleId: "b1", instrumentId: "i1", claimText: "Verified 1", claimType: "fact", verificationStatus: "VERIFIED"),
                ClaimItem(claimId: "c2", bundleId: "b1", instrumentId: "i1", claimText: "Verified 2", claimType: "fact", verificationStatus: "VERIFIED")
            ]
        )
        mockDb.mockEvidenceBundles = [bundle]

        let vm = ResearchEvidenceViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertEqual(vm.criticScorePct, 100.0)
        XCTAssertEqual(vm.criticReportStatus, .pass)
    }

    func testResearchTriggerAction() async {
        let vm = ResearchEvidenceViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.triggerResearch(query: "SPYI", ticker: "IE00B3YLTY66")

        XCTAssertEqual(mockCLI.commandExecutionCount, 1)
        XCTAssertNil(vm.errorMessage)
        XCTAssertNotNil(vm.statusMessage)
    }

    func testResearchEmptyState() async {
        mockDb.mockEvidenceBundles = []
        let vm = ResearchEvidenceViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertTrue(vm.evidenceBundles.isEmpty)
        XCTAssertNil(vm.selectedBundle)
        XCTAssertEqual(vm.totalClaimsCount, 0)
        XCTAssertEqual(vm.criticReportStatus, .notRun)
        XCTAssertNil(vm.criticScorePct)
        XCTAssertTrue(vm.criticFindings.isEmpty)
    }

    // MARK: - 2. ModelRegistryViewModel Tests (Subsystem 4)

    func testModelRegistryLoadData() async {
        let models = [
            ModelRegistryItem(modelId: "mod_local", provider: "local", modelName: "Deterministic Rules", accessTier: "local", status: "eligible", createdAt: "2026-10-01"),
            ModelRegistryItem(modelId: "mod_gemini_pro", provider: "google", modelName: "Gemini Pro", accessTier: "subscription", status: "eligible", createdAt: "2026-10-01")
        ]
        let champions = [
            ModelChampionItem(taskCategory: "table_extraction", modelId: "mod_local", provider: "local", modelName: "Deterministic Rules", accessTier: "local", scorePct: 98.5, evalDatasetVersion: "v1", evaluatedAt: "2026-10-31"),
            ModelChampionItem(taskCategory: "flawed_report_detection", modelId: "mod_gemini_pro", provider: "google", modelName: "Gemini Pro", accessTier: "subscription", scorePct: 94.2, evalDatasetVersion: "v1", evaluatedAt: "2026-10-31")
        ]
        let evals = [
            ModelEvaluationItem(evaluationId: "ev1", modelId: "mod_local", taskCategory: "table_extraction", scorePct: 98.5, criticalErrorPassed: true, isChampion: true)
        ]
        let runs = [
            ModelRunItem(runId: "run_01", taskName: "portfolio_research", quickModelId: "mod_local", deepModelId: "mod_gemini_pro", status: "completed")
        ]

        mockDb.mockModelRegistry = models
        mockDb.mockModelChampions = champions
        mockDb.mockModelEvaluations = evals
        mockDb.mockModelRuns = runs

        let vm = ModelRegistryViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertEqual(vm.registeredModels.count, 2)
        XCTAssertEqual(vm.championModels.count, 2)
        XCTAssertEqual(vm.evaluations.count, 1)
        XCTAssertEqual(vm.modelRuns.count, 1)
        XCTAssertEqual(vm.activeEligibleCount, 2)
        XCTAssertEqual(vm.championsCount, 2)
    }

    func testModelRegistryChampionLookup() async {
        let champion = ModelChampionItem(taskCategory: "claim_source_matching", modelId: "mod_gemini_pro", provider: "google", modelName: "Gemini Pro", accessTier: "subscription", scorePct: 92.0, evalDatasetVersion: "v1", evaluatedAt: "2026-10-31")
        mockDb.mockModelChampions = [champion]

        let vm = ModelRegistryViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        let found = vm.championForTask(category: "claim_source_matching")
        XCTAssertNotNil(found)
        XCTAssertEqual(found?.modelName, "Gemini Pro")

        let notFound = vm.championForTask(category: "nonexistent_task")
        XCTAssertNil(notFound)
    }

    func testModelRegistryLocalVsLLMCalculations() async {
        let models = [
            ModelRegistryItem(modelId: "m1", provider: "local", modelName: "RuleEngine", accessTier: "local", createdAt: "2026-10-01"),
            ModelRegistryItem(modelId: "m2", provider: "google", modelName: "Gemini", accessTier: "subscription", createdAt: "2026-10-01")
        ]
        mockDb.mockModelRegistry = models

        let vm = ModelRegistryViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        let metrics = vm.localVsLLMComparisonMetrics
        XCTAssertEqual(metrics.localModelCount, 1)
        XCTAssertEqual(metrics.cloudModelCount, 1)
        XCTAssertTrue(metrics.zeroCostEnforcement)
        XCTAssertTrue(metrics.confidentialDataPrivacyEnforced)
    }

    func testModelRegistryTriggerEvaluation() async {
        let vm = ModelRegistryViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.triggerModelEvaluation()

        XCTAssertEqual(mockCLI.commandExecutionCount, 1)
        XCTAssertEqual(mockCLI.lastExecutedArguments, ["model", "degerlendir"])
        XCTAssertNil(vm.errorMessage)
    }

    // MARK: - 3. TransactionLedgerViewModel Tests (Subsystem 5)

    func testTransactionLedgerLoadData() async {
        let txs = [
            TransactionItem(recordId: "tx_1", brokerTxId: "brk_1", txType: "BUY", isin: "IE00B3YLTY66", description: "SPDR ACWI Buy", amount: Decimal(-1000.0), quantity: Decimal(10), limitPrice: Decimal(100.0), status: "SETTLED", eventTime: "2026-10-25T10:00:00Z"),
            TransactionItem(recordId: "tx_2", brokerTxId: "brk_2", txType: "DIVIDEND", isin: "IE00B3YLTY66", description: "Dividend Payment", amount: Decimal(50.0), status: "SETTLED", eventTime: "2026-10-26T10:00:00Z"),
            TransactionItem(recordId: "tx_3", brokerTxId: "brk_3", txType: "TAX", description: "Withholding Tax", amount: Decimal(-12.5), status: "SETTLED", eventTime: "2026-10-26T10:00:05Z")
        ]
        let corporateAction = CorporateActionItem(actionId: "ca_1", isin: "US0378331005", actionType: "SPLIT", ratio: "4:1", effectiveDate: "2026-10-15", createdAt: "2026-10-01")
        let rec = ReconciliationItem(reconciliationId: "rec_1", runId: "run_01", reconciliationTime: "2026-10-31T20:00:00Z", status: "CLEAN", sharesMatch: true, cashMatch: true, valuationMatch: true, costBasisMatch: true, cashGapEur: Decimal(0))

        mockDb.mockTransactions = txs
        mockDb.mockCorporateActions = [corporateAction]
        mockDb.mockReconciliations = [rec]

        let vm = TransactionLedgerViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertEqual(vm.totalTransactionsCount, 3)
        XCTAssertEqual(vm.corporateActions.count, 1)
        XCTAssertEqual(vm.reconciliations.count, 1)

        XCTAssertEqual(vm.totalBuyAmountEur, Decimal(1000.0))
        XCTAssertEqual(vm.totalDividendAmountEur, Decimal(50.0))
        XCTAssertEqual(vm.totalTaxWithheldEur, Decimal(12.5))

        XCTAssertTrue(vm.isFullyReconciled)
        XCTAssertFalse(vm.hasCashGapAlert)
    }

    func testTransactionLedgerCashGapAlert() async {
        let rec = ReconciliationItem(reconciliationId: "rec_1", runId: "run_01", reconciliationTime: "2026-10-31T20:00:00Z", status: "DISCREPANCY", sharesMatch: true, cashMatch: false, valuationMatch: true, costBasisMatch: true, cashGapEur: Decimal(25.50))
        mockDb.mockReconciliations = [rec]

        let vm = TransactionLedgerViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertFalse(vm.isFullyReconciled)
        XCTAssertTrue(vm.hasCashGapAlert)
        XCTAssertEqual(vm.cashGapEur, Decimal(25.50))
    }

    func testTransactionFiltering() async {
        let txs = [
            TransactionItem(recordId: "t1", txType: "BUY", isin: "IE00B3YLTY66", amount: 100, eventTime: "2026-10-30T10:00:00Z"),
            TransactionItem(recordId: "t2", txType: "SELL", isin: "IE00BKM4GZ66", amount: 200, eventTime: "2026-10-30T11:00:00Z")
        ]
        mockDb.mockTransactions = txs

        let vm = TransactionLedgerViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        vm.selectedTxType = "BUY"
        XCTAssertEqual(vm.filteredTransactions.count, 1)
        XCTAssertEqual(vm.filteredTransactions.first?.recordId, "t1")

        vm.selectedTxType = nil
        vm.searchText = "BKM4"
        XCTAssertEqual(vm.filteredTransactions.count, 1)
        XCTAssertEqual(vm.filteredTransactions.first?.recordId, "t2")
    }

    func testTransactionLedgerActions() async {
        let vm = TransactionLedgerViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.triggerFetchTransactions()
        XCTAssertEqual(mockCLI.lastExecutedArguments, ["islemler", "cek"])

        await vm.triggerReconciliation()
        XCTAssertEqual(mockCLI.lastExecutedArguments, ["mutabakat", "--detay"])
    }

    // MARK: - 4. TargetBasketOverlapViewModel Tests (Subsystem 6)

    func testTargetBasketLoadDataAndDrift() async throws {
        let tempDir = FileManager.default.temporaryDirectory
        let tempConfigFile = tempDir.appendingPathComponent("test_portfoy_\(UUID().uuidString).json")
        let configData = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 60.0,
                "IE00BKM4GZ66": 10.0,
                "IE00BP3QZ825": 15.0,
                "IE00BP3QZB59": 15.0
            },
            "araclar": {
                "IE00B3YLTY66": {"rol": "SPDR ACWI"},
                "IE00BKM4GZ66": {"rol": "EM IMI"},
                "IE00BP3QZ825": {"rol": "Momentum"},
                "IE00BP3QZB59": {"rol": "Value"}
            }
        }
        """.data(using: .utf8)!
        try configData.write(to: tempConfigFile)
        defer { try? FileManager.default.removeItem(at: tempConfigFile) }

        let sets = [
            HoldingsSetItem(setId: "set_1", isin: "IE00B3YLTY66", asOfDate: "2026-10-31", sourceFile: "acwi.csv", provider: "SPDR", totalRecords: 2800, totalWeightPct: 100, createdAt: "2026-10-31")
        ]
        let matrix = [
            "IE00B3YLTY66": ["IE00B3YLTY66": 100.0, "IE00BP3QZ825": 28.5]
        ]
        let topHoldings = [
            ConsolidatedHoldingItem(constituentName: "APPLE INC", ticker: "APC", constituentIsin: "US0378331005", consolidatedWeightPct: 4.5, sector: "Technology", country: "United States", contributingFunds: ["IE00B3YLTY66"])
        ]
        mockDb.mockHoldingsSets = sets
        mockDb.mockHoldingsOverlap = HoldingsOverlapData(sets: sets, overlapMatrix: matrix, topConsolidatedHoldings: topHoldings)

        // Mock positions to test live weights
        let pos = [
            PositionItem(isin: "IE00B3YLTY66", displayName: "SPDR ACWI", quantity: 60, brokerValuation: 6000),
            PositionItem(isin: "IE00BKM4GZ66", displayName: "EM IMI", quantity: 10, brokerValuation: 1000),
            PositionItem(isin: "IE00BP3QZ825", displayName: "Momentum", quantity: 15, brokerValuation: 1500),
            PositionItem(isin: "IE00BP3QZB59", displayName: "Value", quantity: 15, brokerValuation: 1500)
        ]
        mockDb.mockPositions = pos

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI, configURL: tempConfigFile)
        await vm.loadData()

        XCTAssertTrue(vm.hasTargetWeights)
        XCTAssertEqual(vm.holdingsSets.count, 1)
        XCTAssertEqual(vm.top25Consolidated.count, 1)
        XCTAssertEqual(vm.drifts.count, 4)

        // Under 60/10/15/15 target vs live, drift should be 0.0
        let acwiDrift = vm.drifts.first { $0.isin == "IE00B3YLTY66" }
        XCTAssertNotNil(acwiDrift)
        XCTAssertEqual(acwiDrift?.targetWeightPct, 60.0)
        XCTAssertEqual(acwiDrift?.liveWeightPct, 60.0)
        XCTAssertEqual(acwiDrift?.driftPct, 0.0)
        XCTAssertFalse(acwiDrift?.isDrifting ?? true)
    }

    func testTargetBasketUnconfiguredTargets() async {
        let nonexistentConfig = FileManager.default.temporaryDirectory.appendingPathComponent("nonexistent_\(UUID().uuidString).json")
        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI, configURL: nonexistentConfig)
        await vm.loadData()

        XCTAssertFalse(vm.hasTargetWeights)
        XCTAssertTrue(vm.targetWeights.isEmpty)
        XCTAssertTrue(vm.drifts.isEmpty)
    }

    func testUCITSComplianceEvaluationPass() async {
        let set = HoldingsSetItem(setId: "set_1", isin: "IE00B3YLTY66", asOfDate: "2026-10-31", sourceFile: "acwi.csv", provider: "SPDR", totalRecords: 2800, totalWeightPct: 100, createdAt: "2026-10-31")
        let topHoldings = [
            ConsolidatedHoldingItem(constituentName: "APPLE INC", consolidatedWeightPct: 4.8),
            ConsolidatedHoldingItem(constituentName: "MICROSOFT CORP", consolidatedWeightPct: 4.5)
        ]
        mockDb.mockHoldingsSets = [set]
        mockDb.mockHoldingsOverlap = HoldingsOverlapData(sets: [set], overlapMatrix: [:], topConsolidatedHoldings: topHoldings)

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertTrue(vm.ucitsStatus.isEvaluated)
        XCTAssertTrue(vm.ucitsStatus.isCompliant)
        XCTAssertEqual(vm.ucitsStatus.violations.count, 0)
        XCTAssertEqual(vm.ucitsStatus.maxSingleWeightPct, 4.8)
    }

    func testUCITSComplianceEvaluationNotEvaluatedWhenEmpty() async {
        mockDb.mockHoldingsSets = []
        mockDb.mockHoldingsOverlap = HoldingsOverlapData(sets: [], overlapMatrix: [:], topConsolidatedHoldings: [])

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertFalse(vm.ucitsStatus.isEvaluated)
        XCTAssertFalse(vm.ucitsStatus.isCompliant)
    }

    func testUCITSComplianceEvaluationViolation() async {
        let set = HoldingsSetItem(setId: "set_1", isin: "IE00B3YLTY66", asOfDate: "2026-10-31", sourceFile: "acwi.csv", provider: "SPDR", totalRecords: 2800, totalWeightPct: 100, createdAt: "2026-10-31")
        // Holding exceeds 10%
        let topHoldings = [
            ConsolidatedHoldingItem(constituentName: "MEGA CORP", consolidatedWeightPct: 12.5)
        ]
        mockDb.mockHoldingsSets = [set]
        mockDb.mockHoldingsOverlap = HoldingsOverlapData(sets: [set], overlapMatrix: [:], topConsolidatedHoldings: topHoldings)

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertTrue(vm.ucitsStatus.isEvaluated)
        XCTAssertFalse(vm.ucitsStatus.isCompliant)
        XCTAssertGreaterThan(vm.ucitsStatus.violations.count, 0)
        XCTAssertEqual(vm.ucitsStatus.maxSingleWeightPct, 12.5)
    }

    func testCashInjectionRebalance() async throws {
        let tempDir = FileManager.default.temporaryDirectory
        let tempConfigFile = tempDir.appendingPathComponent("test_portfoy_\(UUID().uuidString).json")
        let configData = """
        {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 60.0,
                "IE00BKM4GZ66": 10.0
            },
            "araclar": {
                "IE00B3YLTY66": {"rol": "SPDR ACWI"},
                "IE00BKM4GZ66": {"rol": "EM IMI"}
            }
        }
        """.data(using: .utf8)!
        try configData.write(to: tempConfigFile)
        defer { try? FileManager.default.removeItem(at: tempConfigFile) }

        let pos = [
            PositionItem(isin: "IE00B3YLTY66", displayName: "SPDR ACWI", quantity: 50, brokerValuation: 5000), // currently 50% vs target 60%
            PositionItem(isin: "IE00BKM4GZ66", displayName: "EM IMI", quantity: 50, brokerValuation: 5000)  // currently 50% vs target 10%
        ]
        mockDb.mockPositions = pos

        let vm = TargetBasketOverlapViewModel(databaseService: mockDb, cliRunner: mockCLI, configURL: tempConfigFile)
        await vm.loadData()

        XCTAssertTrue(vm.hasTargetWeights)
        let acwi = vm.drifts.first { $0.isin == "IE00B3YLTY66" }
        XCTAssertNotNil(acwi)
        XCTAssertTrue(acwi?.isDrifting ?? false) // 50% vs 60% is a 10% drift outside 5% band
        XCTAssertGreaterThan(acwi?.suggestedOrderEur ?? 0, 0)
    }

    // MARK: - 5. ThesisManagementViewModel Tests (Subsystem 7)

    func testThesisManagementLoadData() async {
        let thesis = ThesisItem(
            versionId: "th_v1",
            thesisId: "th_001",
            versionNumber: 1,
            isin: "IE00B3YLTY66",
            instrumentName: "SPDR MSCI ACWI IMI",
            category: "CORE",
            horizon: "LONG_TERM",
            status: "ACTIVE",
            title: "Global Equity Accumulation",
            oneLineSummary: "Long-term low-cost global equity diversification.",
            falsificationTriggers: [
                "TER exceeds 0.25%",
                "Tracking error exceeds 0.50%"
            ],
            targetAllocationPct: Decimal(60.0),
            nextReviewDate: "2026-11-30",
            createdAt: "2026-10-31"
        )
        mockDb.mockTheses = [thesis]

        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.loadData()

        XCTAssertEqual(vm.theses.count, 1)
        XCTAssertEqual(vm.activeThesesCount, 1)
        XCTAssertEqual(vm.selectedThesis?.thesisId, "th_001")
    }

    func testThesisFalsificationValidation() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)

        // Form starts blank per R3.3
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

        // 1. Missing / short title
        vm.newTitle = "Ab"
        vm.newIsin = "IE00B3YLTY66"
        vm.newSummary = "Valid summary with sufficient length."
        vm.newRationale = "Valid economic rationale with sufficient length."
        vm.newFalsificationTriggersText = "Trigger 1: TER > 0.25%\nTrigger 2: Tracking Error > 0.50%"
        var val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertEqual(val.error, "Thesis title must be at least 3 characters.")

        // 2. Invalid ISIN: not matching ISO 6166 or invalid Luhn checksum
        vm.newTitle = "Global Equity Core"
        vm.newIsin = "INVALID_ISIN"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("Invalid ISIN") ?? false)

        // Check digit wrong: IE00B3YLTY65 instead of IE00B3YLTY66
        vm.newIsin = "IE00B3YLTY65"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("Luhn") ?? false)

        // 3. Valid ISIN, but short summary (< 10 chars)
        vm.newIsin = "IE00B3YLTY66"
        vm.newSummary = "Short"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("at least 10 characters") ?? false)

        // 4. Short rationale (< 10 chars)
        vm.newSummary = "Valid summary with sufficient length."
        vm.newRationale = "Too short"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("Economic rationale must be at least 10 characters") ?? false)

        // 5. Only 1 trigger (MANDATORY >= 2 RULE)
        vm.newRationale = "Valid economic rationale with sufficient length."
        vm.newFalsificationTriggersText = "Only One Trigger"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("at least 2 falsification triggers") ?? false)

        // 6. Invalid Target Allocation
        vm.newFalsificationTriggersText = "Trigger 1: TER > 0.25%\nTrigger 2: Tracking Error > 0.50%"
        vm.newTargetAllocationPct = "150"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("Target weight") ?? false)

        // 7. Invalid Review Date format
        vm.newTargetAllocationPct = "25.0"
        vm.newReviewDate = "31-12-2026"
        val = vm.validateNewThesis()
        XCTAssertFalse(val.isValid)
        XCTAssertTrue(val.error?.contains("YYYY-MM-DD") ?? false)

        // 8. Completely valid
        vm.newReviewDate = "2026-12-31"
        val = vm.validateNewThesis()
        XCTAssertTrue(val.isValid)
        XCTAssertNil(val.error)
    }

    func testThesisTriggerCreateThesis() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)
        vm.newTitle = "Global Core Equity"
        vm.newIsin = "IE00B3YLTY66"
        vm.newCategory = "CORE"
        vm.newHorizon = "LONG_TERM"
        vm.newSummary = "Core world equity thesis for global exposure"
        vm.newRationale = "Long-term compounding in low-cost index tracking vehicles"
        vm.newFalsificationTriggersText = "TER > 0.25%\nTracking Error > 0.50%"
        vm.newEvidencePillarsText = "Pillar 1: Broad diversification\nPillar 2: UCITS tax efficiency"
        vm.newCounterArguments = "Market drawdown risk"
        vm.newTargetAllocationPct = "60.0"
        vm.newReviewDate = "2026-12-31"

        await vm.triggerCreateThesis()

        XCTAssertEqual(mockCLI.commandExecutionCount, 1)
        let args = mockCLI.lastExecutedArguments
        XCTAssertEqual(args.prefix(2), ["tez", "ekle"])
        XCTAssertTrue(args.contains("--isin"))
        XCTAssertTrue(args.contains("IE00B3YLTY66"))
        XCTAssertTrue(args.contains("--baslik"))
        XCTAssertTrue(args.contains("Global Core Equity"))
        XCTAssertTrue(args.contains("--gerekce"))
        XCTAssertTrue(args.contains("--tetikleyiciler"))
        XCTAssertTrue(args.contains("--hedef-agirlik"))
        if let idx = args.firstIndex(of: "--hedef-agirlik"), idx + 1 < args.count {
            XCTAssertEqual(args[idx + 1], "0.60")
        }
        XCTAssertTrue(args.contains("--sonraki-kontrol"))
        XCTAssertTrue(args.contains("2026-12-31"))
        XCTAssertTrue(args.contains("--kanitlar"))
        XCTAssertTrue(args.contains("--karsi-gorus"))
    }

    func testThesisManagementKPIProperties() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)
        // Empty state
        XCTAssertEqual(vm.kpiActiveThesesText, "No data")
        XCTAssertEqual(vm.kpiHealthSummaryText, "No data")
        XCTAssertEqual(vm.kpiFalsificationSummaryText, "No data")

        // Populated state
        let thesis = ThesisItem(
            versionId: "v1", thesisId: "t1", isin: "IE00B3YLTY66", status: "ACTIVE",
            title: "T1", oneLineSummary: "S1", nextReviewDate: "2028-12-31", createdAt: "2026-10-31"
        )
        mockDb.mockTheses = [thesis]
        await vm.loadData()

        XCTAssertEqual(vm.kpiActiveThesesText, "1")
        XCTAssertEqual(vm.kpiHealthSummaryText, "Current")
        XCTAssertEqual(vm.kpiFalsificationSummaryText, "GREEN")
    }

    func testThesisHealthStatusCalculations() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)

        // 1. Overdue date
        let overdueThesis = ThesisItem(
            versionId: "v1", thesisId: "t1", isin: "IE00B3YLTY66",
            title: "Overdue", oneLineSummary: "S",
            nextReviewDate: "2020-01-01", createdAt: "2020-01-01"
        )
        XCTAssertEqual(vm.healthStatus(for: overdueThesis), .gecikmis)

        // 2. Future date
        let futureThesis = ThesisItem(
            versionId: "v2", thesisId: "t2", isin: "IE00B3YLTY66",
            title: "Future", oneLineSummary: "S",
            nextReviewDate: "2028-12-31", createdAt: "2026-10-31"
        )
        XCTAssertEqual(vm.healthStatus(for: futureThesis), .guncel)
    }

    func testThesisFalsificationStatusMapping() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)

        let activeThesis = ThesisItem(versionId: "v1", thesisId: "t1", isin: "IE00B3YLTY66", status: "ACTIVE", title: "A", oneLineSummary: "S", createdAt: "2026-10-31")
        XCTAssertEqual(vm.falsificationStatus(for: activeThesis), .green)

        let invalidatedThesis = ThesisItem(versionId: "v2", thesisId: "t2", isin: "IE00B3YLTY66", status: "INVALIDATED", title: "I", oneLineSummary: "S", createdAt: "2026-10-31")
        XCTAssertEqual(vm.falsificationStatus(for: invalidatedThesis), .breached)
    }

    func testThesisTriggerHealthCheckAction() async {
        let vm = ThesisManagementViewModel(databaseService: mockDb, cliRunner: mockCLI)
        await vm.triggerThesisHealthCheck()

        XCTAssertEqual(mockCLI.commandExecutionCount, 1)
        XCTAssertEqual(mockCLI.lastExecutedArguments, ["tez", "kontrol"])
        XCTAssertNil(vm.errorMessage)
    }

    // MARK: - 6. ISINValidator Tests

    func testISINValidatorValid() {
        XCTAssertTrue(ISINValidator.isValid("IE00B3YLTY66")) // SPDR ACWI IMI
        XCTAssertTrue(ISINValidator.isValid("IE00BKM4GZ66")) // Emerging Markets IMI
        XCTAssertTrue(ISINValidator.isValid("US0378331005")) // Apple Inc.
        XCTAssertTrue(ISINValidator.isValid("US5949181045")) // Microsoft Corp.
        XCTAssertTrue(ISINValidator.isValid("DE000BAY0017")) // Bayer AG
    }

    func testISINValidatorInvalid() {
        XCTAssertFalse(ISINValidator.isValid(""))
        XCTAssertFalse(ISINValidator.isValid("IE00B3YLTY6")) // too short (11 chars)
        XCTAssertFalse(ISINValidator.isValid("IE00B3YLTY660")) // too long (13 chars)
        XCTAssertFalse(ISINValidator.isValid("1E00B3YLTY66")) // numbers in country code
        XCTAssertFalse(ISINValidator.isValid("IE00B3YLTY65")) // invalid Luhn check digit
        XCTAssertFalse(ISINValidator.isValid("US0378331006")) // invalid Luhn check digit
    }
}
