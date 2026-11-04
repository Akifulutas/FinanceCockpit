import Foundation

/// A type-safe container for secrets that prevents accidental plaintext printing in logs, debug views, and strings.
public struct SecretString: Sendable, Equatable, Hashable, CustomStringConvertible, CustomDebugStringConvertible {
    private let rawValue: String

    public init(_ value: String) {
        self.rawValue = value
    }

    public var description: String {
        SecretMasker.mask(rawValue)
    }

    public var debugDescription: String {
        SecretMasker.mask(rawValue)
    }

    /// Access the underlying unmasked secret value for authorized cryptographic operations.
    public var unmasked: String {
        rawValue
    }

    public var isEmpty: Bool {
        rawValue.isEmpty
    }
}

public enum SecretMasker {
    // Regular expressions for detecting sensitive tokens in strings
    private static let ibanPattern = #"\b[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}\b"#
    private static let apiKeyPattern = #"\b(sk-[a-zA-Z0-9_\-]{16,}|AIza[0-9A-Za-z\-_]{30,}|ghp_[a-zA-Z0-9]{30,})\b"#
    private static let bearerTokenPattern = #"(?i)bearer\s+([a-zA-Z0-9_\-\.]{15,})"#
    private static let keyValAuthPattern = #"(?i)(api[_-]?key|token|password|secret|auth)\s*[:=]\s*["']?([^"'\s,;]+)["']?"#

    /// Masks a string by keeping the first 3 and last 3 characters, replacing the middle with bullets.
    public static func mask(_ input: String) -> String {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 6 else {
            return "••••••••"
        }
        let prefix = trimmed.prefix(3)
        let suffix = trimmed.suffix(3)
        return "\(prefix)••••••••\(suffix)"
    }

    /// Masks an account ID (e.g. Scalable Capital account) into "rSw…aJ".
    public static func maskAccountId(_ accountId: String) -> String {
        let trimmed = accountId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 5 else {
            return "••••"
        }
        let prefix = trimmed.prefix(3)
        let suffix = trimmed.suffix(2)
        return "\(prefix)…\(suffix)"
    }

    /// Sanitizes an entire log message or string by scanning and masking IBANs, API keys, tokens, and authorization parameters.
    public static func sanitizeLogMessage(_ message: String) -> String {
        var sanitized = message

        // 1. Mask IBANs
        if let regex = try? NSRegularExpression(pattern: ibanPattern) {
            let matches = regex.matches(in: sanitized, range: NSRange(sanitized.startIndex..., in: sanitized)).reversed()
            for match in matches {
                if let range = Range(match.range, in: sanitized) {
                    let matchedIBAN = String(sanitized[range])
                    sanitized.replaceSubrange(range, with: mask(matchedIBAN))
                }
            }
        }

        // 2. Mask Common API Keys (OpenAI, Google, GitHub)
        if let regex = try? NSRegularExpression(pattern: apiKeyPattern) {
            let matches = regex.matches(in: sanitized, range: NSRange(sanitized.startIndex..., in: sanitized)).reversed()
            for match in matches {
                if let range = Range(match.range, in: sanitized) {
                    let matchedKey = String(sanitized[range])
                    sanitized.replaceSubrange(range, with: mask(matchedKey))
                }
            }
        }

        // 3. Mask Bearer Tokens
        if let regex = try? NSRegularExpression(pattern: bearerTokenPattern) {
            let matches = regex.matches(in: sanitized, range: NSRange(sanitized.startIndex..., in: sanitized)).reversed()
            for match in matches {
                if match.numberOfRanges > 1, let tokenRange = Range(match.range(at: 1), in: sanitized) {
                    let matchedToken = String(sanitized[tokenRange])
                    sanitized.replaceSubrange(tokenRange, with: mask(matchedToken))
                }
            }
        }

        // 4. Mask Key-Value Auth pairs e.g. api_key="xyz123"
        if let regex = try? NSRegularExpression(pattern: keyValAuthPattern) {
            let matches = regex.matches(in: sanitized, range: NSRange(sanitized.startIndex..., in: sanitized)).reversed()
            for match in matches {
                if match.numberOfRanges > 2, let secretRange = Range(match.range(at: 2), in: sanitized) {
                    let secretVal = String(sanitized[secretRange])
                    sanitized.replaceSubrange(secretRange, with: mask(secretVal))
                }
            }
        }

        return sanitized
    }
}
