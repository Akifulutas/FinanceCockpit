import Foundation

/// Centralized, secure path resolution for ETFCockpit.
/// Removes hardcoded home directories and enforces file ownership checks.
public enum CockpitPathResolver {

    // MARK: - Workspace Directory

    public static var defaultExecutablePath: String {
        CLIProcessRunner.resolveExecutablePath()
    }

    public static var defaultWorkingDirectory: String {
        if let env = ProcessInfo.processInfo.environment["MASA_WORKSPACE_DIR"], !env.isEmpty {
            return (env as NSString).standardizingPath
        }

        let cwd = FileManager.default.currentDirectoryPath
        let cwdMasa = (cwd as NSString).appendingPathComponent("masa")
        var isDir: ObjCBool = false
        if FileManager.default.fileExists(atPath: cwdMasa, isDirectory: &isDir), isDir.boolValue {
            return cwd
        }

        // Parent check
        let parentMasa = ((cwd as NSString).deletingLastPathComponent as NSString).appendingPathComponent("masa")
        if FileManager.default.fileExists(atPath: parentMasa, isDirectory: &isDir), isDir.boolValue {
            return (cwd as NSString).deletingLastPathComponent
        }

        // User Home standard location
        let homeDir = FileManager.default.homeDirectoryForCurrentUser
        let candidate = homeDir.appendingPathComponent("Documents/ETF").path
        if FileManager.default.fileExists(atPath: candidate, isDirectory: &isDir), isDir.boolValue {
            return candidate
        }

        return cwd
    }

    // MARK: - Database Path

    public static var defaultDatabasePath: String {
        if let env = ProcessInfo.processInfo.environment["MASA_DB_PATH"], !env.isEmpty {
            return (env as NSString).standardizingPath
        }

        let workspace = defaultWorkingDirectory
        let candidate = (workspace as NSString).appendingPathComponent("masa/var/private/masa.db")
        if FileManager.default.fileExists(atPath: candidate) {
            return candidate
        }

        let homeDir = FileManager.default.homeDirectoryForCurrentUser
        let homeCandidate = homeDir.appendingPathComponent("Documents/ETF/masa/var/private/masa.db").path
        if FileManager.default.fileExists(atPath: homeCandidate) {
            return homeCandidate
        }

        return candidate
    }

    // MARK: - Reports Directory

    public static var defaultReportsDirectory: String {
        if let env = ProcessInfo.processInfo.environment["MASA_REPORTS_DIR"], !env.isEmpty {
            return (env as NSString).standardizingPath
        }

        let workspace = defaultWorkingDirectory
        let candidate = (workspace as NSString).appendingPathComponent("masa/var/reports")
        if FileManager.default.fileExists(atPath: candidate) {
            return candidate
        }

        let homeDir = FileManager.default.homeDirectoryForCurrentUser
        return homeDir.appendingPathComponent("Documents/ETF/masa/var/reports").path
    }

    // MARK: - Portfolio Config URL

    public static var defaultPortfolioConfigURL: URL {
        if let customPath = ProcessInfo.processInfo.environment["MASA_CONFIG_DIR"], !customPath.isEmpty {
            return URL(fileURLWithPath: customPath).appendingPathComponent("portfoy.json")
        }

        let workspace = defaultWorkingDirectory
        let candidate = URL(fileURLWithPath: workspace).appendingPathComponent("masa/config/portfoy.json")
        if FileManager.default.fileExists(atPath: candidate.path) {
            return candidate
        }

        let homeDir = FileManager.default.homeDirectoryForCurrentUser
        return homeDir.appendingPathComponent("Documents/ETF/masa/config/portfoy.json")
    }

    // MARK: - File Ownership Validation

    public static func validateFileOwnership(atPath path: String) -> Bool {
        guard FileManager.default.fileExists(atPath: path) else { return false }
        do {
            let attrs = try FileManager.default.attributesOfItem(atPath: path)
            guard let ownerUID = attrs[.ownerAccountID] as? UInt else { return false }
            let currentUID = UInt(getuid())
            // Allowed if owned by current user or root (0)
            return ownerUID == currentUID || ownerUID == 0
        } catch {
            return false
        }
    }
}
