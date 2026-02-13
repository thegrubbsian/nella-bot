"""Browser agent — autonomous loop that navigates pages via Claude vision."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.config import settings
from src.llm.models import _resolve

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# JavaScript that finds interactive elements, injects numbered red labels,
# and returns metadata for each element.
_EXTRACT_ELEMENTS_JS = """
() => {
    const SELECTORS = 'a, button, input, select, textarea, [role="button"], [role="link"]';
    const MAX_ELEMENTS = 50;
    const LABEL_CLASS = '__nella_label__';

    // Remove any previous labels
    document.querySelectorAll('.' + LABEL_CLASS).forEach(el => el.remove());

    const elements = [];
    let index = 0;

    for (const el of document.querySelectorAll(SELECTORS)) {
        if (index >= MAX_ELEMENTS) break;

        // Skip hidden / off-screen elements
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.bottom < 0 || rect.top > window.innerHeight * 2) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;

        const tag = el.tagName.toLowerCase();
        const raw = el.innerText || el.value || el.placeholder
            || el.getAttribute('aria-label') || '';
        const text = raw.trim().slice(0, 80);
        const type = el.getAttribute('type') || '';
        const href = el.getAttribute('href') || '';
        const name = el.getAttribute('name') || '';

        // Inject a red numbered label overlay
        const label = document.createElement('div');
        label.className = LABEL_CLASS;
        label.textContent = String(index);
        label.style.cssText = [
            'position: absolute',
            'z-index: 999999',
            'background: red',
            'color: white',
            'font-size: 12px',
            'font-weight: bold',
            'padding: 1px 4px',
            'border-radius: 3px',
            'pointer-events: none',
            `left: ${rect.left + window.scrollX}px`,
            `top: ${rect.top + window.scrollY - 16}px`,
        ].join(';');
        document.body.appendChild(label);

        elements.push({
            index,
            tag,
            type,
            text,
            href,
            name,
            x: Math.round(rect.x + rect.width / 2),
            y: Math.round(rect.y + rect.height / 2),
        });
        index++;
    }

    return elements;
}
"""

_REMOVE_LABELS_JS = """
() => {
    document.querySelectorAll('.__nella_label__').forEach(el => el.remove());
}
"""

SYSTEM_PROMPT = """\
You are a browser automation agent. You see a screenshot of a web page with numbered red labels \
overlaid on interactive elements. You also receive a list of those elements with metadata.

Your task: {task}

Respond with a single JSON object — no markdown fences, no explanation. Use one of these actions:

{{"action": "click", "index": <element index>}}
{{"action": "fill", "index": <element index>, "value": "<text to type>"}}
{{"action": "select", "index": <element index>, "value": "<option value>"}}
{{"action": "scroll", "direction": "down"}}  — or "up"
{{"action": "navigate", "url": "<full URL>"}}
{{"action": "wait", "seconds": <1-5>}}
{{"action": "done", "summary": "<your answer to the task>"}}

