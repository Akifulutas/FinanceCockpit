"""Comprehensive tests for PromptLoader, SHA-256 auditing, and external AI prompt specifications.

Verifies:
1. PromptLoader discovery, hashing, validation, rendering, and manifest generation.
2. Forensic AST analysis proving ZERO financial/decision logic in loader.py.
3. Contract tests asserting all 7 prompt specifications exist, exceed 2KB,
   contain the standard 7 engineering sections, and embed syntactically valid JSON schemas.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List
import pytest

from masa.prompts.loader import (
    LoadedPrompt,
    MissingPromptError,
    PromptDirectoryNotFoundError,
    PromptIntegrityError,
    PromptLoader,
    PromptMetadata,
    PromptNotFoundError,
    PromptRenderError,
)


@pytest.fixture
def temp_prompts_dir(tmp_path: Path) -> Path:
    """Fixture providing an isolated temporary prompts directory with sample files."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Sample valid prompt
    p1 = prompts_dir / "sample_prompt.md"
    p1.write_text(
        "# Sample Prompt\n\nHello {{ USER_NAME }}! Target: {{ TARGET_ISIN }}.\n"
        "Raw JSON example: { \"nested\": \"value\", \"count\": 42 }\n",
        encoding="utf-8",
    )

    # Sample llm research agent prompt
    p2 = prompts_dir / "llm_research_agent.md"
    p2.write_text(
        "# Research Agent\n\nInput bundle: {{ EVIDENCE_BUNDLE_JSON }}\n"
        "Taxonomy: [fact | sourced_estimate | computation | inference | unknown]\n"
        "Citations: [[source:SRC-01#Sec]] [[metric:METRIC-01]] [[quote:SNAP-01]]\n"
        "Counter-Thesis: Falsification triggers required.\n",
        encoding="utf-8",
    )

    return prompts_dir


