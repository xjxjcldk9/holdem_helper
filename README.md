# Holdem Helper

A LINE bot for tracking buy-ins and calculating final profit/loss in Texas Hold'em cash games.

## Commands

| Command | Example | Description |
|---|---|---|
| `start <amount>` | `start 100` | Start a game; set the buy-in unit |
| `buy` | `buy` | Buy in once (yourself) |
| `buy*N` | `buy*3` | Buy in N times (yourself) |
| `buy <name>` | `buy Alice` | Buy in once for an absent player |
| `buy*N <name>` | `buy*3 Alice` | Buy in N times for an absent player |
| `checkout <chips>` | `checkout 2500` | Cash out yourself |
| `checkout <name> <chips>` | `checkout Alice 2500` | Cash out an absent player |
| `revise <chips>` | `revise 2500` | Fix your own checkout amount |
| `revise <name> <chips>` | `revise Alice 2500` | Fix another player's checkout amount |
| `result` | `result` | Show final P&L (all players must check out first) |
| `status` | `status` | Show current game state mid-session |
| `reset` | `reset` | Clear the game and start fresh |
| `help` | `help` | Show command reference |

Player names are matched case-insensitively. A note `(recorded by X)` is appended whenever someone acts on behalf of another player.

Commands also accept a leading `/` or `.` prefix (e.g. `/start 100`).

## Example Session

```
Alice: start 100
Bot:   Game started! Buy-in unit: 100 chips.

Alice: buy*3
Bot:   Alice bought in x3 (total: 3x = 300 chips)

Bob: buy
Bot:   Bob bought in x1 (total: 1x = 100 chips)

Bob: buy
Bot:   Bob bought in x1 (total: 2x = 200 chips)

# Charlie is not in the chat — Bob registers him
Bob: buy*2 Charlie
Bot:   Charlie bought in x2 (total: 2x = 200 chips) (recorded by Bob)

Alice: checkout 450
Bot:   Alice checked out: 450 chips (invested 300, +150)
       Waiting for 2 more player(s) to check out.

Bob: checkout 50
Bot:   Bob checked out: 50 chips (invested 200, -150)
       Waiting for 1 more player(s) to check out.

Bob: checkout Charlie 300
Bot:   Charlie checked out: 300 chips (invested 200, +100) (recorded by Bob)
       All players checked out! Type 'result' to see final results.

# Alice realises she mistyped — she can revise before result is called
Alice: revise 400
Bot:   Alice checkout revised: 450 → 400 chips (invested 300, +100)

# Or Bob can fix Charlie's amount on his behalf
Bob: revise Charlie 250
Bot:   Charlie checkout revised: 300 → 250 chips (invested 200, +50) (revised by Bob)

Alice: result
Bot:   === Final Results ===
       Buy-in unit: 100 chips

       Charlie: +100 chips  (in: 200 / out: 300)
       Alice:   +150 chips  (in: 300 / out: 450)
       Bob:     -150 chips  (in: 200 / out: 50)

       Total pot: 700 chips
```

## Local Development

```bash
# Install dependencies
uv sync

# Set LINE credentials
export LINE_CHANNEL_SECRET=your_channel_secret
export LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token

# Run locally
uv run python main.py

# Expose local server via cloudflared tunnel
cloudflared tunnel --url http://localhost:8000
# Set webhook URL in LINE Developers Console: https://<tunnel-id>.trycloudflare.com/callback
```

## Deployment on GCP Cloud Run

Cloud Run is the recommended hosting option — it provides a managed HTTPS endpoint (required by LINE), scales to zero when idle, and has a generous free tier.

### Prerequisites

```bash
# Install and authenticate gcloud CLI
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 1. Add a Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync --no-dev
COPY . .
CMD ["uv", "run", "python", "main.py"]
```

### 2. Store secrets in Secret Manager

```bash
echo -n "your_channel_secret" | \
  gcloud secrets create LINE_CHANNEL_SECRET --data-file=-

echo -n "your_access_token" | \
  gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN --data-file=-
```

### 3. Deploy to Cloud Run

```bash
gcloud run deploy holdem-helper \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-secrets="LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest,LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest"
```

Cloud Run will output a `Service URL` like `https://holdem-helper-xxxx-de.a.run.app`.

### 4. Set LINE webhook

In the [LINE Developers Console](https://developers.line.biz/):
- Messaging API → Webhook URL → `https://holdem-helper-xxxx-de.a.run.app/callback`
- Enable "Use webhook"

## LINE Bot Setup

1. Go to [LINE Developers Console](https://developers.line.biz/) and create a provider + Messaging API channel.
2. Under **Messaging API**:
   - Disable "Auto-reply messages"
   - Disable "Greeting messages"
   - Enable "Use webhook"
3. Copy **Channel secret** and **Channel access token** for your deployment.
4. Add the bot to a LINE group chat — the bot tracks state per group.
