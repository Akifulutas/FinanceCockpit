import XCTest
@testable import FinanceCockpit

final class CLIProcessRunnerAdversarialTests: XCTestCase {

    static let pythonPath = "/usr/bin/python3"
    static let tempDir = FileManager.default.temporaryDirectory.path

    final class PidCollector: @unchecked Sendable {
        private var pids: [String: pid_t] = [:]
        private let lock = NSLock()

        func set(key: String, pid: pid_t) {
            lock.lock()
            defer { lock.unlock() }
            pids[key] = pid
        }

        func get(key: String) -> pid_t? {
            lock.lock()
            defer { lock.unlock() }
            return pids[key]
        }

        func all() -> [String: pid_t] {
            lock.lock()
            defer { lock.unlock() }
            return pids
        }
    }

    // MARK: - 1. Multiple levels of grandchildren (Python -> Bash -> Sleep)
    func testGreatGrandchildrenProcessTerminationOnTimeout() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let collector = PidCollector()

            let script = """
            import sys, os, subprocess, time

            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            sys.stdout.write(f"PARENT:{os.getpid()}\\n")
            sys.stdout.flush()

            # Bash process as child
            # Within bash, launch sleep as grandchild
            bash_script = "sleep 60 & echo SLEEP:$! ; wait"
            proc = subprocess.Popen(["/bin/bash", "-c", bash_script], stdout=subprocess.PIPE, text=True)
            sys.stdout.write(f"BASH:{proc.pid}\\n")
            sys.stdout.flush()

            sleep_line = proc.stdout.readline()
            if sleep_line.startswith("SLEEP:"):
                sys.stdout.write(f"GREAT_GRANDCHILD:{sleep_line.split(':')[1].strip()}\\n")
                sys.stdout.flush()

            time.sleep(60)
            """

