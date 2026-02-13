# Nella — Tool Catalog

62 tools across 13 categories. Tools marked with **[confirm]** require explicit
approval via inline keyboard before execution.

---

## Utility (4)

### `get_current_datetime`
Get the current date, time, and day of the week in UTC.

### `save_note`
Save a note to the local database for future reference.

### `search_notes`
Search saved notes by title or content.

### `delete_note` **[confirm]**
Delete a saved note by its ID.

---

## Memory (4)

### `remember_this`
Store something in long-term memory. Use when the user says "remember X",
"save this", "don't forget", etc.

### `forget_this`
Forget something from memory. Searches for matching memories and deletes them.
Use when the user says "forget about X" or "delete that memory". Always tell
the user what you found and confirm before calling this tool.

### `recall`
Search long-term memory. Use when the user asks "what do you remember about X",
"do you know my Y", or when you need to check if you have relevant context.

### `save_reference`
Save a link or article reference with a summary. Use when the user shares a URL
and says "save this", "remember this article", or "I'll want to talk about this
later".

---

## Files / Scratch Space (6)

### `scratch_write`
Write text content to a file in the local scratch space. Creates subdirectories
as needed. Use for drafting documents, saving research notes, or staging content
for other tools.

### `scratch_read`
Read a file from the local scratch space. Returns the text content for text
files, or metadata for binary files.

### `scratch_list`
List all files in the local scratch space with size, age, and modification time.

### `scratch_delete`
Delete a file from the local scratch space.

### `scratch_wipe` **[confirm]**
Delete ALL files from the local scratch space. Use when the scratch space has
too much cruft or stale files.

### `scratch_download`
Download a file from a URL into the local scratch space. Supports any file type
(PDF, images, documents, etc.). Use this to fetch files that other tools can
then process.

---

## Gmail (8)

### `search_emails`
Search emails using Gmail query syntax. Returns message metadata (subject, from,
date, snippet). Use `read_email` for full body.

### `read_email`
Read the full content of an email by message ID.

### `read_thread`
Read all messages in an email thread.

### `send_email` **[confirm]**
Compose and send an email.

### `reply_to_email` **[confirm]**
Reply to an existing email, maintaining the thread.

### `archive_email` **[confirm]**
Archive a single email (remove from inbox).

### `archive_emails` **[confirm]**
Archive multiple emails at once (remove from inbox).

### `download_email_attachment`
Download an email attachment to scratch space. Use `read_email` first to get the
attachment_id, then download it here.

---

## Calendar (7)

### `get_todays_schedule`
Get all events for today.

### `list_events`
List upcoming calendar events for the next N days.

### `get_events_by_date_range`
Get calendar events for a specific date range (past or future). Use this to look
at events on a particular day or span of days, including past events that have
already occurred.

### `check_availability`
Check free/busy status for a given date.

### `create_event` **[confirm]**
Create a new calendar event.

### `update_event` **[confirm]**
Update an existing calendar event. Only specified fields are changed.

### `delete_event` **[confirm]**
Delete a calendar event.

---

## Drive (7)

### `search_files`
Search Google Drive for files by name or content. Optionally scope to a specific
folder.

### `list_recent_files`
List recently modified files in Google Drive.

### `list_folder`
List the contents of a Google Drive folder. Returns files and subfolders sorted
by most recently modified. Use `search_files` to find a folder by name first.

### `read_file`
Read the content of a Google Drive file. Supports Google Docs, plain text, CSV,
and JSON. Returns metadata for binary files.

### `download_drive_file`
Download a file from Google Drive to scratch space. Google Docs/Sheets/Slides
are exported as PDF/XLSX.

### `delete_file` **[confirm]**
Move a Google Drive file to trash.

### `upload_to_drive` **[confirm]**
Upload a file from scratch space to Google Drive.

---

## Docs (4)

### `read_document`
Read the full content of a Google Docs document.

### `create_document` **[confirm]**
Create a new Google Docs document.

### `update_document` **[confirm]**
Replace the entire content of a Google Docs document.

### `append_to_document` **[confirm]**
Append content to the end of a Google Docs document.

---

## Contacts / People (6)

### `search_contacts`
Search Google Contacts by name, email, phone, or other fields. Returns contact
summaries.

### `get_contact`
Get full details of a contact by resource name. Also returns any local notes
stored for this contact.

### `create_contact` **[confirm]**
Create a new Google Contact. Optionally attach local notes.

### `update_contact` **[confirm]**
Update an existing Google Contact's fields.

### `update_contact_notes`
Update local notes for a contact. These notes are stored locally (not in Google)
and are visible when getting contact details.

### `search_contact_notes`
Search local contact notes by name or notes content.

---

## Scheduler (3)

### `schedule_task` **[confirm]**
Schedule a task to run at a specific time or on a recurring schedule. Use
`simple_message` for plain reminders or `ai_task` for tasks that need AI
reasoning and tool access (e.g. checking email, summarising).

### `list_scheduled_tasks`
List all active scheduled tasks with their details and next run time.

### `cancel_scheduled_task` **[confirm]**
Cancel a scheduled task by ID or by searching task names/descriptions. If a
search matches multiple tasks, returns them so the user can choose.

---

## Research (2)

### `web_search`
Search the web using Brave Search. Returns titles, URLs, and descriptions for
matching pages. Use `read_webpage` to get full content of interesting results.

### `read_webpage`
Fetch a URL and extract the main text content, page title, and links. Strips
navigation, ads, and boilerplate. Use this to read pages found via `web_search`
or to follow links from previously read pages.

---

## Observability (1)

### `query_logs`
Search Nella's production logs from SolarWinds/Papertrail. Use this to diagnose
issues, check for errors, or inspect recent activity. Read-only.

---

## GitHub (8)

### `github_get_repo`
Get metadata about a GitHub repository: description, language, stars, forks,
open issues, default branch, and timestamps.

### `github_list_directory`
List files and directories at a given path in a GitHub repo. Returns name, type
(file/dir), size, and path for each entry.

### `github_read_file`
Read the contents of a file from a GitHub repository. Returns the file content
as UTF-8 text, truncated at 100K characters for large files.

### `github_search_code`
Search for code across GitHub repositories using GitHub's code search syntax.
Optionally scope to a specific repo. Returns file names, paths, and repos.

### `github_list_commits`
List recent commits in a GitHub repository. Optionally filter by branch/SHA or
file path. Returns commit SHA, message, author, date, and URL.

### `github_get_commit`
Get detailed information about a specific commit: message, author, stats, and
changed files with patches (truncated at 5K chars per file).

### `github_list_issues`
List issues and pull requests in a GitHub repository. Filter by state
(open/closed/all) and labels. Returns number, title, author, labels, and URL.

### `github_get_issue`
Get full details of a GitHub issue or pull request, including body and comments.
For PRs, includes merge status, base/head branches, and diff stats.

---

## LinkedIn (2)

### `linkedin_create_post` **[confirm]**
Create a new LinkedIn post on behalf of the user. Supports PUBLIC or CONNECTIONS
visibility.

### `linkedin_post_comment` **[confirm]**
Post a comment on an existing LinkedIn post. Provide the LinkedIn post URL and
the comment text.
