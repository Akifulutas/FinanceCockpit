import SwiftUI

/// The 6 primary sections of ETFCockpit v2.
public enum CockpitSection: String, CaseIterable, Identifiable, Hashable, Sendable {
    case today = "Today"
    case portfolio = "Portfolio"
    case forecast = "Forecasts"
    case decisions = "Decisions"
    case discovery = "Discovery"
    case system = "System"

    public var id: String { rawValue }

    public var icon: String {
        switch self {
        case .today:
            return "sun.max.fill"
        case .portfolio:
            return "chart.pie.fill"
        case .forecast:
            return "chart.line.uptrend.xyaxis"
        case .decisions:
            return "scale.3d"
        case .discovery:
            return "sparkle.magnifyingglass"
        case .system:
            return "gearshape.2.fill"
        }
    }

    public var shortcutNumber: Int {
        switch self {
        case .today: return 1
        case .portfolio: return 2
        case .forecast: return 3
        case .decisions: return 4
        case .discovery: return 5
        case .system: return 6
        }
    }

    public var accentColor: Color {
        switch self {
        case .today: return .orange
        case .portfolio: return .blue
        case .forecast: return .indigo
        case .decisions: return .purple
        case .discovery: return .teal
        case .system: return .green
        }
    }

    public var defaultItem: CockpitNavigationItem {
        switch self {
        case .today: return .today
        case .portfolio: return .portfolio
        case .forecast: return .forecast
        case .decisions: return .evaluation
        case .discovery: return .screener
        case .system: return .integrity
        }
    }
}

/// Represents a pinned core ETF asset in the sidebar.
public struct PinnedAsset: Identifiable, Hashable, Sendable {
    public let id: String
    public let symbol: String
    public let isin: String
    public let name: String
    public let priceEur: Double
    public let changePct: Double?
    public let shares: Double
    public let isFresh: Bool

    public init(id: String, symbol: String, isin: String, name: String, priceEur: Double, changePct: Double?, shares: Double, isFresh: Bool = true) {
        self.id = id
        self.symbol = symbol
        self.isin = isin
        self.name = name
        self.priceEur = priceEur
        self.changePct = changePct
        self.shares = shares
        self.isFresh = isFresh
    }

    public static let defaultPinned: [PinnedAsset] = [
        PinnedAsset(id: "SPYI", symbol: "SPYI", isin: "IE00B3YLTY66", name: "SPDR MSCI ACWI IMI", priceEur: 11.61, changePct: 0.4, shares: 158),
        PinnedAsset(id: "IS3N", symbol: "IS3N", isin: "IE00BKM4GZ66", name: "iShares Core MSCI EM IMI", priceEur: 44.82, changePct: -0.2, shares: 22),
        PinnedAsset(id: "IS3R", symbol: "IS3R", isin: "IE00BP3QZ825", name: "iShares MSCI World Momentum", priceEur: 97.08, changePct: 1.1, shares: 10),
        PinnedAsset(id: "IS3S", symbol: "IS3S", isin: "IE00BP3QZB59", name: "iShares MSCI World Value", priceEur: 70.11, changePct: 0.1, shares: 8)
    ]
}

/// Logical grouping categories for Cockpit navigation.
public enum CockpitNavigationCategory: String, CaseIterable, Identifiable, Sendable {
    case operational = "Operational Monitoring"
    case strategy = "Strategy & Research"
    case security = "Security & Automation"

    public var id: String { rawValue }

    public var headerTitle: String { rawValue }

    public var items: [CockpitNavigationItem] {
        switch self {
        case .operational:
            return [.today, .portfolio, .forecast]
        case .strategy:
            return [.evaluation, .screener, .reports, .research, .modelRegistry, .ledger, .basket, .thesis]
        case .security:
            return [.integrity, .scheduler, .configuration]
        }
    }
}

