import SwiftUI
import Combine
import Foundation

/// ViewModel driving the "Bugün" (Today) overview dashboard (E1).
/// Responsible for immediate Scalable Capital session inspection, one-click browser login flow,
/// streaming data refresh (`masa veri` + `masa gecmis`), Xetra market status, and top-level portfolio alerts.
@MainActor
public final class TodayDashboardViewModel: ObservableObject {

    // MARK: - Published State
    @Published public var isSessionActive: Bool? = nil
    @Published public var isCheckingSession: Bool = false
    @Published public var accountInfo: GirisAccountInfo? = nil
    @Published public var sessionErrorMessage: String? = nil

    // MARK: - 6-Step Morning Startup Flow Types (İP-7)
    public enum MorningFlowStepId: Int, CaseIterable, Identifiable, Sendable {
        case session = 1
        case data = 2
        case history = 3
        case evaluation = 4
        case commentary = 5
        case scan = 6

        public var id: Int { rawValue }

        public var title: String {
            switch self {
            case .session: return "1. Session Check & Login"
            case .data: return "2. Live Market Data (masa veri)"
            case .history: return "3. Historical Series (masa gecmis)"
            case .evaluation: return "4. Strategy Evaluation (masa degerlendir)"
            case .commentary: return "5. Analysis Pack (masa yorum)"
            case .scan: return "6. Opportunity Screener (masa tarama)"
            }
        }

        public var shortTitle: String {
            switch self {
            case .session: return "Session"
            case .data: return "Data"
            case .history: return "History"
            case .evaluation: return "Evaluate"
            case .commentary: return "Analysis"
            case .scan: return "Screener"
            }
        }

        public var icon: String {
            switch self {
            case .session: return "lock.shield.fill"
            case .data: return "arrow.triangle.2.circlepath.circle.fill"
            case .history: return "chart.xyaxis.line"
            case .evaluation: return "checkmark.seal.fill"
            case .commentary: return "bubble.left.and.text.bubble.right.fill"
            case .scan: return "magnifyingglass.circle.fill"
            }
        }
    }

    public enum MorningStepStatus: Equatable, Sendable {
        case pending
        case running
        case success(exitCode: Int32)
        case skipped(reason: String)
        case degraded(exitCode: Int32, reason: String)
        case failed(exitCode: Int32, message: String)
        case cancelled
    }

    public struct MorningFlowStepItem: Identifiable, Sendable {
        public let step: MorningFlowStepId
        public var status: MorningStepStatus
        public var startedAt: Date?
        public var finishedAt: Date?
        public var durationSeconds: Double?
        public var exitCode: Int32?
        public var detailText: String?

        public var id: Int { step.rawValue }

        public init(
            step: MorningFlowStepId,
            status: MorningStepStatus = .pending,
            startedAt: Date? = nil,
            finishedAt: Date? = nil,
            durationSeconds: Double? = nil,
            exitCode: Int32? = nil,
            detailText: String? = nil
        ) {
            self.step = step
            self.status = status
            self.startedAt = startedAt
            self.finishedAt = finishedAt
            self.durationSeconds = durationSeconds
            self.exitCode = exitCode
            self.detailText = detailText
        }
    }

    public struct MorningFlowSummary: Equatable, Sendable {
        public var evaluatedPositionsCount: Int = 0
        public var opportunityCandidatesCount: Int = 0
        public var lastQuoteTimestamp: String? = nil
        public var isComplete: Bool = false
        public var summaryMessage: String = ""
        public var completedAt: Date? = nil

        public init(
            evaluatedPositionsCount: Int = 0,
            opportunityCandidatesCount: Int = 0,
            lastQuoteTimestamp: String? = nil,
            isComplete: Bool = false,
            summaryMessage: String = "",
            completedAt: Date? = nil
        ) {
            self.evaluatedPositionsCount = evaluatedPositionsCount
            self.opportunityCandidatesCount = opportunityCandidatesCount
            self.lastQuoteTimestamp = lastQuoteTimestamp
            self.isComplete = isComplete
            self.summaryMessage = summaryMessage
            self.completedAt = completedAt
        }
    }

    // Startup Workflow (1. Safari/CLI -> 2. Phone Approval -> 3. Data Fetch) - Backwards compatible
    public enum StartupStep: Int, CaseIterable, Identifiable {
        case loginAndSafari = 1
        case phoneApproval = 2
        case fetchMarketData = 3

        public var id: Int { rawValue }