class TestPromptLoaderDiscovery:
    """Tests verifying directory discovery and prompt listing."""

    def test_custom_prompts_dir_discovery(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        prompts = loader.list_available_prompts()
        assert "sample_prompt.md" in prompts
        assert "llm_research_agent.md" in prompts

    def test_default_prompts_dir_resolution(self) -> None:
        loader = PromptLoader()
        assert loader.prompts_dir.exists()
        assert loader.prompts_dir.is_dir()
        prompts = loader.list_available_prompts()
        assert "llm_research_agent.md" in prompts
        assert "portfolio_optimization.md" in prompts

    def test_nonexistent_directory_raises_error(self, tmp_path: Path) -> None:
        invalid_dir = tmp_path / "does_not_exist"
        with pytest.raises(PromptDirectoryNotFoundError) as exc_info:
            PromptLoader(invalid_dir)
        assert "Prompt directory not found" in str(exc_info.value)

    def test_load_nonexistent_prompt_raises_error(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        with pytest.raises(PromptNotFoundError) as exc_info:
            loader.load_prompt("missing_file.md")
        assert "Prompt file not found" in str(exc_info.value)


class TestPromptLoaderHashing:
    """Tests verifying SHA-256 cryptographic hashing determinism and sensitivity."""

    def test_sha256_computation_exact_match(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        loaded = loader.load_prompt("sample_prompt")

        file_bytes = (temp_prompts_dir / "sample_prompt.md").read_bytes()
        expected_hash = hashlib.sha256(file_bytes).hexdigest()

        assert loaded.metadata.sha256 == expected_hash
        assert len(loaded.metadata.sha256) == 64

    def test_sha256_changes_on_content_modification(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        loaded_initial = loader.load_prompt("sample_prompt")

        target_file = temp_prompts_dir / "sample_prompt.md"
        target_file.write_text("Altered content for hash test", encoding="utf-8")

        loaded_mutated = loader.load_prompt("sample_prompt")
        assert loaded_initial.metadata.sha256 != loaded_mutated.metadata.sha256

    def test_empty_prompt_file_raises_integrity_error(self, temp_prompts_dir: Path) -> None:
        empty_file = temp_prompts_dir / "empty.md"
        empty_file.write_text("   \n\t  ", encoding="utf-8")

        loader = PromptLoader(temp_prompts_dir)
        with pytest.raises(PromptIntegrityError) as exc_info:
            loader.load_prompt("empty.md")
        assert "cannot be empty" in str(exc_info.value)


class TestPromptLoaderValidation:
    """Tests verifying required prompt validation contracts."""

    def test_validate_required_prompts_success_on_production_prompts(self) -> None:
        loader = PromptLoader()
        verified = loader.validate_required_prompts()
        assert len(verified) == 7
        for name, meta in verified.items():
            assert isinstance(meta, PromptMetadata)
            assert len(meta.sha256) == 64
            assert meta.size_bytes > 2000

    def test_validate_required_prompts_missing_raises_error(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        with pytest.raises(MissingPromptError) as exc_info:
            loader.validate_required_prompts(["llm_research_agent.md", "portfolio_optimization.md"])
        assert "Required prompt documents missing" in str(exc_info.value)
        assert "portfolio_optimization.md" in str(exc_info.value)


class TestPromptLoaderRendering:
    """Tests verifying placeholder rendering and raw JSON preservation."""

    def test_render_substitutes_valid_placeholders(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        prompt = loader.load_prompt("sample_prompt")

        rendered = prompt.render({
            "USER_NAME": "TraderAkif",
            "TARGET_ISIN": "IE00B4L5Y983",
        })

        assert "Hello TraderAkif!" in rendered
        assert "Target: IE00B4L5Y983." in rendered
        # Ensure raw JSON curly braces remained completely intact and uncorrupted
        assert '{ "nested": "value", "count": 42 }' in rendered

    def test_render_missing_placeholder_raises_render_error(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        prompt = loader.load_prompt("sample_prompt")

        with pytest.raises(PromptRenderError) as exc_info:
            prompt.render({"USER_NAME": "TraderAkif"})  # TARGET_ISIN missing
        assert "Missing variables" in str(exc_info.value)
        assert "TARGET_ISIN" in str(exc_info.value)

    def test_render_allow_missing_preserves_unmatched_tags(self, temp_prompts_dir: Path) -> None:
        loader = PromptLoader(temp_prompts_dir)
        prompt = loader.load_prompt("sample_prompt")

        rendered = prompt.render({"USER_NAME": "TraderAkif"}, allow_missing=True)
        assert "Hello TraderAkif!" in rendered
        assert "{{ TARGET_ISIN }}" in rendered


class TestPromptAuditManifest:
    """Tests verifying generation of JSON-serializable audit manifests."""

    def test_audit_manifest_structure(self) -> None:
        loader = PromptLoader()
        manifest = loader.get_audit_manifest()

        assert "llm_research_agent" in manifest
        assert "portfolio_optimization.md" in [entry["filename"] for entry in manifest.values()]

        entry = manifest["llm_research_agent"]
        assert entry["filename"] == "llm_research_agent.md"
        assert len(entry["sha256"]) == 64
        assert entry["size_bytes"] > 2000
        assert "loaded_at_utc" in entry

        # Verify JSON serializability
        serialized = json.dumps(manifest)
        assert len(serialized) > 0


class TestZeroFinancialCodeASTEnforcement:
    """Forensic AST test: Verify PromptLoader contains ZERO financial/decision code."""

    def test_zero_financial_dependencies_in_loader(self) -> None:
        loader_path = Path(__file__).parents[1] / "src" / "masa" / "prompts" / "loader.py"
        assert loader_path.exists(), f"Loader file not found: {loader_path}"

        tree = ast.parse(loader_path.read_text(encoding="utf-8"), filename=str(loader_path))

        forbidden_modules = {
            "sqlite3", "masa.storage", "masa.identity",
            "masa.calendar", "masa.ingestion", "masa.tax", "masa.audit"
        }
        forbidden_keywords = {
            "rebalance", "portfolio_weight", "calculate_tax", "trade_buy",
            "trade_sell", "cashflow", "dietz", "modified_dietz", "xirr"
        }

        imported_modules = set()
        function_and_var_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)
            elif isinstance(node, (ast.FunctionDef, ast.Name)):
                name = getattr(node, "name", None) or getattr(node, "id", None)
                if name:
                    function_and_var_names.add(name.lower())

        # Check forbidden imports
        for mod in imported_modules:
            for forbidden in forbidden_modules:
                assert forbidden not in mod, f"Forbidden financial import '{mod}' found in loader.py"

        # Check forbidden financial keywords
        for keyword in forbidden_keywords:
            assert keyword not in function_and_var_names, (
                f"Forbidden financial keyword '{keyword}' found in loader.py symbols"
            )


class TestAllPromptsContractIntegrity:
    """Contract tests verifying all 7 prompts meet layout, size, and schema requirements."""

    PROMPT_FILENAMES = [
        "portfolio_optimization.md",
        "rebalancing.md",
        "performance_engine.md",
        "etf_lookthrough.md",
        "factor_and_valuation_models.md",
        "red_team_critic.md",
        "llm_research_agent.md",
    ]

    REQUIRED_SECTION_PATTERNS = [
        r"##\s*1\.\s*Metadata",
        r"##\s*2\.\s*Rol",
        r"##\s*3\.\s*Girdi\s*Şeması",
        r"##\s*4\.\s*Matematiksel\s*Formülasyon|##\s*4\.\s*İddia\s*Sınıflandırma",
        r"##\s*5\.\s*Çıktı\s*Sözleşmesi",
        r"##\s*6\.\s*Uç\s*Durumlar",
        r"##\s*7\.\s*Kabul\s*Kriterleri",
    ]

    def test_all_seven_prompts_exist_and_meet_size_threshold(self) -> None:
        loader = PromptLoader()
        for filename in self.PROMPT_FILENAMES:
            prompt_path = loader.prompts_dir / filename
            assert prompt_path.exists(), f"Prompt file does not exist: {filename}"
            content = prompt_path.read_text(encoding="utf-8")
            assert len(content) > 2000, f"Prompt {filename} is smaller than 2KB: {len(content)} bytes"

    def test_all_seven_prompts_contain_required_seven_sections(self) -> None:
        loader = PromptLoader()
        for filename in self.PROMPT_FILENAMES:
            prompt_path = loader.prompts_dir / filename
            content = prompt_path.read_text(encoding="utf-8")

            for pattern in self.REQUIRED_SECTION_PATTERNS:
                match = re.search(pattern, content, re.IGNORECASE)
                assert match is not None, f"Prompt {filename} is missing section matching pattern: {pattern}"

    def test_embedded_json_schemas_are_syntactically_valid(self) -> None:
        loader = PromptLoader()
        for filename in self.PROMPT_FILENAMES:
            prompt_path = loader.prompts_dir / filename
            content = prompt_path.read_text(encoding="utf-8")

            # Extract json code blocks
            json_blocks = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", content)
            assert len(json_blocks) >= 1, f"Prompt {filename} must contain at least one JSON code block"

            for i, block in enumerate(json_blocks):
                try:
                    parsed = json.loads(block)
                    assert isinstance(parsed, dict), f"JSON block {i} in {filename} must be a dict"
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON in {filename} block {i}: {e}")


class TestLLMResearchPromptContentIntegrity:
    """Verifies that masa/prompts/llm_research_agent.md meets all domain requirements."""

    def test_prompt_file_exists_and_meets_size_threshold(self) -> None:
        prompt_file = Path(__file__).parents[1] / "prompts" / "llm_research_agent.md"
        assert prompt_file.exists(), f"llm_research_agent.md not found at {prompt_file}"
        content = prompt_file.read_text(encoding="utf-8")
        assert len(content) > 2000, "Prompt content is too short"

    def test_prompt_contains_five_claim_categories(self) -> None:
        prompt_file = Path(__file__).parents[1] / "prompts" / "llm_research_agent.md"
        content = prompt_file.read_text(encoding="utf-8")

        for category in ["fact", "sourced_estimate", "computation", "inference", "unknown"]:
            assert category in content, f"Claim category '{category}' missing from llm_research_agent.md"

    def test_prompt_contains_semantic_citation_syntax(self) -> None:
        prompt_file = Path(__file__).parents[1] / "prompts" / "llm_research_agent.md"
        content = prompt_file.read_text(encoding="utf-8")

        assert "[[source:" in content
        assert "[[metric:" in content
        assert "[[quote:" in content

    def test_prompt_contains_counter_thesis_and_falsification(self) -> None:
        prompt_file = Path(__file__).parents[1] / "prompts" / "llm_research_agent.md"
        content = prompt_file.read_text(encoding="utf-8")

        assert "counter_thesis" in content.lower() or "karşı-tez" in content.lower()
        assert "falsification" in content.lower()

    def test_prompt_contains_input_and_output_json_schemas(self) -> None:
        prompt_file = Path(__file__).parents[1] / "prompts" / "llm_research_agent.md"
        content = prompt_file.read_text(encoding="utf-8")

        assert "EvidenceBundleInput" in content
        assert "ResearchAgentOutput" in content
        assert '"$schema"' in content
