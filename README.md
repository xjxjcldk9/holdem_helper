# Holdem Helper

A web app for tracking buy-ins and calculating final profit/loss in Texas Hold'em cash games.

## Features

- Create and manage multiple game sessions
- Track player buy-ins, re-buys, and chip counts
- Auto-calculates P&L when everyone checks out
- Regular players list for quick one-click buy-in
- New players are automatically saved as regulars
- Monthly leaderboard on the dashboard
- Persistent storage via SQLite

## Running Locally

```bash
# Install dependencies
uv sync

# Run the web app
uv run python main.py
# Open http://localhost:8000
```

Optional environment variables:
```bash
export PORT=8000
export DB_PATH=/data/holdem.db   # defaults to holdem.db in current directory
```

## Deployment on Railway

1. Push the repo to GitHub and connect it to Railway.
2. Add a **Volume** mounted at `/data`.
3. Set environment variables:
   - `DB_PATH=/data/holdem.db` — keeps the database on the persistent volume
   - `PORT=8000` (Railway sets this automatically)
4. Railway will run `gunicorn main:app --bind 0.0.0.0:$PORT` via the Procfile or start command.

## Architecture

| Layer | File | Responsibility |
|---|---|---|
| Game logic | `game.py` | HoldemGame model, SQLite persistence, all game commands |
| Web app | `main.py` | Flask routes, JSON API |
| UI | `templates/` | Jinja2 + Tailwind CSS |

### Database schema

```sql
games           -- session_id, buyin_amount, players_json, game_name, created_at
regular_players -- name
user_names      -- user_id, name  (legacy, unused by web app)
```

### API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Dashboard with game list and monthly leaderboard |
| GET | `/game/<id>` | Game view |
| POST | `/api/games` | Create a game |
| POST | `/api/games/<id>/buy` | Buy in a player |
| POST | `/api/games/<id>/checkout` | Check out a player |
| POST | `/api/games/<id>/revise` | Revise checkout chips |
| POST | `/api/games/<id>/set-buyins` | Edit buy-in count |
| POST | `/api/games/<id>/remove` | Remove a player |
| DELETE | `/api/games/<id>` | Delete a game |
| GET | `/api/regulars` | List regular players |
| POST | `/api/regulars` | Add a regular |
| DELETE | `/api/regulars/<name>` | Remove a regular |
