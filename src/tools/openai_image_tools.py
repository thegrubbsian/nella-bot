"""Image generation tool — OpenAI GPT-Image-1."""

from __future__ import annotations

import base64
import logging
import time
from typing import TYPE_CHECKING

from pydantic import Field

from src.config import settings
from src.notifications.router import NotificationRouter
from src.scratch import ScratchSpace
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

if TYPE_CHECKING:
    from openai import AsyncOpenAI

    from src.notifications.context import MessageContext

logger = logging.getLogger(__name__)

VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024"}
VALID_QUALITIES = {"low", "medium", "high"}
TELEGRAM_CAPTION_LIMIT = 1024

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Return a lazily-initialised AsyncOpenAI singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


class GenerateImageParams(ToolParams):
    prompt: str = Field(description="Detailed description of the image to generate")
    size: str = Field(
        default="1024x1024",
        description="Image dimensions: 1024x1024, 1024x1536, or 1536x1024",
    )
    quality: str = Field(
        default="medium",
        description="Rendering quality: low, medium, or high",
    )


@registry.tool(
    name="generate_image",
    description=(
        "Generate an image from a text description using OpenAI GPT-Image-1. "
        "The image is saved to scratch space and sent directly to the chat. "
        "Use descriptive, detailed prompts for best results."
    ),
    category="creative",
    params_model=GenerateImageParams,
)
async def generate_image(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "medium",
    msg_context: MessageContext | None = None,
) -> ToolResult:
    if size not in VALID_SIZES:
        valid = ", ".join(sorted(VALID_SIZES))
        return ToolResult(error=f"Invalid size '{size}'. Must be one of: {valid}")

    if quality not in VALID_QUALITIES:
        valid = ", ".join(sorted(VALID_QUALITIES))
        return ToolResult(error=f"Invalid quality '{quality}'. Must be one of: {valid}")

    try:
        client = _get_client()
        response = await client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
    except Exception:
        logger.exception("OpenAI image generation failed")
        return ToolResult(error="Image generation failed. Please try again.")

    image_b64 = response.data[0].b64_json
    if not image_b64:
        return ToolResult(error="No image data returned from OpenAI.")

    image_bytes = base64.b64decode(image_b64)

    # Save to scratch space
    filename = f"generated_{int(time.time())}.png"
    scratch = ScratchSpace.get()
    try:
        scratch.write(filename, image_bytes)
    except ValueError as exc:
        return ToolResult(error=f"Failed to save image: {exc}")

    # Send to user via notification channel
    if msg_context:
        max_len = TELEGRAM_CAPTION_LIMIT
        caption = prompt if len(prompt) <= max_len else prompt[:max_len]
        router = NotificationRouter.get()
        await router.send_photo(
            msg_context.user_id,
            image_bytes,
            channel=msg_context.source_channel,
            caption=caption,
        )

    return ToolResult(
        data={
            "generated": True,
            "path": filename,
            "size_bytes": len(image_bytes),
            "dimensions": size,
            "quality": quality,
            "prompt": prompt,
        }
    )
