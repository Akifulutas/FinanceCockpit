# FinanceCockpit

> **Institutional-grade, local-first macOS ETF portfolio cockpit & deterministic financial analytics engine.**  
> Built with **SwiftUI 6** (macOS Human Interface Guidelines) and **Python 3.13** (`masa`), featuring an append-only SHA-256 cryptographic audit trail, walk-forward multi-model forecasting, German InvStG tax rules, and a strict zero-broker-write safety architecture.

[![Swift 6](https://img.shields.io/badge/Swift-6.0-orange.svg)](https://swift.org)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://python.org)
[![macOS 15+](https://img.shields.io/badge/macOS-Sequoia%2B-purple.svg)](https://apple.com/macos)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Security: Gitleaks Clean](https://img.shields.io/badge/Security-Gitleaks%20Clean-brightgreen.svg)](SECURITY.md)

---

## 🏛 Architecture Overview

FinanceCockpit combines a native macOS SwiftUI desktop application with a deterministic Python analytics and storage core:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   macOS FinanceCockpit (SwiftUI / Swift 6)                 │
│  • 6-Section Workspace (⌘1 Today · ⌘2 Portfolio · ⌘3 Forecasts ·           │
│    ⌘4 Decisions · ⌘5 Discovery · ⌘6 System) + Unified Asset Lens           │
│  • Raycast-Style Command Palette (⌘K), Inspector Drawer & Privacy Mode     │
│  • Non-Blocking Streaming CLI Runner & Direct Read-Only SQLite Queries     │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │ IPC / JSON Contracts & SQLite v3
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      masa Analytics & Audit Engine (Python 3.13)           │
│  • Append-Only SQLite Schema v3 (26 Sealed Tables · 78 Abort Triggers)     │
│  • SHA-256 Cryptographic Hash Chain & GFS Backup Rotation + Restore Drill  │
│  • 4-Dimensional FIFO Ledger Reconciliation (Shares · Cash · Val · Cost)   │
│  • Multi-Model Walk-Forward Forecast Engine (09:30 CET → 17:40 Settlement) │
│  • ETF Look-Through Holdings Overlap, UCITS 5/10/40 & German InvStG Tax    │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Capabilities

1. **6-Section macOS Cockpit (`⌘1`–`⌘6`) & Unified Asset Lens:**
   - **Today (`⌘1`):** 6-step guided morning workflow (Broker Auth → Live Data Seal → Forecast Generation → XETR Settlement → Opportunity Scan → Report & Critique), live XETR session status capsule, and holdings overview.
   - **Portfolio (`⌘2`):** Real-time position valuation, 5-bucket cash breakdown, immutable FIFO transaction ledger, and 4-dimensional broker reconciliation (`MATCH_SEALED` vs `DISCREPANCY_SEALED`).
   - **Forecasts (`⌘3`):** Daily 5 ETF + 5 equity directional forecasts, 17:40 CET XETR settlement verification, Brier/hit-rate leaderboards, and multi-model walk-forward backtest simulation.
   - **Decisions (`⌘4`):** No-sell cash injection rebalance simulator (`+500 €`, `+1,000 €`, `+2,500 €`, `+5,000 €`), ETF look-through holdings overlap (Top 25 constituents), and falsifiable investment theses.
   - **Discovery (`⌘5`):** Candidate ETF/equity screener (Sharpe, max drawdown, portfolio correlation) and SSRF-hardened official factsheet/ECB/EDGAR research evidence collector.
   - **System (`⌘6`):** SHA-256 hash chain verification, GFS backup & zero-touch restore drills, `launchd` automation scheduler, and system configuration.
2. **Honest State Constitution (Zero Mock Data):**
   - Unknown or uncomputed metrics never fall back to fake green badges (`?? true`) or fabricated numbers; missing data is explicitly labeled and actionable.
3. **Zero Broker Write Path:**
   - Broker integration (`sc` CLI for Scalable Capital) is strictly read-only (`shell=False`, whitelisted read verbs only). FinanceCockpit can never execute trades or move funds.
4. **German Tax Law (InvStG) Awareness:**
   - Supports 30% Equity ETF exemption (*Teilfreistellung*), *Sparer-Pauschbetrag* (1,000 € / 2,000 € FSA) tracking, and *Vorabpauschale* estimation.

---

## 🚀 Quick Start (Demo Mode — No Broker Account Required)

You can build and explore all 6 sections of FinanceCockpit immediately using the included synthetic demo database seeder:

### Prerequisites
- **macOS 15.0+** (Sequoia or newer)
- **Xcode 16.0+** / Swift 6.0 toolchain
- **Python 3.13** and [`uv`](https://docs.astral.sh/uv/) package manager

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/Akifulutas/FinanceCockpit.git
cd FinanceCockpit

# Install Python 3.13 environment & dependencies
cd masa && uv sync && cd ..
```

### 2. Seed Synthetic Demo Database

```bash
# Creates a cryptographically sealed v3 database with 4 UCITS ETFs,
# 1-year price charts, FIFO transactions, reconciled ledger, and theses:
./masa/.venv/bin/python scripts/seed_demo_db.py --force

# Verify database hash chain and 78 immutability triggers:
./etf-masa dogrula
```

### 3. Build & Launch macOS Application

```bash
./scripts/build_app.sh
open build/FinanceCockpit.app
```

---

## 🧪 Testing & Security Verification

All test suites run deterministically in isolated temporary directories (`tmp_path`) and are enforced by a strict production isolation barrier that prevents tests from ever touching `masa/var/private/masa.db`.

```bash
# 1. Python Core Engine Test Suite (876+ unit, adversarial & E2E tests)
./masa/.venv/bin/pytest masa/tests/ tests/ -q

# 2. macOS SwiftUI Test Suite (284+ unit & adversarial UI/security tests)
cd macos && swift test && cd ..

# 3. Gitleaks Secret & PII Audit
gitleaks git . -v
./etf-masa guvenlik-tara
```

---

## 🇹🇷 Türkçe Özet (Turkish Summary)

**FinanceCockpit (ETF Yatırım Masası)**, uzun vadeli ETF yatırımcıları için Apple Design Award ve macOS HIG standartlarında geliştirilmiş yerel bir macOS kokpit uygulaması (`macos/`) ve deterministik Python finansal analiz motorudur (`masa/`).

- **Sıfır Emir Yetkisi (Salt-Okunur Güvenlik):** Broker ile yalnızca salt-okunur olarak konuşur; asla alım/satım emri göndermez.
- **Kriptografik Mühür Zinciri (Şema v3):** 26 mühürlü tablo ve 78 SQLite tetikleyicisi (`BEFORE UPDATE` / `BEFORE DELETE` engeli) ile her veri gözlemi SHA-256 zincirine eklenir.
- **Demo Veritabanı ile Hızlı Deneme:** Canlı broker hesabınız olmadan tüm ekranları denemek için `./masa/.venv/bin/python scripts/seed_demo_db.py --force` komutunu çalıştırıp `./scripts/build_app.sh` ile uygulamayı başlatabilirsiniz.

---

## 📄 License

Licensed under the [MIT License](LICENSE). See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md) for security invariants and contribution guidelines.
