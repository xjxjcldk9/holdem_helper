# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the bot locally (requires env vars below)
uv run python main.py

# Expose local server for LINE webhook testing
cloudflared tunnel --url http://localhost:8000
# Webhook URL to set in LINE Developers Console: https://<tunnel-id>.trycloudflare.com/callback
```

Required environment variables:
```bash
export LINE_CHANNEL_SECRET=...
export LINE_CHANNEL_ACCESS_TOKEN=...
export DB_PATH=/data/holdem.db   # optional; defaults to holdem.db in cwd
```

### Railway deployment note

Game state is persisted in SQLite. On Railway, add a **Volume** mounted at `/data` and set `DB_PATH=/data/holdem.db` so the database survives redeploys. Without a volume the file lives in the ephemeral container and is lost on restart.

## Architecture

Two files, clean separation:

- **`game.py`** — game logic + SQLite persistence. State is stored in `holdem.db` (path overridable via `DB_PATH`). Each command loads the game from SQLite, mutates it, then saves back. Schema: single `games` table with `session_id`, `buyin_amount`, and `players_json` (JSON blob). Session ID is group_id > room_id > user_id.
- **`main.py`** — Flask webhook server + LINE Messaging API v3 integration. Parses raw text into commands, calls `game.py` functions, sends reply.

### Game state model

`HoldemGame` holds a `buyin_amount` and a `dict[player_id, Player]`. Player IDs are either LINE `user_id` strings (for present users) or `proxy:<lowercase_name>` strings (for absent players registered by someone else). Name lookup via `_resolve_player()` is case-insensitive and creates a proxy entry on first mention.

### Command parsing flow (`main.py`)

1. `parse_command()` strips leading `/` or `.`, lowercases the verb, splits args.
2. `handle_text()` pattern-matches the verb and delegates to `game.py` functions.
3. `buy*N` is parsed out of the verb itself (e.g. `buy*3` → `cmd="buy*3"`, matched with regex); the optional trailing name arg becomes `target_name`.
4. `checkout <name> <chips>` is distinguished from `checkout <chips>` by checking whether `args[0]` is non-numeric.

### Proxy / on-behalf-of feature

Any present user can act for an absent player by appending the target name:
- `buy*N <name>` — buy in N times for `<name>`
- `checkout <name> <chips>` — cash out `<name>`
- `revise <chips>` / `revise <name> <chips>` — correct an already-submitted checkout amount (aliases: `fix`, `correct`)

Replies append `(recorded by X)` when a proxy action is used.

### LINE webhook

`POST /callback` → validates `X-Line-Signature` with `LINE_CHANNEL_SECRET` → dispatches to `@handler.add(MessageEvent)`. HTTP 400 on signature failure (logged with first 6 chars of secret for debugging).
