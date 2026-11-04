"""Prompt template loader, validator, and cryptographic SHA-256 audit recorder.

ARCHITECTURAL PRINCIPLE (R4): ZERO FINANCIAL/DECISION CODE.
This module is strictly an audit-aware file loader and template renderer.
It contains NO financial logic, NO portfolio calculations, and NO decision rules.
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field


class PromptError(Exception):
    """Base exception for all prompt loader errors."""
    pass


class PromptDirectoryNotFoundError(PromptError):
    """Raised when the target prompts directory does not exist."""
    pass


class PromptNotFoundError(PromptError):
    """Raised when a specific requested prompt file does not exist."""
    pass


class MissingPromptError(PromptError):
    """Raised when one or more required prompt documents are missing."""
    pass


class PromptIntegrityError(PromptError):
    """Raised when a prompt file is empty, unreadable, or corrupted."""
    pass


class PromptRenderError(PromptError):
    """Raised when template substitution fails due to missing required placeholders."""
    pass


class PromptMetadata(BaseModel):
    """Immutable audit metadata for a loaded prompt template."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Logical prompt name (e.g. llm_research_agent)")
    filename: str = Field(description="Filename on disk (e.g. llm_research_agent.md)")
    path: str = Field(description="Full absolute path on disk")
    sha256: str = Field(description="SHA-256 hexadecimal digest (64 chars)", min_length=64, max_length=64)
    size_bytes: int = Field(description="File size in bytes")
    loaded_at_utc: datetime.datetime = Field(description="Timestamp when prompt was loaded (UTC)")


