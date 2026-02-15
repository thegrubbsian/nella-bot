# Nella Functional Test Prompt

Copy everything below the line and send it to Nella in Telegram after major code changes.
Tools that require confirmation will pop up Approve/Deny buttons — approve them all
unless noted otherwise. The prompt is designed to clean up after itself.

If a tool is disabled (missing API key or token), Nella will report that and move on.
That's expected — a failure to call the tool is different from the tool not existing.

---

I need you to run a full functional test of all your tools. Work through each scenario below one at a time. For each one, call the tool, report whether it succeeded or failed, and then run any cleanup step listed. Give me a summary at the end with a pass/fail for each tool.

Important rules:
- Do NOT skip any scenario. If a tool fails, report the error and move on.
- For tools that require confirmation, I will approve them — wait for my approval before continuing.
- If a tool is disabled (missing API key, no token file, etc.), report "DISABLED" and move on.
- After each category, give me a quick status line before continuing.

Here are the scenarios:

## 1. Utility

1.1. **get_current_datetime** — Get the current date and time.

1.2. **save_note** — Save a note with title "FUNCTIONAL TEST" and content "This is a test note created by the functional test suite. Safe to delete."

1.3. **search_notes** — Search notes for "FUNCTIONAL TEST". Confirm the note from 1.2 appears.

1.4. **delete_note** — Delete the note you created in 1.2 using its ID. (Requires confirmation.)

## 2. Memory

2.1. **remember_this** — Remember: "Nella functional test marker — safe to forget."

2.2. **recall** — Search memory for "functional test marker". Confirm it appears. (Note: Mem0 indexing can take a moment — if nothing comes back, wait a few seconds and retry once before marking as FAIL.)

2.3. **forget_this** — Forget memories matching "functional test marker".

2.4. **save_reference** — Save a reference with url "https://example.com/test", title "Functional Test Reference", summary "Test reference — safe to forget."

2.5. **forget_this** — Forget memories matching "Functional Test Reference" to clean up 2.4.

## 3. Files (Scratch Space)

3.1. **scratch_write** — Write a file called "functional_test.txt" with content "Hello from the functional test suite."

3.2. **scratch_read** — Read "functional_test.txt" and confirm the content matches.

3.3. **scratch_list** — List all files in scratch space. Confirm "functional_test.txt" appears.

3.4. **scratch_download** — Download https://httpbin.org/robots.txt to scratch space.

3.5. **scratch_download** — Download a small public PDF: https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf and save it as "test.pdf".

3.6. **scratch_read** — Read "test.pdf". Confirm that extracted text content is returned (not binary metadata). The response should contain a `content` field with readable text and an `extracted_from` field set to "application/pdf".

3.7. **scratch_download** — Download a small public PNG image: https://www.w3.org/WAI/WCAG21/Techniques/pdf/img/table-word.jpg and save it as "test_image.jpg".

3.8. **analyze_image** — Analyze "test_image.jpg" with the prompt "Describe what you see in this image." Confirm it returns an analysis.

3.9. **scratch_delete** — Delete "test_image.jpg".

3.10. **scratch_delete** — Delete "functional_test.txt".

3.11. **scratch_delete** — Delete the robots.txt file downloaded in 3.4.

3.12. **scratch_delete** — Delete "test.pdf" from 3.5.

Skip scratch_wipe — we don't want to nuke any real working files.

## 4. Gmail

4.1. **search_emails** — Search for "subject:test" with max_results=2.

4.2. **read_email** — If 4.1 returned results, read the first email. If no results, search for any recent email instead and read that.

4.3. **read_thread** — Read the thread of the email from 4.2.

4.4. **send_email** — Send an email TO ME (the bot owner) with subject "Nella Functional Test" and body "This is an automated functional test email. Safe to delete." (Requires confirmation.)

4.5. **search_emails** — Search for "subject:Nella Functional Test" to find the email you just sent.

4.6. **archive_email** — Archive the email from 4.5. (Requires confirmation.)

4.7. **trash_email** — Send the archived email to the trash / delete it. (Requires confirmation.)

4.8. **mark_as_unread** — Search for another recent email and mark it as unread.

4.9. **mark_as_read** — Mark that same email as read again.

4.10. **add_label** — Add the label "IMPORTANT" to that email.

4.11. **remove_label** — Remove the "IMPORTANT" label from that email.

4.12. **star_email** — Star that email.

4.13. **unstar_email** — Unstar that email.

4.14. **list_labels** — List all Gmail labels.

4.15. **create_label** — Create a label named "Nella Test Label". (Requires confirmation.)

4.16. **delete_label** — Delete the "Nella Test Label" you just created. (Requires confirmation.)

Skip reply_to_email, archive_emails, and download_email_attachment — they're covered by the patterns above.

## 5. Calendar

5.1. **get_todays_schedule** — Get today's schedule.

5.2. **list_events** — List events for the next 3 days.

5.3. **check_availability** — Check my availability for today.

5.4. **get_events_by_date_range** — Get events for tomorrow only.

5.5. **create_event** — Create an event titled "Nella Functional Test" for tomorrow at 11:00 PM to 11:30 PM. Description: "Auto-created by functional test. Will be deleted." (Requires confirmation.)

5.6. **delete_event** — Delete the event you created in 5.5. (Requires confirmation.)

Skip update_event — the create/delete cycle covers the write path.

## 6. Drive

6.1. **list_recent_files** — List 3 recently modified files.

6.2. **search_files** — Search for any file with query "test".

