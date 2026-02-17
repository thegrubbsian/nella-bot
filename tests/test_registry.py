"""Tests for the tool registry."""

import sys
from pathlib import Path

import pytest
from pydantic import Field

from src.tools.base import BaseTool, ToolParams, ToolResult
from src.tools.registry import ToolRegistry

# Get the actual module (not shadowed by src.tools.__init__)
_reg_mod = sys.modules["src.tools.registry"]

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def reg() -> ToolRegistry:
    """Fresh registry for each test."""
    return ToolRegistry()


# -- Decorator registration --------------------------------------------------


def test_register_via_decorator(reg: ToolRegistry) -> None:
    @reg.tool(name="ping", description="Ping", category="test")
    async def ping() -> ToolResult:
        return ToolResult(data={"pong": True})

    assert "ping" in reg.tool_names
    assert reg.get("ping") is not None
    assert reg.get("ping").category == "test"


def test_decorator_rejects_sync_function(reg: ToolRegistry) -> None:
    with pytest.raises(TypeError, match="must be an async function"):

        @reg.tool(name="bad", description="Bad", category="test")
        def bad() -> ToolResult:
            return ToolResult()


# -- Class-based registration ------------------------------------------------


def test_register_class_based_tool(reg: ToolRegistry) -> None:
    class MyTool(BaseTool):
        name = "my_tool"
        description = "A test tool"
        category = "custom"

        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult(data={"class_based": True})

    reg.register(MyTool())
    assert "my_tool" in reg.tool_names
    assert reg.get("my_tool").description == "A test tool"


# -- Schema generation -------------------------------------------------------


def test_get_schemas_no_params(reg: ToolRegistry) -> None:
    @reg.tool(name="simple", description="Simple tool", category="test")
    async def simple() -> ToolResult:
        return ToolResult()

    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "simple"
    assert schemas[0]["description"] == "Simple tool"
    assert schemas[0]["input_schema"]["type"] == "object"
    assert schemas[0]["input_schema"]["properties"] == {}


def test_get_schemas_with_params(reg: ToolRegistry) -> None:
    class Params(ToolParams):
        query: str = Field(description="Search query")
        limit: int = Field(default=10, description="Max results")

    @reg.tool(
        name="search",
        description="Search things",
        category="test",
        params_model=Params,
    )
    async def search(query: str, limit: int = 10) -> ToolResult:
        return ToolResult()

    schemas = reg.get_schemas()
    props = schemas[0]["input_schema"]["properties"]
    assert "query" in props
    assert "limit" in props
    assert props["query"]["type"] == "string"
    assert props["limit"]["type"] == "integer"
    assert "query" in schemas[0]["input_schema"]["required"]


# -- Execution ---------------------------------------------------------------


async def test_execute_tool(reg: ToolRegistry) -> None:
    @reg.tool(name="greet", description="Greet", category="test")
    async def greet() -> ToolResult:
        return ToolResult(data={"greeting": "hello"})

    result = await reg.execute("greet", {})
    assert result.success
    assert result.data["greeting"] == "hello"


async def test_execute_with_params(reg: ToolRegistry) -> None:
    class AddParams(ToolParams):
        a: int = Field(description="First number")
        b: int = Field(description="Second number")

    @reg.tool(name="add", description="Add", category="test", params_model=AddParams)
    async def add(a: int, b: int) -> ToolResult:
        return ToolResult(data={"sum": a + b})

    result = await reg.execute("add", {"a": 3, "b": 7})
    assert result.success
    assert result.data["sum"] == 10


async def test_execute_unknown_tool(reg: ToolRegistry) -> None:
    result = await reg.execute("nonexistent", {})
    assert not result.success
    assert "Unknown tool" in result.error


async def test_execute_with_invalid_params(reg: ToolRegistry) -> None:
    class Params(ToolParams):
        count: int = Field(description="A number")

    @reg.tool(name="strict", description="Strict", category="test", params_model=Params)
    async def strict(count: int) -> ToolResult:
        return ToolResult(data={"count": count})

    result = await reg.execute("strict", {"count": "not_a_number"})
    assert not result.success


async def test_execute_handler_exception(reg: ToolRegistry) -> None:
    @reg.tool(name="boom", description="Boom", category="test")
    async def boom() -> ToolResult:
        msg = "kaboom"
        raise RuntimeError(msg)

    result = await reg.execute("boom", {})
    assert not result.success
    assert "failed" in result.error


# -- Categories --------------------------------------------------------------


def test_tools_by_category(reg: ToolRegistry) -> None:
    @reg.tool(name="a", description="A", category="alpha")
    async def a() -> ToolResult:
        return ToolResult()

    @reg.tool(name="b", description="B", category="beta")
    async def b() -> ToolResult:
        return ToolResult()

    @reg.tool(name="c", description="C", category="alpha")
    async def c() -> ToolResult:
        return ToolResult()

    groups = reg.get_tools_by_category()
    assert len(groups["alpha"]) == 2
    assert len(groups["beta"]) == 1


# -- TOML-based confirmation -------------------------------------------------


def test_requires_confirmation_from_toml(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool listed as true in TOML should require confirmation."""
    toml_file = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml_file.write_text("[tools]\ndanger = true\nsafe = false\n")

    @reg.tool(name="danger", description="Dangerous", category="test")
    async def danger() -> ToolResult:
        return ToolResult()

    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml_file)
    assert reg.requires_confirmation("danger") is True
    assert reg.requires_confirmation("safe") is False


def test_requires_confirmation_unlisted_defaults_true(
    reg: ToolRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool not listed in TOML should default to True (safe)."""
    toml_file = tmp_path / "TOOL_CONFIRMATIONS.toml"
    toml_file.write_text("[tools]\nother = false\n")

    monkeypatch.setattr(_reg_mod, "_CONFIRMATIONS_PATH", toml_file)
    assert reg.requires_confirmation("unlisted_tool") is True


# -- ToolResult serialization ------------------------------------------------


def test_tool_result_success_serialization() -> None:
    r = ToolResult(data={"key": "val"})
    assert r.success
    assert '"key"' in r.to_content()


def test_tool_result_error_serialization() -> None:
    r = ToolResult(error="something broke")
    assert not r.success
    assert '"error"' in r.to_content()
    assert "something broke" in r.to_content()