class LoadedPrompt(BaseModel):
    """Container holding prompt metadata, raw text, and safe rendering capability."""
    model_config = ConfigDict(extra="forbid")

    metadata: PromptMetadata
    raw_content: str
    detected_placeholders: List[str]

    def render(self, variables: Dict[str, str], allow_missing: bool = False) -> str:
        """Safely substitute {{ PLACEHOLDER }} tags without breaking JSON braces.

        Uses regex substitution rather than str.format() to ensure raw JSON
        and Markdown code blocks containing curly braces remain completely untouched.

        Args:
            variables: Key-value dictionary of string replacements.
            allow_missing: If False, raises PromptRenderError when a placeholder
                           in the template has no corresponding value in variables.

        Returns:
            Rendered prompt string ready for external AI consumption.
        """
        pattern = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

        if not allow_missing:
            missing = [p for p in self.detected_placeholders if p not in variables]
            if missing:
                raise PromptRenderError(
                    f"Prompt '{self.metadata.name}' render error: Missing variables: {missing}"
                )

        def _replace_match(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name in variables:
                return str(variables[var_name])
            if allow_missing:
                return match.group(0)
            raise PromptRenderError(f"Variable not defined: {var_name}")

        return pattern.sub(_replace_match, self.raw_content)


class PromptLoader:
    """Discovers, validates, hashes, and loads prompt templates from disk."""

    CANONICAL_REQUIRED_PROMPTS: List[str] = [
        "portfolio_optimization.md",
        "rebalancing.md",
        "performance_engine.md",
        "etf_lookthrough.md",
        "factor_and_valuation_models.md",
        "red_team_critic.md",
        "llm_research_agent.md",
    ]

    def __init__(self, prompts_dir: Optional[Path | str] = None) -> None:
        """Initialize the prompt loader with a designated prompts directory.

        If prompts_dir is not provided, defaults to the 'prompts' directory
        located at the root of the 'masa' package.
        """
        if prompts_dir is not None:
            self.prompts_dir = Path(prompts_dir).resolve()
        else:
            curr_dir = Path(__file__).resolve().parent
            candidates = [
                curr_dir.parents[2] / "prompts",          # masa/prompts
                curr_dir.parents[3] / "masa" / "prompts", # ETF/masa/prompts
                Path.home() / "Documents" / "ETF" / "masa" / "prompts",
            ]
            selected = None
            for cand in candidates:
                if cand.exists() and cand.is_dir():
                    selected = cand
                    break
            self.prompts_dir = selected or candidates[0]

        if not self.prompts_dir.exists() or not self.prompts_dir.is_dir():
            raise PromptDirectoryNotFoundError(
                f"Prompt directory not found: {self.prompts_dir}"
            )

    @staticmethod
    def compute_sha256(content: str) -> str:
        """Compute SHA-256 hexadecimal digest for UTF-8 encoded string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def extract_placeholders(content: str) -> List[str]:
        """Extract all unique {{ PLACEHOLDER }} names in order of appearance."""
        matches = re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", content)
        seen: Set[str] = set()
        ordered: List[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                ordered.append(m)
        return ordered

    def list_available_prompts(self) -> List[str]:
        """List all markdown prompt template filenames in the prompts directory."""
        return sorted([f.name for f in self.prompts_dir.glob("*.md") if f.is_file()])

    def load_prompt(self, filename_or_name: str) -> LoadedPrompt:
        """Load a single prompt template, compute its SHA-256, and return LoadedPrompt."""
        filename = filename_or_name if filename_or_name.endswith(".md") else f"{filename_or_name}.md"
        prompt_path = self.prompts_dir / filename

        if not prompt_path.exists() or not prompt_path.is_file():
            raise PromptNotFoundError(
                f"Prompt file not found: {prompt_path} (Directory: {self.prompts_dir})"
            )

        try:
            content = prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            raise PromptIntegrityError(f"Cannot read prompt file ({filename}): {e}") from e

        if not content.strip():
            raise PromptIntegrityError(f"Prompt file cannot be empty ({filename}): {prompt_path}")

        sha256_hash = self.compute_sha256(content)
        size_bytes = prompt_path.stat().st_size
        placeholders = self.extract_placeholders(content)
        stem_name = prompt_path.stem

        metadata = PromptMetadata(
            name=stem_name,
            filename=filename,
            path=str(prompt_path),
            sha256=sha256_hash,
            size_bytes=size_bytes,
            loaded_at_utc=datetime.datetime.now(datetime.timezone.utc),
        )

        return LoadedPrompt(
            metadata=metadata,
            raw_content=content,
            detected_placeholders=placeholders,
        )

    def validate_required_prompts(
        self, required_filenames: Optional[List[str]] = None
    ) -> Dict[str, PromptMetadata]:
        """Verify that all required prompt documents exist, are non-empty, and valid.

        Args:
            required_filenames: Optional list of prompt filenames. Defaults to CANONICAL_REQUIRED_PROMPTS.

        Returns:
            Dictionary mapping prompt names to their verified PromptMetadata.

        Raises:
            MissingPromptError: If one or more required prompt files are missing.
            PromptIntegrityError: If any required file is empty or corrupted.
        """
        targets = required_filenames or self.CANONICAL_REQUIRED_PROMPTS
        missing: List[str] = []
        verified: Dict[str, PromptMetadata] = {}

        for req in targets:
            prompt_path = self.prompts_dir / req
            if not prompt_path.exists() or not prompt_path.is_file():
                missing.append(req)
                continue
            loaded = self.load_prompt(req)
            verified[loaded.metadata.name] = loaded.metadata

        if missing:
            raise MissingPromptError(
                f"Required prompt documents missing: {missing} (Directory: {self.prompts_dir})"
            )

        return verified

    def get_audit_manifest(self) -> Dict[str, Dict[str, Any]]:
        """Generate a canonical dictionary of all prompts and their SHA-256 hashes.

        Suitable for serializing to JSON and storing in audit events or model manifests.
        """
        manifest: Dict[str, Dict[str, Any]] = {}
        for fname in self.list_available_prompts():
            loaded = self.load_prompt(fname)
            manifest[loaded.metadata.name] = {
                "filename": loaded.metadata.filename,
                "sha256": loaded.metadata.sha256,
                "size_bytes": loaded.metadata.size_bytes,
                "placeholders_count": len(loaded.detected_placeholders),
                "loaded_at_utc": loaded.metadata.loaded_at_utc.isoformat(),
            }
        return manifest