6.3. **read_file** — If 6.1 or 6.2 returned a Google Doc or text file, read it. Otherwise pick any Doc you can find.

Skip list_folder, delete_file, download_drive_file, and upload_to_drive — they need specific folder IDs and we don't want to create Drive clutter. The read path is what matters most.

## 7. Docs

7.1. **create_document** — Create a Google Doc titled "Nella Functional Test Doc" with content "This document was created by the functional test suite. Safe to delete." (Requires confirmation.)

7.2. **read_document** — Read the document you just created. Confirm the content.

7.3. **append_to_document** — Append "\n\nAppended by functional test." to the document. (Requires confirmation.)

7.4. **read_document** — Read the document again. Confirm the appended text is there.

7.5. **delete_file** — Delete the document via Drive (move to trash) using the document ID from 7.1. (Requires confirmation.)

Skip update_document — append + read covers the write path.

## 8. Contacts / People

8.1. **search_contacts** — Search for any contact (use query "a" to get results).

8.2. **get_contact** — Get full details of the first contact from 8.1.

8.3. **update_contact_notes** — Set local notes for that contact to "Functional test note — will be cleared." (No confirmation needed.)

8.4. **search_contact_notes** — Search for "functional test note". Confirm it appears.

8.5. **update_contact_notes** — Clear the notes by setting them to "" for the same contact.

Skip create_contact and update_contact — we don't want to create or modify real contacts.

## 9. Scheduler

9.1. **list_scheduled_tasks** — List all active scheduled tasks.

9.2. **schedule_task** — Schedule a one-off simple_message task named "Functional Test Task" to run 24 hours from now with message "This is a test task." (Requires confirmation.)

9.3. **list_scheduled_tasks** — List tasks again. Confirm the new task appears.

9.4. **update_scheduled_task** — Update the task from 9.2 to use model "haiku". Confirm the response shows the model was updated.

9.5. **cancel_scheduled_task** — Cancel the task from 9.2. (Requires confirmation.)

## 10. Web Research

10.1. **web_search** — Search for "Anthropic Claude" with count=3.

10.2. **read_webpage** — Read the content of https://example.com (a safe, stable test URL).

## 11. Observability

11.1. **query_logs** — Query recent logs from the last 5 minutes with limit=5.

## 12. GitHub

12.1. **github_get_repo** — Get repo info for your own source repo (if NELLA_SOURCE_REPO is set). If not set, use "anthropics/anthropic-sdk-python".

12.2. **github_list_directory** — List the root directory of that repo.

12.3. **github_read_file** — Read the README.md from that repo.

12.4. **github_search_code** — Search for "async def" in that repo with max_results=3.

12.5. **github_list_commits** — List the 3 most recent commits.

12.6. **github_get_commit** — Get details of the most recent commit from 12.5.

12.7. **github_list_issues** — List open issues (max_results=3).

12.8. **github_get_issue** — If 12.7 returned results, get details of the first issue. If no issues exist, report that and move on.

## 13. Notion

13.1. **notion_list_databases** — List all databases shared with the Notion integration.

13.2. **notion_get_database** — If 13.1 returned results, get the schema of the first database.

13.3. **notion_search** — Search for "test" across all pages and databases.

13.4. **notion_create_page** — Create a page in the first database from 13.1 with title "Nella Functional Test" and any required properties set to reasonable defaults. Add body content: "Created by functional test suite. Safe to delete." (Requires confirmation.)

13.5. **notion_get_page** — Get the page you just created in 13.4 and confirm the properties.

13.6. **notion_read_page_content** — Read the body content of the page from 13.4. Confirm the text matches.

13.7. **notion_query_database** — Query the database from 13.1 for the page you just created (filter by title if possible).

13.8. **notion_append_content** — Append "Appended by functional test." to the page from 13.4. (Requires confirmation.)

13.9. **notion_read_page_content** — Read the page again and confirm the appended text is there.

13.10. **notion_update_page** — Update a property on the page from 13.4 (e.g. change status or add a tag). (Requires confirmation.)

13.11. **notion_archive_page** — Archive the page from 13.4. (Requires confirmation.)

## 14. Browser

14.1. **browse_web** — Browse https://example.com with task "Read the page title and main content." (Requires confirmation.) This is a safe, stable URL that should return quickly.

## 15. Image Generation

15.1. **generate_image** — Generate an image with prompt "A simple red circle on a white background" using quality="low" (to minimize cost). Verify the image appears in the chat and a file was saved to scratch space.

15.2. **scratch_delete** — Delete the generated image file from 15.1.

## 16. LinkedIn

Skip linkedin_create_post and linkedin_post_comment — these post publicly and can't be undone. Just confirm whether the LinkedIn integration is enabled or disabled, and report that.

Note: If Notion is disabled (NOTION_API_KEY not set), report scenarios 13.1-13.11 as "DISABLED" and move on.
Note: If browser automation is disabled (BROWSER_ENABLED=false), report scenario 14.1 as "DISABLED" and move on.
Note: If OpenAI image generation is disabled (OPENAI_API_KEY not set), report scenarios 15.1-15.2 as "DISABLED" and move on.

---

After all scenarios, give me a summary table like:

| # | Tool | Status |
|---|------|--------|
| 1.1 | get_current_datetime | PASS |
| 1.2 | save_note | PASS |
| ... | ... | ... |

Use PASS, FAIL (with brief reason), or DISABLED.

Tell me the total: X passed, Y failed, Z disabled out of N scenarios.
