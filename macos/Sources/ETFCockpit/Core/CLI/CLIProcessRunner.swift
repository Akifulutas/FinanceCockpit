import Foundation

public actor CLIProcessRunner: CLIProcessRunnerProtocol {
    public let executablePath: String
    public let workingDirectory: String
    public let defaultTimeout: TimeInterval

    public enum ProcessError: Error, LocalizedError, Equatable {
        case binaryNotFound(path: String)
        case timedOut(seconds: TimeInterval)
        case executionFailed(exitCode: Int32, message: String)

        public var errorDescription: String? {
            switch self {
            case .binaryNotFound(let path):
                return "CLI executable not found or not executable: \(path)"
            case .timedOut(let s):
                return "CLI command timed out (\(s) seconds)."
            case .executionFailed(let code, let msg):
                return "CLI command failed (exit code: \(code)): \(msg)"
            }
        }
    }

    public init(
        executablePath: String? = nil,
        workingDirectory: String? = nil,
        defaultTimeout: TimeInterval = 60.0
    ) {
        let resolvedExec = Self.resolveExecutablePath(customPath: executablePath)
        self.executablePath = resolvedExec
        self.workingDirectory = Self.resolveWorkingDirectory(customPath: workingDirectory, forExecutable: resolvedExec)
        self.defaultTimeout = defaultTimeout
    }

    // MARK: - Dynamic Path Resolution

    public nonisolated static func resolveExecutablePath(customPath: String? = nil) -> String {
        if let customPath = customPath, !customPath.trimmingCharacters(in: .whitespaces).isEmpty {
            return customPath
        }

        // 1. Environment variable MASA_EXECUTABLE_PATH
        if let envPath = ProcessInfo.processInfo.environment["MASA_EXECUTABLE_PATH"],
           !envPath.isEmpty,
           FileManager.default.isExecutableFile(atPath: envPath) {
            return envPath
        }

        // 2. Candidate workspace paths
        let cwd = FileManager.default.currentDirectoryPath
        let defaultWs = CockpitPathResolver.defaultWorkingDirectory
        let candidates = [
            cwd + "/etf-masa",
            cwd + "/../etf-masa",
            (cwd as NSString).appendingPathComponent("etf-masa"),
            (defaultWs as NSString).appendingPathComponent("etf-masa"),
            FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Documents/ETF/etf-masa").path
        ]
        for candidate in candidates {
            if FileManager.default.isExecutableFile(atPath: candidate) && CockpitPathResolver.validateFileOwnership(atPath: candidate) {
                return (candidate as NSString).standardizingPath
            }
        }

        // 3. Search system PATH
        if let pathEnv = ProcessInfo.processInfo.environment["PATH"] {
            let dirs = pathEnv.split(separator: ":")
            for dir in dirs {
                let candidate = (String(dir) as NSString).appendingPathComponent("etf-masa")
                if FileManager.default.isExecutableFile(atPath: candidate) && CockpitPathResolver.validateFileOwnership(atPath: candidate) {
                    return candidate
                }
            }
        }

        // 4. Bundle resources
        if let bundlePath = Bundle.main.path(forResource: "etf-masa", ofType: nil),
           FileManager.default.isExecutableFile(atPath: bundlePath) {
            return bundlePath
        }

        // 5. Fallback canonical path
        return (defaultWs as NSString).appendingPathComponent("etf-masa")
    }

    public nonisolated static func resolveWorkingDirectory(customPath: String? = nil, forExecutable executablePath: String? = nil) -> String {
        if let customPath = customPath, !customPath.trimmingCharacters(in: .whitespaces).isEmpty {
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: customPath, isDirectory: &isDir), isDir.boolValue {
                return (customPath as NSString).standardizingPath
            }
            return customPath
        }

        // If executable path is known, check if its containing directory has a masa/ subdirectory
        if let exec = executablePath, !exec.isEmpty {
            let execDir = (exec as NSString).deletingLastPathComponent
            let masaDir = (execDir as NSString).appendingPathComponent("masa")
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: masaDir, isDirectory: &isDir), isDir.boolValue {
                return execDir
            }
        }

        // Check current directory for masa/
        let cwd = FileManager.default.currentDirectoryPath
        let cwdMasa = (cwd as NSString).appendingPathComponent("masa")
        var isDir: ObjCBool = false
        if FileManager.default.fileExists(atPath: cwdMasa, isDirectory: &isDir), isDir.boolValue {
            return cwd
        }

        return CockpitPathResolver.defaultWorkingDirectory
    }

    // MARK: - Command Timeout Resolver

    public nonisolated static func resolveCommandTimeout(
        for arguments: [String],
        fallback: TimeInterval? = nil
    ) -> TimeInterval {
        let cleanArgs = arguments.filter { !$0.hasPrefix("-") }
        guard let first = cleanArgs.first else {
            return fallback ?? 60.0
        }

        // Fast path for tarama --son
        if first == "tarama" && arguments.contains("--son") {
            return 30.0
        }

        // 3600s: arastir, tradingagents, yorum, baslat
        if ["arastir", "tradingagents", "yorum", "baslat"].contains(first) {
            return 3600.0
        }

        // 600s: gecmis, tarama (live)
        if ["gecmis", "tarama"].contains(first) {
            return 600.0
        }

        // 300s: veri, giris --login, tahmin uret, islemler cek
        if first == "veri" || (first == "giris" && arguments.contains("--login")) {
            return 300.0
        }
        if first == "tahmin" && cleanArgs.contains("uret") {
            return 300.0
        }
        if first == "islemler" && cleanArgs.contains("cek") {
            return 300.0
        }

        // 180s: degerlendir, plan, mutabakat, yedek --prova, tahmin uzlas, model degerlendir
        if ["degerlendir", "plan", "mutabakat"].contains(first) {
            return 180.0
        }
        if first == "yedek" && arguments.contains("--prova") {
            return 180.0
        }
        if first == "tahmin" && cleanArgs.contains("uzlas") {
            return 180.0
        }
        if first == "model" && cleanArgs.contains("degerlendir") {
            return 180.0
        }

        // 120s: guvenlik-tara, tez, rapor, yedek
        if ["guvenlik-tara", "tez", "rapor", "yedek"].contains(first) {
            return 120.0
        }

        // 30s: durum, kontrol, zamanla durum, zamanla bildirim-test, ayar goster, giris --json
        if ["durum", "kontrol"].contains(first) ||
           (first == "zamanla" && cleanArgs.contains("durum")) ||
           (first == "zamanla" && cleanArgs.contains("bildirim-test")) ||
           (first == "ayar" && cleanArgs.contains("goster")) ||
           (first == "giris" && arguments.contains("--json")) {
            return 30.0
        }

        // Default
        return fallback ?? 60.0
    }

    // MARK: - Graceful Termination

    private nonisolated static func sendSignal(
        target: pid_t,
        signal: Int32,
        signalName: String,
        context: String
    ) {
        let res = kill(target, signal)
        if res != 0 {
            let err = errno
            CockpitLogger.shared.debug("kill(\(target), \(signalName)) in \(context): res=\(res), errno=\(err) (\(String(cString: strerror(err))))")
        } else {
            CockpitLogger.shared.debug("kill(\(target), \(signalName)) succeeded in \(context)")
        }
    }

    public nonisolated static func terminateGracefully(
        process: Process,
        gracePeriod: TimeInterval = 10.0
    ) async {
        let pid = process.processIdentifier
        guard pid > 0 else {
            if process.isRunning {
                process.terminate()
            }
            return
        }

        // Determine if process is group leader
        let pgid = getpgid(pid)
        let isGroupLeader = (pgid > 0 && pgid == pid)
        let target = isGroupLeader ? -pgid : pid

        if process.isRunning {
            // Step 1: Send SIGINT to process group (or single pid if not leader)
            sendSignal(target: target, signal: SIGINT, signalName: "SIGINT", context: "terminateGracefully Step 1")

            // Poll for up to gracePeriod seconds while process is running
            let deadline = Date().addingTimeInterval(gracePeriod)
            while process.isRunning && Date() < deadline {
                try? await Task.sleep(nanoseconds: 25_000_000) // 25ms intervals
            }

            // Step 2: Escalate to SIGTERM if still alive
            if process.isRunning {
                sendSignal(target: target, signal: SIGTERM, signalName: "SIGTERM", context: "terminateGracefully Step 2")
                let termDeadline = Date().addingTimeInterval(1.0)
                while process.isRunning && Date() < termDeadline {
                    try? await Task.sleep(nanoseconds: 25_000_000)
                }
            }

            // Step 3: Hard kill if still alive
            if process.isRunning {
                sendSignal(target: target, signal: SIGKILL, signalName: "SIGKILL", context: "terminateGracefully Step 3")
            }
        }

        // Final cleanup: if process group leader, check if any lingering grandchildren remain in the group
        if isGroupLeader && kill(-pgid, 0) == 0 {
            sendSignal(target: -pgid, signal: SIGTERM, signalName: "SIGTERM", context: "terminateGracefully lingering grandchildren")
            if kill(-pgid, 0) == 0 {
                sendSignal(target: -pgid, signal: SIGKILL, signalName: "SIGKILL", context: "terminateGracefully lingering grandchildren kill")
            }
        }
    }

    // MARK: - Core Process Execution

    public func runCommand(
        arguments: [String],
        timeoutSeconds: TimeInterval? = nil,
        stdin: String? = nil,
        onStdoutChunk: (@Sendable (String) -> Void)? = nil,
        onStderrChunk: (@Sendable (String) -> Void)? = nil
    ) async throws -> CLIOperationResult {
        guard FileManager.default.isExecutableFile(atPath: executablePath) else {
            throw ProcessError.binaryNotFound(path: executablePath)
        }

        let effectiveTimeout: TimeInterval
        if let explicit = timeoutSeconds {
            effectiveTimeout = explicit
        } else {
            effectiveTimeout = Self.resolveCommandTimeout(for: arguments, fallback: defaultTimeout)
        }

        return try await Self.executeProcess(
            executablePath: executablePath,
            arguments: arguments,
            workingDirectory: workingDirectory,
            timeoutSeconds: effectiveTimeout,
            stdin: stdin,
            onStdoutChunk: onStdoutChunk,
            onStderrChunk: onStderrChunk
        )
    }

    public nonisolated static func executeProcess(
        executablePath: String,
        arguments: [String],
        workingDirectory: String,
        timeoutSeconds: TimeInterval,
        stdin: String? = nil,
        onStdoutChunk: (@Sendable (String) -> Void)? = nil,
        onStderrChunk: (@Sendable (String) -> Void)? = nil
    ) async throws -> CLIOperationResult {
        let process = Process()
        let outPipe = Pipe()
        let errPipe = Pipe()

        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = arguments
        process.currentDirectoryURL = URL(fileURLWithPath: workingDirectory)
        process.standardOutput = outPipe
        process.standardError = errPipe

        let inPipe: Pipe?
        let stdinData: Data?
        if let stdin = stdin, let data = stdin.data(using: .utf8) {
            let pipe = Pipe()
            process.standardInput = pipe
            inPipe = pipe
            stdinData = data
        } else {
            inPipe = nil
            stdinData = nil
        }

        // Configure sanitized execution environment
        var env = ProcessInfo.processInfo.environment
        let standardPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        if let currentPath = env["PATH"] {
            env["PATH"] = "\(standardPath):\(currentPath)"
        } else {
            env["PATH"] = standardPath
        }
        env["LANG"] = "en_US.UTF-8"
        env["LC_ALL"] = "en_US.UTF-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["MASA_OWN_PGRP"] = "1"
        process.environment = env

        CockpitLogger.shared.info("CLI Executing: \(executablePath) \(arguments.joined(separator: " "))")

        let (outStream, outContinuation) = AsyncStream<Data>.makeStream()
        let (errStream, errContinuation) = AsyncStream<Data>.makeStream()

        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                outContinuation.finish()
            } else {
                outContinuation.yield(data)
            }
        }

        errPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                errContinuation.finish()
            } else {
                errContinuation.yield(data)
            }
        }

        let stdoutTask = Task<Data, Never> {
            var accumulated = Data()
            for await chunk in outStream {
                accumulated.append(chunk)
                if let onStdoutChunk {
                    let chunkStr = String(decoding: chunk, as: UTF8.self)
                    onStdoutChunk(chunkStr)
                }
            }
            return accumulated
        }

        let stderrTask = Task<Data, Never> {
            var accumulated = Data()
            for await chunk in errStream {
                accumulated.append(chunk)
                if let onStderrChunk {
                    let chunkStr = String(decoding: chunk, as: UTF8.self)
                    onStderrChunk(chunkStr)
                }
            }
            return accumulated
        }

        let context = ProcessContext(process: process)
        let exitWatcher = ProcessExitWatcher()

        // 1. Assign terminationHandler BEFORE run()
        process.terminationHandler = { proc in
            exitWatcher.markExited(status: proc.terminationStatus)
        }

        do {
            try Task.checkCancellation()
            try process.run()
            let pid = process.processIdentifier
            if pid > 0 {
                let res = setpgid(pid, pid)
                if res != 0 {
                    let err = errno
                    CockpitLogger.shared.debug("setpgid(\(pid), \(pid)) res=\(res), errno=\(err) (\(String(cString: strerror(err))))")
                } else {
                    CockpitLogger.shared.debug("setpgid(\(pid), \(pid)) succeeded")
                }
            }
            if Task.isCancelled {
                await Self.terminateGracefully(process: process)
                throw CancellationError()
            }
            // Close parent write file descriptors so the child is the sole writer.
            try? outPipe.fileHandleForWriting.close()
            try? errPipe.fileHandleForWriting.close()
        } catch {
            outPipe.fileHandleForReading.readabilityHandler = nil
            errPipe.fileHandleForReading.readabilityHandler = nil
            try? outPipe.fileHandleForWriting.close()
            try? errPipe.fileHandleForWriting.close()
            try? inPipe?.fileHandleForWriting.close()
            outContinuation.finish()
            errContinuation.finish()
            stdoutTask.cancel()
            stderrTask.cancel()
            if error is CancellationError {
                throw error
            }
            throw ProcessError.executionFailed(exitCode: -1, message: "Process run failed: \(error.localizedDescription)")
        }

        // Asynchronously stream stdin to process after run() has begun
        let stdinTask: Task<Void, Never>?
        if let inPipe = inPipe, let stdinData = stdinData {
            stdinTask = Task {
                let writeHandle = inPipe.fileHandleForWriting
                let chunkSize = 65536
                var offset = 0
                while offset < stdinData.count && !Task.isCancelled {
                    let end = min(offset + chunkSize, stdinData.count)
                    let chunk = stdinData.subdata(in: offset..<end)
                    do {
                        try writeHandle.write(contentsOf: chunk)
                    } catch {
                        break
                    }
                    offset = end
                }
                try? writeHandle.close()
            }
        } else {
            stdinTask = nil
        }

        do {
            return try await withTaskCancellationHandler {
                try await withThrowingTaskGroup(of: CLIOperationResult.self) { group in
                    // Execution Task: Wait for exit watcher asynchronously without blocking
                    group.addTask {
                        let exitStatus = await withCheckedContinuation { cont in
                            exitWatcher.setContinuation(cont)
                        }

                        if context.didTimeout {
                            outPipe.fileHandleForReading.readabilityHandler = nil
                            errPipe.fileHandleForReading.readabilityHandler = nil
                            outContinuation.finish()
                            errContinuation.finish()
                            stdoutTask.cancel()
                            stderrTask.cancel()
                            throw ProcessError.timedOut(seconds: timeoutSeconds)
                        }
                        if Task.isCancelled {
                            outPipe.fileHandleForReading.readabilityHandler = nil
                            errPipe.fileHandleForReading.readabilityHandler = nil
                            outContinuation.finish()
                            errContinuation.finish()
                            stdoutTask.cancel()
                            stderrTask.cancel()
                            throw CancellationError()
                        }

                        // Wait for pipe EOF of BOTH stdout and stderr concurrently with an upper limit of 2.0 seconds
                        let isDrainTimedOut = await withTaskGroup(of: Bool.self) { drainGroup in
                            drainGroup.addTask {
                                async let out = stdoutTask.value
                                async let err = stderrTask.value
                                _ = await (out, err)
                                return false
                            }
                            drainGroup.addTask {
                                do {
                                    try await Task.sleep(nanoseconds: 2_000_000_000)
                                } catch {
                                    return false
                                }
                                outPipe.fileHandleForReading.readabilityHandler = nil
                                errPipe.fileHandleForReading.readabilityHandler = nil
                                outContinuation.finish()
                                errContinuation.finish()
                                stdoutTask.cancel()
                                stderrTask.cancel()
                                return true
                            }
                            let timedOut = await drainGroup.next() ?? false
                            drainGroup.cancelAll()
                            return timedOut
                        }

                        let outData = await stdoutTask.value
                        let errData = await stderrTask.value

                        outPipe.fileHandleForReading.readabilityHandler = nil
                        errPipe.fileHandleForReading.readabilityHandler = nil
                        try? outPipe.fileHandleForWriting.close()
                        try? errPipe.fileHandleForWriting.close()

                        if context.didTimeout {
                            throw ProcessError.timedOut(seconds: timeoutSeconds)
                        }
                        if Task.isCancelled {
                            throw CancellationError()
                        }

                        let stdout = String(data: outData, encoding: .utf8) ?? String(decoding: outData, as: UTF8.self)
                        let stderr = String(data: errData, encoding: .utf8) ?? String(decoding: errData, as: UTF8.self)
                        let isSuccess = (exitStatus == 0)

                        return CLIOperationResult(
                            isSuccess: isSuccess,
                            exitCode: exitStatus,
                            stdout: stdout,
                            stderr: stderr,
                            message: isSuccess ? "Operation completed successfully." : (stderr.isEmpty ? stdout : stderr),
                            outputTruncated: isDrainTimedOut
                        )
                    }

                    // Timeout Task
                    group.addTask {
                        do {
                            try await Task.sleep(nanoseconds: UInt64(timeoutSeconds * 1_000_000_000))
                        } catch {
                            // Cancelled before timeout expired - expected normal completion path
                            return CLIOperationResult(isSuccess: false, exitCode: -999, stdout: "", stderr: "", message: "Cancelled")
                        }

                        context.markTimeout()
                        if process.isRunning {
                            let grace = min(10.0, max(0.2, timeoutSeconds))
                            await Self.terminateGracefully(process: process, gracePeriod: grace)
                        }
                        stdinTask?.cancel()
                        try? inPipe?.fileHandleForWriting.close()
                        outPipe.fileHandleForReading.readabilityHandler = nil
                        errPipe.fileHandleForReading.readabilityHandler = nil
                        outContinuation.finish()
                        errContinuation.finish()
                        stdoutTask.cancel()
                        stderrTask.cancel()
                        throw ProcessError.timedOut(seconds: timeoutSeconds)
                    }

                    var finalResult: CLIOperationResult?
                    while let nextResult = try await group.next() {
                        if nextResult.exitCode != -999 {
                            finalResult = nextResult
                            break
                        }
                    }
                    guard let result = finalResult else {
                        throw ProcessError.executionFailed(exitCode: -1, message: "Could not obtain operation result.")
                    }
                    stdinTask?.cancel()
                    try? inPipe?.fileHandleForWriting.close()
                    group.cancelAll()
                    return result
                }
            } onCancel: {
                stdinTask?.cancel()
                try? inPipe?.fileHandleForWriting.close()
                let pid = process.processIdentifier
                if pid > 0 {
                    let pgid = getpgid(pid)
                    let isLeader = (pgid > 0 && pgid == pid)
                    let target = isLeader ? -pgid : pid
                    sendSignal(target: target, signal: SIGINT, signalName: "SIGINT", context: "onCancel")
                }
                Task {
                    await Self.terminateGracefully(process: process)
                }
            }
        } catch {
            outPipe.fileHandleForReading.readabilityHandler = nil
            errPipe.fileHandleForReading.readabilityHandler = nil
            try? outPipe.fileHandleForWriting.close()
            try? errPipe.fileHandleForWriting.close()
            outContinuation.finish()
            errContinuation.finish()
            stdoutTask.cancel()
            stderrTask.cancel()
            if process.isRunning {
                await Self.terminateGracefully(process: process)
            }
            throw error
        }
    }

    // MARK: - Subsystem 8: Integrity & Security Commands

    public func runVerifyIntegrity() async throws -> IntegrityCheckResult {
        let result = try await runCommand(arguments: ["dogrula"])
        return CLIOutputParsers.parseDogrula(output: result.stdout)
    }

    public func runBackup(drillOnly: Bool = false) async throws -> BackupResult {
        let args = drillOnly ? ["yedek", "--prova"] : ["yedek"]
        let result = try await runCommand(arguments: args)
        return CLIOutputParsers.parseYedek(output: result.stdout, exitCode: result.exitCode)
    }

    public func runSecurityScan() async throws -> SecurityScanResult {
        let result = try await runCommand(arguments: ["guvenlik-tara"])
        return CLIOutputParsers.parseGuvenlikTara(output: result.stdout, exitCode: result.exitCode)
    }

    // MARK: - Subsystem 2: Forecast & Settlement Commands

    public func runForecastMorning() async throws -> CLIOperationResult {
        return try await runCommand(arguments: ["tahmin", "uret"])
    }

    public func runSettleEvening() async throws -> CLIOperationResult {
        return try await runCommand(arguments: ["tahmin", "uzlas"])
    }

    public func runForecastSimulation(days: Int = 30) async throws -> CLIOperationResult {
        return try await runCommand(arguments: ["tahmin", "gecmis-simule", "--gun", String(days)], timeoutSeconds: 300.0)
    }

    // MARK: - Subsystem 3: Research Commands

    public func runResearch(isin: String, horizon: String? = nil) async throws -> CLIOperationResult {
        var args = ["arastir", isin]
        if let horizon = horizon, !horizon.isEmpty {
            args.append(contentsOf: ["--vade", horizon])
        }
        return try await runCommand(arguments: args, timeoutSeconds: 3600.0)
    }

    public func runResearch(query: String?, ticker: String?) async throws -> CLIOperationResult {
        let identifier = ticker ?? (query ?? "")
        guard !identifier.isEmpty else {
            return CLIOperationResult(isSuccess: false, exitCode: 1, stdout: "", stderr: "Ticker or query must not be empty", message: "Eksik parametre")
        }
        return try await runResearch(isin: identifier, horizon: nil)
    }

    // MARK: - Subsystem 9: Scheduler Commands

    public func runSchedulerAction(agent: String, action: String) async throws -> CLIOperationResult {
        return try await runCommand(arguments: ["zamanla", action])
    }
}

// MARK: - Process Context Helper

private final class ProcessContext: @unchecked Sendable {
    let process: Process
    private let lock = NSLock()
    private var _didTimeout = false

    init(process: Process) {
        self.process = process
    }

    var didTimeout: Bool {
        lock.lock()
        defer { lock.unlock() }
        return _didTimeout
    }

    func markTimeout() {
        lock.lock()
        _didTimeout = true
        lock.unlock()
    }
}

// MARK: - Process Exit Watcher

private final class ProcessExitWatcher: @unchecked Sendable {
    private var continuation: CheckedContinuation<Int32, Never>?
    private let lock = NSLock()
    private var didExit = false
    private var exitStatus: Int32 = -1

    func setContinuation(_ cont: CheckedContinuation<Int32, Never>) {
        lock.lock()
        defer { lock.unlock() }
        if didExit {
            cont.resume(returning: exitStatus)
        } else {
            self.continuation = cont
        }
    }

    func markExited(status: Int32) {
        lock.lock()
        defer { lock.unlock() }
        didExit = true
        exitStatus = status
        if let cont = continuation {
            continuation = nil
            cont.resume(returning: status)
        }
    }
}

