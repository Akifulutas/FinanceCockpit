import XCTest
@testable import FinanceCockpit

final class CLIProcessRunnerTests: XCTestCase {

    let cliPath = CockpitPathResolver.defaultExecutablePath
    let workingDir = CockpitPathResolver.defaultWorkingDirectory

    func testVerifyIntegrity() async throws {
        let runner = CLIProcessRunner(executablePath: cliPath, workingDirectory: workingDir)
        let result = try await runner.runVerifyIntegrity()

        XCTAssertTrue(result.ok, "Expected integrity verification to pass (ok == true)")
        XCTAssertTrue(result.fileVaultActive, "Expected FileVault disk encryption to be active")
        XCTAssertEqual(result.schemaVersion, 3, "Expected SQLite schema version 3")
        XCTAssertEqual(result.triggerCount, 78, "Expected 78 append-only triggers")
        XCTAssertTrue(result.snapshotChainOk, "Expected snapshot hash chain to be valid")
        XCTAssertTrue(result.auditChainOk, "Expected audit event hash chain to be valid")
        XCTAssertFalse(result.criticalIntegrityViolation, "Expected zero critical integrity violations")
        XCTAssertFalse(result.chainTip.isEmpty, "Expected non-empty chain tip")
    }

    func testSecurityScan() async throws {
        let runner = CLIProcessRunner(executablePath: cliPath, workingDirectory: workingDir)
        let result = try await runner.runSecurityScan()

        XCTAssertTrue(result.isSuccess, "Expected security scan to succeed")
        XCTAssertTrue(result.permissionsOk, "Expected POSIX permissions 0700/0600 compliance")
        XCTAssertEqual(result.gitleaksLeaksCount, 0, "Expected zero secret leaks detected by Gitleaks")
    }

    func testBackupProva() async throws {
        let runner = CLIProcessRunner(executablePath: cliPath, workingDirectory: workingDir)
        let result = try await runner.runBackup(drillOnly: true)

        XCTAssertTrue(result.isSuccess, "Expected backup prova to succeed")
        XCTAssertTrue(result.restoreDrillOk, "Expected restore drill to pass SQLite quick_check")
        XCTAssertNotNil(result.backupFilePath, "Expected non-nil backup file path")
        XCTAssertNotNil(result.sha256, "Expected non-nil SHA-256 digest")
    }

    func testBinaryNotFound() async {
        let runner = CLIProcessRunner(executablePath: "/nonexistent/binary/path/runner")
        do {
            _ = try await runner.runVerifyIntegrity()
            XCTFail("Expected runVerifyIntegrity to throw binaryNotFound")
        } catch {
            guard case CLIProcessRunner.ProcessError.binaryNotFound = error else {
                XCTFail("Expected ProcessError.binaryNotFound, got: \(error)")
                return
            }
        }
    }

    func testCLIOutputParsersDogrula() {
        let sampleOutput = """
        ========================================================================
          BÜTÜNLÜK DOĞRULAMASI
        ========================================================================
          ✓ Şifreleme durumu: FileVault Açık (Disk Şifreli - APFS XTS-AES)
          journal_mode                   truncate
          recursive_triggers             True
          foreign_keys                   True
          schema_version                 3
          sqlite_version                 3.50.4
          trigger_count                  78
          snapshots                      30
          raw_objects                    60
          audit_events                   43
          chain_tip                      0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a
          snapshot_chain_ok              True
          snapshot_chain_error           None
          audit_chain_ok                 True
          audit_chain_error              None
          chain_tip_status               MATCH_SEALED
          chain_tip_details              Canlı veritabanı uçları harici kütükteki son mühürlü uçlarla birebir eşleşiyor.
          sealed_snapshot_tip            0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a
          sealed_audit_tip               54a2dc18c9aed00a4dd02551833e67f21d938019b8d07efa196e892d7cbc2cd8
          critical_integrity_violation   False
          ok                             True
        """

        let report = CLIOutputParsers.parseDogrula(output: sampleOutput)
        XCTAssertTrue(report.ok)
        XCTAssertTrue(report.fileVaultActive)
        XCTAssertEqual(report.schemaVersion, 3)
        XCTAssertEqual(report.triggerCount, 78)
        XCTAssertEqual(report.snapshotsCount, 30)
        XCTAssertEqual(report.auditEventsCount, 43)
        XCTAssertEqual(report.chainTip, "0a92cf40df7c901dcbf64d746aa22a85e5db6458e0fb0ed98e9240049c0cef8a")
        XCTAssertTrue(report.snapshotChainOk)
        XCTAssertTrue(report.auditChainOk)
        XCTAssertEqual(report.chainTipStatus, "MATCH_SEALED")
        XCTAssertFalse(report.criticalIntegrityViolation)
    }

