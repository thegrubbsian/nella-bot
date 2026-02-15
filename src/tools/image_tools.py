"""Image analysis tool — Claude vision for images in scratch space."""

import base64
import logging
import mimetypes

from pydantic import Field

from src.scratch import ScratchSpace
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

DEFAULT_PROMPT = "Describe this image in detail. What do you see?"


class AnalyzeImageParams(ToolParams):
    path: str = Field(description="File path relative to scratch space (e.g. 'photo.jpg')")
    prompt: str = Field(
        default=DEFAULT_PROMPT,
        description="What to analyze or look for in the image",
    )


@registry.tool(
    name="analyze_image",
    description=(
        "Analyze an image file in scratch space using vision. "
        "Supports JPEG, PNG, GIF, and WebP. Use this to describe images, "
        "read text from screenshots, extract data from charts, or answer "
        "questions about visual content."
    ),
    category="files",
    params_model=AnalyzeImageParams,
)
async def analyze_image(path: str, prompt: str = DEFAULT_PROMPT) -> ToolResult:
    scratch = ScratchSpace.get()

    try:
        data = scratch.read_bytes(path)
    except FileNotFoundError:
        return ToolResult(error=f"File not found: {path}")
    except ValueError as exc:
        return ToolResult(error=str(exc))

    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if media_type not in SUPPORTED_MEDIA_TYPES:
        return ToolResult(
            error=(
                f"Unsupported image type: {media_type}. "
                f"Supported: {', '.join(sorted(SUPPORTED_MEDIA_TYPES))}"
            )
        )

    if len(data) > MAX_IMAGE_SIZE:
        return ToolResult(
            error=f"Image too large: {len(data)} bytes (max {MAX_IMAGE_SIZE})"
        )

    image_b64 = base64.b64encode(data).decode()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
        }
    ]

    try:
        # Lazy import to avoid circular dependency:
        # src.llm.client → src.tools → image_tools → src.llm.client
        from src.llm.client import complete_text

        analysis = await complete_text(messages, max_tokens=2048)
        return ToolResult(data={"path": path, "analysis": analysis})
    except Exception:
        logger.exception("Image analysis failed for %s", path)
        return ToolResult(error=f"Image analysis failed for {path}")
