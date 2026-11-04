# Security & Privacy Policy (`SECURITY.md`)

FinanceCockpit is designed from the ground up with a **Zero-Execution, Local-First, Cryptographically Sealed** security posture.

## Core Security Invariants

1. **Zero Broker Write Path:**
   - The system never places, modifies, or cancels orders at any broker.
   - All CLI interactions with external broker tools (`sc`) pass through a strict read-only command allowlist (`whoami`, `broker holdings`, `broker cash-breakdown`, `broker quote`, `broker chart`, `broker transactions`) with `shell=False` and an explicit ban on mutating verbs (`buy`, `sell`, `trade`, `order`, `transfer`, `withdraw`).
2. **Append-Only Cryptographic Audit Trail (Schema v3):**
   - All 26 sealed SQLite tables are protected by **78 database-level triggers** (`BEFORE UPDATE`, `BEFORE DELETE`, and duplicate-overwrite guards) that abort any mutation attempt.
   - Every snapshot and record is chained via deterministic **SHA-256 hashes** (`prev_hash` → `curr_hash`) anchored to a genesis hash.
3. **Filesystem Hardening & PII Sanitization:**
   - Runtime directories (`masa/var/`) enforce `0700` permissions and database/session files enforce `0600` permissions.
   - IBANs, bearer tokens, session cookies, national ID numbers, and local user paths (`/Users/<username>/`) are automatically masked by `SecretMasker` (Swift) and `masa.privacy` (Python) before logging or LLM context construction.
4. **Continuous Secret & PII Scanning:**
   - Every commit is validated against `.gitleaks.toml` (Gitleaks 8.30+) with custom rules for European/Turkish IBANs, broker session tokens, personal emails, local user paths, and portfolio tables.

## Pre-Commit Verification

Before opening a Pull Request, run the full security verification locally:

```bash
# 1. Scan git history and working directory with Gitleaks
gitleaks git . -v
gitleaks dir . -v

# 2. Run the integrated security and permission check
./etf-masa guvenlik-tara
```

## Reporting a Vulnerability

If you discover a security or privacy issue, please open a private security advisory on GitHub rather than posting sensitive details in a public issue.
