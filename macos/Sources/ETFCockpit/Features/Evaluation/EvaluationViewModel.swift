import SwiftUI
import Combine

/// ViewModel driving the "Değerlendirme" (Position Evaluation) screen (E2).
/// Displays rule-based recommendation tags (TUT, EKLE, AZALT), policy status,
/// German tax notes, and TradingAgents opinions with strict disclaimer enforcement.
@MainActor
public final class EvaluationViewModel: ObservableObject {

    // MARK: - Published State
    @Published public var assessments: [DegerlendirAssessmentDTO] = []
    @Published public var runId: String? = nil
    @Published public var warningMessage: String? = nil
    @Published public var isLoading: Bool = false
    @Published public var errorMessage: String? = nil

    @Published public var isRunningDeepAnalysis: Bool = false
    @Published public var deepAnalysisOutput: String? = nil
    @Published public var showDeepAnalysisConfirmation: Bool = false

    // MARK: - Dependencies
    private let cliRunner: CLIProcessRunnerProtocol

    public init(cliRunner: CLIProcessRunnerProtocol) {
        self.cliRunner = cliRunner
    }

    // MARK: - Load Data
    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            let result = try await cliRunner.runCommand(arguments: ["degerlendir", "--json"])
            if let data = result.stdout.data(using: .utf8) {
                let response = try JSONDecoder().decode(DegerlendirResponse.self, from: data)
                assessments = response.assessments
                runId = response.runId
                warningMessage = response.warning
            } else {
                errorMessage = "Failed to parse JSON output."
            }
        } catch {
            errorMessage = error.localizedDescription
            CockpitLogger.shared.error("Failed to load evaluation data: \(error.localizedDescription)")
        }
        isLoading = false
    }

    // MARK: - Deep Analysis Action
    public func triggerDeepAnalysis() async {
        isRunningDeepAnalysis = true
        deepAnalysisOutput = nil
        do {
            let result = try await cliRunner.runCommand(arguments: ["degerlendir"])
            deepAnalysisOutput = result.stdout.isEmpty ? result.stderr : result.stdout
            await loadData()
        } catch {
            errorMessage = "Deep analysis error: \(error.localizedDescription)"
            CockpitLogger.shared.error("Deep analysis failed: \(error.localizedDescription)")
        }
        isRunningDeepAnalysis = false
    }
}
