import XCTest
@testable import FinanceCockpit

struct ProcessTestTimeoutError: Error, CustomStringConvertible {
    let seconds: TimeInterval
    var description: String { "Test exceeded maximum timeout of \(seconds)s" }
}

func withTestTimeout<T: Sendable>(seconds: TimeInterval = 15.0, operation: @Sendable @escaping () async throws -> T) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask {
            try await operation()
        }
        group.addTask {
            try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            throw ProcessTestTimeoutError(seconds: seconds)
        }
        let result = try await group.next()!
        group.cancelAll()
        return result
    }
}

final class CLIProcessRunnerStressTests: XCTestCase {

    static let pythonPath = "/usr/bin/python3"
    static let sleepPath = "/bin/sleep"
    static let tempDir = FileManager.default.temporaryDirectory.path

    // MARK: - Challenge 1: Timeout Prompt Enforcement (/bin/sleep)
    func testTimeoutPromptEnforcement() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.sleepPath, workingDirectory: Self.tempDir)
            let startTime = Date()

            do {
                _ = try await runner.runCommand(arguments: ["10"], timeoutSeconds: 1.0)
                XCTFail("Expected runCommand to throw ProcessError.timedOut")
            } catch {
                let elapsed = Date().timeIntervalSince(startTime)
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Expected ProcessError.timedOut, got: \(error)")
                    return
                }
                XCTAssertLessThan(elapsed, 4.0, "Timeout must abort within 4 seconds, but took \(elapsed) seconds")
            }
        }
    }

    // MARK: - Python SIGINT Timeout Handling
    func testPythonSigintHandling() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let script = "import time; time.sleep(10)"
            let startTime = Date()

            do {
                _ = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 1.0)
                XCTFail("Expected runCommand to throw ProcessError.timedOut")
            } catch {
                let elapsed = Date().timeIntervalSince(startTime)
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Expected ProcessError.timedOut, got: \(error)")
                    return
                }
                XCTAssertLessThan(elapsed, 4.0, "Python timeout must abort within 4 seconds, but took \(elapsed) seconds")
            }
        }
    }

    // MARK: - Grandchild Process Keeps Pipe Open (Bounded Exit <= 4s)
    func testGrandchildProcessKeepsPipeOpenBoundedExit() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            // Python process launches /bin/sleep 30 as a grandchild inheriting stdout, then Python exits immediately.
            let script = "import sys, subprocess; subprocess.Popen(['/bin/sleep', '30'], stdout=sys.stdout); sys.stdout.write('PARENT_DONE\\n'); sys.stdout.flush()"
            let startTime = Date()

            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0)
            let elapsed = Date().timeIntervalSince(startTime)

            XCTAssertTrue(result.isSuccess, "Parent should exit successfully")
            XCTAssertTrue(result.stdout.contains("PARENT_DONE"), "Should read stdout from parent")
            XCTAssertLessThan(elapsed, 4.0, "Grandchild pipe leak must not block; completed in \(elapsed)s (must be <= 4s)")
        }
    }

    // MARK: - Normal Exit: Output Is Not Lost (Including Last Line)
    func testNormalExitNoOutputLossIncludingLastLine() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            // Writes 3 lines, with the last line lacking a trailing newline
            let script = "import sys; sys.stdout.write('LINE_ONE\\nLINE_TWO\\nLAST_LINE_NO_NEWLINE'); sys.stdout.flush()"

            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 5.0)

            XCTAssertTrue(result.isSuccess)
            XCTAssertTrue(result.stdout.contains("LINE_ONE"), "Must contain line 1")
            XCTAssertTrue(result.stdout.contains("LINE_TWO"), "Must contain line 2")
            XCTAssertTrue(result.stdout.contains("LAST_LINE_NO_NEWLINE"), "Must contain last line without trailing newline")
        }
    }

    // MARK: - 200 KB Stdin Streaming
    func testAsyncStdinStreaming200KB() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let payload = String(repeating: "Z", count: 200 * 1024)
            let script = "import sys; data = sys.stdin.read(); sys.stdout.write(f'BYTES_{len(data)}'); sys.stdout.flush()"

            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0, stdin: payload)

            XCTAssertTrue(result.isSuccess)
            XCTAssertEqual(result.stdout, "BYTES_204800")
        }
    }

    // MARK: - Task Cancellation Stops Promptly
    func testProcessCancellationStopsPromptly() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let script = "import time; time.sleep(20)"

            let startTime = Date()
            let task = Task {
                try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 30.0)
            }

            // Let it start
            try await Task.sleep(nanoseconds: 200_000_000)
            task.cancel()

            do {
                _ = try await task.value
                XCTFail("Cancelled task should throw CancellationError")
            } catch {
                let elapsed = Date().timeIntervalSince(startTime)
                XCTAssertTrue(error is CancellationError || (error as? CLIProcessRunner.ProcessError) != nil)
                XCTAssertLessThan(elapsed, 3.0, "Cancelled process must stop within 3 seconds, took \(elapsed)s")
            }
        }
    }

    // MARK: - Rapid Stream Cancellation Kills Process
    func testRapidStreamCancellationKillsProcess() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let heartBeatFile = FileManager.default.temporaryDirectory.appendingPathComponent("heartbeat_\(UUID().uuidString).txt")
            defer { try? FileManager.default.removeItem(at: heartBeatFile) }

            let script = """
            import sys, time
            hb_path = sys.argv[1]
            for i in range(100):
                sys.stdout.write(f"CHUNK_{i}\\n")
                sys.stdout.flush()
                with open(hb_path, "a") as f:
                    f.write(f"{i}\\n")
                time.sleep(0.1)
            """

            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)

            var chunksReceived = 0
            let stream = runner.runStream(arguments: ["-c", script, heartBeatFile.path], timeoutSeconds: 30.0)

            for try await _ in stream {
                chunksReceived += 1
                if chunksReceived >= 3 {
                    break
                }
            }

            XCTAssertGreaterThanOrEqual(chunksReceived, 3)

            // Wait 1.0 second for cancellation propagation
            try await Task.sleep(nanoseconds: 1_000_000_000)

            let content1 = (try? String(contentsOf: heartBeatFile, encoding: .utf8)) ?? ""
            let lines1 = content1.components(separatedBy: .newlines).filter { !$0.isEmpty }

            // Wait another 0.8 second
            try await Task.sleep(nanoseconds: 800_000_000)

            let content2 = (try? String(contentsOf: heartBeatFile, encoding: .utf8)) ?? ""
            let lines2 = content2.components(separatedBy: .newlines).filter { !$0.isEmpty }

            XCTAssertEqual(lines1.count, lines2.count, "Process continued running after stream cancellation!")
        }
    }

    // MARK: - SIGINT to SIGTERM Escalation
    func testSigintToSigtermEscalation() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: Self.pythonPath)
            let script = """
            import signal, time, sys
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            time.sleep(30)
            """
            process.arguments = ["-c", script]
            try process.run()

            try await Task.sleep(nanoseconds: 200_000_000)

            let start = Date()
            await CLIProcessRunner.terminateGracefully(process: process, gracePeriod: 1.0)
            let duration = Date().timeIntervalSince(start)

            XCTAssertFalse(process.isRunning, "Process ignoring SIGINT must be terminated by SIGTERM")
            XCTAssertLessThan(duration, 4.0, "Escalation to SIGTERM took too long: \(duration)s")
        }
    }

    // MARK: - SQLite Transaction Rollback and Lock Clearance on SIGINT
    func testSQLiteTransactionRollbackOnSigint() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let dbFile = FileManager.default.temporaryDirectory.appendingPathComponent("stress_rollback_\(UUID().uuidString).db")
            defer {
                try? FileManager.default.removeItem(at: dbFile)
                try? FileManager.default.removeItem(atPath: dbFile.path + "-wal")
                try? FileManager.default.removeItem(atPath: dbFile.path + "-shm")
            }

            let setupProcess = Process()
            setupProcess.executableURL = URL(fileURLWithPath: Self.pythonPath)
            setupProcess.arguments = ["-c", "import sqlite3; c = sqlite3.connect('\(dbFile.path)'); c.execute('CREATE TABLE t (x INT)'); c.commit(); c.close()"]
            try setupProcess.run()
            setupProcess.waitUntilExit()
            XCTAssertEqual(setupProcess.terminationStatus, 0)

            let workerProcess = Process()
            workerProcess.executableURL = URL(fileURLWithPath: Self.pythonPath)
            let workerScript = """
            import sqlite3, time, sys
            conn = sqlite3.connect('\(dbFile.path)')
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES (42)")
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                conn.rollback()
                conn.close()
                sys.exit(0)
            """
            workerProcess.arguments = ["-c", workerScript]
            try workerProcess.run()

            try await Task.sleep(nanoseconds: 300_000_000)

            await CLIProcessRunner.terminateGracefully(process: workerProcess, gracePeriod: 2.0)

            XCTAssertFalse(workerProcess.isRunning, "Worker process should be terminated")
            XCTAssertEqual(workerProcess.terminationStatus, 0, "Worker should cleanly catch KeyboardInterrupt and exit 0")

            let verifyProcess = Process()
            let pipe = Pipe()
            verifyProcess.standardOutput = pipe
            verifyProcess.executableURL = URL(fileURLWithPath: Self.pythonPath)
            verifyProcess.arguments = ["-c", "import sqlite3; c = sqlite3.connect('\(dbFile.path)'); print(c.execute('SELECT COUNT(*) FROM t').fetchone()[0])"]
            try verifyProcess.run()
            verifyProcess.waitUntilExit()

            let countData = pipe.fileHandleForReading.readDataToEndOfFile()
            let countStr = String(decoding: countData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)

            XCTAssertEqual(verifyProcess.terminationStatus, 0, "Database should be accessible without lock errors")
            XCTAssertEqual(countStr, "0", "Transaction must be completely rolled back; table count should be 0")
        }
    }

    // MARK: - Stream Backpressure and Pipe Capacity
    func testHighThroughputStreamRapidCancellation() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let script = "import sys; [sys.stdout.write('A' * 65536) or sys.stdout.flush() for _ in range(160)]"

            var chunks = 0
            for try await _ in runner.runStream(arguments: ["-c", script], timeoutSeconds: 15.0) {
                chunks += 1
                if chunks >= 5 {
                    break
                }
            }
            XCTAssertGreaterThanOrEqual(chunks, 5)
        }
    }

    // MARK: - R3 (İP-2): Grandchild Process Clean Termination on Timeout
    func testGrandchildProcessTerminationWithinOneSecondOnTimeout() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)

            let script = """
            import sys, os, subprocess, time
            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            child = subprocess.Popen(["/bin/sleep", "60"])
            sys.stdout.write(f"GRANDCHILD:{child.pid}\\n")
            sys.stdout.flush()
            time.sleep(60)
            """

            final class Box: @unchecked Sendable {
                var pid: pid_t?
                let lock = NSLock()
                func set(_ val: pid_t) { lock.lock(); pid = val; lock.unlock() }
                func get() -> pid_t? { lock.lock(); defer { lock.unlock() }; return pid }
            }
            let box = Box()

            do {
                _ = try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 1.0,
                    onStdoutChunk: { chunk in
                        if let range = chunk.range(of: "GRANDCHILD:") {
                            let sub = chunk[range.upperBound...]
                            if let line = sub.components(separatedBy: .newlines).first,
                               let parsed = pid_t(line.trimmingCharacters(in: .whitespaces)) {
                                box.set(parsed)
                            }
                        }
                    }
                )
                XCTFail("Komut zaman aşımına uğramalıydı")
            } catch {
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Beklenen ProcessError.timedOut, gelen: \(error)")
                    return
                }
            }

            guard let gPid = box.get() else {
                XCTFail("Torun PID yakalanamadı")
                return
            }

            // 1 saniye içinde torun sürecin ESRCH (-1) ile kapandığını doğrula
            var isDead = false
            let deadline = Date().addingTimeInterval(1.0)
            while Date() < deadline {
                if kill(gPid, 0) == -1 && errno == ESRCH {
                    isDead = true
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }

            // Clean up grandchild if still alive to avoid leaving rogue background processes
            if !isDead {
                kill(gPid, SIGKILL)
            }

            XCTAssertTrue(isDead, "Torun süreç (PID: \(gPid)) zaman aşımından sonra 1 saniye içinde sonlandırılmalıdır (kill(pid, 0) == -1, errno == ESRCH)")
        }
    }

    // MARK: - R4 (İP-3): Pipe Streaming Stress - 2 MB Stdout + Empty Stderr (100 Reps)
    func testPipeStreamingStress2MBStdoutEmptyStderr100Reps() async throws {
        let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
        let bytes = 2 * 1024 * 1024
        let script = "import sys; sys.stdout.buffer.write(b'A' * \(bytes)); sys.stdout.buffer.flush()"

        for i in 1...100 {
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0)
            XCTAssertTrue(result.isSuccess, "İterasyon \(i) başarısız")
            XCTAssertFalse(result.outputTruncated, "İterasyon \(i) kesintiye uğradı")
            XCTAssertEqual(result.stdout.utf8.count, bytes, "İterasyon \(i) bayt kaybı")
            XCTAssertTrue(result.stderr.isEmpty, "İterasyon \(i) stderr boş olmalı")
        }
    }

    // MARK: - R4 (İP-3): Pipe Streaming Stress - 1 MB Stderr + Empty Stdout (100 Reps)
    func testPipeStreamingStress1MBStderrEmptyStdout100Reps() async throws {
        let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
        let bytes = 1 * 1024 * 1024
        let script = "import sys; sys.stderr.buffer.write(b'B' * \(bytes)); sys.stderr.buffer.flush()"

        for i in 1...100 {
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0)
            XCTAssertTrue(result.isSuccess, "İterasyon \(i) başarısız")
            XCTAssertFalse(result.outputTruncated, "İterasyon \(i) kesintiye uğradı")
            XCTAssertEqual(result.stderr.utf8.count, bytes, "İterasyon \(i) stderr bayt kaybı")
            XCTAssertTrue(result.stdout.isEmpty, "İterasyon \(i) stdout boş olmalı")
        }
    }

    // MARK: - R4 (İP-3): Output Truncation Flag and Explicit JSON Decode Error
    func testOutputTruncationFlagAndExplicitJSONError() throws {
        let truncatedResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "{\"status\": \"ok\", \"items\": [",
            stderr: "",
            message: "",
            outputTruncated: true
        )

        struct TestPayload: Decodable {
            let status: String
        }

        XCTAssertThrowsError(try truncatedResult.decodeJSON(TestPayload.self)) { error in
            guard case CLIDecodeError.outputTruncated = error else {
                XCTFail("Beklenen CLIDecodeError.outputTruncated, gelen: \(error)")
                return
            }
        }
    }

    // MARK: - R4 Adversarial: Simultaneous 2 MB Stdout + 2 MB Stderr
    func testAdversarialSimultaneous2MBStdoutAnd2MBStderr() async throws {
        try await withTestTimeout(seconds: 20.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let bytes = 2 * 1024 * 1024
            let script = """
            import sys, threading

            def write_out():
                sys.stdout.buffer.write(b'X' * \(bytes))
                sys.stdout.buffer.flush()

            def write_err():
                sys.stderr.buffer.write(b'Y' * \(bytes))
                sys.stderr.buffer.flush()

            t1 = threading.Thread(target=write_out)
            t2 = threading.Thread(target=write_err)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            """
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 15.0)
            XCTAssertTrue(result.isSuccess, "Simultaneous stdout/stderr should exit cleanly")
            XCTAssertFalse(result.outputTruncated, "Output should not be truncated")
            XCTAssertEqual(result.stdout.utf8.count, bytes, "Stdout should have exactly 2 MB")
            XCTAssertEqual(result.stderr.utf8.count, bytes, "Stderr should have exactly 2 MB")
        }
    }

    // MARK: - R4 Adversarial: Slow Producer Arriving at 1.95s (Before 2.0s Drain Ceiling)
    func testAdversarialSlowProducerBeforeDrainCeiling() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            // Grandchild inherits stdout, sleeps for 1.85s (arriving just before 2.0s ceiling), then writes and exits
            let script = """
            import sys, subprocess
            subprocess.Popen([
                sys.executable, "-c",
                "import sys, time; time.sleep(1.85); sys.stdout.write('LATE_DATA_ARRIVED\\\\n'); sys.stdout.flush()"
            ], stdout=sys.stdout)
            """
            let start = Date()
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0)
            let elapsed = Date().timeIntervalSince(start)

            XCTAssertTrue(result.isSuccess, "Parent exited 0")
            XCTAssertFalse(result.outputTruncated, "Drain should NOT be truncated when output arrives before 2.0s ceiling")
            XCTAssertTrue(result.stdout.contains("LATE_DATA_ARRIVED"), "Output arriving at ~1.85-1.95s must be completely captured")
            XCTAssertGreaterThanOrEqual(elapsed, 1.8, "Execution should have waited for late-arriving output")
            XCTAssertLessThan(elapsed, 3.0, "Execution should complete promptly after late-arriving output")
        }
    }

    // MARK: - R4 Adversarial: Abrupt Child Crash While Writing to Pipe
    func testAdversarialAbruptChildCrashWhileWriting() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let script = """
            import sys, os, signal
            sys.stdout.write("CRASH_TEST_PRE_CRASH_DATA\\n")
            sys.stdout.flush()
            # Abruptly kill self via SIGKILL without closing fds cleanly
            os.kill(os.getpid(), signal.SIGKILL)
            """
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 5.0)
            XCTAssertFalse(result.isSuccess, "Process killed with SIGKILL should not be success")
            XCTAssertNotEqual(result.exitCode, 0, "Exit code should be non-zero (killed by SIGKILL)")
            XCTAssertFalse(result.outputTruncated, "Abrupt crash should close pipe via OS and not cause drain timeout")
            XCTAssertTrue(result.stdout.contains("CRASH_TEST_PRE_CRASH_DATA"), "Data written before crash must be preserved")
        }
    }

    // MARK: - R4 Adversarial: Output Truncation When 2.0s Ceiling Is Exceeded
    func testAdversarialOutputTruncationWhenCeilingExceeded() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            // Grandchild inherits stdout and sleeps for 4 seconds, holding pipe open after parent exits
            let script = """
            import sys, subprocess
            subprocess.Popen(["/bin/sleep", "4"], stdout=sys.stdout)
            sys.stdout.write('{"status": "ok", "items": [')
            sys.stdout.flush()
            """
            let start = Date()
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 10.0)
            let elapsed = Date().timeIntervalSince(start)

            XCTAssertLessThan(elapsed, 3.5, "Should not wait for grandchild 4s sleep; drain ceiling is 2.0s")
            XCTAssertTrue(result.outputTruncated, "outputTruncated flag MUST be true when 2.0s ceiling is exceeded")
            XCTAssertTrue(result.stdout.contains("items"), "Stdout up to truncation point must be captured")

            struct TestPayload: Decodable {
                let status: String
                let items: [String]
            }

            // Decoding JSON from truncated output MUST throw CLIDecodeError.outputTruncated
            XCTAssertThrowsError(try result.decodeJSON(TestPayload.self)) { error in
                guard case CLIDecodeError.outputTruncated(let msg) = error else {
                    XCTFail("Expected CLIDecodeError.outputTruncated, got: \(error)")
                    return
                }
                XCTAssertTrue(msg.contains("outputTruncated = true"))
            }
        }
    }
}
