import XCTest
@testable import FinanceCockpit

final class ContractTests: XCTestCase {

    let decoder = JSONDecoder()

    func testGirisContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "active": true,
          "session_ok": true,
          "reader_path": "/opt/homebrew/bin/sc",
          "account_info": {
            "account_id": "ACC12345",
            "email": "user@example.com"
          }
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(GirisResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertTrue(response.active)
        XCTAssertTrue(response.sessionOk)
        XCTAssertEqual(response.readerPath, "/opt/homebrew/bin/sc")
        XCTAssertEqual(response.accountInfo?.accountId, "ACC12345")
    }

    func testDurumContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "ok": true,
          "database_path": "/Users/user/ETF/masa/var/private/masa.db",
          "integrity": {
            "schema_version": 3,
            "trigger_count": 78,
            "snapshots": 30,
            "audit_events": 43,
            "chain_tip_status": "MATCH_SEALED",
            "ok": true
          },
          "capabilities": {
            "version": "1.0.0",
            "command_count": 38,
            "drift_level": "CLEAN"
          },
          "queue": {
            "pending_count": 0,
            "recent_jobs": [
              {
                "job_type": "BACKUP",
                "state": "COMPLETED",
                "count": 1
              }
            ]
          }
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(DurumResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertTrue(response.ok)
        XCTAssertEqual(response.integrity.schemaVersion, 3)
        XCTAssertEqual(response.integrity.triggerCount, 78)
        XCTAssertEqual(response.integrity.chainTipStatus, "MATCH_SEALED")
        XCTAssertEqual(response.queue.pendingCount, 0)
        XCTAssertEqual(response.queue.recentJobs?.first?.jobType, "BACKUP")
    }

    func testPortfoyContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "run_id": "run_01",
          "completed_at": "2026-11-01T10:00:00Z",
          "positions_count": 2,
          "cash_eur": 1250.50,
          "total_eur": 15000.75,
          "warning": null,
          "positions": [
            {
              "isin": "IE00B4L5Y983",
              "name": "iShares Core MSCI World UCITS ETF",
              "role": "CORE",
              "quantity": 150.0,
              "mid_eur": 85.50,
              "value_eur": 12825.00,
              "weight_pct": 85.49,
              "quality": "VERIFIED",
              "fifo_price_eur": 72.10
            },
            {
              "isin": "IE00BKM4GZ66",
              "name": "iShares Core MSCI EM IMI UCITS ETF",
              "role": "SATELLITE",
              "quantity": 30.0,
              "mid_eur": 30.84,
              "value_eur": 925.25,
              "weight_pct": 6.16,
              "quality": "VERIFIED",
              "fifo_price_eur": 28.50
            }
          ]
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(PortfoyResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertEqual(response.positionsCount, 2)
        XCTAssertEqual(response.cashEur, 1250.50)
        XCTAssertEqual(response.totalEur, 15000.75)
        XCTAssertEqual(response.positions.count, 2)
        XCTAssertEqual(response.positions[0].isin, "IE00B4L5Y983")
        XCTAssertEqual(response.positions[0].weightPct, 85.49)
    }

    func testDegerlendirContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "run_id": "eval_123",
          "warning": null,
          "assessments": [
            {
              "isin": "IE00B4L5Y983",
              "name": "iShares Core MSCI World",
              "label": "TUT",
              "reasons": ["Hedef ağırlık dahilinde (%70 hedef, %68 mevcut)"],
              "notes": ["Teilfreistellung %30 aktif", "Karar desteğidir; sistem işlem yapmaz."]
            }
          ]
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(DegerlendirResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertEqual(response.assessments.count, 1)
        XCTAssertEqual(response.assessments[0].isin, "IE00B4L5Y983")
        XCTAssertEqual(response.assessments[0].label, "TUT")
        XCTAssertTrue(response.assessments[0].notes.contains(where: { $0.contains("Karar desteğidir") }))
    }

    func testTaramaContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "pool_count": 10,
          "warning": null,
          "candidates": [
            {
              "isin": "IE00B3YLTY66",
              "name": "SPDR MSCI Europe Small Cap Value",
              "label": "EKLE",
              "score": 8.75,
              "reasons": ["Yüksek Sharpe oranı (1.24)", "Düşük korelasyon (%0.42)"]
            }
          ]
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(TaramaResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertEqual(response.poolCount, 10)
        XCTAssertEqual(response.candidates.count, 1)
        XCTAssertEqual(response.candidates[0].score, 8.75)
        XCTAssertEqual(response.candidates[0].label, "EKLE")
    }

    func testTahminKarneContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "total_forecasts": 35,
          "settled_count": 30,
          "pending_count": 5,
          "hit_rate_pct": "%60,00",
          "etf_hit_rate_pct": "%62,50",
          "stock_hit_rate_pct": "%50,00",
          "mape_pct": "%1,25",
          "mae_eur": "1,10 €",
          "mpe_pct": "%0,15",
          "is_small_sample": false,
          "warning_message": null,
          "baseline_flat_hit_rate_pct": "%50,00",
          "baseline_yesterday_hit_rate_pct": "%53,33",
          "beats_baselines": true,
          "baseline_warning": null
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(TahminKarneResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertEqual(response.totalForecasts, 35)
        XCTAssertEqual(response.settledCount, 30)
        XCTAssertEqual(response.pendingCount, 5)
        XCTAssertEqual(response.hitRatePct, "%60,00")
        XCTAssertFalse(response.isSmallSample)
        XCTAssertEqual(response.beatsBaselines, true)
    }

    func testZamanlaDurumContractDecoding() throws {
        let json = """
        {
          "schema_version": "1.0.0",
          "agents": [
            {
              "label": "com.etf.sabah",
              "description": "Sabah açılış kontrolü ve veri mühürleme",
              "schedule": "Hafta içi 08:45",
              "installed": true,
              "loaded": true,
              "last_exit_code": 0,
              "plist_path": "/Users/user/Library/LaunchAgents/com.etf.sabah.plist",
              "log_lines": ["08:45:00 - Başlatıldı", "08:45:05 - Mühürlendi"]
            }
          ]
        }
        """.data(using: .utf8)!

        let response = try decoder.decode(SchedulerStatusResponse.self, from: json)
        XCTAssertEqual(response.schemaVersion, "1.0.0")
        XCTAssertEqual(response.agents.count, 1)
        XCTAssertTrue(response.agents[0].isInstalled)
        XCTAssertTrue(response.agents[0].isActive)
        XCTAssertEqual(response.agents[0].lastExitCode, 0)
    }
}
