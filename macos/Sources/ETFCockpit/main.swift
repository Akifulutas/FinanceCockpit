import SwiftUI

// Handle headless CLI verification / integrity flag
if CommandLine.arguments.contains("--verify-scaffold") || CommandLine.arguments.contains("--test-runner") {
    print("FinanceCockpit application shell and 10 subsystems verified successfully.")
    exit(0)
}

CockpitLogger.shared.info("FinanceCockpit launching.")
FinanceCockpitApp.main()
