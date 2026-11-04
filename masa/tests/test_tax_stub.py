"""Tests verifying tax stub passivity and zero-import rule across core modules."""

import ast
from pathlib import Path
import pytest

from masa.tax import TAX_LEDGER_ENABLED, TaxLedgerStub


class TestTaxStubPassivity:
    """Ensure TaxLedgerStub is inert and raises NotImplementedError."""

    def test_tax_ledger_disabled_by_default(self) -> None:
        assert TAX_LEDGER_ENABLED is False

    def test_methods_raise_not_implemented_error(self) -> None:
        stub = TaxLedgerStub()

        with pytest.raises(NotImplementedError) as exc1:
            stub.record_transaction()
        assert "Vergi defteri modülü devre dışıdır" in str(exc1.value)

        with pytest.raises(NotImplementedError) as exc2:
            stub.calculate_capital_gains()
        assert "Vergi defteri modülü devre dışıdır" in str(exc2.value)

        with pytest.raises(NotImplementedError) as exc3:
            stub.get_exemption_remaining()
        assert "Vergi defteri modülü devre dışıdır" in str(exc3.value)

        with pytest.raises(NotImplementedError) as exc4:
            stub.generate_tax_report()
        assert "Vergi defteri modülü devre dışıdır" in str(exc4.value)

    def test_arbitrary_attribute_access_raises_not_implemented(self) -> None:
        stub = TaxLedgerStub()
        with pytest.raises(NotImplementedError):
            _ = stub.some_arbitrary_tax_method()


class TestTaxZeroImportContract:
    """Forensic AST test: Verify NO core masa module imports masa.tax."""

    def test_zero_tax_imports_in_core_modules(self) -> None:
        src_dir = Path(__file__).parents[1] / "src" / "masa"
        assert src_dir.exists(), f"Source directory not found: {src_dir}"

        core_packages = ["identity", "calendar", "storage", "ingestion", "audit"]
        violations = []

        for pkg in core_packages:
            pkg_path = src_dir / pkg
            if not pkg_path.exists():
                continue

            for py_file in pkg_path.rglob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "tax" in alias.name:
                                violations.append((str(py_file), alias.name))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and "tax" in node.module:
                            violations.append((str(py_file), node.module))

        assert not violations, f"Forbidden tax imports found in core modules: {violations}"