    func testCLIOutputParsersYedek() {
        let sampleOutput = """
        ========================================================================
          VERİTABANI YEDEKLEME (SQLite Online Backup)
        ========================================================================
          ✓ Şifreleme durumu: FileVault Açık (Disk Şifreli - APFS XTS-AES)
          ✓ Canlı DB: /var/app/ETF/masa/var/private/masa.db
          ✓ Yedek dosyası: /var/app/ETF/masa/var/backups/backup-20261031_203905.db (2,621,440 bayt)
          ✓ SHA-256: ef2808ec3649e5b553632d45
          ✓ Mühür zincir ucu: 0a92cf40df7c901d (30 mühür)
          ✓ Denetim zincir ucu: 54a2dc18c9aed00a (43 olay)
          ✓ Manifest: /var/app/ETF/masa/var/backups/backup-20261031_203905.json
          ✓ Bağımsız kütük güncellendi: zincir-uclari.jsonl

          [Geri Yükleme Provası (restore_drill)]
          ✓ SHA-256 doğrulandı
          ✓ SQLite PRAGMA quick_check: OK
          ✓ Mühür ve denetim zincirleri izole alanda doğrulandı
          ✓ Canlı veritabanına dokunulmadı
        ========================================================================
          Sonuç: YEDEK BAŞARIYLA ALINDI VE PROVA DOĞRULANDI
        """

        let result = CLIOutputParsers.parseYedek(output: sampleOutput, exitCode: 0)
        XCTAssertTrue(result.isSuccess)
        XCTAssertTrue(result.restoreDrillOk)
        XCTAssertEqual(result.backupFilePath, "/var/app/ETF/masa/var/backups/backup-20261031_203905.db")
        XCTAssertEqual(result.sha256, "ef2808ec3649e5b553632d45")
        XCTAssertEqual(result.manifestPath, "/var/app/ETF/masa/var/backups/backup-20261031_203905.json")
    }

    func testCLIOutputParsersGuvenlikTara() {
        let sampleOutput = """
        ========================================================================
          GÜVENLİK VE GİZLİLİK DENETİMİ (İP-10)
        ========================================================================
          ✓ Dosya ve dizin izinleri tam uyumlu (0700/0600).
          ✓ Gitleaks gizli anahtar ve PII taraması: 0 sızıntı tespit edildi (TEMİZ).
        ========================================================================
          Sonuç: GÜVENLİK VE GİZLİLİK SERTLEŞTİRMESİ TAMAMLANDI
        """

        let result = CLIOutputParsers.parseGuvenlikTara(output: sampleOutput, exitCode: 0)
        XCTAssertTrue(result.isSuccess)
        XCTAssertTrue(result.permissionsOk)
        XCTAssertEqual(result.gitleaksLeaksCount, 0)
    }

    // MARK: - H6: Concurrency, Streaming & Timeouts Tests

    func testLargeOutputDeadlockPrevention() async throws {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        let script = "import sys; sys.stdout.write('X' * 250000); sys.stderr.write('Y' * 100000); sys.stdout.flush(); sys.stderr.flush()"
        let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 15.0)

