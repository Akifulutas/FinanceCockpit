import SwiftUI

public struct SystemIntegrityView: View {
    @ObservedObject public var viewModel: SystemIntegrityViewModel
    @State private var selectedEvent: AuditEventItem?
    @State private var isDetailSheetPresented: Bool = false

    public init(viewModel: SystemIntegrityViewModel) {
        self.viewModel = viewModel
    }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // MARK: - Header & Action Bar
                headerSection

                // MARK: - Feedback Banners
                feedbackBannersSection

                // MARK: - KPI / Diagnostic Metric Cards
                diagnosticCardsSection

                // MARK: - Cryptographic Chain Details
                cryptographicChainsSection

                // MARK: - Backup & Security Scan Results
                operationsStatusSection

                // MARK: - Audit Events Log
                auditEventsTableSection
            }
            .padding(20)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            if viewModel.auditEvents.isEmpty {
                await viewModel.loadData()
            }
        }
        .sheet(item: $selectedEvent) { event in
            auditEventDetailSheet(event: event)
        }
    }

    // MARK: - Subviews

    private var headerSection: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("System Integrity & Cryptographic Audit")
                        .font(.system(size: 20, weight: .bold))

                    if let result = viewModel.integrityResult {
                        StatusPillView(
                            text: result.ok ? "Integrity Verified" : "Integrity Breach",
                            level: result.ok ? .success : .error,
                            icon: result.ok ? "checkmark.shield.fill" : "xmark.shield.fill"
                        )
                    } else {
                        StatusPillView(
                            text: "Pending Verification",
                            level: .neutral,
                            icon: "shield"
                        )
                    }
                }

                if let date = viewModel.lastVerifiedDate {
                    Text("Last Verified: \(Formatters.formatISO8601(date.ISO8601Format()))")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Born-Sealed SHA-256 Cryptographic Audit Center")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            // Verification Action Bar
            HStack(spacing: 10) {
                Button {
                    Task { await viewModel.runAuditVerification() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isVerifying {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "checkmark.seal.fill")
                        }
                        Text("Verify Integrity")
                    }
                }
                .disabled(viewModel.isVerifying || viewModel.isBackingUp || viewModel.isScanning)

                Menu {
                    Button("Create Live Backup") {
                        Task { await viewModel.runBackup(drillOnly: false) }
                    }
                    Button("Backup & Verification Drill") {
                        Task { await viewModel.runBackup(drillOnly: true) }
                    }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isBackingUp {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "externaldrive.fill.badge.plus")
                        }
                        Text("Backup")
                    }
                }
                .disabled(viewModel.isBackingUp || viewModel.isVerifying)

                Button {
                    Task { await viewModel.runSecurityScan() }
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isScanning {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "lock.shield.fill")
                        }
                        Text("Security Audit")
                    }
                }
                .disabled(viewModel.isScanning || viewModel.isVerifying)

                Button {
                    Task { await viewModel.loadData() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Reload")
            }
        }
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

    private var diagnosticCardsSection: some View {
        HStack(spacing: 12) {
            MetricCardView(
                title: "System Integrity",
                value: viewModel.integrityResult != nil ? (viewModel.isIntegrityValid ? "VALID" : "CORRUPT") : "UNTESTED",
                subtitle: viewModel.integrityResult != nil ? (viewModel.isIntegrityValid ? "0 Cryptographic Errors" : "Critical Violation!") : "Verification required",
                trend: viewModel.integrityResult != nil ? (viewModel.isIntegrityValid ? .up : .down) : nil,
                badge: "SHA-256",
                badgeColor: viewModel.isIntegrityValid ? .green : .red
            )

            MetricCardView(
                title: "Disk Encryption",
                value: viewModel.fileVaultActive ? "ACTIVE" : "CHECK",
                subtitle: "APFS XTS-AES 128/256",
                trend: nil,
                badge: "FileVault",
                badgeColor: viewModel.fileVaultActive ? .green : .orange
            )

            MetricCardView(
                title: "Active Triggers",
                value: "\(viewModel.triggerCount) / 78",
                subtitle: "Schema v\(viewModel.schemaVersion) Guard",
                trend: nil,
                badge: "Triggers",
                badgeColor: viewModel.triggerCount == 78 ? .blue : .red
            )

            MetricCardView(
                title: "Audit Records",
                value: "\(viewModel.auditEventsCount)",
                subtitle: "\(viewModel.snapshotsCount) Sealed Snapshots",
                trend: nil,
                badge: "EVENTS"
            )

            MetricCardView(
                title: "Secret Key Scan",
                value: "\(viewModel.securityScanResult?.gitleaksLeaksCount ?? 0) Leaks",
                subtitle: "Gitleaks & POSIX 0700/0600",
                trend: (viewModel.securityScanResult?.gitleaksLeaksCount ?? 0) == 0 ? .up : .down,
                badge: "Gitleaks",
                badgeColor: (viewModel.securityScanResult?.gitleaksLeaksCount ?? 0) == 0 ? .green : .red
            )
        }
    }

    private var cryptographicChainsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Cryptographic Hash Chain Seal Status")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.secondary)

            HStack(spacing: 16) {
                // Snapshot Chain Card
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Image(systemName: "link.circle.fill")
                            .foregroundStyle(viewModel.snapshotChainOk ? .green : .secondary)
                        Text("Snapshot Hash Chain")
                            .font(.system(size: 12, weight: .semibold))
                        Spacer()
                        StatusPillView(
                            text: viewModel.snapshotChainOk ? "Verified" : "Pending",
                            level: viewModel.snapshotChainOk ? .success : .neutral
                        )
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Live Chain Tip:")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                        HStack {
                            Text(viewModel.chainTip.isEmpty ? "—" : Formatters.formatTruncatedHash(viewModel.chainTip))
                                .font(.system(size: 11, design: .monospaced))
                            Spacer()
                            if !viewModel.chainTip.isEmpty {
                                Button {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(viewModel.chainTip, forType: .string)
                                } label: {
                                    Image(systemName: "doc.on.doc")
                                        .font(.system(size: 10))
                                }
                                .buttonStyle(.plain)
                                .help("Copy Hash")
                            }
                        }

                        Text("Sealed Tip (chain-tips.jsonl):")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                            .padding(.top, 2)
                        Text(viewModel.sealedSnapshotTip.isEmpty ? "—" : Formatters.formatTruncatedHash(viewModel.sealedSnapshotTip))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.secondary)

                        HStack {
                            Text("Status:")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.secondary)
                            Text(viewModel.chainTipStatus)
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .foregroundStyle(viewModel.chainTipStatus == "MATCH" ? .green : .orange)
                        }
                        .padding(.top, 2)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

                // Audit Chain Card
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Image(systemName: "shield.lefthalf.filled")
                            .foregroundStyle(viewModel.auditChainOk ? .green : .secondary)
                        Text("Audit Trail Chain")
                            .font(.system(size: 12, weight: .semibold))
                        Spacer()
                        StatusPillView(
                            text: viewModel.auditChainOk ? "Verified" : "Pending",
                            level: viewModel.auditChainOk ? .success : .neutral
                        )
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Latest Audit Event Hash:")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                        HStack {
                            let lastEventHash = viewModel.auditEvents.first?.currHash ?? ""
                            Text(lastEventHash.isEmpty ? "—" : Formatters.formatTruncatedHash(lastEventHash))
                                .font(.system(size: 11, design: .monospaced))
                            Spacer()
                            if !lastEventHash.isEmpty {
                                Button {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(lastEventHash, forType: .string)
                                } label: {
                                    Image(systemName: "doc.on.doc")
                                        .font(.system(size: 10))
                                }
                                .buttonStyle(.plain)
                                .help("Copy Hash")
                            }
                        }

                        Text("Sealed Audit Tip:")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                            .padding(.top, 2)
                        Text(viewModel.sealedAuditTip.isEmpty ? "—" : Formatters.formatTruncatedHash(viewModel.sealedAuditTip))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.secondary)

                        HStack {
                            Text("Total Verified Events:")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.secondary)
                            Text("\(viewModel.auditEventsCount) events")
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .foregroundStyle(.primary)
                        }
                        .padding(.top, 2)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            }
        }
    }

    private var operationsStatusSection: some View {
        HStack(alignment: .top, spacing: 16) {
            // Backup Manager Card
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: "archivebox.fill")
                        .foregroundStyle(.blue)
                    Text("Latest Backup & Disaster Recovery")
                        .font(.system(size: 12, weight: .semibold))
                    Spacer()
                    if let backup = viewModel.backupResult {
                        StatusPillView(
                            text: backup.isSuccess ? "Backup Created" : "Error",
                            level: backup.isSuccess ? .success : .error
                        )
                    }
                }

                Divider()

                if let backup = viewModel.backupResult {
                    VStack(alignment: .leading, spacing: 4) {
                        if let path = backup.backupFilePath {
                            Text("Path: \(path)")
                                .font(.system(size: 10, design: .monospaced))
                                .lineLimit(1)
                        }
                        if let sha = backup.sha256 {
                            Text("SHA-256: \(Formatters.formatTruncatedHash(sha))")
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Text("Restore Drill:")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.secondary)
                            Text(backup.restoreDrillOk ? "✓ Passed (quick_check OK)" : "Not Drilled")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(backup.restoreDrillOk ? .green : .secondary)
                        }
                    }
                } else {
                    Text("No live backup initiated yet. Trigger a drill or full backup from the 'Backup' menu.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

            // POSIX & Permissions Card
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: "lock.laptopcomputer")
                        .foregroundStyle(.purple)
                    Text("POSIX Permissions & Security")
                        .font(.system(size: 12, weight: .semibold))
                    Spacer()
                    if let scan = viewModel.securityScanResult {
                        StatusPillView(
                            text: scan.permissionsOk ? "0700/0600 Compliant" : "Permission Warning",
                            level: scan.permissionsOk ? .success : .warning
                        )
                    }
                }

                Divider()

                if let scan = viewModel.securityScanResult {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Directory Permissions: 0700 (drwx------)")
                            .font(.system(size: 10, design: .monospaced))
                        Text("Database Files: 0600 (-rw-------)")
                            .font(.system(size: 10, design: .monospaced))
                        Text("Gitleaks Scan: \(scan.gitleaksLeaksCount) leaks")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(scan.gitleaksLeaksCount == 0 ? .green : .red)
                    }
                } else {
                    Text("Security scan not executed yet. Trigger POSIX permission and secret checks via 'Security Audit'.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    private var auditEventsTableSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Table Filters
            HStack(spacing: 12) {
                Text("Audit Events Ledger")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.secondary)

                Spacer()

                // Action Filter Picker
                Picker("Action", selection: $viewModel.selectedActionFilter) {
                    ForEach(viewModel.availableActionTypes, id: \.self) { act in
                        Text(act).tag(act)
                    }
                }
                .frame(width: 140)

                // Search field
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("Search audit events...", text: $viewModel.searchText)
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
                .frame(width: 250)
            }

            // Table
            VStack(spacing: 0) {
                // Header
                HStack(spacing: 12) {
                    Text("ID / Timestamp")
                        .frame(width: 140, alignment: .leading)
                    Text("Actor")
                        .frame(width: 100, alignment: .leading)
                    Text("Action")
                        .frame(width: 120, alignment: .leading)
                    Text("Entity")
                        .frame(width: 140, alignment: .leading)
                    Text("Prev Hash")
                        .frame(width: 110, alignment: .leading)
                    Text("Curr Hash")
                        .frame(width: 110, alignment: .leading)
                    Text("Details")
                        .frame(width: 50, alignment: .center)
                }
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.primary.opacity(0.03))

                Divider()

                if viewModel.filteredAuditEvents.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "tray")
                            .font(.system(size: 24))
                            .foregroundStyle(.secondary)
                        Text("No audit events recorded.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    ForEach(viewModel.filteredAuditEvents) { event in
                        auditEventRow(event: event)
                        Divider()
                    }
                }
            }
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    private func auditEventRow(event: AuditEventItem) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("#\(event.eventId)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                Text(Formatters.formatISO8601(event.eventTime))
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
            }
            .frame(width: 140, alignment: .leading)

            Text(event.actor)
                .font(.system(size: 11, weight: .medium))
                .frame(width: 100, alignment: .leading)

            StatusPillView(
                text: event.action,
                level: actionLevel(for: event.action),
                showIcon: false
            )
            .frame(width: 120, alignment: .leading)

            VStack(alignment: .leading, spacing: 1) {
                Text(event.entityType)
                    .font(.system(size: 10, weight: .semibold))
                Text(event.entityId)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .frame(width: 140, alignment: .leading)

            Text(Formatters.formatTruncatedHash(event.prevHash))
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
                .frame(width: 110, alignment: .leading)

            Text(Formatters.formatTruncatedHash(event.currHash))
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(.primary)
                .frame(width: 110, alignment: .leading)

            Button {
                selectedEvent = event
            } label: {
                Image(systemName: "info.circle")
            }
            .buttonStyle(.plain)
            .frame(width: 50, alignment: .center)
            .help("Inspect JSON Payload")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private func actionLevel(for action: String) -> StatusLevel {
        let upper = action.uppercased()
        if upper.contains("DELETE") || upper.contains("REVOKE") || upper.contains("FAIL") {
            return .error
        } else if upper.contains("UPDATE") || upper.contains("REVISE") {
            return .warning
        } else if upper.contains("INSERT") || upper.contains("CREATE") || upper.contains("SEAL") {
            return .success
        } else {
            return .info
        }
    }

    private func auditEventDetailSheet(event: AuditEventItem) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Audit Event Details (#\(event.eventId))")
                    .font(.system(size: 15, weight: .bold))
                Spacer()
                Button("Close") {
                    selectedEvent = nil
                }
            }

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                detailRow(label: "Event UUID", value: event.eventUuid)
                detailRow(label: "Timestamp", value: event.eventTime)
                detailRow(label: "Actor", value: event.actor)
                detailRow(label: "Action", value: event.action)
                detailRow(label: "Entity Type", value: event.entityType)
                detailRow(label: "Entity ID", value: event.entityId)
                detailRow(label: "Prev Hash", value: event.prevHash)
                detailRow(label: "Curr Hash", value: event.currHash)
            }

            Text("JSON Payload:")
                .font(.system(size: 11, weight: .bold))
                .padding(.top, 4)

            ScrollView {
                Text(event.payloadJson ?? "{}")
                    .font(.system(size: 11, design: .monospaced))
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .textBackgroundColor)))
            }
            .frame(maxHeight: 180)
        }
        .padding(20)
        .frame(minWidth: 500, minHeight: 420)
    }

    private func detailRow(label: String, value: String) -> some View {
        HStack(alignment: .top) {
            Text(label + ":")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .frame(width: 100, alignment: .leading)
            Text(value)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.primary)
                .textSelection(.enabled)
        }
    }
}
