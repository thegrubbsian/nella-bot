"""Tool framework — import tool modules here to register them."""

# Import tool modules so their @registry.tool() decorators execute.
# To add a new integration, create a file in src/tools/ and add an import here.
from src.tools import memory_tools, utility  # noqa: F401
from src.tools.registry import registry

__all__ = ["registry"]