        public var title: String {
            switch self {
            case .loginAndSafari:
                return "1. Safari & CLI Login"
            case .phoneApproval:
                return "2. Phone Approval"
            case .fetchMarketData:
                return "3. Live Price & Data Fetch"
            }
        }
    }

    @Published public var morningFlowSteps: [MorningFlowStepItem] = MorningFlowStepId.allCases.map { MorningFlowStepItem(step: $0) }
    @Published public var morningFlowSummary: MorningFlowSummary? = nil
    @Published public var isMorningFlowRunning: Bool = false
    private var morningFlowTask: Task<Void, Never>? = nil

    @Published public var hasUninstalledSchedulerWarning: Bool = false
    @Published public var isSchedulerInstalled: Bool = false

    @Published public var currentStartupStep: StartupStep? = nil
    @Published public var isStartupSequenceRunning: Bool = false

    @Published public var loginPromptMessage: String? = nil
    @Published public var isVerifyingSession: Bool = false
    @Published public var isLoginProcessRunning: Bool = false
    @Published public var loginAuthURL: String? = nil
    @Published public var activationURL: String? = nil
    @Published public var activationCode: String? = nil
    private var loginTask: Task<Void, Never>? = nil

    @Published public var isRefreshingData: Bool = false
    @Published public var streamingLogs: [String] = []

    @Published public var totalEur: Double? = nil
    @Published public var cashEur: Double? = nil
    @Published public var positionsCount: Int = 0
    @Published public var positions: [PositionItem] = []
    @Published public var quotes: [QuoteItem] = []
    @Published public var hasWaitingAuthAlert: Bool = false
    @Published public var integrityTipStatus: String = "MATCH_SEALED"
    @Published public var isXetraOpen: Bool = false
    @Published public var xetraStatusText: String = "Calculating..."
    @Published public var lastUpdatedDate: Date? = nil

