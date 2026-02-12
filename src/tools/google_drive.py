"""Google Drive tools — search, list, read, delete, download, upload files."""

import asyncio
import logging
import mimetypes

from googleapiclient.http import MediaInMemoryUpload
from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.scratch import ScratchSpace
from src.tools.base import GoogleToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_drive"

_FILE_FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink)"

_EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}


def _auth(account: str | None = None) -> GoogleAuthManager:
    return GoogleAuthManager.get(account)


def _escape_query(text: str) -> str:
    """Escape single quotes for Google Drive query strings."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


# -- search_files ------------------------------------------------------------


class SearchFilesParams(GoogleToolParams):
    query: str = Field(description="Search query (searches file names and content)")
    folder_id: str | None = Field(
        default=None,
        description="Optional folder ID to scope search to a specific folder",
    )
    max_results: int = Field(default=10, description="Maximum number of results")


@registry.tool(
    name="search_files",
    description=(
        "Search Google Drive for files by name or content. "
        "Optionally scope to a specific folder."
    ),
    category=_CATEGORY,
    params_model=SearchFilesParams,
)
async def search_files(
    query: str,
    folder_id: str | None = None,
    max_results: int = 10,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).drive()

    # Search in both full text and file name
    escaped = _escape_query(query)
    q = f"fullText contains '{escaped}' or name contains '{escaped}'"
    if folder_id:
        q = f"'{folder_id}' in parents and ({q})"

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


class ListRecentFilesParams(GoogleToolParams):
    max_results: int = Field(default=10, description="Maximum number of results")


@registry.tool(
    name="list_recent_files",
    description="List recently modified files in Google Drive.",
    category=_CATEGORY,
    params_model=ListRecentFilesParams,
)
async def list_recent_files(max_results: int = 10, account: str | None = None) -> ToolResult:
    service = _auth(account).drive()

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


# -- list_folder -------------------------------------------------------------


class ListFolderParams(GoogleToolParams):
    folder_id: str = Field(description="Google Drive folder ID")
    max_results: int = Field(default=20, description="Maximum number of results")


@registry.tool(
    name="list_folder",
    description=(
        "List the contents of a Google Drive folder. Returns files and subfolders "
        "sorted by most recently modified. Use search_files to find a folder by name first."
    ),
    category=_CATEGORY,
    params_model=ListFolderParams,
)
async def list_folder(
    folder_id: str, max_results: int = 20, account: str | None = None
) -> ToolResult:
    service = _auth(account).drive()

    q = f"'{folder_id}' in parents"

    result = await asyncio.to_thread(
        lambda: service.files()
        .list(
            q=q,
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


class ReadFileParams(GoogleToolParams):
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
async def read_file(file_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).drive()

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

        content = await _read_document_content(meta["id"], account=account)
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


class DeleteFileParams(GoogleToolParams):
    file_id: str = Field(description="Google Drive file ID to delete (moves to trash)")


@registry.tool(
    name="delete_file",
    description="Move a Google Drive file to trash.",
    category=_CATEGORY,
    params_model=DeleteFileParams,
    requires_confirmation=True,
)
async def delete_file(file_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).drive()

    await asyncio.to_thread(
        lambda: service.files()
        .update(fileId=file_id, body={"trashed": True})
        .execute()
    )

    return ToolResult(data={"trashed": True, "file_id": file_id})


# -- download_drive_file -----------------------------------------------------


class DownloadDriveFileParams(GoogleToolParams):
    file_id: str = Field(description="Google Drive file ID to download")
    filename: str | None = Field(
        default=None,
        description="Filename to save as in scratch space (uses Drive name if omitted)",
    )


@registry.tool(
    name="download_drive_file",
    description=(
        "Download a file from Google Drive to scratch space. "
        "Google Docs/Sheets/Slides are exported as PDF/XLSX."
    ),
    category=_CATEGORY,
    params_model=DownloadDriveFileParams,
)
async def download_drive_file(
    file_id: str, filename: str | None = None, account: str | None = None
) -> ToolResult:
    service = _auth(account).drive()

    meta = await asyncio.to_thread(
        lambda: service.files()
        .get(fileId=file_id, fields="id,name,mimeType,webViewLink")
        .execute()
    )

    drive_name = meta.get("name", "file")
    mime_type = meta.get("mimeType", "")

    # Google Workspace files need export
    export_fmt = _EXPORT_FORMATS.get(mime_type)
    if export_fmt:
        export_mime, ext = export_fmt
        data = await asyncio.to_thread(
            lambda: service.files()
            .export(fileId=file_id, mimeType=export_mime)
            .execute()
        )
        # Add extension if the drive name doesn't already have one
        if filename is None:
            filename = drive_name + ext if not drive_name.endswith(ext) else drive_name
        mime_type = export_mime
    else:
        data = await asyncio.to_thread(
            lambda: service.files().get_media(fileId=file_id).execute()
        )
        if filename is None:
            filename = drive_name

    try:
        scratch = ScratchSpace.get()
        scratch.write(filename, data)
    except (ValueError, OSError) as exc:
        return ToolResult(error=str(exc))

    return ToolResult(data={
        "downloaded": True,
        "path": filename,
        "size": len(data),
        "mime_type": mime_type,
        "drive_file_id": meta["id"],
        "drive_file_name": drive_name,
    })


# -- upload_to_drive ---------------------------------------------------------


class UploadToDriveParams(GoogleToolParams):
    path: str = Field(description="Scratch-space file path to upload")
    folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID to upload into (root if omitted)",
    )
    filename: str | None = Field(
        default=None,
        description="Name for the file in Drive (uses scratch filename if omitted)",
    )


@registry.tool(
    name="upload_to_drive",
    description="Upload a file from scratch space to Google Drive.",
    category=_CATEGORY,
    params_model=UploadToDriveParams,
    requires_confirmation=True,
)
async def upload_to_drive(
    path: str,
    folder_id: str | None = None,
    filename: str | None = None,
    account: str | None = None,
) -> ToolResult:
    try:
        scratch = ScratchSpace.get()
        data = scratch.read_bytes(path)
    except (FileNotFoundError, ValueError) as exc:
        return ToolResult(error=str(exc))

    name = filename or (path.rsplit("/", 1)[-1] if "/" in path else path)
    mime_type, _ = mimetypes.guess_type(name)
    mime_type = mime_type or "application/octet-stream"

    file_metadata: dict = {"name": name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=False)
    service = _auth(account).drive()

    result = await asyncio.to_thread(
        lambda: service.files()
        .create(body=file_metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )

    logger.info("Uploaded %s to Drive: %s", name, result["id"])
    return ToolResult(data={
        "uploaded": True,
        "file_id": result["id"],
        "name": result.get("name", name),
        "web_link": result.get("webViewLink", ""),
        "size": len(data),
    })
