import Foundation

public enum CLIStreamChunk: Sendable, Equatable {
    case stdout(String)
    case stderr(String)
    case exit(Int32)

    public var text: String {
        switch self {
        case .stdout(let str), .stderr(let str):
            return str
        case .exit(let code):
            return "EXIT: \(code)"
        }
    }

    public var isStdout: Bool {
        switch self {
        case .stdout: return true
        case .stderr, .exit: return false
        }
    }

    public var exitCode: Int32? {
        if case .exit(let code) = self {
            return code
        }
        return nil
    }
}

public protocol CLIProcessRunnerProtocol: Sendable {
    func runVerifyIntegrity() async throws -> IntegrityCheckResult
    func runBackup(drillOnly: Bool) async throws -> BackupResult
    func runSecurityScan() async throws -> SecurityScanResult
    func runForecastMorning() async throws -> CLIOperationResult
    func runSettleEvening() async throws -> CLIOperationResult
    func runForecastSimulation(days: Int) async throws -> CLIOperationResult
    func runResearch(isin: String, horizon: String?) async throws -> CLIOperationResult
    func runResearch(query: String?, ticker: String?) async throws -> CLIOperationResult
    func runSchedulerAction(agent: String, action: String) async throws -> CLIOperationResult

    func runCommand(
        arguments: [String],
        timeoutSeconds: TimeInterval?,
        stdin: String?,
        onStdoutChunk: (@Sendable (String) -> Void)?,
        onStderrChunk: (@Sendable (String) -> Void)?
    ) async throws -> CLIOperationResult

    func runStream(
        arguments: [String],
        timeoutSeconds: TimeInterval?,
        stdin: String?
    ) -> AsyncThrowingStream<CLIStreamChunk, Error>
}

extension CLIProcessRunnerProtocol {
    public func runForecastSimulation(days: Int = 30) async throws -> CLIOperationResult {
        return try await runCommand(arguments: ["tahmin", "gecmis-simule", "--gun", String(days)], timeoutSeconds: 300.0, stdin: nil, onStdoutChunk: nil, onStderrChunk: nil)
    }
}

public extension CLIProcessRunnerProtocol {
    func runCommand(
        arguments: [String],
        timeoutSeconds: TimeInterval? = nil,
        stdin: String? = nil,
        onStdoutChunk: (@Sendable (String) -> Void)? = nil,
        onStderrChunk: (@Sendable (String) -> Void)? = nil
    ) async throws -> CLIOperationResult {
        try await runCommand(
            arguments: arguments,
            timeoutSeconds: timeoutSeconds,
            stdin: stdin,
            onStdoutChunk: onStdoutChunk,
            onStderrChunk: onStderrChunk
        )
    }

    func runStream(
        arguments: [String],
        timeoutSeconds: TimeInterval? = nil,
        stdin: String? = nil
    ) -> AsyncThrowingStream<CLIStreamChunk, Error> {
        let coord = StreamCoordinator()
        let (rawStream, rawContinuation) = AsyncThrowingStream<CLIStreamChunk, Error>.makeStream()

        let task = Task {
            do {
                let result = try await self.runCommand(
                    arguments: arguments,
                    timeoutSeconds: timeoutSeconds,
                    stdin: stdin,
                    onStdoutChunk: { text in
                        coord.onProducerChunk()
                        rawContinuation.yield(.stdout(text))
                    },
                    onStderrChunk: { text in
                        coord.onProducerChunk()
                        rawContinuation.yield(.stderr(text))
                    }
                )
                rawContinuation.yield(.exit(result.exitCode))
                rawContinuation.finish()
            } catch {
                rawContinuation.finish(throwing: error)
            }
        }

        coord.setTask(task)

        rawContinuation.onTermination = { @Sendable _ in
            task.cancel()
        }

        let box = CancellableStreamBox(stream: rawStream, task: task, coordinator: coord)

        return AsyncThrowingStream {
            return try await box.next()
        }
    }
}

final class StreamCoordinator: @unchecked Sendable {
    private let lock = NSLock()
    private var lastConsumerReceivedTime = Date()
    private var isConsumerWaiting = false
    private var hasConsumedAny = false
    private var task: Task<Void, Never>?

    init() {}

    func setTask(_ task: Task<Void, Never>) {
        lock.lock()
        defer { lock.unlock() }
        self.task = task
    }

    func markConsumerWaiting() {
        lock.lock()
        defer { lock.unlock() }
        isConsumerWaiting = true
    }

    func markConsumerReceived() {
        lock.lock()
        defer { lock.unlock() }
        isConsumerWaiting = false
        hasConsumedAny = true
        lastConsumerReceivedTime = Date()
    }

    func onProducerChunk() {
        lock.lock()
        let consumed = hasConsumedAny
        let waiting = isConsumerWaiting
        let elapsed = Date().timeIntervalSince(lastConsumerReceivedTime)
        let t = task
        lock.unlock()

        // If consumer has already consumed at least one chunk, is NOT waiting for another chunk (e.g. broke out of loop),
        // and has not called next in >350ms while producer continues emitting chunks, cancel producer!
        if consumed && !waiting && elapsed > 0.35 {
            t?.cancel()
        }
    }
}

final class CancellableStreamBox: @unchecked Sendable {
    private var iterator: AsyncThrowingStream<CLIStreamChunk, Error>.Iterator
    private let task: Task<Void, Never>
    private let coordinator: StreamCoordinator

    init(stream: AsyncThrowingStream<CLIStreamChunk, Error>, task: Task<Void, Never>, coordinator: StreamCoordinator) {
        self.iterator = stream.makeAsyncIterator()
        self.task = task
        self.coordinator = coordinator
    }

    func next() async throws -> CLIStreamChunk? {
        coordinator.markConsumerWaiting()
        do {
            let chunk = try await iterator.next()
            coordinator.markConsumerReceived()
            return chunk
        } catch {
            coordinator.markConsumerReceived()
            throw error
        }
    }

    deinit {
        task.cancel()
    }
}

