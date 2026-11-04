import SwiftUI
import Combine

public struct ReportFileItem: Identifiable, Sendable, Equatable, Hashable {
    public var id: String { fileName }
    public let fileName: String
    public let filePath: String
    public let modifiedDate: Date
    public let title: String
    public let reportType: String

    public init(fileName: String, filePath: String, modifiedDate: Date) {
        self.fileName = fileName
        self.filePath = filePath
        self.modifiedDate = modifiedDate

        if fileName.contains("yorum-paketi") {
            self.title = "Commentary Package"
            self.reportType = "COMMENTARY"
        } else if fileName.contains("tradingagents") {
            self.title = "TradingAgents Report"
            self.reportType = "AGENT"
        } else if fileName.contains("arastirma") {
            self.title = "Instrument Research Report"
            self.reportType = "RESEARCH"
        } else {
            self.title = "Portfolio Status Report"
            self.reportType = "REPORT"
        }
    }
}

/// ViewModel driving the "Rapor ve Yorum" screen (E4).
/// Reads local markdown reports from `var/reports/` and allows generation of new reports and commentary packages.
@MainActor
public final class ReportsViewModel: ObservableObject {

    // MARK: - Published State
    @Published public var reports: [ReportFileItem] = []
    @Published public var selectedReport: ReportFileItem? = nil
    @Published public var reportContent: String = ""
    @Published public var isLoading: Bool = false
    @Published public var errorMessage: String? = nil

    @Published public var isGeneratingReport: Bool = false
    @Published public var isGeneratingCommentary: Bool = false
    @Published public var actionFeedbackMessage: String? = nil

    // MARK: - Dependencies
    private let reportsDirectory: String
    private let cliRunner: CLIProcessRunnerProtocol

    public init(
        reportsDirectory: String = CockpitPathResolver.defaultReportsDirectory,
        cliRunner: CLIProcessRunnerProtocol
    ) {
        self.reportsDirectory = reportsDirectory
        self.cliRunner = cliRunner
    }

    // MARK: - Load Reports
    public func loadReports() async {
        isLoading = true
        errorMessage = nil

        var items: [ReportFileItem] = []
        let fm = FileManager.default

        if fm.fileExists(atPath: reportsDirectory) {
            do {
                let fileNames = try fm.contentsOfDirectory(atPath: reportsDirectory)
                for name in fileNames where name.hasSuffix(".md") {
                    let fullPath = (reportsDirectory as NSString).appendingPathComponent(name)
                    let attrs = try? fm.attributesOfItem(atPath: fullPath)
                    let modDate = (attrs?[.modificationDate] as? Date) ?? Date.distantPast
                    items.append(ReportFileItem(fileName: name, filePath: fullPath, modifiedDate: modDate))
                }
            } catch {
                errorMessage = "Failed to read reports directory: \(error.localizedDescription)"
                CockpitLogger.shared.error("Failed to read reports directory: \(error.localizedDescription)")
            }
        }

        // Sort descending by modification date
        items.sort { $0.modifiedDate > $1.modifiedDate }
        reports = items

        if selectedReport == nil || !items.contains(where: { $0.id == selectedReport?.id }) {
            selectedReport = items.first
        }

        if let selected = selectedReport {
            await selectReport(selected)
        } else {
            reportContent = ""
        }

        isLoading = false
    }

    public func selectReport(_ item: ReportFileItem) async {
        selectedReport = item
        do {
            let content = try String(contentsOfFile: item.filePath, encoding: .utf8)
            reportContent = content
        } catch {
            reportContent = "Failed to read file content: \(error.localizedDescription)"
        }
    }

    // MARK: - Actions (masa rapor & masa yorum)
    public func generateNewReport() async {
        isGeneratingReport = true
        actionFeedbackMessage = "Compiling status report (masa rapor)..."
        do {
            let result = try await cliRunner.runCommand(arguments: ["rapor"])
            if result.isSuccess {
                actionFeedbackMessage = "✓ Status report generated successfully."
                await loadReports()
            } else {
                actionFeedbackMessage = "Error: \(result.message)"
            }
        } catch {
            actionFeedbackMessage = "Error: \(error.localizedDescription)"
        }
        isGeneratingReport = false
    }

    public func generateCommentaryPackage() async {
        isGeneratingCommentary = true
        actionFeedbackMessage = "Generating commentary package (masa yorum)..."
        do {
            let result = try await cliRunner.runCommand(arguments: ["yorum"])
            if result.isSuccess {
                actionFeedbackMessage = "✓ Commentary package generated successfully."
                await loadReports()
            } else {
                actionFeedbackMessage = "Error: \(result.message)"
            }
        } catch {
            actionFeedbackMessage = "Error: \(error.localizedDescription)"
        }
        isGeneratingCommentary = false
    }
}
