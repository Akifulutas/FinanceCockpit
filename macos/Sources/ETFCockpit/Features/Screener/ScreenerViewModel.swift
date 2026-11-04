import SwiftUI
import Combine

/// ViewModel driving the "Fırsat Taraması" (Opportunity Screener) screen (E3).
/// Interacts with `masa tarama --json` and provides candidate pool management (`masa ayar`).
@MainActor
public final class ScreenerViewModel: ObservableObject {

    // MARK: - Published State
    @Published public var candidates: [TaramaCandidateDTO] = []
    @Published public var poolCount: Int = 0
    @Published public var warningMessage: String? = nil
    @Published public var isLoading: Bool = false
    @Published public var errorMessage: String? = nil

    @Published public var selectedCandidate: TaramaCandidateDTO? = nil

    // Pool Editor State
    @Published public var showPoolEditor: Bool = false
    @Published public var poolISINsText: String = ""
    @Published public var poolEditorValidationMessage: String? = nil
    @Published public var isSavingPool: Bool = false

    // MARK: - Dependencies
    private let cliRunner: CLIProcessRunnerProtocol

    public init(cliRunner: CLIProcessRunnerProtocol) {
        self.cliRunner = cliRunner
    }

    // MARK: - Load Data (Read-only latest sealed scan)
    public func loadData() async {
        isLoading = true
        errorMessage = nil
        do {
            let result = try await cliRunner.runCommand(arguments: ["tarama", "--son", "--json"])
            if let data = result.stdout.data(using: .utf8) {
                let response = try JSONDecoder().decode(TaramaResponse.self, from: data)
                candidates = response.candidates
                poolCount = response.poolCount
                warningMessage = response.warning
                if selectedCandidate == nil {
                    selectedCandidate = candidates.first
                }
            } else {
                errorMessage = "Failed to parse screener JSON response."
            }
        } catch {
            errorMessage = error.localizedDescription
            CockpitLogger.shared.error("Failed to load screener data: \(error.localizedDescription)")
        }
        isLoading = false
    }

    // MARK: - Live Scan Execution
    public func triggerLiveScan() async {
        isLoading = true
        errorMessage = nil
        do {
            let sessionResult = try await cliRunner.runCommand(arguments: ["giris", "--json"])
            if let data = sessionResult.stdout.data(using: .utf8),
               let response = try? JSONDecoder().decode(GirisResponse.self, from: data),
               !response.active {
                errorMessage = "Active broker session required for screener. Please log in first."
                isLoading = false
                return
            }

            let result = try await cliRunner.runCommand(arguments: ["tarama", "--json"])
            if let data = result.stdout.data(using: .utf8) {
                let response = try JSONDecoder().decode(TaramaResponse.self, from: data)
                candidates = response.candidates
                poolCount = response.poolCount
                warningMessage = response.warning
                if selectedCandidate == nil {
                    selectedCandidate = candidates.first
                }
            } else {
                errorMessage = "Failed to parse screener JSON response."
            }
        } catch {
            errorMessage = error.localizedDescription
            CockpitLogger.shared.error("Failed to run live screener: \(error.localizedDescription)")
        }
        isLoading = false
    }

    // MARK: - Pool Editor Actions
    public func openPoolEditor() async {
        showPoolEditor = true
        poolEditorValidationMessage = nil
        do {
            let result = try await cliRunner.runCommand(arguments: ["ayar", "goster", "--json"])
            if let data = result.stdout.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let portfoy = json["portfoy"] as? [String: Any],
               let araclar = portfoy["araclar"] as? [String: Any] {
                let isins = araclar.keys.sorted()
                poolISINsText = isins.joined(separator: "\n")
            }
        } catch {
            poolEditorValidationMessage = "Failed to read current screener pool: \(error.localizedDescription)"
        }
    }

    public func savePool() async -> Bool {
        poolEditorValidationMessage = nil
        let isinList = poolISINsText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        guard !isinList.isEmpty else {
            poolEditorValidationMessage = "Screener pool must contain at least one valid ISIN."
            return false
        }

        // Validate each ISIN with Luhn algorithm
        for isin in isinList {
            guard ISINValidator.isValid(isin) else {
                poolEditorValidationMessage = "Invalid ISIN format or checksum: '\(isin)'"
                return false
            }
        }

        isSavingPool = true
        do {
            let payload: [String: Any] = [
                "araclar": isinList.reduce(into: [String: [String: String]]()) { dict, isin in
                    dict[isin] = ["rol": "SATELLITE"]
                }
            ]
            let jsonData = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted])
            let jsonString = String(data: jsonData, encoding: .utf8) ?? "{}"

            let result = try await cliRunner.runCommand(
                arguments: ["ayar", "yaz", "--dosya", "havuz", "--json", "-"],
                stdin: jsonString
            )

            if result.isSuccess {
                isSavingPool = false
                showPoolEditor = false
                await loadData()
                return true
            } else {
                poolEditorValidationMessage = result.message
            }
        } catch {
            poolEditorValidationMessage = "Failed to save pool: \(error.localizedDescription)"
        }

        isSavingPool = false
        return false
    }
}
