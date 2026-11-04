import Foundation

public struct ConfigParameters: Sendable, Equatable {
    public let coreIsin: String
    public let targetWeights: [String: Decimal]
    public let policyApprovalStatus: String
    public let absoluteTolerance: Decimal
    public let relativeTolerance: Decimal
    public let minTradeEur: Decimal
    public let targetCashRatio: Decimal
    public let ucitsEnforcement: Bool
    public let trendAlertThreshold: Decimal
    public let drawdownReviewThreshold: Decimal
    public let spreadWarningPct: Decimal
    public let brokerPath: String
    public let accountId: String

    public init(
        coreIsin: String = "",
        targetWeights: [String: Decimal] = [:],
        policyApprovalStatus: String = "TASLAK",
        absoluteTolerance: Decimal = 0.05,
        relativeTolerance: Decimal = 0.25,
        minTradeEur: Decimal = 25,
        targetCashRatio: Decimal = 0.0,
        ucitsEnforcement: Bool = false,
        trendAlertThreshold: Decimal = -0.05,
        drawdownReviewThreshold: Decimal = -0.20,
        spreadWarningPct: Decimal = 1.0,
        brokerPath: String = "/opt/homebrew/bin/sc",
        accountId: String = "—"
    ) {
        self.coreIsin = coreIsin
        self.targetWeights = targetWeights
        self.policyApprovalStatus = policyApprovalStatus
        self.absoluteTolerance = absoluteTolerance
        self.relativeTolerance = relativeTolerance
        self.minTradeEur = minTradeEur
        self.targetCashRatio = targetCashRatio
        self.ucitsEnforcement = ucitsEnforcement
        self.trendAlertThreshold = trendAlertThreshold
        self.drawdownReviewThreshold = drawdownReviewThreshold
        self.spreadWarningPct = spreadWarningPct
        self.brokerPath = brokerPath
        self.accountId = accountId
    }
}

// MARK: - CLI Configuration DTOs (schema_version 1.0.0)

public struct PortfoyInstrumentDTO: Codable, Sendable, Equatable {
    public let rol: String?
    public let tur: String?
    public let yahoo: String?
    public let faktor: Bool?

    public init(rol: String? = nil, tur: String? = nil, yahoo: String? = nil, faktor: Bool? = nil) {
        self.rol = rol
        self.tur = tur
        self.yahoo = yahoo
        self.faktor = faktor
    }
}

public struct PortfoyConfigDTO: Codable, Sendable, Equatable {
    public let cekirdekIsin: String?
    public let hedefDurumu: String?
    public let hedefAgirliklar: [String: Double]
    public let araclar: [String: PortfoyInstrumentDTO]?

    enum CodingKeys: String, CodingKey {
        case cekirdekIsin = "cekirdek_isin"
        case hedefDurumu = "hedef_durumu"
        case hedefAgirliklar = "hedef_agirliklar"
        case araclar
    }

    public init(
        cekirdekIsin: String? = nil,
        hedefDurumu: String? = nil,
        hedefAgirliklar: [String: Double] = [:],
        araclar: [String: PortfoyInstrumentDTO]? = nil
    ) {
        self.cekirdekIsin = cekirdekIsin
        self.hedefDurumu = hedefDurumu
        self.hedefAgirliklar = hedefAgirliklar
        self.araclar = araclar
    }
}

public struct PolitikaTaramaDTO: Codable, Sendable, Equatable {
    public let minSharpe: Double?
    public let maxMakasYuzde: Double?
    public let maxKorelasyon: Double?
    public let ustAdaySayisi: Int?

    enum CodingKeys: String, CodingKey {
        case minSharpe = "min_sharpe"
        case maxMakasYuzde = "max_makas_yuzde"
        case maxKorelasyon = "max_korelasyon"
        case ustAdaySayisi = "ust_aday_sayisi"
    }

    public init(
        minSharpe: Double? = 0.5,
        maxMakasYuzde: Double? = 0.5,
        maxKorelasyon: Double? = 0.85,
        ustAdaySayisi: Int? = 3
    ) {
        self.minSharpe = minSharpe
        self.maxMakasYuzde = maxMakasYuzde
        self.maxKorelasyon = maxKorelasyon
        self.ustAdaySayisi = ustAdaySayisi
    }
}

public struct PolitikaConfigDTO: Codable, Sendable, Equatable {
    public let durum: String
    public let toleransMutlak: Double
    public let toleransGoreli: Double
    public let trendUyari: Double
    public let dususInceleme: Double
    public let minEmirEur: Double
    public let nakitHedefi: Double
    public let ucitsKontrolu: Bool
    public let tarama: PolitikaTaramaDTO?

    enum CodingKeys: String, CodingKey {
        case durum
        case toleransMutlak = "tolerans_mutlak"
        case toleransGoreli = "tolerans_goreli"
        case trendUyari = "trend_uyari"
        case dususInceleme = "dusus_inceleme"
        case minEmirEur = "min_emir_eur"
        case nakitHedefi = "nakit_hedefi"
        case ucitsKontrolu = "ucits_kontrolu"
        case tarama
    }

