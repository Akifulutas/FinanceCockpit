import SwiftUI

public struct SchedulerAutomationView: View {
    @ObservedObject public var viewModel: SchedulerAutomationViewModel
    @State private var selectedJob: JobQueueItem? = nil

    public init(viewModel: SchedulerAutomationViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header
                headerSection

                // MARK: - Critical WAITING_AUTH Alert Banner
                if viewModel.hasWaitingAuthAlert {
                    waitingAuthAlertBanner
                }

                // MARK: - Feedback & Error Banners
                feedbackBannersSection

                // MARK: - KPI Metric Cards Row
                kpiSection

                // MARK: - Launchd Agents Control Cards
                launchdAgentsSection

                // MARK: - Work Queue Table
                jobsTableSection
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .sheet(item: $selectedJob) { job in
            jobDetailSheet(job: job)
        }
        .task {
            await viewModel.loadData()
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Scheduler & Task Automation")
                        .font(.system(size: 20, weight: .bold))

                    StatusPillView(
                        text: "\(viewModel.launchdAgents.filter(\.isActive).count)/\(viewModel.launchdAgents.count) Services Active",
                        level: viewModel.launchdAgents.allSatisfy(\.isActive) ? .success : .warning,
                        icon: "clock.badge.checkmark"
                    )
                }

                if let date = viewModel.lastRefreshDate {
                    Text("Last Queue Refresh: \(Formatters.formatISO8601(date.ISO8601Format()))")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                } else {
                    Text("macOS native launchd & asynchronous work queue management")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            // Header Action Buttons
            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.sendNotificationTest() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "bell.badge.fill")
                        Text("Notification Test")
                    }
                }
                .disabled(viewModel.isExecutingAction)

                Button {
                    Task { await viewModel.loadData() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isLoading {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                        Text("Refresh Queue")
                    }
                }
                .disabled(viewModel.isLoading || viewModel.isExecutingAction)
            }
        }
    }

    private var waitingAuthAlertBanner: some View {
        HStack(spacing: 12) {
            Image(systemName: "exclamationmark.octagon.fill")
                .font(.system(size: 24))
                .foregroundStyle(.orange)

            VStack(alignment: .leading, spacing: 2) {
                Text("Broker Session Expired (WAITING_AUTH)")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.orange)
                Text("Scalable Capital session has expired. \(viewModel.waitingAuthJobs.count) jobs in queue waiting for authentication.")
                    .font(.system(size: 11))
                    .foregroundStyle(.primary)
            }

            Spacer()

            Button {
                Task { await viewModel.resolveWaitingAuth() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "key.fill")
                    Text("Verify Session")
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.orange.opacity(0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(Color.orange.opacity(0.3), lineWidth: 1)
        )
    }

    private var feedbackBannersSection: some View {
        Group {
            if let error = viewModel.errorMessage {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                    Text(error)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.red)
                    Spacer()
                }
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.red.opacity(0.1)))
            }

            if let status = viewModel.statusMessage {
                HStack(spacing: 8) {
                    Image(systemName: "info.circle.fill")
                        .foregroundStyle(.blue)
                    Text(status)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.blue)
                    Spacer()
                }
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.blue.opacity(0.1)))
            }
        }
    }

    private var kpiSection: some View {
        HStack(spacing: 12) {
            MetricCardView(
                title: "LaunchAgent Daemons",
                value: "\(viewModel.launchdAgents.filter(\.isActive).count) / \(viewModel.launchdAgents.count)",
                subtitle: "macOS launchd background",
                trend: nil,
                badge: "launchctl",
                badgeColor: .blue
            )

            MetricCardView(
                title: "Queued Jobs",
                value: "\(viewModel.pendingJobsCount)",
                subtitle: "Pending execution",
                trend: nil,
                badge: "QUEUED"
            )

            MetricCardView(
                title: "Running Jobs",
                value: "\(viewModel.runningJobsCount)",
                subtitle: "In progress",
                trend: nil,
                badge: "RUNNING",
                badgeColor: .purple
            )

            MetricCardView(
                title: "Awaiting Auth",
                value: "\(viewModel.waitingAuthJobs.count)",
                subtitle: "WAITING_AUTH state",
                trend: viewModel.hasWaitingAuthAlert ? .down : nil,
                badge: "AUTH",
                badgeColor: viewModel.hasWaitingAuthAlert ? .orange : .green
            )

            MetricCardView(
                title: "Failed Jobs",
                value: "\(viewModel.failedJobsCount)",
                subtitle: "Requires inspection",
                trend: viewModel.failedJobsCount > 0 ? .down : .up,
                badge: "FAILED",
                badgeColor: viewModel.failedJobsCount > 0 ? .red : .green
            )
        }
    }

    private var launchdAgentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("macOS LaunchAgents Daemons")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                Spacer()

                Button {
                    Task { await viewModel.installLaunchdAgents() }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "arrow.down.doc.fill")
                        Text("Install Daemons (launchctl load)")
                    }
                }
                .disabled(viewModel.isExecutingAction)

                Button {
                    Task { await viewModel.uninstallLaunchdAgents() }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "trash")
                        Text("Uninstall (launchctl unload)")
                    }
                }
                .disabled(viewModel.isExecutingAction)
            }

            // Cards Grid
            HStack(spacing: 14) {
                ForEach(viewModel.launchdAgents) { agent in
                    launchdAgentCard(agent: agent)
                }
            }
        }
    }

    private func launchdAgentCard(agent: LaunchdAgentItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: agentIcon(for: agent.label))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.blue)

                Text(agent.label.replacingOccurrences(of: "com.etf.masa.", with: "").uppercased())
                    .font(.system(size: 12, weight: .bold, design: .rounded))

                Spacer()

                StatusPillView(
                    text: agent.isActive ? "Active" : (agent.isInstalled ? "Stopped" : "Not Installed"),
                    level: agent.isActive ? .success : (agent.isInstalled ? .warning : .neutral)
                )
            }

            Text(agent.description)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(2)

            Divider()

            HStack {
                Image(systemName: "calendar.badge.clock")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                Text(agent.schedule)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)

                Spacer()

                Button {
                    Task { await viewModel.runAgentManually(agentLabel: agent.label) }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "play.fill")
                            .font(.system(size: 8))
                        Text("Run")
                            .font(.system(size: 10))
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(viewModel.isExecutingAction)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
    }

    private func agentIcon(for label: String) -> String {
        if label.contains("sabah") { return "sun.horizon.fill" }
        if label.contains("aksam") { return "moon.stars.fill" }
        if label.contains("cuma") { return "chart.bar.doc.horizontal" }
        return "gearshape.2.fill"
    }

    private var jobsTableSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Filters and Search Bar
            HStack(spacing: 12) {
                Text("Asynchronous Work Queue (Work Queue State Machine)")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                Spacer()

                // Filter Picker
                Picker("Filter", selection: $viewModel.selectedJobFilter) {
                    Text("All (ALL)").tag("ALL")
                    Text("Pending").tag("PENDING")
                    Text("Running").tag("RUNNING")
                    Text("WAITING_AUTH").tag("WAITING_AUTH")
                    Text("Failed").tag("FAILED")
                    Text("Completed").tag("COMPLETED")
                }
                .frame(width: 160)

                // Search field
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search by Job ID or type...", text: $viewModel.searchText)
                        .textFieldStyle(.plain)
                    if !viewModel.searchText.isEmpty {
                        Button {
                            viewModel.searchText = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.1), lineWidth: 1))
                .frame(width: 220)
            }

            // Table View
            VStack(spacing: 0) {
                // Header
                HStack(spacing: 12) {
                    Text("Job ID")
                        .frame(width: 140, alignment: .leading)
                    Text("Job Type")
                        .frame(width: 130, alignment: .leading)
                    Text("Status")
                        .frame(width: 120, alignment: .leading)
                    Text("Retries")
                        .frame(width: 80, alignment: .center)
                    Text("Created At")
                        .frame(width: 120, alignment: .leading)
                    Text("Completed At")
                        .frame(width: 120, alignment: .leading)
                    Text("Details")
                        .frame(width: 50, alignment: .center)
                }
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.primary.opacity(0.03))

                Divider()

                if viewModel.filteredJobs.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "tray")
                            .font(.system(size: 24))
                            .foregroundStyle(.secondary)
                        Text("No jobs found in queue.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ForEach(viewModel.filteredJobs) { job in
                        jobRow(job: job)
                        Divider()
                    }
                }
            }
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    private func jobRow(job: JobQueueItem) -> some View {
        HStack(spacing: 12) {
            Text(job.jobId)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .frame(width: 140, alignment: .leading)
                .lineLimit(1)

            Text(job.jobType)
                .font(.system(size: 11, weight: .medium))
                .frame(width: 130, alignment: .leading)

            StatusPillView(
                text: job.status,
                level: jobStatusLevel(for: job.status),
                icon: jobStatusIcon(for: job.status)
            )
            .frame(width: 120, alignment: .leading)

            Text("\(job.retryCount)")
                .font(.system(size: 11, design: .monospaced))
                .frame(width: 80, alignment: .center)

            Text(Formatters.formatISO8601(job.createdAt))
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .frame(width: 120, alignment: .leading)

            Text(job.completedAt != nil ? Formatters.formatISO8601(job.completedAt) : "—")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .frame(width: 120, alignment: .leading)

            Button {
                selectedJob = job
            } label: {
                Image(systemName: "info.circle")
            }
            .buttonStyle(.plain)
            .frame(width: 50, alignment: .center)
            .help("Show Job Details")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private func jobStatusLevel(for status: String) -> StatusLevel {
        switch status.uppercased() {
        case "SUCCESS", "PUBLISHED", "COMPLETED":
            return .success
        case "WAITING_AUTH":
            return .warning
        case "FAILED", "DEAD_LETTER":
            return .error
        case "RUNNING", "COLLECTING", "CALCULATING", "RESEARCHING", "VALIDATING":
            return .info
        case "PENDING", "QUEUED":
            return .neutral
        default:
            return .neutral
        }
    }

    private func jobStatusIcon(for status: String) -> String {
        switch status.uppercased() {
        case "SUCCESS", "PUBLISHED", "COMPLETED":
            return "checkmark.circle.fill"
        case "WAITING_AUTH":
            return "key.horizontal.fill"
        case "FAILED", "DEAD_LETTER":
            return "exclamationmark.triangle.fill"
        case "RUNNING", "COLLECTING", "CALCULATING", "RESEARCHING", "VALIDATING":
            return "arrow.triangle.2.circlepath"
        default:
            return "clock.fill"
        }
    }

    private func jobDetailSheet(job: JobQueueItem) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Job Details: \(job.jobId)")
                    .font(.system(size: 15, weight: .bold))
                Spacer()
                Button("Close") {
                    selectedJob = nil
                }
            }

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                detailRow(label: "Job Type", value: job.jobType)
                detailRow(label: "Status", value: job.status)
                detailRow(label: "Idempotency (Dedup)", value: job.dedupKey ?? "None")
                detailRow(label: "Created At", value: job.createdAt)
                detailRow(label: "Started At", value: job.startedAt ?? "Not started")
                detailRow(label: "Completed At", value: job.completedAt ?? "Not completed")
                detailRow(label: "Retries", value: "\(job.retryCount)")
            }

            if let err = job.errorMessage, !err.isEmpty {
                Text("Error Message:")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.red)
                Text(err)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.red)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color.red.opacity(0.1)))
            }

            if let params = job.paramsJson, !params.isEmpty {
                Text("Parameters (Params JSON):")
                    .font(.system(size: 11, weight: .bold))
                ScrollView {
                    Text(params)
                        .font(.system(size: 10, design: .monospaced))
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .textBackgroundColor)))
                }
                .frame(maxHeight: 120)
            }
        }
        .padding(20)
        .frame(minWidth: 500, minHeight: 400)
    }

    private func detailRow(label: String, value: String) -> some View {
        HStack(alignment: .top) {
            Text(label + ":")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .frame(width: 140, alignment: .leading)
            Text(value)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.primary)
                .textSelection(.enabled)
        }
    }
}
