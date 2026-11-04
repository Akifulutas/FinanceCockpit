import SwiftUI
import Combine

@MainActor
public final class SchedulerAutomationViewModel: ObservableObject {
    // MARK: - Injected Dependencies
    public let databaseService: DatabaseServiceProtocol
    public let cliRunner: CLIProcessRunnerProtocol

    // MARK: - Published State
    @Published public var launchdAgents: [LaunchdAgentItem] = []
    @Published public var jobs: [JobQueueItem] = []

    @Published public var isLoading: Bool = false
    @Published public var isExecutingAction: Bool = false
    @Published public var statusMessage: String?
    @Published public var errorMessage: String?
    @Published public var lastActionResult: CLIOperationResult?
    @Published public var lastRefreshDate: Date?

    @Published public var selectedJobFilter: String = "ALL"
    @Published public var searchText: String = ""

    // MARK: - Initializer
    public init(
        databaseService: DatabaseServiceProtocol,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.databaseService = databaseService
        self.cliRunner = cliRunner
        self.launchdAgents = Self.defaultLaunchdAgents()
    }

    // MARK: - Default Launchd Configuration
    public static func defaultLaunchdAgents() -> [LaunchdAgentItem] {
        [
            LaunchdAgentItem(
                label: "com.etf.masa.sabah",
                description: "Morning Forecast Engine (5 ETFs + 5 Equities)",
                schedule: "Mon-Fri 09:30 CET",
                isInstalled: false,
                isActive: false,
                lastExitCode: nil
            ),
            LaunchdAgentItem(
                label: "com.etf.masa.aksam",
                description: "Evening Settlement & Dashboard Refresh",
                schedule: "Mon-Fri 17:40 CET",
                isInstalled: false,
                isActive: false,
                lastExitCode: nil
            ),
            LaunchdAgentItem(
                label: "com.etf.masa.cuma",
                description: "Weekly Model Performance Scorecard",
                schedule: "Fri 18:00 CET",
                isInstalled: false,
                isActive: false,
                lastExitCode: nil
            )
        ]
    }

    // MARK: - Computed Properties

    public var waitingAuthJobs: [JobQueueItem] {
        jobs.filter { $0.status.uppercased() == "WAITING_AUTH" }
    }

    public var hasWaitingAuthAlert: Bool {
        !waitingAuthJobs.isEmpty
    }

    public var pendingJobsCount: Int {
        jobs.filter {
            let s = $0.status.uppercased()
            return s == "PENDING" || s == "QUEUED"
        }.count
    }

    public var runningJobsCount: Int {
        jobs.filter {
            let s = $0.status.uppercased()
            return s == "RUNNING" || s == "COLLECTING" || s == "CALCULATING" || s == "RESEARCHING" || s == "VALIDATING"
        }.count
    }

    public var failedJobsCount: Int {
        jobs.filter {
            let s = $0.status.uppercased()
            return s == "FAILED" || s == "DEAD_LETTER" || s == "NEEDS_REVIEW"
        }.count
    }

    public var completedJobsCount: Int {
        jobs.filter {
            let s = $0.status.uppercased()
            return s == "SUCCESS" || s == "PUBLISHED" || s == "COMPLETED"
        }.count
    }

    public var filteredJobs: [JobQueueItem] {
        var items = jobs

        // Status Filter
        switch selectedJobFilter.uppercased() {
        case "ALL":
            break
        case "WAITING_AUTH":
            items = items.filter { $0.status.uppercased() == "WAITING_AUTH" }
        case "PENDING":
            items = items.filter { $0.status.uppercased() == "PENDING" || $0.status.uppercased() == "QUEUED" }
        case "RUNNING":
            items = items.filter {
                let s = $0.status.uppercased()
                return s == "RUNNING" || s == "COLLECTING" || s == "CALCULATING" || s == "RESEARCHING" || s == "VALIDATING"
            }
        case "FAILED":
            items = items.filter {
                let s = $0.status.uppercased()
                return s == "FAILED" || s == "DEAD_LETTER" || s == "NEEDS_REVIEW"
            }
        case "COMPLETED":
            items = items.filter {
                let s = $0.status.uppercased()
                return s == "SUCCESS" || s == "PUBLISHED" || s == "COMPLETED"
            }
        default:
            items = items.filter { $0.status.localizedCaseInsensitiveCompare(selectedJobFilter) == .orderedSame }
        }

        // Search text
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !query.isEmpty {
            items = items.filter {
                $0.jobId.lowercased().contains(query) ||
                $0.jobType.lowercased().contains(query) ||
                ($0.dedupKey?.lowercased().contains(query) ?? false) ||
                ($0.errorMessage?.lowercased().contains(query) ?? false)
            }
        }

        return items
    }

