"""Tool framework — import tool modules here to register them."""

# Import tool modules so their @registry.tool() decorators execute.
# To add a new integration, create a file in src/tools/ and add an import here.
from src.integrations.google_auth import GoogleAuthManager
from src.tools import memory_tools, scheduler_tools, utility  # noqa: F401
from src.tools.registry import registry

# Conditionally load Google tools when at least one account has a token file.
if GoogleAuthManager.any_enabled():
    from src.tools import google_calendar, google_docs, google_drive, google_gmail  # noqa: F401

__all__ = ["registry"]
