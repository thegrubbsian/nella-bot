"""Tests for TOML-based tool confirmation configuration."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from src.tools.registry import ToolRegistry, _load_confirmation_config

# Get the actual module (not shadowed by src.tools.__init__)
_reg_mod = sys.modules["src.tools.registry"]


@pytest.fixture
def reg() -> ToolRegistry:
    return ToolRegistry()


# -- _load_confirmation_config -----------------------------------------------


def test_no_toml_file_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", tmp_path / "missing.toml")
    assert _load_confirmation_config() == {}


def test_valid_toml_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("[tools]\nsend_email = true\nsearch_emails = false\n")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    config = _load_confirmation_config()
    assert config["send_email"] is True
    assert config["search_emails"] is False


def test_malformed_toml_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("this is not valid [[[ toml")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    assert _load_confirmation_config() == {}


# -- requires_confirmation method --------------------------------------------


def test_override_true_honored(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("[tools]\nmy_tool = true\n")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    assert reg.requires_confirmation("my_tool") is True


def test_override_false_honored(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("[tools]\nmy_tool = false\n")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    assert reg.requires_confirmation("my_tool") is False


def test_unlisted_tool_defaults_true(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("[tools]\nother = false\n")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    assert reg.requires_confirmation("unlisted") is True


def test_no_file_defaults_true(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", tmp_path / "missing.toml")
    assert reg.requires_confirmation("anything") is True


def test_malformed_toml_defaults_true(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml.write_text("bad [[[")
    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml)
    assert reg.requires_confirmation("anything") is True


# -- Drift detection ---------------------------------------------------------


def _extract_tool_names_from_source() -> set[str]:
    """Scan src/tools/*.py for all tool name= registrations in @registry.tool blocks.

    Only matches actual decorator calls (lines starting with @), not examples
    in docstrings.
    """
    tools_dir = Path(__file__).resolve().parent.parent / "src" / "tools"
    names: set[str] = set()
    # Match @registry.tool(...) that starts at column 0 or with leading whitespace
    # (actual decorators), skipping indented examples inside docstrings.
    # Real decorators are at the top level of a function definition.
    decorator_pattern = re.compile(r"^@registry\.tool\(\s*(.*?)\)", re.DOTALL | re.MULTILINE)
    name_pattern = re.compile(r'name\s*=\s*"([^"]+)"')
    for py_file in tools_dir.glob("*.py"):
        if py_file.name in ("__init__.py", "base.py", "registry.py"):
            continue
        text = py_file.read_text()
        for dec_match in decorator_pattern.finditer(text):
            block = dec_match.group(1)
            name_match = name_pattern.search(block)
            if name_match:
                names.add(name_match.group(1))
    return names


def _extract_tool_names_from_example_toml() -> set[str]:
    """Read tool names from TOOL_CONFIRMATIONS.toml.EXAMPLE."""
    example = Path(__file__).resolve().parent.parent / "config" / "TOOL_CONFIRMATIONS.toml.EXAMPLE"
    if not example.exists():
        pytest.skip("TOOL_CONFIRMATIONS.toml.EXAMPLE not found")
    import tomllib

    with example.open("rb") as f:
        data = tomllib.load(f)
    return set(data.get("tools", {}).keys())


def test_toml_example_covers_all_registered_tools() -> None:
    """Every tool registered via @registry.tool must appear in the EXAMPLE TOML."""
    source_names = _extract_tool_names_from_source()
    toml_names = _extract_tool_names_from_example_toml()
    missing = source_names - toml_names
    assert not missing, f"Tools in source but not in TOML.EXAMPLE: {sorted(missing)}"


def test_toml_example_has_no_stale_tools() -> None:
    """Every tool in the EXAMPLE TOML must exist in source code."""
    source_names = _extract_tool_names_from_source()
    toml_names = _extract_tool_names_from_example_toml()
    stale = toml_names - source_names
    assert not stale, f"Tools in TOML.EXAMPLE but not in source: {sorted(stale)}"
