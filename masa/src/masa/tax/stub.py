"""Tax ledger passive stub for Milestone 2.

This module is intentionally disabled in Phase 0 and Phase 1.
The core data ingestion and snapshot pipeline must never depend on tax calculations.
"""

from __future__ import annotations

from typing import Any

TAX_LEDGER_ENABLED: bool = False


class TaxLedgerError(Exception):
    """Base error for tax ledger module."""
    pass


class TaxLedgerStub:
    """Completely passive tax stub.

    Raises NotImplementedError on any calculation, record, or inspection attempt.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if not TAX_LEDGER_ENABLED:
            # Instantiation is tolerated only as an inert placeholder
            pass

    def record_transaction(self, *args: Any, **kwargs: Any) -> None:
        """Record tax-relevant transaction."""
        raise NotImplementedError(
            "Vergi defteri modülü devre dışıdır (TAX_LEDGER_ENABLED=False). "
            "Faz 0 ve Faz 1 kapsamında vergi gölge defteri kullanılmaz."
        )

    def calculate_capital_gains(self, *args: Any, **kwargs: Any) -> None:
        """Calculate capital gains tax."""
        raise NotImplementedError(
            "Vergi defteri modülü devre dışıdır (TAX_LEDGER_ENABLED=False). "
            "Sermaye kazancı veya Vorabpauschale hesaplaması yapılamaz."
        )

    def get_exemption_remaining(self, *args: Any, **kwargs: Any) -> None:
        """Get remaining Sparer-Pauschbetrag."""
        raise NotImplementedError(
            "Vergi defteri modülü devre dışıdır (TAX_LEDGER_ENABLED=False). "
            "Muafiyet takibi çekirdek akışında desteklenmez."
        )

    def generate_tax_report(self, *args: Any, **kwargs: Any) -> None:
        """Generate annual tax summary report."""
        raise NotImplementedError(
            "Vergi defteri modülü devre dışıdır (TAX_LEDGER_ENABLED=False). "
            "Vergi raporlama motoru pasiftir."
        )

    def __getattr__(self, name: str) -> Any:
        """Catch-all for any unimplemented tax attribute or method."""
        raise NotImplementedError(
            f"Vergi defteri modülü devre dışıdır (TAX_LEDGER_ENABLED=False). "
            f"'{name}' işlevi çağrılamaz."
        )
