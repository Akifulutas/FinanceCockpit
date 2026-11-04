import SwiftUI
import Combine

public enum PositionFilter: String, CaseIterable, Identifiable, Sendable {
    case all = "All"
    case etf = "ETFs"
    case equity = "Equities"

    public var id: String { rawValue }
}

public enum PositionSortField: String, CaseIterable, Identifiable, Sendable {
    case valuation = "Valuation"
    case name = "Name"
    case isin = "ISIN"
    case quantity = "Quantity"
    case midPrice = "Price"
    case weight = "Weight"
    case unrealizedPnL = "P&L"

    public var id: String { rawValue }
}

public struct AssetAllocationSlice: Identifiable, Sendable, Equatable {
    public var id: String { name }
    public let name: String
    public let value: Double
    public let percentage: Double
    public let color: Color

    public init(name: String, value: Double, percentage: Double, color: Color) {
        self.name = name
        self.value = value
        self.percentage = percentage
        self.color = color
    }
}

public struct ExposureSlice: Identifiable, Sendable, Equatable {
    public var id: String { title }
    public let title: String
    public let value: Double
    public let percentage: Double
    public let count: Int

    public init(title: String, value: Double, percentage: Double, count: Int) {
        self.title = title
        self.value = value
        self.percentage = percentage
        self.count = count
    }
}

