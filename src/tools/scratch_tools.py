"""Scratch space tools — local file storage for temporary working files."""

import logging
import mimetypes
from urllib.parse import unquote, urlparse

import httpx
from pydantic import Field

from src.scratch import MAX_FILE_SIZE, ScratchSpace
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "NellaBot/1.0"


# -- Param models --------------------------------------------------------------


class WriteFileParams(ToolParams):
    path: str = Field(
        description=(
            "File path relative to scratch space"
            " (e.g. 'notes.txt' or 'research/summary.md')"
        ),
    )
    content: str = Field(description="Text content to write to the file")


class ReadFileParams(ToolParams):
    path: str = Field(description="File path relative to scratch space")


class ListFilesParams(ToolParams):
    pass


class DeleteFileParams(ToolParams):
    path: str = Field(description="File path relative to scratch space")


class DownloadFileParams(ToolParams):
    url: str = Field(description="URL to download the file from")
    filename: str | None = Field(
        default=None,
        description="Optional filename to save as. If omitted, derived from the URL.",
    )


# -- Tools ---------------------------------------------------------------------


@registry.tool(
    name="write_file",
    description=(
        "Write text content to a file in the local scratch space. "
        "Creates subdirectories as needed. Use for drafting documents, "
        "saving research notes, or staging content for other tools."
    ),
    category="files",
    params_model=WriteFileParams,
)
async def write_file(path: str, content: str) -> ToolResult:
    scratch = ScratchSpace.get()
    try:
        abs_path = scratch.write(path, content)
        return ToolResult(data={
            "written": True,
            "path": path,
            "size": abs_path.stat().st_size,
        })
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except OSError as exc:
        logger.exception("Failed to write scratch file")
        return ToolResult(error=f"Write failed: {exc}")


@registry.tool(
    name="read_file",
    description=(
        "Read a file from the local scratch space. Returns the text content "
        "for text files, or metadata for binary files."
    ),
    category="files",
    params_model=ReadFileParams,
)
async def read_file(path: str) -> ToolResult:
    scratch = ScratchSpace.get()
    try:
        content = scratch.read(path)
        target = scratch.resolve(path)
        return ToolResult(data={
            "path": path,
            "content": content,
            "size": target.stat().st_size,
        })
    except FileNotFoundError:
        return ToolResult(error=f"File not found: {path}")
    except ValueError:
        # Binary file — return metadata instead
        target = scratch.resolve(path)
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return ToolResult(data={
            "path": path,
            "binary": True,
            "size": target.stat().st_size,
            "mime_type": mime_type,
            "message": f"Binary file ({mime_type}). Reference this file by path in other tools.",
        })


@registry.tool(
    name="list_files",
    description=(
        "List all files in the local scratch space with size, age, "
        "and modification time."
    ),
    category="files",
    params_model=ListFilesParams,
)
async def list_files() -> ToolResult:
    scratch = ScratchSpace.get()
    files = scratch.list_files()
    return ToolResult(data={
        "files": files,
        "count": len(files),
        "total_size": scratch.total_size(),
    })


@registry.tool(
    name="delete_file",
    description="Delete a file from the local scratch space.",
    category="files",
    params_model=DeleteFileParams,
)
async def delete_file(path: str) -> ToolResult:
    scratch = ScratchSpace.get()
    try:
        deleted = scratch.delete(path)
        if deleted:
            return ToolResult(data={"deleted": True, "path": path})
        return ToolResult(error=f"File not found: {path}")
    except ValueError as exc:
        return ToolResult(error=str(exc))


@registry.tool(
    name="download_file",
    description=(
        "Download a file from a URL into the local scratch space. "
        "Supports any file type (PDF, images, documents, etc.). "
        "Use this to fetch files that other tools can then process."
    ),
    category="files",
    params_model=DownloadFileParams,
)
async def download_file(url: str, filename: str | None = None) -> ToolResult:
    # Derive filename from URL if not provided
    if not filename:
        parsed = urlparse(url)
        url_path = unquote(parsed.path)
        filename = url_path.rsplit("/", 1)[-1] if "/" in url_path else url_path
        if not filename:
            filename = "download"

    scratch = ScratchSpace.get()

    try:
        target = scratch.resolve(filename)
    except ValueError as exc:
        return ToolResult(error=str(exc))

    try:
        async with httpx.AsyncClient(  # noqa: SIM117
            timeout=60,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            max_redirects=5,
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()

                # Check Content-Length header if available
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    return ToolResult(
                        error=(
                            f"File too large: {content_length} bytes"
                            f" (max {MAX_FILE_SIZE})"
                        ),
                    )

                # Stream to disk, enforcing size limit
                target.parent.mkdir(parents=True, exist_ok=True)
                total_bytes = 0
                with target.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        if total_bytes > MAX_FILE_SIZE:
                            f.close()
                            target.unlink(missing_ok=True)
                            msg = (
                                "File too large: exceeded"
                                f" {MAX_FILE_SIZE} bytes"
                            )
                            return ToolResult(error=msg)
                        f.write(chunk)

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return ToolResult(data={
            "downloaded": True,
            "path": filename,
            "size": total_bytes,
            "mime_type": mime_type,
            "source_url": url,
        })

    except httpx.TimeoutException:
        target.unlink(missing_ok=True)
        return ToolResult(error=f"Timeout downloading {url}")
    except httpx.HTTPStatusError as exc:
        target.unlink(missing_ok=True)
        return ToolResult(error=f"HTTP {exc.response.status_code} downloading {url}")
    except httpx.HTTPError as exc:
        target.unlink(missing_ok=True)
        logger.exception("Failed to download file")
        return ToolResult(error=f"Download failed: {exc}")
    except OSError as exc:
        target.unlink(missing_ok=True)
        logger.exception("Failed to write downloaded file")
        return ToolResult(error=f"Write failed: {exc}")
