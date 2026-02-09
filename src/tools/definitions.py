"""Tool definitions for Claude function calling."""

TOOLS: list[dict] = [
    {
        "name": "get_todays_events",
        "description": "Get all calendar events for today.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_upcoming_events",
        "description": "Get calendar events for the next N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look ahead. Default 7.",
                    "default": 7,
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_event",
        "description": "Create a new calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start": {"type": "string", "description": "Start time in ISO 8601 format."},
                "end": {"type": "string", "description": "End time in ISO 8601 format."},
                "description": {
                    "type": "string",
                    "description": "Event description.",
                    "default": "",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses.",
                },
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "get_recent_emails",
        "description": "Fetch recent emails from Gmail inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return. Default 10.",
                    "default": 10,
                },
                "query": {
                    "type": "string",
                    "description": "Gmail search query to filter results.",
                    "default": "",
                },
            },
            "required": [],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email via Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Email body text."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "remember",
        "description": "Store information in long-term memory for future reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to remember.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall",
        "description": "Search long-term memory for information related to a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memory.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_current_time",
        "description": "Get the current date and time.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
