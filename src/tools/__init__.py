"""Tool framework — import tool modules here to register them."""

# Import tool modules so their @registry.tool() decorators execute.
# To add a new integration, create a file in src/tools/ and add an import here.
from src.config import settings
from src.integrations.google_auth import GoogleAuthManager
from src.tools import memory_tools, scheduler_tools, scratch_tools, utility  # noqa: F401
from src.tools.registry import registry

# Conditionally load Google tools when at least one account has a token file.
if GoogleAuthManager.any_enabled():
    from src.tools import (  # noqa: F401
        google_calendar,
        google_docs,
        google_drive,
        google_gmail,
        google_people,
    )

# Conditionally load log tools when API token is configured.
if settings.papertrail_api_token:
    from src.tools import log_tools  # noqa: F401

# Conditionally load web research tools when Brave Search API key is configured.
if settings.brave_search_api_key:
    from src.tools import web_tools  # noqa: F401

# Conditionally load GitHub tools when token is configured.
if settings.github_token:
    from src.tools import github_tools  # noqa: F401

# Conditionally load LinkedIn tools when token file exists.
from src.integrations.linkedin_auth import LinkedInAuth

if LinkedInAuth.enabled():
    from src.tools import linkedin_tools  # noqa: F401

# Conditionally load browser automation tool when enabled.
if settings.browser_enabled:
    from src.tools import browser_tools  # noqa: F401

__all__ = ["registry"]
