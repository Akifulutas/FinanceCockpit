"""Scalable CLI ingestion exceptions."""

from __future__ import annotations


class ScalableReaderError(Exception):
    """Base exception for all Scalable CLI reader errors."""
    pass


class ScalableSecurityViolation(ScalableReaderError):
    """Raised when a forbidden command, write operation, or injection attempt is detected."""
    pass


class SingleISINViolation(ScalableSecurityViolation):
    """Raised when multiple ISINs or comma-separated batching is passed to a single ISIN method."""
    pass


class ScalableCommandError(ScalableReaderError):
    """Raised when the sc CLI subprocess exits with a non-zero return code."""

    def __init__(self, command: list[str], returncode: int, stderr: str):
        super().__init__(f"Scalable CLI command failed (code {returncode}): {' '.join(command)}\nError: {stderr}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class ScalableParsingError(ScalableReaderError):
    """Raised when the CLI output cannot be parsed as valid JSON or violates schema contracts."""
    pass


class ScalableTimeoutError(ScalableReaderError):
    """Raised when the sc CLI subprocess times out."""
    pass