    public init(
        durum: String = "TASLAK",
        toleransMutlak: Double = 0.05,
        toleransGoreli: Double = 0.25,
        trendUyari: Double = -0.05,
        dususInceleme: Double = -0.20,
        minEmirEur: Double = 25.0,
        nakitHedefi: Double = 0.0,
        ucitsKontrolu: Bool = false,
        tarama: PolitikaTaramaDTO? = nil
    ) {
        self.durum = durum
        self.toleransMutlak = toleransMutlak
        self.toleransGoreli = toleransGoreli
        self.trendUyari = trendUyari
        self.dususInceleme = dususInceleme
        self.minEmirEur = minEmirEur
        self.nakitHedefi = nakitHedefi
        self.ucitsKontrolu = ucitsKontrolu
        self.tarama = tarama
    }
}

public struct ModelErisimDTO: Codable, Sendable, Equatable {
    public let providers: [String]
    public let chatgptAuthExists: Bool
    public let chatgptAuthPath: String
    public let googleModel: String

    enum CodingKeys: String, CodingKey {
        case providers
        case chatgptAuthExists = "chatgpt_auth_exists"
        case chatgptAuthPath = "chatgpt_auth_path"
        case googleModel = "google_model"
    }

    public init(
        providers: [String] = [],
        chatgptAuthExists: Bool = false,
        chatgptAuthPath: String = "~/.tradingagents/chatgpt-auth.json",
        googleModel: String = "google / gemini-3.8-flash"
    ) {
        self.providers = providers
        self.chatgptAuthExists = chatgptAuthExists
        self.chatgptAuthPath = chatgptAuthPath
        self.googleModel = googleModel
    }
}

public struct BrokerConfigDTO: Codable, Sendable, Equatable {
    public let cliPath: String
    public let cliExists: Bool

    enum CodingKeys: String, CodingKey {
        case cliPath = "cli_path"
        case cliExists = "cli_exists"
    }

    public init(
        cliPath: String = "/opt/homebrew/bin/sc",
        cliExists: Bool = false
    ) {
        self.cliPath = cliPath
        self.cliExists = cliExists
    }
}

public struct AyarGosterResponse: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let portfoy: PortfoyConfigDTO
    public let politika: PolitikaConfigDTO
    public let modelErisim: ModelErisimDTO
    public let broker: BrokerConfigDTO

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case portfoy
        case politika
        case modelErisim = "model_erisim"
        case broker
    }

    public init(
        schemaVersion: String = "1.0.0",
        portfoy: PortfoyConfigDTO,
        politika: PolitikaConfigDTO,
        modelErisim: ModelErisimDTO,
        broker: BrokerConfigDTO
    ) {
        self.schemaVersion = schemaVersion
        self.portfoy = portfoy
        self.politika = politika
        self.modelErisim = modelErisim
        self.broker = broker
    }
}


public struct CLIOperationResult: Sendable, Equatable {
    public let isSuccess: Bool
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String
    public let message: String
    public let outputTruncated: Bool

    public init(
        isSuccess: Bool,
        exitCode: Int32,
        stdout: String = "",
        stderr: String = "",
        message: String = "",
        outputTruncated: Bool = false
    ) {
        self.isSuccess = isSuccess
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
        self.message = message
        self.outputTruncated = outputTruncated
    }
}

public enum CLIDecodeError: Error, LocalizedError, Equatable {
    case outputTruncated(message: String)
    case emptyOutput
    case jsonDecodeFailed(underlyingError: String)

    public var errorDescription: String? {
        switch self {
        case .outputTruncated(let msg):
            return "CLI output truncated: \(msg). Data integrity could not be verified."
        case .emptyOutput:
            return "CLI output is empty."
        case .jsonDecodeFailed(let err):
            return "Failed to decode JSON output: \(err)"
        }
    }
}

public extension CLIOperationResult {
    func decodeJSON<T: Decodable>(_ type: T.Type, decoder: JSONDecoder = JSONDecoder()) throws -> T {
        if outputTruncated {
            throw CLIDecodeError.outputTruncated(message: "Pipe closed before the process stream completed (outputTruncated = true).")
        }
        guard let data = stdout.data(using: .utf8), !data.isEmpty else {
            throw CLIDecodeError.emptyOutput
        }
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw CLIDecodeError.jsonDecodeFailed(underlyingError: error.localizedDescription)
        }
    }
}

public struct NotificationPreferences: Sendable, Equatable {
    public var morningForecastAlerts: Bool
    public var eveningSettlementAlerts: Bool
    public var waitingAuthAlerts: Bool
    public var soundEnabled: Bool
    public var defaultTimeframe: String

    public init(
        morningForecastAlerts: Bool = true,
        eveningSettlementAlerts: Bool = true,
        waitingAuthAlerts: Bool = true,
        soundEnabled: Bool = true,
        defaultTimeframe: String = "1Y"
    ) {
        self.morningForecastAlerts = morningForecastAlerts
        self.eveningSettlementAlerts = eveningSettlementAlerts
        self.waitingAuthAlerts = waitingAuthAlerts
        self.soundEnabled = soundEnabled
        self.defaultTimeframe = defaultTimeframe
    }
}

public struct CredentialItem: Identifiable, Sendable, Equatable {
    public var id: String { provider }
    public let provider: String
    public let displayName: String
    public let maskedSecret: SecretString
    public let isConfigured: Bool
    public let storageLocation: String
    public let lastUpdated: String?

    public init(
        provider: String,
        displayName: String,
        maskedSecret: SecretString,
        isConfigured: Bool,
        storageLocation: String = "macOS Keychain",
        lastUpdated: String? = nil
    ) {
        self.provider = provider
        self.displayName = displayName
        self.maskedSecret = maskedSecret
        self.isConfigured = isConfigured
        self.storageLocation = storageLocation
        self.lastUpdated = lastUpdated
    }
}

