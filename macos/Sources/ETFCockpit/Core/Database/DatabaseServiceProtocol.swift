import Foundation

public protocol DatabaseServiceProtocol: Sendable {
    func fetchPortfolioSummary() async throws -> PortfolioSummary
    func fetchPositions() async throws -> [PositionItem]
    func fetchCashObservations() async throws -> CashObservation?
    func fetchQuotes() async throws -> [QuoteItem]
    func fetchForecastEntries(targetDate: String?) async throws -> [ForecastEntryItem]
    func fetchForecastPerformance() async throws -> ForecastPerformanceSummary
    func fetchEvidenceBundles() async throws -> [EvidenceBundleItem]
    func fetchSources() async throws -> [SourceItem]
    func fetchMetrics(bundleId: String?) async throws -> [MetricItem]
    func fetchModelRegistry() async throws -> [ModelRegistryItem]
    func fetchModelChampions() async throws -> [ModelChampionItem]
    func fetchModelEvaluations() async throws -> [ModelEvaluationItem]
    func fetchModelRuns() async throws -> [ModelRunItem]
    func fetchTransactions() async throws -> [TransactionItem]
    func fetchCorporateActions() async throws -> [CorporateActionItem]
    func fetchReconciliations() async throws -> [ReconciliationItem]
    func fetchHoldingsSets() async throws -> [HoldingsSetItem]
    func fetchHoldingConstituents(setId: String) async throws -> [HoldingConstituentItem]
    func fetchHoldingsOverlap() async throws -> HoldingsOverlapData
    func fetchTheses() async throws -> [ThesisItem]
    func fetchAuditEvents(limit: Int) async throws -> [AuditEventItem]
    func fetchJobs() async throws -> [JobQueueItem]
    func fetchLastHistorySnapshotTimestamp() async throws -> Date?
}
