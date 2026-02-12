"""Google People tools — search, get, create, update contacts + local notes."""

import asyncio
import logging

from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.people.store import PeopleStore
from src.tools.base import GoogleToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_people"
_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,"
    "biographies,userDefined,memberships,metadata"
)


def _auth(account: str | None = None) -> GoogleAuthManager:
    return GoogleAuthManager.get(account)


def _format_contact(person: dict) -> dict:
    """Extract a flat summary from a People API person resource."""
    names = person.get("names", [{}])
    name_obj = names[0] if names else {}

    emails = person.get("emailAddresses", [{}])
    email_obj = emails[0] if emails else {}

    phones = person.get("phoneNumbers", [{}])
    phone_obj = phones[0] if phones else {}

    orgs = person.get("organizations", [{}])
    org_obj = orgs[0] if orgs else {}

    bios = person.get("biographies", [{}])
    bio_obj = bios[0] if bios else {}

    return {
        "resource_name": person.get("resourceName", ""),
        "name": name_obj.get("displayName", ""),
        "given_name": name_obj.get("givenName", ""),
        "family_name": name_obj.get("familyName", ""),
        "email": email_obj.get("value", ""),
        "phone": phone_obj.get("value", ""),
        "organization": org_obj.get("name", ""),
        "title": org_obj.get("title", ""),
        "biography": bio_obj.get("value", ""),
    }


# -- search_contacts ----------------------------------------------------------


class SearchContactsParams(GoogleToolParams):
    query: str = Field(description="Search query (name, email, phone, etc.)")
    max_results: int = Field(default=10, description="Maximum number of results (max 30)")


@registry.tool(
    name="search_contacts",
    description=(
        "Search Google Contacts by name, email, phone, or other fields. "
        "Returns contact summaries."
    ),
    category=_CATEGORY,
    params_model=SearchContactsParams,
)
async def search_contacts(
    query: str, max_results: int = 10, account: str | None = None
) -> ToolResult:
    service = _auth(account).people()

    result = await asyncio.to_thread(
        lambda: service.people()
        .searchContacts(query=query, readMask=_PERSON_FIELDS, pageSize=min(max_results, 30))
        .execute()
    )

    contacts = [_format_contact(r["person"]) for r in result.get("results", [])]
    return ToolResult(data={"contacts": contacts, "count": len(contacts)})


# -- get_contact ---------------------------------------------------------------


class GetContactParams(GoogleToolParams):
    resource_name: str = Field(
        description="Contact resource name (e.g. 'people/c1234567890')"
    )


@registry.tool(
    name="get_contact",
    description=(
        "Get full details of a contact by resource name. "
        "Also returns any local notes stored for this contact."
    ),
    category=_CATEGORY,
    params_model=GetContactParams,
)
async def get_contact(
    resource_name: str, account: str | None = None
) -> ToolResult:
    service = _auth(account).people()

    person = await asyncio.to_thread(
        lambda: service.people()
        .get(resourceName=resource_name, personFields=_PERSON_FIELDS)
        .execute()
    )

    contact = _format_contact(person)

    # Merge local notes if they exist
    store = PeopleStore.get()
    local = await store.get_by_id(resource_name)
    if local:
        contact["notes"] = local["notes"]
        contact["notes_updated_at"] = local["updated_at"]

    return ToolResult(data=contact)


# -- create_contact ------------------------------------------------------------


class CreateContactParams(GoogleToolParams):
    given_name: str = Field(description="First name")
    family_name: str | None = Field(default=None, description="Last name")
    email: str | None = Field(default=None, description="Email address")
    phone: str | None = Field(default=None, description="Phone number")
    organization: str | None = Field(default=None, description="Company or organization name")
    title: str | None = Field(default=None, description="Job title")
    notes: str | None = Field(
        default=None,
        description="Personal notes about this contact (stored locally, not in Google)",
    )


@registry.tool(
    name="create_contact",
    description="Create a new Google Contact. Optionally attach local notes.",
    category=_CATEGORY,
    params_model=CreateContactParams,
    requires_confirmation=True,
)
async def create_contact(
    given_name: str,
    family_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    organization: str | None = None,
    title: str | None = None,
    notes: str | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).people()

    # Build the person body
    person_body: dict = {
        "names": [{"givenName": given_name}],
    }
    if family_name:
        person_body["names"][0]["familyName"] = family_name

    if email:
        person_body["emailAddresses"] = [{"value": email}]
    if phone:
        person_body["phoneNumbers"] = [{"value": phone}]
    if organization or title:
        org: dict = {}
        if organization:
            org["name"] = organization
        if title:
            org["title"] = title
        person_body["organizations"] = [org]

    created = await asyncio.to_thread(
        lambda: service.people().createContact(body=person_body).execute()
    )

    resource_name = created.get("resourceName", "")
    display_name = _format_contact(created)["name"]

    # Save local notes if provided
    if notes and resource_name:
        store = PeopleStore.get()
        await store.upsert(resource_name, display_name, notes)

    logger.info("Created contact: %s (%s)", display_name, resource_name)
    return ToolResult(data={
        "created": True,
        "resource_name": resource_name,
        "name": display_name,
    })