@MainActor
public final class PortfolioViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var summary: PortfolioSummary?
    @Published public var positions: [PositionItem] = []
    @Published public var cash: CashObservation?
    @Published public var quotes: [QuoteItem] = []

    @Published public var isLoading: Bool = false
    @Published public var isRefreshing: Bool = false
    @Published public var errorMessage: String?
    @Published public var statusMessage: String?
    @Published public var lastRefreshDate: Date?

    @Published public var searchText: String = ""
    @Published public var selectedFilter: PositionFilter = .all
    @Published public var sortField: PositionSortField = .valuation
    @Published public var sortAscending: Bool = false

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
    }

    // MARK: - Computed Properties

    public var totalValuation: Decimal {
        investedAssets + totalCash
    }

    public var investedAssets: Decimal {
        positions.reduce(Decimal(0)) { $0 + $1.brokerValuation }
    }

    public var totalCash: Decimal {
        cash?.totalCash ?? 0
    }

    public var settledCash: Decimal {
        cash?.settledCash ?? 0
    }

    public var unsettledCash: Decimal {
        cash?.unsettledCash ?? 0
    }

    public var accruedCash: Decimal {
        cash?.accruedCash ?? 0
    }

    public var buyingPower: Decimal {
        cash?.buyingPower ?? 0
    }

    public var pendingBuyOrders: Decimal {
        cash?.pendingBuyOrdersAmount ?? 0
    }

    public var possibleTaxes: Decimal {
        cash?.possibleTaxes ?? 0
    }

    public var totalCostBasis: Decimal {
        positions.compactMap(\.totalCostBasis).reduce(Decimal(0), +)
    }

    public var totalUnrealizedPnLEur: Decimal {
        let withCost = positions.compactMap(\.unrealizedPnLEur)
        return withCost.reduce(Decimal(0), +)
    }

    public var totalUnrealizedPnLPct: Decimal? {
        guard totalCostBasis > 0 else { return nil }
        return ((investedAssets - totalCostBasis) / totalCostBasis) * 100
    }

    public func weight(for position: PositionItem) -> Decimal {
        guard totalValuation > 0 else { return 0 }
        return (position.brokerValuation / totalValuation) * 100
    }

    public var filteredPositions: [PositionItem] {
        var items = positions

        // 1. Filter by category
        switch selectedFilter {
        case .all:
            break
        case .etf:
            items = items.filter { $0.securityType.uppercased().contains("ETF") }
        case .equity:
            items = items.filter { !$0.securityType.uppercased().contains("ETF") }
        }

        // 2. Filter by search query
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            items = items.filter {
                $0.isin.lowercased().contains(query) ||
                $0.displayName.lowercased().contains(query)
            }
        }

        // 3. Sort
        items.sort { a, b in
            let comparison: Bool
            switch sortField {
            case .valuation:
                comparison = a.brokerValuation > b.brokerValuation
            case .name:
                comparison = a.displayName.localizedCaseInsensitiveCompare(b.displayName) == .orderedAscending
            case .isin:
                comparison = a.isin < b.isin
            case .quantity:
                comparison = a.quantity > b.quantity
            case .midPrice:
                let midA = a.computedMid ?? 0
                let midB = b.computedMid ?? 0
                comparison = midA > midB
            case .weight:
                comparison = self.weight(for: a) > self.weight(for: b)
            case .unrealizedPnL:
                let pnlA = a.unrealizedPnLEur ?? 0
                let pnlB = b.unrealizedPnLEur ?? 0
                comparison = pnlA > pnlB
            }
            return sortAscending ? !comparison : comparison
        }

        return items
    }

    public var assetAllocationBreakdown: [AssetAllocationSlice] {
        let totalDouble = NSDecimalNumber(decimal: totalValuation).doubleValue
        guard totalDouble > 0 else { return [] }

        let etfTotal = NSDecimalNumber(decimal: positions.filter { $0.securityType.uppercased().contains("ETF") }.reduce(Decimal(0)) { $0 + $1.brokerValuation }).doubleValue
        let equityTotal = NSDecimalNumber(decimal: positions.filter { !$0.securityType.uppercased().contains("ETF") }.reduce(Decimal(0)) { $0 + $1.brokerValuation }).doubleValue
        let cashTotal = NSDecimalNumber(decimal: totalCash).doubleValue

        var slices: [AssetAllocationSlice] = []
        if etfTotal > 0 {
            slices.append(AssetAllocationSlice(
                name: "ETFs (Broad Market & Factors)",
                value: etfTotal,
                percentage: (etfTotal / totalDouble) * 100,
                color: Color.blue
            ))
        }
        if equityTotal > 0 {
            slices.append(AssetAllocationSlice(
                name: "Single Equities",
                value: equityTotal,
                percentage: (equityTotal / totalDouble) * 100,
                color: Color.purple
            ))
        }
        if cashTotal > 0 {
            slices.append(AssetAllocationSlice(
                name: "Cash (EUR Liquidity)",
                value: cashTotal,
                percentage: (cashTotal / totalDouble) * 100,
                color: Color.green
            ))
        }

        return slices
    }

    public var geographicExposureBreakdown: [ExposureSlice] {
        let totalDouble = NSDecimalNumber(decimal: totalValuation).doubleValue
        guard totalDouble > 0 else { return [] }

        var map: [String: (value: Double, count: Int)] = [:]

        for p in positions {
            let prefix = String(p.isin.prefix(2)).uppercased()
            let title: String
            switch prefix {
            case "IE": title = "Ireland UCITS (Global ETF)"
            case "US": title = "US Equities"
            case "DE": title = "Germany (DAX)"
            case "NL": title = "Netherlands (AEX)"
            default: title = "\(prefix) Domicile"
            }
            let val = NSDecimalNumber(decimal: p.brokerValuation).doubleValue
            let current = map[title] ?? (0.0, 0)
            map[title] = (current.value + val, current.count + 1)
        }

        let cashDouble = NSDecimalNumber(decimal: totalCash).doubleValue
        if cashDouble > 0 {
            map["EUR Cash & Liquidity"] = (cashDouble, 1)
        }

        return map.map { (key, tuple) in
            ExposureSlice(
                title: key,
                value: tuple.value,
                percentage: (tuple.value / totalDouble) * 100,
                count: tuple.count
            )
        }.sorted { $0.value > $1.value }
    }

    // MARK: - Actions

    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            async let summaryTask = databaseService.fetchPortfolioSummary()
            async let positionsTask = databaseService.fetchPositions()
            async let cashTask = databaseService.fetchCashObservations()
            async let quotesTask = databaseService.fetchQuotes()

            let (sum, pos, c, q) = try await (summaryTask, positionsTask, cashTask, quotesTask)
            self.summary = sum
            self.positions = pos
            self.cash = c
            self.quotes = q
            self.lastRefreshDate = Date()
            self.isLoading = false
        } catch {
            self.errorMessage = "Failed to load portfolio data: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func refreshLiveQuotes() async {
        isRefreshing = true
        errorMessage = nil
        statusMessage = "Fetching live market quotes..."
        do {
            let result = try await cliRunner.runCommand(arguments: ["veri"])
            if result.isSuccess {
                statusMessage = "Market quotes updated successfully."
                await loadData()
            } else {
                errorMessage = "Failed to fetch market quotes: \(result.message)"
            }
        } catch {
            errorMessage = "Error fetching market quotes: \(error.localizedDescription)"
        }
        isRefreshing = false
    }
}
