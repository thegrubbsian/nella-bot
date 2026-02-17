"""Base types for the tool-calling framework."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class ToolResult:
    """Result of a tool execution.

    Every tool returns one of these. The LLM client serializes it
    into a tool_result content block for Claude.
    """

    data: dict[str, Any] | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None

    def to_content(self) -> str:
        """Serialize for the Claude tool_result content field."""
        if self.error:
            return json.dumps({"error": self.error})
        return json.dumps(self.data or {})


class ToolParams(BaseModel):
    """Base class for tool parameter models.

    Subclass with Field() definitions. The JSON schema is auto-generated
    via model_json_schema() for Claude's tool definitions.
    """


class GoogleToolParams(ToolParams):
    """Base params for all Google Workspace tools.

    Adds an optional ``account`` parameter so Claude can choose which
    Google account to use (e.g. 'work', 'personal'). When omitted the
    default account from settings is used.
    """

    account: str | None = Field(
        default=None,
        description="Google account to use (e.g. 'work', 'personal'). Uses default if omitted.",
    )


class BaseTool(ABC):
    """Abstract base for class-based tool implementations.

    Use this when a tool needs initialization state (API clients, DB
    connections, etc.). For simple stateless tools, prefer the
    @registry.tool() decorator instead.

    Example::

        class MyTool(BaseTool):
            name = "my_tool"
            description = "Does a thing"
            category = "custom"
            params_model = MyToolParams

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(data={"ok": True})
    """

    name: str = ""
    description: str = ""
    category: str = ""
    params_model: type[ToolParams] | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with validated parameters."""
        ...