            do {
                _ = try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 1.0,
                    onStdoutChunk: { chunk in
                        for line in chunk.components(separatedBy: .newlines) {
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            if trimmed.hasPrefix("PARENT:") {
                                if let p = pid_t(trimmed.dropFirst("PARENT:".count)) {
                                    collector.set(key: "PARENT", pid: p)
                                }
                            } else if trimmed.hasPrefix("BASH:") {
                                if let p = pid_t(trimmed.dropFirst("BASH:".count)) {
                                    collector.set(key: "BASH", pid: p)
                                }
                            } else if trimmed.hasPrefix("GREAT_GRANDCHILD:") {
                                if let p = pid_t(trimmed.dropFirst("GREAT_GRANDCHILD:".count)) {
                                    collector.set(key: "GREAT_GRANDCHILD", pid: p)
                                }
                            }
                        }
                    }
                )
                XCTFail("Expected runCommand to time out")
            } catch {
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Expected ProcessError.timedOut, got: \(error)")
                    return
                }
            }

            guard let bashPid = collector.get(key: "BASH"),
                  let sleepPid = collector.get(key: "GREAT_GRANDCHILD") else {
                XCTFail("Failed to collect child/grandchild PIDs: \(collector.all())")
                return
            }

            // Verify both Bash and Sleep are terminated within 1.0 second
            let deadline = Date().addingTimeInterval(1.0)
            var bashDead = false
            var sleepDead = false

            while Date() < deadline {
                if !bashDead && kill(bashPid, 0) == -1 && errno == ESRCH {
                    bashDead = true
                }
                if !sleepDead && kill(sleepPid, 0) == -1 && errno == ESRCH {
                    sleepDead = true
                }
                if bashDead && sleepDead {
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }

            // Cleanup safeguard
            if !bashDead { kill(bashPid, SIGKILL) }
            if !sleepDead { kill(sleepPid, SIGKILL) }

            XCTAssertTrue(bashDead, "Child bash (PID: \(bashPid)) should be dead within 1.0s (kill == -1, errno == ESRCH)")
            XCTAssertTrue(sleepDead, "Great-grandchild sleep (PID: \(sleepPid)) should be dead within 1.0s (kill == -1, errno == ESRCH)")
        }
    }

    // MARK: - 2. SIGHUP, SIGINT, SIGTERM resistance in child & grandchild
    func testSignalResistantChildAndGrandchildCleanedUpBySigkill() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let collector = PidCollector()

            let script = """
            import sys, os, subprocess, time, signal

            # Resist SIGHUP, SIGINT, SIGTERM
            for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
                try:
                    signal.signal(sig, signal.SIG_IGN)
                except Exception:
                    pass

            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            sys.stdout.write(f"PARENT:{os.getpid()}\\n")
            sys.stdout.flush()

            # Grandchild that also resists SIGHUP, SIGINT, SIGTERM
            gc_script = \"\"\"
            import time, signal, os, sys
            for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
                try:
                    signal.signal(sig, signal.SIG_IGN)
                except Exception:
                    pass
            print(f"GRANDCHILD:{os.getpid()}", flush=True)
            time.sleep(60)
            \"\"\"

            subprocess.Popen([sys.executable, "-c", gc_script])
            time.sleep(60)
            """

            do {
                _ = try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 2.0,
                    onStdoutChunk: { chunk in
                        for line in chunk.components(separatedBy: .newlines) {
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            if trimmed.hasPrefix("PARENT:") {
                                if let p = pid_t(trimmed.dropFirst("PARENT:".count)) {
                                    collector.set(key: "PARENT", pid: p)
                                }
                            } else if trimmed.hasPrefix("GRANDCHILD:") {
                                if let p = pid_t(trimmed.dropFirst("GRANDCHILD:".count)) {
                                    collector.set(key: "GRANDCHILD", pid: p)
                                }
                            }
                        }
                    }
                )
                XCTFail("Expected runCommand to time out")
            } catch {
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Expected ProcessError.timedOut, got: \(error)")
                    return
                }
            }

            guard let parentPid = collector.get(key: "PARENT"),
                  let gcPid = collector.get(key: "GRANDCHILD") else {
                XCTFail("Failed to collect resistant PIDs: \(collector.all())")
                return
            }

            // Verify both are dead within 1.0s after runCommand returned timedOut
            let deadline = Date().addingTimeInterval(1.0)
            var parentDead = false
            var gcDead = false

            while Date() < deadline {
                if !parentDead && kill(parentPid, 0) == -1 && errno == ESRCH {
                    parentDead = true
                }
                if !gcDead && kill(gcPid, 0) == -1 && errno == ESRCH {
                    gcDead = true
                }
                if parentDead && gcDead {
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }

            if !parentDead { kill(parentPid, SIGKILL) }
            if !gcDead { kill(gcPid, SIGKILL) }

            XCTAssertTrue(parentDead, "Resistant parent (PID: \(parentPid)) must be killed by SIGKILL escalation")
            XCTAssertTrue(gcDead, "Resistant grandchild (PID: \(gcPid)) must be killed by SIGKILL escalation")
        }
    }

    // MARK: - 3. Lingering resistant grandchild killed when parent exits on SIGINT
    func testLingeringResistantGrandchildKilledWhenParentDiesOnSigint() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let collector = PidCollector()

            // Parent exits cleanly on SIGINT, but grandchild ignores SIGINT and SIGTERM
            let script = """
            import sys, os, subprocess, time, signal

            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            print(f"PARENT:{os.getpid()}", flush=True)

            gc_script = \"\"\"
            import time, signal, os, sys
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print(f"GRANDCHILD:{os.getpid()}", flush=True)
            time.sleep(60)
            \"\"\"

            subprocess.Popen([sys.executable, "-c", gc_script])
            time.sleep(60)
            """

            do {
                _ = try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 1.5,
                    onStdoutChunk: { chunk in
                        for line in chunk.components(separatedBy: .newlines) {
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            if trimmed.hasPrefix("PARENT:") {
                                if let p = pid_t(trimmed.dropFirst("PARENT:".count)) {
                                    collector.set(key: "PARENT", pid: p)
                                }
                            } else if trimmed.hasPrefix("GRANDCHILD:") {
                                if let p = pid_t(trimmed.dropFirst("GRANDCHILD:".count)) {
                                    collector.set(key: "GRANDCHILD", pid: p)
                                }
                            }
                        }
                    }
                )
                XCTFail("Expected runCommand to time out")
            } catch {
                guard case CLIProcessRunner.ProcessError.timedOut = error else {
                    XCTFail("Expected ProcessError.timedOut, got: \(error)")
                    return
                }
            }

            guard let gcPid = collector.get(key: "GRANDCHILD") else {
                XCTFail("Failed to collect grandchild PID: \(collector.all())")
                return
            }

            let deadline = Date().addingTimeInterval(1.0)
            var gcDead = false
            while Date() < deadline {
                if kill(gcPid, 0) == -1 && errno == ESRCH {
                    gcDead = true
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            if !gcDead { kill(gcPid, SIGKILL) }

            XCTAssertTrue(gcDead, "Lingering grandchild (PID: \(gcPid)) must be killed within 1.0s even when parent died on SIGINT")
        }
    }

    // MARK: - 4. Cancellation kills grandchild promptly
    func testCancellationKillsGrandchildPromptly() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let collector = PidCollector()

            let script = """
            import sys, os, subprocess, time

            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            child = subprocess.Popen(["/bin/sleep", "60"])
            print(f"GRANDCHILD:{child.pid}", flush=True)
            time.sleep(60)
            """

            let task = Task {
                try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 30.0,
                    onStdoutChunk: { chunk in
                        for line in chunk.components(separatedBy: .newlines) {
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            if trimmed.hasPrefix("GRANDCHILD:") {
                                if let p = pid_t(trimmed.dropFirst("GRANDCHILD:".count)) {
                                    collector.set(key: "GRANDCHILD", pid: p)
                                }
                            }
                        }
                    }
                )
            }

            // Wait until grandchild is running
            let pollDeadline = Date().addingTimeInterval(5.0)
            while collector.get(key: "GRANDCHILD") == nil && Date() < pollDeadline {
                try await Task.sleep(nanoseconds: 50_000_000)
            }

            guard let gcPid = collector.get(key: "GRANDCHILD") else {
                task.cancel()
                XCTFail("Failed to collect grandchild PID before cancelling")
                return
            }

            // Cancel task
            task.cancel()

            do {
                _ = try await task.value
                XCTFail("Cancelled task should throw")
            } catch {
                XCTAssertTrue(error is CancellationError || (error as? CLIProcessRunner.ProcessError) != nil)
            }

            // Verify grandchild is dead within 1.0s
            let deadline = Date().addingTimeInterval(1.0)
            var gcDead = false
            while Date() < deadline {
                if kill(gcPid, 0) == -1 && errno == ESRCH {
                    gcDead = true
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            if !gcDead { kill(gcPid, SIGKILL) }

            XCTAssertTrue(gcDead, "Grandchild (PID: \(gcPid)) must be killed within 1.0s on cancellation")
        }
    }

    // MARK: - 5. Fast process exit before timeout vs timeout race conditions
    func testFastProcessExitVsTimeoutRaceGrandchildTermination() async throws {
        try await withTestTimeout(seconds: 15.0) {
            let runner = CLIProcessRunner(executablePath: Self.pythonPath, workingDirectory: Self.tempDir)
            let collector = PidCollector()

            // Script spawns grandchild sleep 60, then parent exits right around the timeout threshold (e.g. 0.5s)
            let script = """
            import sys, os, subprocess, time

            if os.environ.get("MASA_OWN_PGRP") == "1":
                try:
                    if os.getpgrp() != os.getpid():
                        os.setpgid(0, 0)
                except OSError:
                    pass

            child = subprocess.Popen(["/bin/sleep", "60"])
            print(f"GRANDCHILD:{child.pid}", flush=True)
            time.sleep(0.48)
            sys.exit(0)
            """

            var executionThrew = false
            do {
                _ = try await runner.runCommand(
                    arguments: ["-c", script],
                    timeoutSeconds: 0.5,
                    onStdoutChunk: { chunk in
                        for line in chunk.components(separatedBy: .newlines) {
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            if trimmed.hasPrefix("GRANDCHILD:") {
                                if let p = pid_t(trimmed.dropFirst("GRANDCHILD:".count)) {
                                    collector.set(key: "GRANDCHILD", pid: p)
                                }
                            }
                        }
                    }
                )
            } catch {
                executionThrew = true
            }

            guard let gcPid = collector.get(key: "GRANDCHILD") else {
                XCTFail("Failed to collect grandchild PID")
                return
            }

            // Check if grandchild is alive
            var isDead = false
            let deadline = Date().addingTimeInterval(1.0)
            while Date() < deadline {
                if kill(gcPid, 0) == -1 && errno == ESRCH {
                    isDead = true
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }

            if !isDead {
                kill(gcPid, SIGKILL)
            }

            if executionThrew {
                XCTAssertTrue(isDead, "If execution timed out or threw, grandchild PID \(gcPid) MUST be dead within 1.0s")
            }
        }
    }
}

