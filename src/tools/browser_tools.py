"""Browser automation tool — browse interactive websites via Playwright."""

import logging

from pydantic import Field

from src.browser.agent import BrowserAgent
from src.browser.session import BrowserSession
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)


class BrowseWebParams(ToolParams):
    url: str = Field(description="URL to navigate to")
    task: str = Field(
        description=(
            "What to accomplish on this page — e.g. 'Find movie showtimes for "
            "tonight', 'Search for flights from Austin to NYC on March 15', "
            "'Look up the restaurant menu and hours'."
        )
    )


@registry.tool(
    name="browse_web",
    description=(
        "Browse a website interactively using a real browser. Unlike read_webpage, "
        "this tool can handle JavaScript-heavy sites, fill forms, click buttons, "
        "and navigate through multi-step flows. Use this for sites that need "
        "interaction — movie times, restaurant reservations, flight searches, "
        "shopping, etc. Returns a text summary of what was found."
    ),
    category="research",
    params_model=BrowseWebParams,

)
async def browse_web(url: str, task: str) -> ToolResult:
    try:
        async with BrowserSession() as session:
            page = await session.new_page()
            agent = BrowserAgent(page, task)
            result = await agent.run(url)

        if result.success:
            return ToolResult(data={
                "summary": result.summary,
                "final_url": result.url,
                "steps_taken": result.steps_taken,
            })
        else:
            error_msg = f"Browsing failed after {result.steps_taken} steps"
            if result.error:
                error_msg += f": {result.error}"
            if result.summary:
                error_msg += f"\nPartial result: {result.summary}"
            return ToolResult(error=error_msg)

    except Exception:
        logger.exception("browse_web tool failed")
        return ToolResult(error="Browser automation failed. Check logs for details.")