# -- update_contact ------------------------------------------------------------


class UpdateContactParams(GoogleToolParams):
    resource_name: str = Field(
        description="Contact resource name (e.g. 'people/c1234567890')"
    )
    given_name: str | None = Field(default=None, description="New first name")
    family_name: str | None = Field(default=None, description="New last name")
    email: str | None = Field(default=None, description="New email address")
    phone: str | None = Field(default=None, description="New phone number")
    organization: str | None = Field(default=None, description="New company or organization")
    title: str | None = Field(default=None, description="New job title")


@registry.tool(
    name="update_contact",
    description="Update an existing Google Contact's fields.",
    category=_CATEGORY,
    params_model=UpdateContactParams,
    requires_confirmation=True,
)
async def update_contact(
    resource_name: str,
    given_name: str | None = None,
    family_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    organization: str | None = None,
    title: str | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).people()

    # Fetch current person for etag
    current = await asyncio.to_thread(
        lambda: service.people()
        .get(resourceName=resource_name, personFields=_PERSON_FIELDS)
        .execute()
    )

    etag = current.get("etag", "")
    update_fields: list[str] = []
    person_body: dict = {"etag": etag}

    if given_name is not None or family_name is not None:
        name_obj: dict = {}
        if given_name is not None:
            name_obj["givenName"] = given_name
        if family_name is not None:
            name_obj["familyName"] = family_name
        person_body["names"] = [name_obj]
        update_fields.append("names")

    if email is not None:
        person_body["emailAddresses"] = [{"value": email}]
        update_fields.append("emailAddresses")

    if phone is not None:
        person_body["phoneNumbers"] = [{"value": phone}]
        update_fields.append("phoneNumbers")

    if organization is not None or title is not None:
        org: dict = {}
        if organization is not None:
            org["name"] = organization
        if title is not None:
            org["title"] = title
        person_body["organizations"] = [org]
        update_fields.append("organizations")

    if not update_fields:
        return ToolResult(error="No fields to update. Provide at least one field.")

    updated = await asyncio.to_thread(
        lambda: service.people()
        .updateContact(
            resourceName=resource_name,
            body=person_body,
            updatePersonFields=",".join(update_fields),
        )
        .execute()
    )

    display_name = _format_contact(updated)["name"]
    logger.info("Updated contact: %s (%s)", display_name, resource_name)
    return ToolResult(data={
        "updated": True,
        "resource_name": resource_name,
        "name": display_name,
    })


# -- update_contact_notes ------------------------------------------------------


class UpdateContactNotesParams(GoogleToolParams):
    resource_name: str = Field(
        description="Contact resource name (e.g. 'people/c1234567890')"
    )
    notes: str = Field(description="Notes content to save for this contact")


@registry.tool(
    name="update_contact_notes",
    description=(
        "Update local notes for a contact. These notes are stored locally "
        "(not in Google) and are visible when getting contact details."
    ),
    category=_CATEGORY,
    params_model=UpdateContactNotesParams,
)
async def update_contact_notes(
    resource_name: str, notes: str, account: str | None = None
) -> ToolResult:
    store = PeopleStore.get()

    # Check if we already have a local record
    existing = await store.get_by_id(resource_name)
    if existing:
        display_name = existing["display_name"]
    else:
        # Fetch display name from People API
        service = _auth(account).people()
        person = await asyncio.to_thread(
            lambda: service.people()
            .get(resourceName=resource_name, personFields="names")
            .execute()
        )
        display_name = _format_contact(person)["name"]

    await store.upsert(resource_name, display_name, notes)
    return ToolResult(data={
        "updated": True,
        "resource_name": resource_name,
        "display_name": display_name,
    })


# -- search_contact_notes -----------------------------------------------------


class SearchContactNotesParams(GoogleToolParams):
    query: str = Field(description="Search query for contact notes (searches name and notes)")


@registry.tool(
    name="search_contact_notes",
    description="Search local contact notes by name or notes content.",
    category=_CATEGORY,
    params_model=SearchContactNotesParams,
)
async def search_contact_notes(
    query: str, account: str | None = None  # noqa: ARG001
) -> ToolResult:
    store = PeopleStore.get()
    results = await store.search(query)
    return ToolResult(data={"results": results, "count": len(results)})