        XCTAssertTrue(result.isSuccess, "Command should succeed without deadlock")
        XCTAssertEqual(result.exitCode, 0)
        XCTAssertEqual(result.stdout.count, 250000, "Should read all 250,000 bytes from stdout")
        XCTAssertEqual(result.stderr.count, 100000, "Should read all 100,000 bytes from stderr")
    }

    func testVolumeStress1MB_2MB_5MB() async throws {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        for mb in [1, 2, 5] {
            let bytes = mb * 1024 * 1024
            let script = """
import sys, threading
def write_stdout():
    chunk = b'A' * 65536
    total = \(bytes)
    written = 0
    while written < total:
        to_write = min(len(chunk), total - written)
        sys.stdout.buffer.write(chunk[:to_write])
        written += to_write
    sys.stdout.buffer.flush()

def write_stderr():
    chunk = b'B' * 65536
    total = \(bytes)
    written = 0
    while written < total:
        to_write = min(len(chunk), total - written)
        sys.stderr.buffer.write(chunk[:to_write])
        written += to_write
    sys.stderr.buffer.flush()

t1 = threading.Thread(target=write_stdout)
t2 = threading.Thread(target=write_stderr)
t1.start()
t2.start()
t1.join()
t2.join()
"""
            let result = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 30.0)
            XCTAssertTrue(result.isSuccess, "Volume test failed for \(mb)MB")
            XCTAssertEqual(result.stdout.utf8.count, bytes, "Stdout byte count mismatch for \(mb)MB")
            XCTAssertEqual(result.stderr.utf8.count, bytes, "Stderr byte count mismatch for \(mb)MB")
        }
    }

    func testSubprocessTimeoutUnderInfiniteLoop() async {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        let script = "import time; time.sleep(10)"
        let start = Date()
        do {
            _ = try await runner.runCommand(arguments: ["-c", script], timeoutSeconds: 1.0)
            XCTFail("Expected runCommand to throw ProcessError.timedOut under infinite loop")
        } catch {
            let elapsed = Date().timeIntervalSince(start)
            guard case CLIProcessRunner.ProcessError.timedOut(let seconds) = error else {
                XCTFail("Expected ProcessError.timedOut, got: \(error)")
                return
            }
            XCTAssertEqual(seconds, 1.0, accuracy: 0.1)
            XCTAssertLessThan(elapsed, 3.0, "Timeout must return within 3.0s, but took \(elapsed)s because waitUntilExit blocked!")
        }
    }


    func testCommandTimeoutResolver() {
        // 3600s: arastir, tradingagents, yorum, baslat
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["arastir", "IE00B3YLTY66"]), 3600.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tradingagents"]), 3600.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["yorum"]), 3600.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["baslat"]), 3600.0)

        // 600s: gecmis, tarama
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["gecmis"]), 600.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tarama"]), 600.0)

        // 300s: veri, giris --login, tahmin uret, islemler cek
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["veri"]), 300.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["giris", "--login"]), 300.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tahmin", "uret"]), 300.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["islemler", "cek"]), 300.0)

        // 180s: degerlendir, plan, mutabakat, yedek --prova, tahmin uzlas, model degerlendir
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["degerlendir"]), 180.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["plan"]), 180.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["mutabakat"]), 180.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["yedek", "--prova"]), 180.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tahmin", "uzlas"]), 180.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["model", "degerlendir"]), 180.0)

        // 120s: guvenlik-tara, tez, rapor, yedek
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["guvenlik-tara"]), 120.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tez", "kontrol"]), 120.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["rapor"]), 120.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["yedek"]), 120.0)

        // 30s: quick status & JSON reads
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["durum"]), 30.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["kontrol"]), 30.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["tarama", "--son"]), 30.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["zamanla", "durum"]), 30.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["ayar", "goster"]), 30.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["giris", "--json"]), 30.0)

        // 60s default / fallback
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["islemler", "listele"]), 60.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["dogrula"]), 60.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: []), 60.0)
        XCTAssertEqual(CLIProcessRunner.resolveCommandTimeout(for: ["ozel_komut"], fallback: 45.0), 45.0)
    }

    func testDynamicExecutableAndWorkingDirResolution() {
        // Custom path takes precedence
        let customExec = "/tmp/custom_executable_test"
        XCTAssertEqual(CLIProcessRunner.resolveExecutablePath(customPath: customExec), customExec)

        // Fallback default
        let defaultExec = CLIProcessRunner.resolveExecutablePath(customPath: nil)
        XCTAssertFalse(defaultExec.isEmpty)

        // Working directory resolution
        let customDir = "/tmp"
        XCTAssertEqual(CLIProcessRunner.resolveWorkingDirectory(customPath: customDir), customDir)

        let defaultDir = CLIProcessRunner.resolveWorkingDirectory(customPath: nil, forExecutable: cliPath)
        XCTAssertFalse(defaultDir.isEmpty)
    }

    func testLiveStreamingCallbacks() async throws {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        let script = "import sys, time; sys.stdout.write('OUT_1\\n'); sys.stdout.flush(); sys.stderr.write('ERR_1\\n'); sys.stderr.flush(); sys.stdout.write('OUT_2\\n'); sys.stdout.flush()"

        final class StreamAccumulator: @unchecked Sendable {
            var stdoutChunks: [String] = []
            var stderrChunks: [String] = []
            let lock = NSLock()

            func appendStdout(_ chunk: String) {
                lock.lock()
                defer { lock.unlock() }
                stdoutChunks.append(chunk)
            }

            func appendStderr(_ chunk: String) {
                lock.lock()
                defer { lock.unlock() }
                stderrChunks.append(chunk)
            }
        }

        let acc = StreamAccumulator()

        let result = try await runner.runCommand(
            arguments: ["-c", script],
            timeoutSeconds: 10.0,
            onStdoutChunk: { text in
                acc.appendStdout(text)
            },
            onStderrChunk: { text in
                acc.appendStderr(text)
            }
        )

        XCTAssertTrue(result.isSuccess)
        let combinedStdout = acc.stdoutChunks.joined()
        let combinedStderr = acc.stderrChunks.joined()
        XCTAssertTrue(combinedStdout.contains("OUT_1"))
        XCTAssertTrue(combinedStdout.contains("OUT_2"))
        XCTAssertTrue(combinedStderr.contains("ERR_1"))
        XCTAssertEqual(result.stdout, combinedStdout)
        XCTAssertEqual(result.stderr, combinedStderr)
    }

    func testRunStreamAsyncSequence() async throws {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        let script = "import sys; sys.stdout.write('LINE1\\n'); sys.stdout.flush(); sys.stderr.write('WARN1\\n'); sys.stderr.flush(); sys.stdout.write('LINE2\\n'); sys.stdout.flush()"

        var receivedChunks: [CLIStreamChunk] = []
        for try await chunk in runner.runStream(arguments: ["-c", script], timeoutSeconds: 10.0) {
            receivedChunks.append(chunk)
        }

        let stdoutTexts = receivedChunks.compactMap { chunk -> String? in
            if case .stdout(let text) = chunk { return text }
            return nil
        }.joined()

        let stderrTexts = receivedChunks.compactMap { chunk -> String? in
            if case .stderr(let text) = chunk { return text }
            return nil
        }.joined()

        XCTAssertTrue(stdoutTexts.contains("LINE1"))
        XCTAssertTrue(stdoutTexts.contains("LINE2"))
        XCTAssertTrue(stderrTexts.contains("WARN1"))
    }

    func testAsyncStdinStreaming200KB() async throws {
        let runner = CLIProcessRunner(executablePath: "/usr/bin/python3", workingDirectory: "/tmp")
        let script = "import sys; data = sys.stdin.read(); sys.stdout.write(f'BYTES:{len(data)}')"
        let largePayload = String(repeating: "X", count: 200 * 1024) // 200 KB

        let result = try await runner.runCommand(
            arguments: ["-c", script],
            timeoutSeconds: 10.0,
            stdin: largePayload
        )

        XCTAssertTrue(result.isSuccess)
        XCTAssertEqual(result.stdout, "BYTES:204800")
    }

    func testGracefulCancellationSigintTrap() async throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        let script = """
        import signal, time, sys
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        time.sleep(10)
        """
        process.arguments = ["-c", script]
        try process.run()

        // Wait briefly for Python to start and register the signal handler
        try await Task.sleep(nanoseconds: 200_000_000)

        // Call terminateGracefully, which sends SIGINT first
        await CLIProcessRunner.terminateGracefully(process: process, gracePeriod: 2.0)

        XCTAssertFalse(process.isRunning, "Process should have exited")
        XCTAssertEqual(process.terminationStatus, 0, "Python process should have cleanly exited with code 0 via SIGINT handler")
    }

    func testMockCLIProcessRunnerStreaming() async throws {
        let mock = MockCLIProcessRunner()
        mock.mockResult = CLIOperationResult(
            isSuccess: true,
            exitCode: 0,
            stdout: "Streamed stdout data",
            stderr: "Streamed stderr warning",
            message: "Success"
        )

        final class SafeBox: @unchecked Sendable {
            var stdout = ""
            var stderr = ""
            let lock = NSLock()

            func appendStdout(_ text: String) {
                lock.lock()
                defer { lock.unlock() }
                stdout += text
            }

            func appendStderr(_ text: String) {
                lock.lock()
                defer { lock.unlock() }
                stderr += text
            }
        }

        let box = SafeBox()

        let result = try await mock.runCommand(
            arguments: ["test"],
            onStdoutChunk: { box.appendStdout($0) },
            onStderrChunk: { box.appendStderr($0) }
        )

        XCTAssertTrue(result.isSuccess)
        XCTAssertEqual(box.stdout, "Streamed stdout data")
        XCTAssertEqual(box.stderr, "Streamed stderr warning")

        var streamChunks: [CLIStreamChunk] = []
        for try await chunk in mock.runStream(arguments: ["test"]) {
            streamChunks.append(chunk)
        }

        XCTAssertEqual(streamChunks.count, 3)
        XCTAssertEqual(streamChunks[0], .stdout("Streamed stdout data"))
        XCTAssertEqual(streamChunks[1], .stderr("Streamed stderr warning"))
        XCTAssertEqual(streamChunks[2], .exit(0))
    }
}
