# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the web app locally
uv run python main.py
# Open http://localhost:8000

# Production (gunicorn)
uv run gunicorn main:app --bind 0.0.0.0:$PORT
```

Optional environment variable:
```bash
export DB_PATH=/data/holdem.db   # defaults to holdem.db in cwd
export PORT=8000
```

### Railway deployment note

Game state is persisted in SQLite. On Railway, add a **Volume** mounted at `/data` and set `DB_PATH=/data/holdem.db` so the database survives redeploys.

## Architecture

Three layers:

- **`game.py`** — game logic + SQLite persistence. Schema: `games` table with `session_id` (UUID), `buyin_amount`, `players_json` (JSON blob), `game_name`, `created_at`; `regular_players` table for saved players. Key public functions: `list_games()`, `get_game_state()`, `get_monthly_leaderboard()`, `get_regulars()`, `add_regular()`, `remove_regular()`.
- **`main.py`** — Flask web app. Serves two HTML pages (`/` dashboard, `/game/<id>` game view) and a JSON API (`/api/games`, `/api/games/<id>/buy|checkout|revise|remove`, `DELETE /api/games/<id>`, `/api/regulars`). Every buy-in automatically calls `add_regular()` to save the player name.
- **`templates/`** — Jinja2 templates with Tailwind CSS (CDN). `base.html` → `index.html` (dashboard with monthly leaderboard + game list) and `game.html` (game view).

### Game state model

`HoldemGame` holds a `buyin_amount` and a `dict[player_id, Player]`. In the webapp, player IDs are `web:<lowercase_name>`. Name lookup via `_resolve_player()` is case-insensitive.

### Session IDs

Web-created games use UUID v4 session IDs generated at game creation.

### Web API

All `/api/…` POST endpoints accept JSON and return `{ message, state }` where `state` is the full serialised game state from `get_game_state()`. On error they return `{ error }` with an appropriate HTTP status code.
