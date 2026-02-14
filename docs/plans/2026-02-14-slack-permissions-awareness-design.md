# Slack Permissions Awareness Design

## Summary

Add a single source of truth for Slack permissions by parsing `slack_manifest.yaml`, then surface the derived scopes in two places: the system prompt (short inline note) and the Slack setup section of the README. The implementation must handle both bot and user scopes, remain resilient to missing/invalid manifests, and avoid duplicating static lists.

## Goals

- Keep Slack scopes in sync with `slack_manifest.yaml` without manual updates.
- Inform Claude which Slack permissions are available via a short prompt note.
- Show the same resolved scopes near the Slack setup instructions in `README.md`.
- Support both bot and user scopes if added later.

## Non-Goals

- Add or change any Slack API functionality or tool behavior.
- Modify Slack permissions in the manifest itself.

## Approach

### Data Source

Create a small helper that reads `slack_manifest.yaml` and extracts scopes from `oauth_config.scopes.bot` and `oauth_config.scopes.user`. Merge both lists, de-duplicate, sort, and return a stable list of strings. If the manifest is missing or malformed, return an empty list and log a warning.

### System Prompt

Add a short note to the system prompt in `src/llm/prompt.py` near other integration availability sections:

`Slack scopes available: chat:write, im:write, search:read:users, app_mentions:read`

This should be omitted if no scopes are resolved.

### README

Update the Slack setup section to show the derived scope list. Replace the hard-coded list with a short sentence that references `slack_manifest.yaml` as the source of truth and includes the resolved list for convenience.

### Error Handling

If the manifest cannot be read or parsed, do not fail startup. The prompt note is skipped and the README defaults to a generic instruction (no list) or keeps the prior text if we choose not to remove it. Warnings should be logged for debugging.

## Data Flow

`slack_manifest.yaml` → `slack_manifest.py` helper →
1. `build_system_prompt()` injects “Slack scopes available: …”
2. `README.md` displays resolved scopes in Slack setup instructions

## Testing

- No runtime behavior change besides prompt text; no new tests required.
- Manual check by running the bot or printing the prompt with the manifest present and verifying the note renders.

## Risks and Mitigations

- **Manifest path assumptions**: Use a repo-root-relative path to avoid CWD issues.
- **YAML parsing errors**: Fail silently with a warning; do not block startup.

## Rollout Plan

1. Implement manifest parser helper.
2. Update prompt assembly.
3. Update README Slack setup section.
4. Run lint (optional) and verify prompt output locally.
