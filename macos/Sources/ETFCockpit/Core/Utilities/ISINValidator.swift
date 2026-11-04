import Foundation

public enum ISINValidator {
    private static let isinRegex: NSRegularExpression = {
        do {
            return try NSRegularExpression(pattern: "^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
        } catch {
            fatalError("Invalid ISIN regex pattern")
        }
    }()

    /// Validates an ISIN string against ISO 6166 format and the Luhn Modulus-10 checksum algorithm.
    public static func isValid(_ isin: String) -> Bool {
        let clean = isin.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard clean.count == 12 else { return false }

        let range = NSRange(location: 0, length: clean.utf16.count)
        guard isinRegex.firstMatch(in: clean, options: [], range: range) != nil else {
            return false
        }

        let prefix11 = String(clean.prefix(11))
        guard let expectedCheck = calculateCheckDigit(prefix11: prefix11) else {
            return false
        }

        guard let actualCheckChar = clean.last, let actualCheck = Int(String(actualCheckChar)) else {
            return false
        }

        return actualCheck == expectedCheck
    }

    /// Calculates the ISO 6166 Luhn Modulus-10 check digit for the first 11 characters of an ISIN.
    public static func calculateCheckDigit(prefix11: String) -> Int? {
        guard prefix11.count == 11 else { return nil }

        var digits: [Int] = []
        for char in prefix11 {
            if let ascii = char.asciiValue {
                if ascii >= 48 && ascii <= 57 { // '0'...'9'
                    digits.append(Int(ascii - 48))
                } else if ascii >= 65 && ascii <= 90 { // 'A'...'Z'
                    let val = Int(ascii - 65 + 10)
                    digits.append(val / 10)
                    digits.append(val % 10)
                } else {
                    return nil
                }
            } else {
                return nil
            }
        }

        var totalSum = 0
        for (offsetFromRight, digit) in digits.reversed().enumerated() {
            if offsetFromRight % 2 == 0 {
                let product = digit * 2
                totalSum += (product / 10) + (product % 10)
            } else {
                totalSum += digit
            }
        }

        return (10 - (totalSum % 10)) % 10
    }
}
