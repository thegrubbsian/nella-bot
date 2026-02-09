"""Tool registry — central catalog for all tools."""

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.tools.base import BaseTool, ToolParams, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    """Internal representation of a registered tool."""

    name: str
    description: str
    category: str
    handler: Callable[..., Awaitable[ToolResult]]
    params_model: type[ToolParams] | None = None
    requires_confirmation: bool = False


class ToolRegistry:
    """Central registry for all tools.

    Supports two registration styles:

    1. Decorator (for simple stateless tools)::

        @registry.tool(
            name="my_tool",
            description="Does a thing",
            category="utility",
        )
        async def my_tool() -> ToolResult:
            return ToolResult(data={"ok": True})

    2. Class-based (for tools that need state)::

        class MyTool(BaseTool):
            name = "my_tool"
            ...
        registry.register(MyTool())
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def tool(
        self,
        *,
        name: str,
        description: str,
        category: str,
        params_model: type[ToolParams] | None = None,
        requires_confirmation: bool = False,
    ) -> Callable:
        """Decorator to register an async function as a tool."""

        def decorator(fn: Callable[..., Awaitable[ToolResult]]) -> Callable:
            if not inspect.iscoroutinefunction(fn):
                msg = f"Tool handler '{name}' must be an async function"
                raise TypeError(msg)

            self._tools[name] = ToolDef(
                name=name,
                description=description,
                category=category,
                handler=fn,
                params_model=params_model,
                requires_confirmation=requires_confirmation,
            )
            return fn

        return decorator

    def register(self, tool_instance: BaseTool) -> None:
        """Register a class-based tool instance."""
        self._tools[tool_instance.name] = ToolDef(
            name=tool_instance.name,
            description=tool_instance.description,
            category=tool_instance.category,
            handler=tool_instance.execute,
            params_model=tool_instance.params_model,
            requires_confirmation=tool_instance.requires_confirmation,
        )

    def get(self, name: str) -> ToolDef | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        """All registered tool names."""
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Generate Claude-compatible tool schemas for all registered tools."""
        return [self._tool_schema(t) for t in self._tools.values()]

    def get_tools_by_category(self) -> dict[str, list[ToolDef]]:
        """Group registered tools by category."""
        groups: dict[str, list[ToolDef]] = {}
        for tool_def in self._tools.values():
            groups.setdefault(tool_def.category, []).append(tool_def)
        return groups

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with the given arguments.

        Validates arguments against the params_model if one is defined.
        """
        tool_def = self._tools.get(name)
        if tool_def is None:
            return ToolResult(error=f"Unknown tool: {name}")

        try:
            if tool_def.params_model is not None:
                params = tool_def.params_model(**arguments)
                return await tool_def.handler(**params.model_dump())
            return await tool_def.handler(**arguments)
        except Exception:
            logger.exception("Tool '%s' failed", name)
            return ToolResult(error=f"Tool '{name}' failed. Check logs for details.")

    @staticmethod
    def _tool_schema(tool_def: ToolDef) -> dict[str, Any]:
        """Build a single Claude tool schema dict."""
        if tool_def.params_model is not None:
            input_schema = tool_def.params_model.model_json_schema()
        else:
            input_schema = {"type": "object", "properties": {}}

        return {
            "name": tool_def.name,
            "description": tool_def.description,
            "input_schema": input_schema,
        }


# Global registry — import this from anywhere to register or look up tools.
registry = ToolRegistry()
