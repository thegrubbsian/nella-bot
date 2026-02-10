"""Google Docs tools — read, create, update, append documents."""

import asyncio
import logging

from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_docs"


def _auth():
    return GoogleAuthManager.get()


def _extract_text(doc: dict) -> str:
    """Walk a Docs API document body and extract structured text."""
    lines: list[str] = []

    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue

        style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
        prefix = ""
        if style == "HEADING_1":
            prefix = "# "
        elif style == "HEADING_2":
            prefix = "## "
        elif style == "HEADING_3":
            prefix = "### "

        # Check if it's a list item
        bullet = paragraph.get("bullet")
        if bullet:
            prefix = "- "

        text_parts: list[str] = []
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if text_run:
                text_parts.append(text_run.get("content", ""))

        line = prefix + "".join(text_parts)
        lines.append(line)

    return "".join(lines)


async def _read_document_content(document_id: str) -> str:
    """Read document text — shared by read_document and Drive's read_file."""
    service = _auth().docs()

    doc = await asyncio.to_thread(
        lambda: service.documents().get(documentId=document_id).execute()
    )

    return _extract_text(doc)


# -- read_document -----------------------------------------------------------


class ReadDocumentParams(ToolParams):
    document_id: str = Field(description="Google Docs document ID")


@registry.tool(
    name="read_document",
    description="Read the full content of a Google Docs document.",
    category=_CATEGORY,
    params_model=ReadDocumentParams,
)
async def read_document(document_id: str) -> ToolResult:
    service = _auth().docs()

    doc = await asyncio.to_thread(
        lambda: service.documents().get(documentId=document_id).execute()
    )

    content = _extract_text(doc)
    doc_url = f"https://docs.google.com/document/d/{document_id}/edit"

    return ToolResult(data={
        "document_id": document_id,
        "title": doc.get("title", ""),
        "content": content,
        "web_link": doc_url,
    })


# -- create_document ---------------------------------------------------------


class CreateDocumentParams(ToolParams):
    title: str = Field(description="Document title")
    content: str = Field(default="", description="Initial document content")


@registry.tool(
    name="create_document",
    description="Create a new Google Docs document.",
    category=_CATEGORY,
    params_model=CreateDocumentParams,
    requires_confirmation=True,
)
async def create_document(title: str, content: str = "") -> ToolResult:
    service = _auth().docs()

    doc = await asyncio.to_thread(
        lambda: service.documents().create(body={"title": title}).execute()
    )

    document_id = doc["documentId"]

    if content:
        await asyncio.to_thread(
            lambda: service.documents()
            .batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {"insertText": {"location": {"index": 1}, "text": content}}
                    ]
                },
            )
            .execute()
        )

    doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
    logger.info("Created document: %s", document_id)

    return ToolResult(data={
        "document_id": document_id,
        "title": title,
        "web_link": doc_url,
    })


# -- update_document ---------------------------------------------------------


class UpdateDocumentParams(ToolParams):
    document_id: str = Field(description="Google Docs document ID")
    content: str = Field(description="New document content (replaces all existing content)")


@registry.tool(
    name="update_document",
    description="Replace the entire content of a Google Docs document.",
    category=_CATEGORY,
    params_model=UpdateDocumentParams,
    requires_confirmation=True,
)
async def update_document(document_id: str, content: str) -> ToolResult:
    service = _auth().docs()

    # Get current document to find end index
    doc = await asyncio.to_thread(
        lambda: service.documents().get(documentId=document_id).execute()
    )

    body_content = doc.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 1) if body_content else 1

    requests: list[dict] = []
    # Delete existing content (if any beyond the initial newline)
    if end_index > 2:
        requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_index - 1}
            }
        })
    # Insert new content
    requests.append({"insertText": {"location": {"index": 1}, "text": content}})

    await asyncio.to_thread(
        lambda: service.documents()
        .batchUpdate(documentId=document_id, body={"requests": requests})
        .execute()
    )

    doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
    return ToolResult(data={
        "document_id": document_id,
        "title": doc.get("title", ""),
        "web_link": doc_url,
    })


# -- append_to_document ------------------------------------------------------


class AppendToDocumentParams(ToolParams):
    document_id: str = Field(description="Google Docs document ID")
    content: str = Field(description="Content to append to the end of the document")


@registry.tool(
    name="append_to_document",
    description="Append content to the end of a Google Docs document.",
    category=_CATEGORY,
    params_model=AppendToDocumentParams,
    requires_confirmation=True,
)
async def append_to_document(document_id: str, content: str) -> ToolResult:
    service = _auth().docs()

    # Get current document to find end index
    doc = await asyncio.to_thread(
        lambda: service.documents().get(documentId=document_id).execute()
    )

    body_content = doc.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 1) if body_content else 1

    await asyncio.to_thread(
        lambda: service.documents()
        .batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": end_index - 1},
                            "text": content,
                        }
                    }
                ]
            },
        )
        .execute()
    )

    doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
    return ToolResult(data={
        "document_id": document_id,
        "title": doc.get("title", ""),
        "web_link": doc_url,
    })