Rules:
- Only use "done" when you have the information requested or have completed the task.
- If the page hasn't loaded useful content yet, try scrolling or waiting.
- When filling a form field, click it first if needed (the fill action clicks automatically).
- Keep your summary concise and factual when done.
"""


@dataclass
class BrowseResult:
    """Outcome of a browser agent run."""

    success: bool
    summary: str
    steps_taken: int
    url: str
    error: str | None = None


@dataclass
class _AgentState:
    """Mutable state for the agent loop."""

    steps: int = 0
    last_url: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)


class BrowserAgent:
    """Autonomous browser agent that uses Claude vision to navigate pages."""

    def __init__(
        self,
        page: Page,
        task: str,
        *,
        max_steps: int | None = None,
        model: str | None = None,
    ) -> None:
        self._page = page
        self._task = task
        self._max_steps = max_steps or settings.browser_max_steps
        self._model = self._resolve_model(model or settings.browser_model)
        self._state = _AgentState()

    @staticmethod
    def _resolve_model(name: str) -> str:
        """Resolve friendly model name to full ID."""
        resolved = _resolve(name)
        if resolved is None:
            logger.warning("Unknown browser model '%s', falling back to sonnet", name)
            resolved = _resolve("sonnet")
        return resolved  # type: ignore[return-value]

    async def run(self, url: str) -> BrowseResult:
        """Execute the browsing task starting at the given URL."""
        try:
            logger.info("Browser agent starting: url=%s task=%s", url, self._task[:80])
            await self._page.goto(url, wait_until="domcontentloaded")
            self._state.last_url = self._page.url

            while self._state.steps < self._max_steps:
                result = await self._step()
                if result is not None:
                    return result

            # Hit max steps
            summary = "Reached maximum steps without completing the task."
            if self._state.actions:
                last = self._state.actions[-1]
                if last.get("action") == "done":
                    summary = last.get("summary", summary)

            return BrowseResult(
                success=False,
                summary=summary,
                steps_taken=self._state.steps,
                url=self._page.url,
                error="Max steps reached",
            )

        except Exception as exc:
            logger.exception("Browser agent failed")
            return BrowseResult(
                success=False,
                summary="",
                steps_taken=self._state.steps,
                url=self._state.last_url or url,
                error=str(exc),
            )

    async def _step(self) -> BrowseResult | None:
        """Run a single agent step: extract → screenshot → ask Claude → execute."""
        self._state.steps += 1
        logger.info("Browser step %d/%d on %s", self._state.steps, self._max_steps, self._page.url)

        # Extract interactive elements (also injects labels)
        elements = await self._page.evaluate(_EXTRACT_ELEMENTS_JS)

        # Screenshot with labels visible
        screenshot_bytes = await self._page.screenshot(full_page=False)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

        # Remove labels so they don't interfere with actions
        await self._page.evaluate(_REMOVE_LABELS_JS)

        # Build element list text
        element_text = self._format_elements(elements)

        # Ask Claude what to do
        action = await self._ask_claude(screenshot_b64, element_text)
        self._state.actions.append(action)
        self._state.last_url = self._page.url

        if action.get("action") == "done":
            return BrowseResult(
                success=True,
                summary=action.get("summary", "Task completed."),
                steps_taken=self._state.steps,
                url=self._page.url,
            )

        await self._execute_action(action, elements)
        return None

    async def _ask_claude(self, screenshot_b64: str, element_text: str) -> dict[str, Any]:
        """Send screenshot + element list to Claude, get back an action."""
        # Lazy import to avoid circular dependency:
        # src.llm.client → src.tools → browser_tools → agent → src.llm.client
        from src.llm.client import complete_text
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Interactive elements on this page:\n"
                            f"{element_text}\n\n"
                            f"What action should I take?"
                        ),
                    },
                ],
            }
        ]

        system = SYSTEM_PROMPT.format(task=self._task)
        raw = await complete_text(messages, system=system, model=self._model, max_tokens=1024)
        return self._parse_action(raw)

    async def _execute_action(self, action: dict[str, Any], elements: list[dict[str, Any]]) -> None:
        """Execute a single action on the page."""
        act = action.get("action", "")
        logger.info("Executing action: %s", action)

        if act == "click":
            idx = action.get("index", -1)
            el = self._find_element(elements, idx)
            if el:
                await self._page.mouse.click(el["x"], el["y"])
                await self._page.wait_for_load_state("domcontentloaded", timeout=10000)

        elif act == "fill":
            idx = action.get("index", -1)
            value = action.get("value", "")
            el = self._find_element(elements, idx)
            if el:
                await self._page.mouse.click(el["x"], el["y"])
                await self._page.keyboard.type(value, delay=30)

        elif act == "select":
            idx = action.get("index", -1)
            value = action.get("value", "")
            el = self._find_element(elements, idx)
            if el and el.get("name"):
                await self._page.select_option(f'[name="{el["name"]}"]', value)

        elif act == "scroll":
            direction = action.get("direction", "down")
            delta = -500 if direction == "up" else 500
            await self._page.mouse.wheel(0, delta)
            await self._page.wait_for_timeout(500)

        elif act == "navigate":
            url = action.get("url", "")
            if url:
                await self._page.goto(url, wait_until="domcontentloaded")

        elif act == "wait":
            seconds = min(action.get("seconds", 2), 5)
            await self._page.wait_for_timeout(seconds * 1000)

        else:
            logger.warning("Unknown action: %s", act)

    @staticmethod
    def _find_element(elements: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
        """Find an element by its overlay index."""
        for el in elements:
            if el.get("index") == index:
                return el
        logger.warning("Element index %d not found", index)
        return None

    @staticmethod
    def _format_elements(elements: list[dict[str, Any]]) -> str:
        """Format element metadata as a compact text list for Claude."""
        lines = []
        for el in elements:
            parts = [f"[{el['index']}]", el["tag"]]
            if el.get("type"):
                parts.append(f'type="{el["type"]}"')
            if el.get("text"):
                parts.append(f'"{el["text"]}"')
            if el.get("href"):
                parts.append(f'href="{el["href"][:100]}"')
            if el.get("name"):
                parts.append(f'name="{el["name"]}"')
            lines.append(" ".join(parts))
        return "\n".join(lines) if lines else "(no interactive elements found)"

    @staticmethod
    def _parse_action(raw: str) -> dict[str, Any]:
        """Parse Claude's response into an action dict.

        Handles:
        - Clean JSON
        - JSON wrapped in markdown fences
        - Freeform text (treated as "done" with the text as summary)
        """
        text = raw.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in freeform text
        match = re.search(r"\{[^{}]*\"action\"[^{}]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict) and "action" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # Fall back: treat entire response as a "done" summary
        logger.warning("Could not parse action JSON, treating as done: %s", text[:200])
        return {"action": "done", "summary": text}
