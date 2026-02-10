"""Google Drive tools — search, list, read, delete files."""

import asyncio
import logging

from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_drive"

_FILE_FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink)"


def _auth():
    return GoogleAuthManager.get()


# -- search_files ------------------------------------------------------------


class SearchFilesParams(ToolParams):
    query: str = Field(description="Search query (searches file names and content)")
    max_results: int = Field(default=10, description="Maximum number of results")


@registry.tool(
    name="search_files",
    description="Search Google Drive for files by name or content.",
    category=_CATEGORY,
    params_model=SearchFilesParams,
)
async def search_files(query: str, max_results: int = 10) -> ToolResult:
    service = _auth().drive()

    # Search in both full text and file name
    q = f"fullText contains '{query}' or name contains '{query}'"

    result = await asyncio.to_thread(
        lambda: service.files()
        .list(q=q, pageSize=max_results, fields=_FILE_FIELDS)
        .execute()
    )

    files = [
        {
            "id": f["id"],
            "name": f["name"],
            "mime_type": f.get("mimeType", ""),
            "modified_time": f.get("modifiedTime", ""),
            "web_link": f.get("webViewLink", ""),
        }
        for f in result.get("files", [])
    ]

    return ToolResult(data={"files": files, "count": len(files)})


# -- list_recent_files -------------------------------------------------------


class ListRecentFilesParams(ToolParams):
    max_results: int = Field(default=10, description="Maximum number of results")


@registry.tool(
    name="list_recent_files",
    description="List recently modified files in Google Drive.",
    category=_CATEGORY,
    params_model=ListRecentFilesParams,
)
async def list_recent_files(max_results: int = 10) -> ToolResult:
    service = _auth().drive()

    result = await asyncio.to_thread(
        lambda: service.files()
        .list(
            orderBy="modifiedTime desc",
            pageSize=max_results,
            fields=_FILE_FIELDS,
        )
        .execute()
    )

    files = [
        {
            "id": f["id"],
            "name": f["name"],
            "mime_type": f.get("mimeType", ""),
            "modified_time": f.get("modifiedTime", ""),
            "web_link": f.get("webViewLink", ""),
        }
        for f in result.get("files", [])
    ]

    return ToolResult(data={"files": files, "count": len(files)})


# -- read_file ---------------------------------------------------------------


class ReadFileParams(ToolParams):
    file_id: str = Field(description="Google Drive file ID")


@registry.tool(
    name="read_file",
    description=(
        "Read the content of a Google Drive file. Supports Google Docs, "
        "plain text, CSV, and JSON. Returns metadata for binary files."
    ),
    category=_CATEGORY,
    params_model=ReadFileParams,
)
async def read_file(file_id: str) -> ToolResult:
    service = _auth().drive()

    # Get file metadata
    meta = await asyncio.to_thread(
        lambda: service.files()
        .get(fileId=file_id, fields="id,name,mimeType,modifiedTime,webViewLink,size")
        .execute()
    )

    mime_type = meta.get("mimeType", "")
    name = meta.get("name", "")
    base_info = {
        "id": meta["id"],
        "name": name,
        "mime_type": mime_type,
        "modified_time": meta.get("modifiedTime", ""),
        "web_link": meta.get("webViewLink", ""),
    }

    # Google Docs → use Docs API
    if mime_type == "application/vnd.google-apps.document":
        from src.tools.google_docs import _read_document_content

        content = await _read_document_content(meta["id"])
        return ToolResult(data={**base_info, "content": content})

    # Google Sheets / Slides → return metadata only (complex to parse)
    if mime_type in (
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
    ):
        return ToolResult(data={
            **base_info,
            "content": f"[{mime_type} — open in browser: {base_info['web_link']}]",
        })

    # Text-based files: plain text, CSV, JSON, markdown, etc.
    text_types = {"text/plain", "text/csv", "text/markdown", "application/json"}
    is_text = mime_type in text_types or name.endswith((".txt", ".csv", ".json", ".md"))

    if is_text:
        content_bytes = await asyncio.to_thread(
            lambda: service.files().get_media(fileId=file_id).execute()
        )
        content = content_bytes.decode("utf-8", errors="replace")
        # Truncate very long files
        if len(content) > 50_000:
            content = content[:50_000] + "\n\n[truncated — file too large]"
        return ToolResult(data={**base_info, "content": content})

    # Images, PDFs, and other binary files → metadata only
    return ToolResult(data={
        **base_info,
        "size": meta.get("size", "unknown"),
        "content": f"[Binary file: {mime_type} — open in browser: {base_info['web_link']}]",
    })


# -- delete_file -------------------------------------------------------------


class DeleteFileParams(ToolParams):
    file_id: str = Field(description="Google Drive file ID to delete (moves to trash)")


@registry.tool(
    name="delete_file",
    description="Move a Google Drive file to trash.",
    category=_CATEGORY,
    params_model=DeleteFileParams,
    requires_confirmation=True,
)
async def delete_file(file_id: str) -> ToolResult:
    service = _auth().drive()

    await asyncio.to_thread(
        lambda: service.files()
        .update(fileId=file_id, body={"trashed": True})
        .execute()
    )

    return ToolResult(data={"trashed": True, "file_id": file_id})
