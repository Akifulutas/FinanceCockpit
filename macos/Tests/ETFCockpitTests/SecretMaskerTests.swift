import XCTest
@testable import FinanceCockpit

final class SecretMaskerTests: XCTestCase {

    func testMaskShortString() {
        XCTAssertEqual(SecretMasker.mask("abc"), "••••••••")
        XCTAssertEqual(SecretMasker.mask("123456"), "••••••••")
    }

    func testMaskLongString() {
        let testToken = "sk-" + "1234567890abcdef"
        let masked = SecretMasker.mask(testToken)
        XCTAssertEqual(masked, "sk-••••••••def")

        let testKey = "AIza" + "Test1234567890ABCDEF123456"
        let maskedKey = SecretMasker.mask(testKey)
        XCTAssertEqual(maskedKey, "AIz••••••••456")
    }

    func testMaskAccountId() {
        let masked = SecretMasker.maskAccountId("ACT1234567890ZZ")
        XCTAssertEqual(masked, "ACT…ZZ")

        let short = SecretMasker.maskAccountId("123")
        XCTAssertEqual(short, "••••")
    }

    func testSanitizeLogMessageIBAN() {
        let logMsg = "Connecting broker account for IBAN DE89370400440532013000 at Deutsche Bank"
        let sanitized = SecretMasker.sanitizeLogMessage(logMsg)
        XCTAssertFalse(sanitized.contains("DE89370400440532013000"), "IBAN should not be in plaintext")
        XCTAssertTrue(sanitized.contains("DE8••••••••000"), "IBAN should be masked: \(sanitized)")
    }

    func testSanitizeLogMessageAPIKeys() {
        let dummyOpenAI = "sk-test-" + "sampletest1234567890abcdef12345678"
        let openAILog = "Using model with key \(dummyOpenAI) for research"
        let sanitizedOpenAI = SecretMasker.sanitizeLogMessage(openAILog)
        XCTAssertFalse(sanitizedOpenAI.contains(dummyOpenAI))
        XCTAssertTrue(sanitizedOpenAI.contains("••••••••"))

        let dummyGoogle = "AIzaTest-" + "sampletest1234567890abcdefghij123456"
        let googleLog = "Gemini API initialized with \(dummyGoogle)"
        let sanitizedGoogle = SecretMasker.sanitizeLogMessage(googleLog)
        XCTAssertFalse(sanitizedGoogle.contains(dummyGoogle))
        XCTAssertTrue(sanitizedGoogle.contains("••••••••"))

        let dummyGithub = "ghp_" + "sampletest1234567890abcdefghijklmnopqrstuvwxyz"
        let githubLog = "Downloaded repo token \(dummyGithub)"
        let sanitizedGithub = SecretMasker.sanitizeLogMessage(githubLog)
        XCTAssertFalse(sanitizedGithub.contains(dummyGithub))
        XCTAssertTrue(sanitizedGithub.contains("••••••••"))
    }

    func testSanitizeLogMessageBearerToken() {
        let authMsg = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        let sanitized = SecretMasker.sanitizeLogMessage(authMsg)
        XCTAssertFalse(sanitized.contains("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"))
        XCTAssertTrue(sanitized.contains("Bearer eyJ••••••••In0"), "Expected masked bearer token: \(sanitized)")
    }

    func testSanitizeLogMessageKeyValueAuth() {
        let configLog = "Loaded config: token='mock_test_token_123456' and endpoint='http://localhost'"
        let sanitized = SecretMasker.sanitizeLogMessage(configLog)
        XCTAssertFalse(sanitized.contains("mock_test_token_123456"))
        XCTAssertTrue(sanitized.contains("moc••••••••456"))
    }

    func testSecretStringContainer() {
        let testVal = "sk-test-" + "mocktestsampletoken1234567890"
        let secret = SecretString(testVal)

        // description and debugDescription must be masked
        XCTAssertFalse(secret.description.contains("mocktestsampletoken"))
        XCTAssertTrue(secret.description.contains("••••••••"))
        XCTAssertFalse(secret.debugDescription.contains("mocktestsampletoken"))

        // unmasked provides the exact value
        XCTAssertEqual(secret.unmasked, testVal)
    }

    func testCockpitLoggerZeroLeakage() {
        let logger = CockpitLogger.shared
        // Test that info, debug, warning, error do not crash with sensitive messages
        logger.info("Test IBAN DE89370400440532013000")
        let dummyKey = "sk-" + "12345678901234567890"
        logger.debug("Test Key \(dummyKey)")
        logger.warning("Test Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        logger.error("Test Error with api_key: 'supersecret'")
    }
}
