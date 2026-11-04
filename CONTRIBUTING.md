# Contributing to FinanceCockpit

Thank you for your interest in contributing to **FinanceCockpit**!

## Engineering Principles

1. **Zero Mock / Honest State Constitution:**
   - Never display fabricated numbers, hardcoded fallback returns, or false-positive green status badges (`?? true`) when data is missing or unverified.
   - Unknown or uncomputed metrics must explicitly render as `"No data"` / `"Not Run"` with neutral styling.
2. **Strict Type Safety & Determinism:**
   - Swift code targets **Swift 6.0** with strict concurrency (`@MainActor` view models, `Sendable` models).
   - Python financial calculations use `Decimal` for monetary/FIFO accounting and deterministic seeds for tests.
   - Tests must never touch the live database (`masa/var/private/masa.db`); all tests run in isolated temporary directories (`tmp_path`).
3. **Privacy by Default:**
   - Never commit real portfolio snapshots, personal IBANs, broker tokens, or hardcoded `/Users/<username>/` paths.
   - Always run `gitleaks git .` before pushing.

## Local Development Workflow

```bash
# 1. Set up Python environment
cd masa && uv sync && cd ..

# 2. Seed a local demo database (optional, for UI testing without a broker)
./masa/.venv/bin/python scripts/seed_demo_db.py --db-path /tmp/demo_masa.db --force

# 3. Run Python test suite (876+ tests)
./masa/.venv/bin/pytest masa/tests/ tests/ -q

# 4. Run SwiftUI test suite (284+ tests)
cd macos && swift test && cd ..

# 5. Run Gitleaks security check
gitleaks git .
```
