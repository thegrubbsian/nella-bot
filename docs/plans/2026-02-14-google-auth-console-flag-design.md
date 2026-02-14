# Google Auth Console Flag Design

## Summary
Add an opt-in `--console` flag to `scripts/google_auth.py` so the OAuth flow can run without opening a local browser. Default behavior stays the same, using the existing local-server browser flow unless the flag is provided.

## Architecture
Introduce a CLI flag that selects between the existing `InstalledAppFlow.run_local_server()` and the console-based `InstalledAppFlow.run_console()` methods. No other structural changes are needed.

## Components
- Argument parsing: add `--console` boolean flag.
- OAuth flow selection: call `run_console()` when `--console` is set, otherwise call `run_local_server(port=0)`.
- Token persistence: keep the current overwrite prompt and token write logic.

## Data Flow
CLI args -> account and credentials resolution -> optional overwrite prompt -> OAuth flow (console or browser) -> token JSON saved to `auth_tokens/google_<account>_auth_token.json`.

## Error Handling
No new error cases beyond existing missing credentials or overwrite prompts. OAuth exceptions propagate as they do today.

## Testing
Manual validation:
- Run `uv run python scripts/google_auth.py --account default --console` and confirm the console URL prompt appears.
- Run `uv run python scripts/google_auth.py --account default` and confirm browser-based flow remains unchanged.