/// The primary navigation destinations across all Cockpit subsystems.
public enum CockpitNavigationItem: String, CaseIterable, Identifiable, Hashable, Sendable {
    // 1. Operational Monitoring
    case today = "Today"
    case portfolio = "Portfolio & Holdings"
    case forecast = "Daily Forecast & Settlement"

    // 2. Strategy & Research
    case evaluation = "Evaluation"
    case screener = "Opportunity Screener"
    case reports = "Reports & Commentary"
    case research = "Evidence Research"
    case modelRegistry = "Model Registry & Benchmarking"
    case ledger = "Transaction Ledger"
    case basket = "Target Basket & Overlap"
    case thesis = "Investment Theses"

    // 3. Security & Automation
    case integrity = "Integrity & Security"
    case scheduler = "Task Scheduler"
    case configuration = "System Configuration"

    public var id: String { rawValue }

    public var section: CockpitSection {
        switch self {
        case .today:
            return .today
        case .portfolio, .ledger, .basket:
            return .portfolio
        case .forecast, .modelRegistry:
            return .forecast
        case .evaluation, .thesis, .reports:
            return .decisions
        case .screener, .research:
            return .discovery
        case .integrity, .scheduler, .configuration:
            return .system
        }
    }

    public var category: CockpitNavigationCategory {
        switch self {
        case .today, .portfolio, .forecast:
            return .operational
        case .evaluation, .screener, .reports, .research, .modelRegistry, .ledger, .basket, .thesis:
            return .strategy
        case .integrity, .scheduler, .configuration:
            return .security
        }
    }

    public var icon: String {
        switch self {
        case .today:
            return "sun.max.fill"
        case .portfolio:
            return "chart.pie.fill"
        case .forecast:
            return "chart.line.uptrend.xyaxis"
        case .evaluation:
            return "checklist"
        case .screener:
            return "slider.horizontal.3"
        case .reports:
            return "newspaper.fill"
        case .research:
            return "doc.text.magnifyingglass"
        case .modelRegistry:
            return "cpu"
        case .ledger:
            return "list.bullet.rectangle.portrait"
        case .basket:
            return "square.grid.2x2"
        case .thesis:
            return "lightbulb.fill"
        case .integrity:
            return "lock.shield.fill"
        case .scheduler:
            return "clock.badge.checkmark"
        case .configuration:
            return "gearshape.2.fill"
        }
    }

    public var subtitle: String {
        switch self {
        case .today:
            return "Session check, live data pipeline, and summary"
        case .portfolio:
            return "Holdings, cash reserve, and live valuation"
        case .forecast:
            return "09:30 CET forecasts and 17:40 CET settlement"
        case .evaluation:
            return "Rule-based and model decision support"
        case .screener:
            return "Candidate ETF scoring and pool management"
        case .reports:
            return "Status reports and commentary packages"
        case .research:
            return "Deep evidence packs and adversarial analysis"
        case .modelRegistry:
            return "Model performance and benchmark scorecard"
        case .ledger:
            return "Transaction ledger and 4-way reconciliation"
        case .basket:
            return "Target weights, correlation, and overlap"
        case .thesis:
            return "Investment theses and falsifiability tracking"
        case .integrity:
            return "Cryptographic SHA-256 chain and security"
        case .scheduler:
            return "Background launchd services and timer"
        case .configuration:
            return "Portfolio targets, policies, and parameters"
        }
    }

    public var accentColor: Color {
        switch self {
        case .today:
            return .orange
        case .portfolio:
            return .blue
        case .forecast:
            return .indigo
        case .evaluation:
            return .indigo
        case .screener:
            return .teal
        case .reports:
            return .purple
        case .research:
            return .teal
        case .modelRegistry:
            return .purple
        case .ledger:
            return .cyan
        case .basket:
            return .mint
        case .thesis:
            return .yellow
        case .integrity:
            return .green
        case .scheduler:
            return .orange
        case .configuration:
            return .gray
        }
    }
}
