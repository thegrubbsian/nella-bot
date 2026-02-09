# Nella — Tool Catalog

## Calendar Tools

### `get_todays_events`
Retrieve all events for today from Google Calendar.

### `get_upcoming_events`
Retrieve events for the next N days. Default: 7.

### `create_event`
Create a new calendar event with title, start/end time, description, and optional attendees.

### `update_event`
Modify an existing calendar event by ID.

### `delete_event`
Delete a calendar event by ID.

## Gmail Tools

### `get_recent_emails`
Fetch recent emails from inbox. Supports filtering by sender, subject, label.

### `get_email`
Read a specific email by ID, including full body.

### `draft_email`
Create a draft email with to, subject, and body.

### `send_email`
Send an email (or send an existing draft).

## Task Tools

### `get_task_lists`
List all Google Task lists.

### `get_tasks`
Get tasks from a specific list, optionally filtered by status.

### `create_task`
Add a new task to a list with title, notes, and optional due date.

### `complete_task`
Mark a task as completed.

### `delete_task`
Remove a task from a list.

## Memory Tools

### `remember`
Store a piece of information in long-term memory.

### `recall`
Search memory for information related to a query.

### `forget`
Remove a specific memory entry.

## Utility Tools

### `get_current_time`
Return the current date and time in the user's timezone.

### `set_reminder`
Schedule a message to be sent at a specific time.
