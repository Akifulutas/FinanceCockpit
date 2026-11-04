import Foundation
import os

/// Thread-safe logger ensuring zero secret leakage by routing all messages through `SecretMasker`.
public final class CockpitLogger: Sendable {
    public static let shared = CockpitLogger()
    private let logger: Logger

    public init(subsystem: String = "com.etf.cockpit", category: String = "Core") {
        self.logger = Logger(subsystem: subsystem, category: category)
    }

    public func info(_ message: String) {
        let safe = SecretMasker.sanitizeLogMessage(message)
        logger.info("\(safe, privacy: .public)")
    }

    public func debug(_ message: String) {
        let safe = SecretMasker.sanitizeLogMessage(message)
        logger.debug("\(safe, privacy: .public)")
    }

    public func warning(_ message: String) {
        let safe = SecretMasker.sanitizeLogMessage(message)
        logger.warning("\(safe, privacy: .public)")
    }

    public func error(_ message: String) {
        let safe = SecretMasker.sanitizeLogMessage(message)
        logger.error("\(safe, privacy: .public)")
    }
}