    // MARK: - Actions

    public func loadScheduleStatus() async {
        do {
            let res = try await cliRunner.runCommand(arguments: ["zamanla", "durum", "--json"])
            if res.isSuccess, let data = res.stdout.data(using: .utf8) {
                let response = try JSONDecoder().decode(SchedulerStatusResponse.self, from: data)
                self.launchdAgents = response.agents
            }
        } catch {
            CockpitLogger.shared.error("Failed to load scheduler status: \(error.localizedDescription)")
        }
    }

    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            async let queueJobsTask = databaseService.fetchJobs()
            async let scheduleStatusTask: () = loadScheduleStatus()

            let (queueJobs, _) = try await (queueJobsTask, scheduleStatusTask)
            self.jobs = queueJobs
            self.lastRefreshDate = Date()
            self.isLoading = false
        } catch {
            self.errorMessage = "Failed to load work queue: \(error.localizedDescription)"
            self.isLoading = false
        }
    }

    public func installLaunchdAgents() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Installing and starting LaunchAgent daemons..."
        do {
            let result = try await cliRunner.runSchedulerAction(agent: "all", action: "kur")
            self.lastActionResult = result
            if result.isSuccess {
                self.statusMessage = "LaunchAgent services successfully installed and activated."
                await loadScheduleStatus()
            } else {
                self.errorMessage = "Failed to install services: \(result.message)"
            }
        } catch {
            self.errorMessage = "Installation failed: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func uninstallLaunchdAgents() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Stopping and unloading LaunchAgent daemons..."
        do {
            let result = try await cliRunner.runSchedulerAction(agent: "all", action: "kaldir")
            self.lastActionResult = result
            if result.isSuccess {
                self.statusMessage = "LaunchAgent services removed."
                await loadScheduleStatus()
            } else {
                self.errorMessage = "Failed to remove services: \(result.message)"
            }
        } catch {
            self.errorMessage = "Removal failed: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func sendNotificationTest() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Sending test notification..."
        do {
            let result = try await cliRunner.runSchedulerAction(agent: "test", action: "bildirim-test")
            self.lastActionResult = result
            if result.isSuccess {
                self.statusMessage = "Test notification sent to macOS Notification Center."
            } else {
                self.errorMessage = "Failed to send notification: \(result.message)"
            }
        } catch {
            self.errorMessage = "Notification test failed: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func runAgentManually(agentLabel: String) async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Running \(agentLabel) manually..."

        do {
            let result: CLIOperationResult
            if agentLabel.contains("sabah") {
                result = try await cliRunner.runForecastMorning()
            } else if agentLabel.contains("aksam") {
                result = try await cliRunner.runSettleEvening()
            } else if agentLabel.contains("cuma") {
                result = try await cliRunner.runCommand(arguments: ["tahmin", "karne", "--detay"])
            } else {
                self.errorMessage = "Unknown scheduler agent: \(agentLabel)"
                isExecutingAction = false
                return
            }

            self.lastActionResult = result
            if result.isSuccess {
                self.statusMessage = "\(agentLabel) completed successfully."
                await loadData()
            } else {
                self.errorMessage = "Job execution failed: \(result.message)"
            }
        } catch {
            self.errorMessage = "Execution error: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }

    public func resolveWaitingAuth() async {
        isExecutingAction = true
        errorMessage = nil
        statusMessage = "Validating Scalable Capital session..."
        do {
            let result = try await cliRunner.runCommand(arguments: ["kontrol"])
            self.lastActionResult = result
            if result.isSuccess {
                self.statusMessage = "Broker session verified. Updating work queue."
                await loadData()
            } else {
                self.errorMessage = "Broker session could not be verified. Please run './etf-masa giris' from terminal."
            }
        } catch {
            self.errorMessage = "Session refresh error: \(error.localizedDescription)"
        }
        isExecutingAction = false
    }
}
