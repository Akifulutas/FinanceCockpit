import Foundation

public enum CLIOutputParsers {

    /// Parses the key-value text output of `./etf-masa dogrula` into a strongly typed `IntegrityCheckResult`.
    public static func parseDogrula(output: String) -> IntegrityCheckResult {
        var map: [String: String] = [:]

        for line in output.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix("=") || trimmed.hasPrefix("✓") {
                continue
            }
            // Lines are formatted as "key   value" with variable spaces
            let parts = trimmed.split(whereSeparator: { $0.isWhitespace })
            if parts.count >= 2 {
                let key = String(parts[0])
                let value = parts.dropFirst().joined(separator: " ")
                map[key] = value
            }
        }

        let isOk = (map["ok"]?.lowercased() == "true")
        let fileVault = output.contains("FileVault Açık")
        let schemaVer = Int(map["schema_version"] ?? "3") ?? 3
        let triggers = Int(map["trigger_count"] ?? "78") ?? 78
        let snapshots = Int(map["snapshots"] ?? "0") ?? 0
        let rawObjects = Int(map["raw_objects"] ?? "0") ?? 0
        let auditEvents = Int(map["audit_events"] ?? "0") ?? 0
        let tip = map["chain_tip"] ?? ""
        let snapOk = (map["snapshot_chain_ok"]?.lowercased() == "true")
        let auditOk = (map["audit_chain_ok"]?.lowercased() == "true")
        let tipStatus = map["chain_tip_status"] ?? "UNKNOWN"
        let tipDetails = map["chain_tip_details"] ?? ""
        let sealedSnap = map["sealed_snapshot_tip"] ?? ""
        let sealedAudit = map["sealed_audit_tip"] ?? ""
        let critViolation = (map["critical_integrity_violation"]?.lowercased() == "true")

        return IntegrityCheckResult(
            ok: isOk,
            fileVaultActive: fileVault,
            schemaVersion: schemaVer,
            triggerCount: triggers,
            snapshotsCount: snapshots,
            rawObjectsCount: rawObjects,
            auditEventsCount: auditEvents,
            chainTip: tip,
            snapshotChainOk: snapOk,
            auditChainOk: auditOk,
            chainTipStatus: tipStatus,
            chainTipDetails: tipDetails,
            sealedSnapshotTip: sealedSnap,
            sealedAuditTip: sealedAudit,
            criticalIntegrityViolation: critViolation,
            rawOutput: output
        )
    }

    /// Parses the text output of `./etf-masa yedek` into `BackupResult`.
    public static func parseYedek(output: String, exitCode: Int32 = 0) -> BackupResult {
        let isSuccess = (exitCode == 0) && (output.contains("BAŞARIYLA ALINDI") || output.contains("PROVA DOĞRULANDI"))
        var backupPath: String?
        var sha256: String?
        var snapTip: String?
        var auditTip: String?
        var manifestPath: String?
        let restoreDrill = output.contains("restore_drill") && output.contains("SQLite PRAGMA quick_check: OK")

        for line in output.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.contains("Yedek dosyası:") || trimmed.contains("Mevcut geçerli yedek:") {
                // e.g. "✓ Yedek dosyası: /.../backup-xxx.db (2,621,440 bayt)" or "✓ Mevcut geçerli yedek: /.../backup-xxx.db (2,621,440 bayt)"
                let marker = trimmed.contains("Yedek dosyası:") ? "Yedek dosyası:" : "Mevcut geçerli yedek:"
                let components = trimmed.components(separatedBy: marker)
                if components.count > 1 {
                    let sub = components[1].trimmingCharacters(in: .whitespaces)
                    backupPath = sub.components(separatedBy: " ").first
                }
            } else if trimmed.contains("SHA-256:") {
                let components = trimmed.components(separatedBy: "SHA-256:")
                if components.count > 1 {
                    sha256 = components[1].trimmingCharacters(in: .whitespaces)
                }
            } else if trimmed.contains("Mühür zincir ucu:") {
                let components = trimmed.components(separatedBy: "Mühür zincir ucu:")
                if components.count > 1 {
                    snapTip = components[1].trimmingCharacters(in: .whitespaces)
                }
            } else if trimmed.contains("Denetim zincir ucu:") {
                let components = trimmed.components(separatedBy: "Denetim zincir ucu:")
                if components.count > 1 {
                    auditTip = components[1].trimmingCharacters(in: .whitespaces)
                }
            } else if trimmed.contains("Manifest:") {
                let components = trimmed.components(separatedBy: "Manifest:")
                if components.count > 1 {
                    manifestPath = components[1].trimmingCharacters(in: .whitespaces)
                }
            }
        }

        return BackupResult(
            isSuccess: isSuccess,
            backupFilePath: backupPath,
            sha256: sha256,
            snapshotTip: snapTip,
            auditTip: auditTip,
            manifestPath: manifestPath,
            restoreDrillOk: restoreDrill,
            rawOutput: output
        )
    }

    /// Parses the text output of `./etf-masa guvenlik-tara` into `SecurityScanResult`.
    public static func parseGuvenlikTara(output: String, exitCode: Int32 = 0) -> SecurityScanResult {
        let isSuccess = (exitCode == 0) && output.contains("TAMAMLANDI")
        let permissionsOk = output.contains("0700/0600") && output.contains("uyumlu")

        var leaks = 0
        if output.contains("0 sızıntı") {
            leaks = 0
        } else if let match = output.range(of: #"\b([0-9]+)\s+sızıntı"#, options: .regularExpression) {
            let numStr = output[match].components(separatedBy: " ").first ?? "0"
            leaks = Int(numStr) ?? 0
        }

        return SecurityScanResult(
            isSuccess: isSuccess,
            permissionsOk: permissionsOk,
            gitleaksLeaksCount: leaks,
            rawOutput: output
        )
    }
}