    // MARK: - Dependencies
    private let databaseService: DatabaseServiceProtocol
    private let cliRunner: CLIProcessRunnerProtocol

    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
    }

    // MARK: - Lifecycle / Load
    public func loadData() async {
        await checkSession()
        updateXetraStatus()
        await loadPortfolioSummary()
        await checkIntegrityAndAlerts()
        await checkSchedulerStatus()
        lastUpdatedDate = Date()
    }

    // MARK: - Session Verification
    public func checkSession() async {
        isCheckingSession = true
        sessionErrorMessage = nil
        do {
            let result = try await cliRunner.runCommand(arguments: ["giris", "--json"])
            if let data = result.stdout.data(using: .utf8) {
                let response = try JSONDecoder().decode(GirisResponse.self, from: data)
                isSessionActive = response.active
                accountInfo = response.accountInfo
                if !response.active && loginPromptMessage == nil {
                    loginPromptMessage = "Scalable Capital session has expired or is inactive. Please sign in to update data."
                }
            } else {
                isSessionActive = false
                sessionErrorMessage = "Could not read JSON response."
            }
        } catch {
            isSessionActive = false
            sessionErrorMessage = error.localizedDescription
            CockpitLogger.shared.error("Giris check failed: \(error.localizedDescription)")
        }
        isCheckingSession = false
    }

    // MARK: - One-Click Safari Login Flow (Capturing CLI Device Code URL)
    public func startCLILogin() {
        loginTask = Task {
            await runLoginStream()
        }
    }

    public func runLoginStream() async {
        guard !isLoginProcessRunning else { return }
        isLoginProcessRunning = true
        loginAuthURL = nil
        activationURL = nil
        activationCode = nil
        loginPromptMessage = "Starting Scalable Capital CLI session..."

        var exitCode: Int32? = nil
        var browserPrompted = false
        var hasBlockedUrl = false
        var lineBuffer = ""

        func processLine(_ line: String) {
            guard !hasBlockedUrl else { return }

            // Capture Scalable login URL if printed by CLI
            if let urlMatch = line.range(of: #"https?://[^\s]+"#, options: .regularExpression) {
                let candidateStr = String(line[urlMatch])
                guard let parsedURL = URL(string: candidateStr) else {
                    hasBlockedUrl = true
                    self.loginAuthURL = nil
                    self.activationURL = nil
                    self.loginPromptMessage = "⚠️ Unexpected link: Untrusted or invalid login URL blocked."
                    CockpitLogger.shared.warning("Untrusted or invalid login URL blocked: \(candidateStr)")
                    return
                }

                let rawPath = parsedURL.path
                let standardPath = (rawPath as NSString).standardizingPath
                let isPathValid = (standardPath == "/activate" || standardPath.hasPrefix("/activate/"))
                    && !rawPath.contains("..")
                    && !rawPath.contains("//")
                    && !parsedURL.pathComponents.contains("..")

                let isSchemeValid = parsedURL.scheme == "https"
                let isHostValid = parsedURL.host == "secure.scalable.capital"
                let isPortValid = parsedURL.port == nil || parsedURL.port == 443
                let isFragmentValid = parsedURL.fragment == nil && !candidateStr.contains("#")
                let isUserInfoValid = parsedURL.user == nil && parsedURL.password == nil

                if isSchemeValid && isHostValid && isPortValid && isFragmentValid && isUserInfoValid && isPathValid {
                    if !browserPrompted {
                        browserPrompted = true
                        self.loginAuthURL = candidateStr
                        self.activationURL = candidateStr

                        #if os(macOS)
                        // Strictly avoid popping Safari during automated tests
                        let isTesting = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil ||
                                        NSClassFromString("XCTestCase") != nil
                        if !isTesting {
                            NSWorkspace.shared.open(parsedURL)
                        }
                        #endif

                        self.currentStartupStep = .phoneApproval
                        self.loginPromptMessage = "Confirm your session on the Safari page and approve the Scalable notification on your phone."
                    }
                } else {
                    hasBlockedUrl = true
                    self.loginAuthURL = nil
                    self.activationURL = nil
                    self.loginPromptMessage = "⚠️ Unexpected link: Untrusted or invalid login URL blocked."
                    CockpitLogger.shared.warning("Untrusted or invalid login URL blocked: \(candidateStr)")
                    return
                }
            }

            // Capture activation / device code if printed by CLI
            if self.activationCode == nil {
                if let codeMatch = line.range(of: #"(?:[Kk]od|[Cc]ode|onay kodu):\s*([A-Z0-9-]+)"#, options: .regularExpression) {
                    let matched = String(line[codeMatch])
                    if let colon = matched.firstIndex(of: ":") {
                        let code = matched[matched.index(after: colon)...].trimmingCharacters(in: .whitespacesAndNewlines)
                        if !code.isEmpty {
                            self.activationCode = code
                        }
                    }
                }
            }
        }

        func flushLineBuffer() {
            if !lineBuffer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                processLine(lineBuffer)
                lineBuffer = ""
            }
        }

        do {
            for try await chunk in cliRunner.runStream(arguments: ["giris", "--login"]) {
                switch chunk {
                case .exit(let code):
                    exitCode = code
                    flushLineBuffer()
                case .stdout(let t), .stderr(let t):
                    lineBuffer.append(t)
                    while let newlineIndex = lineBuffer.firstIndex(of: "\n") {
                        let line = String(lineBuffer[..<newlineIndex])
                        lineBuffer.removeSubrange(...newlineIndex)
                        processLine(line)
                    }
                }
            }

            flushLineBuffer()

            self.isLoginProcessRunning = false

            if hasBlockedUrl {
                self.isSessionActive = false
                return
            }

            // Strict exit-code and verification checks (İP-1)
            if let code = exitCode, code != 0 {
                self.isSessionActive = false
                self.loginPromptMessage = "Login failed (exit code: \(code)). Please try again."
                return
            }

            // Verify explicitly with `giris --json`
            await self.checkSession()

            if self.isSessionActive == true {
                self.loginPromptMessage = "✓ Login successful! Scalable Capital session verified and connected."
                self.hasWaitingAuthAlert = false
                await self.loadData()
            } else if browserPrompted {
                self.isSessionActive = false
                self.loginPromptMessage = "Confirm your session on the Safari page and approve the Scalable notification on your phone."
            } else {
                self.isSessionActive = false
                self.loginPromptMessage = "Login incomplete: Session not yet active. Please complete browser and phone approval."
            }
        } catch {
            self.isLoginProcessRunning = false
            self.isSessionActive = false
            self.loginPromptMessage = "Login process ended or timed out."
        }
    }

    // MARK: - Automated 6-Step Morning Sequence (İP-7)
    public func startInitialStartupSequence() {
        startMorningFlow()
    }

    public func startMorningFlow() {
        guard !isMorningFlowRunning else { return }
        morningFlowTask = Task {
            await runFullMorningFlow()
        }
    }

    public func cancelLogin() {
        cancelMorningFlow()
    }

    public func cancelMorningFlow() {
        morningFlowTask?.cancel()
        morningFlowTask = nil
        loginTask?.cancel()
        loginTask = nil
        isMorningFlowRunning = false
        isStartupSequenceRunning = false
        isLoginProcessRunning = false

        for i in 0..<morningFlowSteps.count {
            if morningFlowSteps[i].status == .running {
                morningFlowSteps[i].status = .cancelled
                morningFlowSteps[i].finishedAt = Date()
                if let started = morningFlowSteps[i].startedAt {
                    morningFlowSteps[i].durationSeconds = Date().timeIntervalSince(started)
                }
            } else if morningFlowSteps[i].status == .pending {
                morningFlowSteps[i].status = .cancelled
            }
        }
        loginPromptMessage = "Morning flow cancelled."
    }

    public func runInitialStartupSequence() async {
        await runFullMorningFlow()
    }

    public func runFullMorningFlow() async {
        guard !isMorningFlowRunning else { return }
        isMorningFlowRunning = true
        isStartupSequenceRunning = true
        loginPromptMessage = "Starting morning flow (6 steps)..."
        streamingLogs.removeAll()
        morningFlowSummary = nil
        morningFlowSteps = MorningFlowStepId.allCases.map { MorningFlowStepItem(step: $0) }

        defer {
            isMorningFlowRunning = false
            isStartupSequenceRunning = false
            currentStartupStep = nil
        }

        // ====================================================================
        // Adım 1: Oturum Kontrolü & Giriş (giris --json / sc login)
        // ====================================================================
        updateStep(stepId: .session, status: .running, startedAt: Date())
        currentStartupStep = .loginAndSafari
        loginPromptMessage = "1/6: Checking Scalable Capital session..."
        await checkSession()

        if isSessionActive != true {
            loginPromptMessage = "1/6: Session inactive, starting browser activation..."
            currentStartupStep = .phoneApproval
            await runLoginStream()
            await checkSession()
        }

        if Task.isCancelled {
            markStepCancelled(stepId: .session)
            return
        }

        if isSessionActive == true {
            completeStep(stepId: .session, status: .success(exitCode: 0), exitCode: 0, detail: "Session active and verified.")
        } else {
            completeStep(stepId: .session, status: .failed(exitCode: 1, message: "Session could not be opened or approved."), exitCode: 1, detail: "Session failed.")
            cancelRemainingSteps(after: .session)
            loginPromptMessage = "1/6: Session verification failed. Flow stopped."
            return
        }

        // ====================================================================
        // Adım 2: Canlı Veri (masa veri)
        // ====================================================================
        updateStep(stepId: .data, status: .running, startedAt: Date())
        currentStartupStep = .fetchMarketData
        loginPromptMessage = "2/6: Fetching live portfolio and quotes (masa veri)..."
        var veriExitCode: Int32 = 0
        do {
            for try await chunk in cliRunner.runStream(arguments: ["veri"]) {
                if Task.isCancelled { break }
                switch chunk {
                case .exit(let code):
                    veriExitCode = code
                case .stdout(let text), .stderr(let text):
                    let lines = text.components(separatedBy: .newlines).filter { !$0.isEmpty }
                    for line in lines { streamingLogs.append(line) }
                }
            }
            if Task.isCancelled {
                markStepCancelled(stepId: .data)
                return
            }
            if veriExitCode == 0 {
                completeStep(stepId: .data, status: .success(exitCode: 0), exitCode: 0, detail: "All quotes and portfolio sealed.")
            } else if veriExitCode == 2 {
                completeStep(stepId: .data, status: .degraded(exitCode: 2, reason: "Market closed or partial quotes (DEGRADED)."), exitCode: 2, detail: "Partial quotes (DEGRADED).")
            } else {
                completeStep(stepId: .data, status: .failed(exitCode: veriExitCode, message: "Data fetch failed: session error or network issue."), exitCode: veriExitCode, detail: "Data fetch failed.")
                cancelRemainingSteps(after: .data)
                loginPromptMessage = "2/6: Data fetch failed (exit code: \(veriExitCode)). Flow stopped."
                return
            }
        } catch {
            completeStep(stepId: .data, status: .failed(exitCode: -1, message: error.localizedDescription), exitCode: -1, detail: error.localizedDescription)
            cancelRemainingSteps(after: .data)
            return
        }

        // ====================================================================
        // Adım 3: Geçmiş Seriler (masa gecmis - son 24 saat kontrolü)
        // ====================================================================
        updateStep(stepId: .history, status: .running, startedAt: Date())
        loginPromptMessage = "3/6: Checking historical price series (masa gecmis)..."
        var skipHistory = false
        var skipReason = ""
        if let lastHistoryDate = try? await databaseService.fetchLastHistorySnapshotTimestamp() {
            let diffHours = Date().timeIntervalSince(lastHistoryDate) / 3600.0
            if diffHours < 24.0 {
                skipHistory = true
                let timeFormatter = DateFormatter()
                timeFormatter.dateFormat = "HH:mm"
                let timeStr = timeFormatter.string(from: lastHistoryDate)
                skipReason = "Fetched within last 24 hours (\(timeStr)), skipped."
            }
        }

        if skipHistory {
            completeStep(stepId: .history, status: .skipped(reason: skipReason), exitCode: 0, detail: skipReason)
            streamingLogs.append("[\(currentTimeString())] ℹ \(skipReason)")
        } else {
            var gecmisExitCode: Int32 = 0
            do {
                for try await chunk in cliRunner.runStream(arguments: ["gecmis"]) {
                    if Task.isCancelled { break }
                    switch chunk {
                    case .exit(let code):
                        gecmisExitCode = code
                    case .stdout(let text), .stderr(let text):
                        let lines = text.components(separatedBy: .newlines).filter { !$0.isEmpty }
                        for line in lines { streamingLogs.append(line) }
                    }
                }
                if Task.isCancelled {
                    markStepCancelled(stepId: .history)
                    return
                }
                if gecmisExitCode == 0 {
                    completeStep(stepId: .history, status: .success(exitCode: 0), exitCode: 0, detail: "All historical series updated.")
                } else if gecmisExitCode == 2 {
                    completeStep(stepId: .history, status: .degraded(exitCode: 2, reason: "Partial series fetched."), exitCode: 2, detail: "Partial series fetched.")
                } else {
                    completeStep(stepId: .history, status: .failed(exitCode: gecmisExitCode, message: "Failed to fetch historical series."), exitCode: gecmisExitCode, detail: "Error")
                }
            } catch {
                completeStep(stepId: .history, status: .failed(exitCode: -1, message: error.localizedDescription), exitCode: -1, detail: error.localizedDescription)
            }
        }

        // ====================================================================
        // Adım 4: Değerlendirme (masa degerlendir --json)
        // ====================================================================
        updateStep(stepId: .evaluation, status: .running, startedAt: Date())
        loginPromptMessage = "4/6: Running hold/reduce evaluation (masa degerlendir)..."
        var evaluatedCount = 0
        do {
            let degResult = try await cliRunner.runCommand(arguments: ["degerlendir", "--json"])
            if Task.isCancelled {
                markStepCancelled(stepId: .evaluation)
                return
            }
            if degResult.isSuccess, let data = degResult.stdout.data(using: .utf8) {
                let evalResp = try? JSONDecoder().decode(DegerlendirResponse.self, from: data)
                evaluatedCount = evalResp?.assessments.count ?? positionsCount
                let labels = evalResp?.assessments.map { $0.label }.joined(separator: ", ") ?? ""
                completeStep(stepId: .evaluation, status: .success(exitCode: 0), exitCode: 0, detail: "\(evaluatedCount) positions evaluated (\(labels)).")
            } else {
                completeStep(stepId: .evaluation, status: .failed(exitCode: degResult.exitCode, message: degResult.stderr), exitCode: degResult.exitCode, detail: "Evaluation failed.")
                cancelRemainingSteps(after: .evaluation)
                loginPromptMessage = "4/6: Evaluation failed. Flow stopped."
                return
            }
        } catch {
            completeStep(stepId: .evaluation, status: .failed(exitCode: -1, message: error.localizedDescription), exitCode: -1, detail: error.localizedDescription)
            cancelRemainingSteps(after: .evaluation)
            return
        }

        // ====================================================================
        // Adım 5: Yorum Paketi (masa yorum)
        // ====================================================================
        updateStep(stepId: .commentary, status: .running, startedAt: Date())
        loginPromptMessage = "5/6: Compiling analysis and commentary pack (masa yorum)..."
        do {
            let yorumResult = try await cliRunner.runCommand(arguments: ["yorum"])
            if Task.isCancelled {
                markStepCancelled(stepId: .commentary)
                return
            }
            if yorumResult.isSuccess {
                completeStep(stepId: .commentary, status: .success(exitCode: 0), exitCode: 0, detail: "Commentary pack generated.")
            } else {
                let errText = !yorumResult.stderr.isEmpty ? yorumResult.stderr : yorumResult.stdout
                let isQuota = errText.contains("429") || errText.lowercased().contains("quota") || errText.lowercased().contains("kota")
                let detail: String
                if isQuota {
                    detail = "Model quota exhausted, deterministic evaluation valid."
                } else {
                    let firstLine = errText.components(separatedBy: .newlines).first(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) ?? "Commentary failed."
                    detail = firstLine.trimmingCharacters(in: .whitespaces)
                }
                completeStep(stepId: .commentary, status: .degraded(exitCode: yorumResult.exitCode, reason: detail), exitCode: yorumResult.exitCode, detail: detail)
            }
        } catch {
            let errText = error.localizedDescription
            let isQuota = errText.contains("429") || errText.lowercased().contains("quota") || errText.lowercased().contains("kota")
            let detail = isQuota ? "Model quota exhausted, deterministic evaluation valid." : errText
            completeStep(stepId: .commentary, status: .degraded(exitCode: -1, reason: detail), exitCode: -1, detail: detail)
        }

        // ====================================================================
        // Adım 6: Fırsat Taraması (masa tarama --json)
        // ====================================================================
        updateStep(stepId: .scan, status: .running, startedAt: Date())
        loginPromptMessage = "6/6: Scanning 17-asset pool (masa tarama)..."
        var candidatesCount = 0
        do {
            let scanResult = try await cliRunner.runCommand(arguments: ["tarama", "--json"])
            if Task.isCancelled {
                markStepCancelled(stepId: .scan)
                return
            }
            if scanResult.isSuccess, let data = scanResult.stdout.data(using: .utf8) {
                let scanResp = try? JSONDecoder().decode(TaramaResponse.self, from: data)
                let totalScanned = scanResp?.candidates.count ?? 0
                // Labels are CLI data values emitted by masa/scanner.py (Turkish); English aliases accepted for forward compatibility.
                let opps = scanResp?.candidates.filter { ["ARAŞTIRMAYA DEĞER", "EKLE", "WORTH_RESEARCHING", "ADD"].contains($0.label) } ?? []
                candidatesCount = opps.count
                let detailText: String
                if candidatesCount == 0 {
                    detailText = "0 opportunities (\(totalScanned) assets scanned)"
                } else {
                    detailText = "\(candidatesCount) opportunity candidates identified."
                }
                completeStep(stepId: .scan, status: .success(exitCode: 0), exitCode: 0, detail: detailText)
            } else {
                completeStep(stepId: .scan, status: .failed(exitCode: scanResult.exitCode, message: scanResult.stderr), exitCode: scanResult.exitCode, detail: "Scan failed.")
            }
        } catch {
            completeStep(stepId: .scan, status: .failed(exitCode: -1, message: error.localizedDescription), exitCode: -1, detail: error.localizedDescription)
        }

        // ====================================================================
        // Sonuç Kartı Özeti (İP-7)
        // ====================================================================
        let firstQuoteTime = quotes.first?.quoteTimestamp.trimmingCharacters(in: .whitespacesAndNewlines)
        let lastQuoteTime: String
        if let fqt = firstQuoteTime, !fqt.isEmpty {
            lastQuoteTime = fqt
        } else {
            lastQuoteTime = "no quotes"
        }

        var warningCount = 0
        var errorCount = 0
        for step in morningFlowSteps {
            switch step.status {
            case .degraded:
                warningCount += 1
            case .failed:
                errorCount += 1
            default:
                break
            }
        }

        let statusSummary: String
        if warningCount > 0 && errorCount > 0 {
            statusSummary = "Completed · \(warningCount) warning(s) · \(errorCount) error(s)"
        } else if warningCount > 0 {
            statusSummary = "Completed · \(warningCount) warning(s)"
        } else if errorCount > 0 {
            statusSummary = "Completed · \(errorCount) error(s)"
        } else {
            statusSummary = "Completed"
        }

        morningFlowSummary = MorningFlowSummary(
            evaluatedPositionsCount: evaluatedCount,
            opportunityCandidatesCount: candidatesCount,
            lastQuoteTimestamp: lastQuoteTime,
            isComplete: true,
            summaryMessage: "\(statusSummary): \(evaluatedCount) positions evaluated, \(candidatesCount) opportunity candidates, data freshness: \(lastQuoteTime)",
            completedAt: Date()
        )

        if warningCount > 0 || errorCount > 0 {
            loginPromptMessage = "\(statusSummary): \(evaluatedCount) positions evaluated, \(candidatesCount) opportunity candidates."
        } else {
            loginPromptMessage = "✓ Morning startup flow completed successfully: \(evaluatedCount) positions evaluated, \(candidatesCount) opportunity candidates."
        }
        lastUpdatedDate = Date()
        await loadData()
    }

    public func updateStep(stepId: MorningFlowStepId, status: MorningStepStatus, startedAt: Date? = nil) {
        if let idx = morningFlowSteps.firstIndex(where: { $0.step == stepId }) {
            morningFlowSteps[idx].status = status
            if let startedAt {
                morningFlowSteps[idx].startedAt = startedAt
            }
        }
    }

    public func completeStep(stepId: MorningFlowStepId, status: MorningStepStatus, exitCode: Int32?, detail: String?) {
        if let idx = morningFlowSteps.firstIndex(where: { $0.step == stepId }) {
            morningFlowSteps[idx].status = status
            morningFlowSteps[idx].finishedAt = Date()
            morningFlowSteps[idx].exitCode = exitCode
            morningFlowSteps[idx].detailText = detail
            if let started = morningFlowSteps[idx].startedAt {
                morningFlowSteps[idx].durationSeconds = Date().timeIntervalSince(started)
            }
        }
    }

    public func markStepCancelled(stepId: MorningFlowStepId) {
        if let idx = morningFlowSteps.firstIndex(where: { $0.step == stepId }) {
            morningFlowSteps[idx].status = .cancelled
            morningFlowSteps[idx].finishedAt = Date()
            if let started = morningFlowSteps[idx].startedAt {
                morningFlowSteps[idx].durationSeconds = Date().timeIntervalSince(started)
            }
        }
        cancelRemainingSteps(after: stepId)
    }

    public func cancelRemainingSteps(after: MorningFlowStepId) {
        for i in 0..<morningFlowSteps.count {
            if morningFlowSteps[i].step.rawValue > after.rawValue && morningFlowSteps[i].status == .pending {
                morningFlowSteps[i].status = .cancelled
            }
        }
    }

    // MARK: - Scheduler Status & Installation (İP-10)
    public func checkSchedulerStatus() async {
        do {
            let res = try await cliRunner.runCommand(arguments: ["zamanla", "durum", "--json"])
            if let data = res.stdout.data(using: .utf8) {
                let response = try? JSONDecoder().decode(SchedulerStatusResponse.self, from: data)
                let installed = response?.agents.allSatisfy { $0.isInstalled } ?? false
                self.isSchedulerInstalled = installed
                self.hasUninstalledSchedulerWarning = !installed
            }
        } catch {
            self.hasUninstalledSchedulerWarning = false
        }
    }

    public func installScheduler(confirm: Bool) async -> Bool {
        guard confirm else { return false }
        do {
            let res = try await cliRunner.runCommand(arguments: ["zamanla", "kur"])
            await checkSchedulerStatus()
            return res.isSuccess
        } catch {
            CockpitLogger.shared.error("Scheduler install failed: \(error.localizedDescription)")
            return false
        }
    }

    public func openSafariLoginURL() {
        let urlStr = loginAuthURL ?? activationURL
        if let urlStr, let url = URL(string: urlStr) {
            #if os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }

    public func openActivationURLInSafari() {
        openSafariLoginURL()
    }

    public func openSafariLogin() {
        startCLILogin()
    }

    public func verifySessionAfterLogin() async {
        isVerifyingSession = true
        await checkSession()
        isVerifyingSession = false

        if isSessionActive == true {
            loginPromptMessage = "✓ Scalable Capital session successfully verified!"
            hasWaitingAuthAlert = false
        } else {
            loginPromptMessage = "Session does not appear active yet. Please complete the login and 2FA approval in your browser, then click 'Verify Session' again."
        }
    }

    // MARK: - Streaming Data Refresh (masa veri + masa gecmis)
    public func refreshData() async {
        guard !isRefreshingData else { return }
        isRefreshingData = true
        streamingLogs.removeAll()
        streamingLogs.append("[\(currentTimeString())] Data pipeline starting (masa veri)...")

        var veriExitCode: Int32 = 0
        var gecmisExitCode: Int32 = 0

        do {
            for try await chunk in cliRunner.runStream(arguments: ["veri"]) {
                switch chunk {
                case .exit(let code):
                    veriExitCode = code
                case .stdout(let text), .stderr(let text):
                    let lines = text.components(separatedBy: .newlines).filter { !$0.isEmpty }
                    for line in lines {
                        streamingLogs.append(line)
                    }
                }
            }

            if veriExitCode == 1 {
                streamingLogs.append("[\(currentTimeString())] ERROR: Data fetch failed: session required.")
                loginPromptMessage = "Data fetch failed: session required"
                isRefreshingData = false
                return
            } else if veriExitCode == 2 {
                streamingLogs.append("[\(currentTimeString())] WARNING: Partial data: Quotes missing or market closed (DEGRADED).")
                loginPromptMessage = "Partial data: Quotes missing or OUTDATED"
            }

            streamingLogs.append("[\(currentTimeString())] Updating historical price series (masa gecmis)...")
            for try await chunk in cliRunner.runStream(arguments: ["gecmis"]) {
                switch chunk {
                case .exit(let code):
                    gecmisExitCode = code
                case .stdout(let text), .stderr(let text):
                    let lines = text.components(separatedBy: .newlines).filter { !$0.isEmpty }
                    for line in lines {
                        streamingLogs.append(line)
                    }
                }
            }

            if veriExitCode == 0 && gecmisExitCode == 0 {
                streamingLogs.append("[\(currentTimeString())] Running portfolio evaluation (masa degerlendir)...")
                let degResult = try await cliRunner.runCommand(arguments: ["degerlendir", "--json"])
                if degResult.isSuccess {
                    streamingLogs.append("[\(currentTimeString())] Evaluation successfully sealed.")
                }
                streamingLogs.append("[\(currentTimeString())] Data refresh and evaluation completed successfully.")
                loginPromptMessage = "✓ Data refresh completed successfully."
            } else if veriExitCode == 2 && gecmisExitCode == 0 {
                streamingLogs.append("[\(currentTimeString())] Running portfolio evaluation (masa degerlendir)...")
                _ = try? await cliRunner.runCommand(arguments: ["degerlendir", "--json"])
                streamingLogs.append("[\(currentTimeString())] Completed with partial data (DEGRADED).")
                // Keep partial notice in prompt
            } else {
                streamingLogs.append("[\(currentTimeString())] Data pipeline completed with partial errors.")
                loginPromptMessage = "Data pipeline completed with partial errors."
            }
            await loadData()
        } catch {
            streamingLogs.append("[\(currentTimeString())] ERROR: \(error.localizedDescription)")
            loginPromptMessage = "Data refresh error: \(error.localizedDescription)"
            CockpitLogger.shared.error("Refresh data failed: \(error.localizedDescription)")
        }

        isRefreshingData = false
    }

    // MARK: - Portfolio Summary & Alerts
    private func loadPortfolioSummary() async {
        do {
            let summary = try await databaseService.fetchPortfolioSummary()
            totalEur = NSDecimalNumber(decimal: summary.totalValueEur).doubleValue
            cashEur = NSDecimalNumber(decimal: summary.totalCashEur).doubleValue
            positionsCount = summary.positions.count
            positions = summary.positions
            quotes = (try? await databaseService.fetchQuotes()) ?? []
        } catch {
            CockpitLogger.shared.error("Failed to fetch portfolio summary: \(error.localizedDescription)")
        }
    }

    private func checkIntegrityAndAlerts() async {
        do {
            let jobs = try await databaseService.fetchJobs()
            hasWaitingAuthAlert = jobs.contains(where: { $0.status.uppercased() == "WAITING_AUTH" })
        } catch {
            CockpitLogger.shared.error("Failed to check waiting_auth jobs: \(error.localizedDescription)")
        }
    }

    public func updateXetraStatus() {
        let status = Self.checkIsXetraOpen()
        isXetraOpen = status.isOpen
        xetraStatusText = status.text
    }

    public static func checkIsXetraOpen(at date: Date = Date()) -> (isOpen: Bool, text: String) {
        var cal = Calendar(identifier: .gregorian)
        guard let tz = TimeZone(identifier: "Europe/Berlin") else {
            return (false, "Xetra Closed (Timezone error)")
        }
        cal.timeZone = tz
        let weekday = cal.component(.weekday, from: date)
        // 1 = Sunday, 7 = Saturday
        if weekday == 1 || weekday == 7 {
            return (false, "Xetra Closed (Weekend)")
        }
        let hour = cal.component(.hour, from: date)
        let minute = cal.component(.minute, from: date)
        let timeInMinutes = hour * 60 + minute
        let openTime = 9 * 60        // 09:00 CET
        let closeTime = 17 * 60 + 30  // 17:30 CET

        if timeInMinutes >= openTime && timeInMinutes <= closeTime {
            return (true, "Xetra Open (09:00 - 17:30 CET)")
        } else {
            return (false, "Xetra Closed (Trading Hours: 09:00 - 17:30 CET)")
        }
    }

    public var lastUpdatedDateText: String {
        guard let d = lastUpdatedDate else { return "Not Sealed Yet" }
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }

    private func currentTimeString() -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: Date())
    }
}
