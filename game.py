import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "holdem.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS games (
            session_id   TEXT PRIMARY KEY,
            buyin_amount INTEGER NOT NULL,
            players_json TEXT NOT NULL DEFAULT '{}',
            game_name    TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS user_names (
            user_id TEXT PRIMARY KEY,
            name    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS regular_players (
            name TEXT PRIMARY KEY
        );
        """
    )
    # Migrate older schemas
    for col, definition in [
        ("game_name", "TEXT"),
        ("created_at", "TEXT DEFAULT (datetime('now'))"),
    ]:
        try:
            conn.execute(f"ALTER TABLE games ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def get_stored_name(user_id: str) -> Optional[str]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM user_names WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def cmd_setname(user_id: str, name: str) -> str:
    name = name.strip()
    if not name:
        return "Usage: name <your display name>"
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_names (user_id, name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name
            """,
            (user_id, name),
        )
    return f"✅ Display name set to: {name}"


@dataclass
class Player:
    name: str
    buyins: int = 0
    checkout_chips: Optional[int] = None


class HoldemGame:
    def __init__(self, buyin_amount: int):
        self.buyin_amount = buyin_amount
        self.players: dict[str, Player] = {}

    def total_bought_in(self) -> int:
        return sum(p.buyins * self.buyin_amount for p in self.players.values())

    def total_checked_out(self) -> int:
        return sum(
            p.checkout_chips
            for p in self.players.values()
            if p.checkout_chips is not None
        )

    def all_checked_out(self) -> bool:
        return bool(self.players) and all(
            p.checkout_chips is not None for p in self.players.values()
        )

    def is_balanced(self) -> bool:
        if not self.all_checked_out():
            return False
        return self.total_bought_in() == self.total_checked_out()


def _load_game(session_id: str) -> Optional[HoldemGame]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT buyin_amount, players_json FROM games WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    game = HoldemGame(buyin_amount=row[0])
    raw = json.loads(row[1])
    for pid, data in raw.items():
        game.players[pid] = Player(
            name=data["name"],
            buyins=data["buyins"],
            checkout_chips=data.get("checkout_chips"),
        )
    return game


def _save_game(session_id: str, game: HoldemGame, game_name: Optional[str] = None) -> None:
    players_json = json.dumps(
        {
            pid: {
                "name": p.name,
                "buyins": p.buyins,
                "checkout_chips": p.checkout_chips,
            }
            for pid, p in game.players.items()
        }
    )
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO games (session_id, buyin_amount, players_json, game_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                buyin_amount = excluded.buyin_amount,
                players_json = excluded.players_json,
                game_name    = COALESCE(excluded.game_name, game_name)
            """,
            (session_id, game.buyin_amount, players_json, game_name),
        )


def _resolve_player(game: HoldemGame, target_name: str) -> tuple[str, str]:
    """Find existing player by name (case-insensitive) or create a proxy entry.

    Returns (player_id, resolved_display_name).
    """
    needle = target_name.strip().lower()
    for pid, player in game.players.items():
        if player.name.lower() == needle:
            return pid, player.name
    # Not found — create a proxy player keyed by normalised name
    proxy_id = f"proxy:{needle}"
    if proxy_id not in game.players:
        game.players[proxy_id] = Player(name=target_name.strip())
    return proxy_id, game.players[proxy_id].name


def cmd_start(session_id: str, buyin_amount: int, game_name: str = "") -> str:
    if buyin_amount <= 0:
        return "Buy-in amount must be a positive number."
    game = HoldemGame(buyin_amount)
    _save_game(session_id, game, game_name=game_name or None)
    return (
        f"🃏 Game started!\n"
        f"Buy-in unit: {buyin_amount} chips\n"
        f"\n"
        f"buy / buy*N — buy in\n"
        f"checkout <chips> — cash out\n"
        f"result — final results\n"
        f"help — all commands"
    )


def cmd_buyin(
    session_id: str,
    user_id: str,
    user_name: str,
    times: int = 1,
    target_name: Optional[str] = None,
) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running. Start one with: start <amount>"
    if times <= 0:
        return "Buy-in times must be a positive number."

    if target_name:
        player_id, display_name = _resolve_player(game, target_name)
        actor_note = f" (recorded by {user_name})"
    else:
        player_id, display_name = user_id, user_name
        actor_note = ""
        if player_id not in game.players:
            game.players[player_id] = Player(name=display_name)

    player = game.players[player_id]
    if player.checkout_chips is not None:
        return f"{display_name} has already checked out. Cannot buy in again."

    player.buyins += times
    total_invested = player.buyins * game.buyin_amount
    _save_game(session_id, game)
    return (
        f"✅ {display_name} bought in x{times}\n"
        f"  Total: {player.buyins}x = {total_invested} chips"
        + (f"\n  {actor_note.strip()}" if actor_note else "")
    )


def cmd_checkout(
    session_id: str,
    user_id: str,
    user_name: str,
    chips: int,
    target_name: Optional[str] = None,
) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running. Start one with: start <amount>"
    if chips < 0:
        return "Chip count cannot be negative."

    if target_name:
        player_id, display_name = _resolve_player(game, target_name)
        # _resolve_player may have just created a proxy with 0 buy-ins
        if game.players[player_id].buyins == 0:
            return f"{display_name} has no buy-ins recorded. Use 'buy {display_name}' first."
        actor_note = f" (recorded by {user_name})"
    else:
        player_id, display_name = user_id, user_name
        actor_note = ""
        if player_id not in game.players or game.players[player_id].buyins == 0:
            return f"{display_name} has no buy-ins recorded. Use 'buy' first."

    player = game.players[player_id]
    if player.checkout_chips is not None:
        return f"{display_name} already checked out with {player.checkout_chips} chips."

    player.checkout_chips = chips
    invested = player.buyins * game.buyin_amount
    delta = chips - invested
    sign = "+" if delta >= 0 else ""

    checked_out_count = sum(1 for p in game.players.values() if p.checkout_chips is not None)
    total_players = len(game.players)
    remaining = total_players - checked_out_count

    lines = [
        f"✅ {display_name} checked out",
        f"  Chips: {chips}",
        f"  Invested: {invested}",
        f"  Result: {sign}{delta} chips",
    ]
    if actor_note:
        lines.append(f"  {actor_note.strip()}")

    if remaining > 0:
        lines.append(f"\n⏳ Waiting for {remaining} more player(s)")
    else:
        total_in = game.total_bought_in()
        total_out = game.total_checked_out()
        if total_in == total_out:
            lines.append("\n🎉 All checked out! Type 'result' for final results.")
        else:
            diff = total_out - total_in
            lines.append(
                f"\n⚠️ Totals don't match!\n"
                f"  Bought in: {total_in}\n"
                f"  Cashed out: {total_out}\n"
                f"  Diff: {diff:+}\n"
                f"  Please recheck chip counts."
            )

    _save_game(session_id, game)
    return "\n".join(lines)


def cmd_result(session_id: str) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running."
    if not game.players:
        return "No players in this game."
    if not game.all_checked_out():
        pending = [p.name for p in game.players.values() if p.checkout_chips is None]
        return "Not everyone has checked out yet:\n" + ", ".join(pending)

    total_in = game.total_bought_in()
    total_out = game.total_checked_out()
    if total_in != total_out:
        diff = total_out - total_in
        return (
            f"Totals don't balance! Cannot finalize.\n"
            f"Total bought in: {total_in}  |  Total cashed out: {total_out}  |  Diff: {diff:+}\n"
            f"Please correct chip counts with 'checkout <chips>' again."
        )

    lines = ["🏆 Final Results", f"Buy-in unit: {game.buyin_amount} chips"]
    sorted_players = sorted(
        game.players.values(),
        key=lambda p: (p.checkout_chips or 0) - p.buyins * game.buyin_amount,
        reverse=True,
    )
    for player in sorted_players:
        invested = player.buyins * game.buyin_amount
        delta = (player.checkout_chips or 0) - invested
        sign = "+" if delta >= 0 else ""
        medal = "🥇" if delta == max((p.checkout_chips or 0) - p.buyins * game.buyin_amount for p in sorted_players) else ""
        lines.append(f"\n{medal}{player.name}")
        lines.append(f"  In: {invested}  Out: {player.checkout_chips}")
        lines.append(f"  {sign}{delta} chips")

    lines.append(f"\nTotal pot: {total_in} chips")
    return "\n".join(lines)


def cmd_status(session_id: str) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running."
    if not game.players:
        return f"Game active. Buy-in unit: {game.buyin_amount}. No players yet."

    lines = [f"=== Game Status ===", f"Buy-in unit: {game.buyin_amount} chips"]
    for player in game.players.values():
        invested = player.buyins * game.buyin_amount
        if player.checkout_chips is not None:
            delta = player.checkout_chips - invested
            sign = "+" if delta >= 0 else ""
            status = f"Cashed out: {player.checkout_chips} chips ({sign}{delta})"
        else:
            status = "In game"
        lines.append(f"\n{player.name}")
        lines.append(f"  {player.buyins}x buy-in ({invested} chips)")
        lines.append(f"  {status}")
    lines.append(f"\nTotal pot: {game.total_bought_in()} chips")
    return "\n".join(lines)


def cmd_revise(
    session_id: str,
    user_id: str,
    user_name: str,
    chips: int,
    target_name: Optional[str] = None,
) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running."
    if chips < 0:
        return "Chip count cannot be negative."

    if target_name:
        player_id, display_name = _resolve_player(game, target_name)
        actor_note = f" (revised by {user_name})"
    else:
        player_id, display_name = user_id, user_name
        actor_note = ""

    player = game.players.get(player_id)
    if player is None or player.buyins == 0:
        return f"{display_name} has no buy-ins recorded."
    if player.checkout_chips is None:
        return f"{display_name} hasn't checked out yet. Use 'checkout' instead."

    old = player.checkout_chips
    player.checkout_chips = chips
    invested = player.buyins * game.buyin_amount
    delta = chips - invested
    sign = "+" if delta >= 0 else ""
    _save_game(session_id, game)
    return (
        f"✏️ {display_name} checkout revised\n"
        f"  {old} → {chips} chips\n"
        f"  Invested: {invested}\n"
        f"  Result: {sign}{delta} chips"
        + (f"\n  {actor_note.strip()}" if actor_note else "")
    )


def cmd_remove(session_id: str, target_name: str) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running."

    needle = target_name.strip().lower()
    found_pid = None
    for pid, player in game.players.items():
        if player.name.lower() == needle:
            found_pid = pid
            break

    if found_pid is None:
        return f"No player named '{target_name}' found."

    removed = game.players.pop(found_pid)
    _save_game(session_id, game)
    invested = removed.buyins * game.buyin_amount
    return (
        f"🗑️ {removed.name} removed\n"
        f"  ({removed.buyins}x buy-in, {invested} chips deducted from pot)"
    )


def cmd_set_buyins(session_id: str, target_name: str, count: int) -> str:
    game = _load_game(session_id)
    if game is None:
        return "No game running."
    if count <= 0:
        return "Buy-in count must be at least 1."

    player_id, display_name = _resolve_player(game, target_name)
    player = game.players[player_id]

    if player.checkout_chips is not None:
        return f"{display_name} has already checked out — use 'revise' to adjust chips."

    old = player.buyins
    player.buyins = count
    invested = count * game.buyin_amount
    _save_game(session_id, game)
    return (
        f"✏️ {display_name} buy-ins updated\n"
        f"  {old}× → {count}× = {invested} chips invested"
    )


def cmd_reset(session_id: str) -> str:
    with _get_conn() as conn:
        conn.execute("DELETE FROM games WHERE session_id = ?", (session_id,))
    return "Game reset. Start a new game with: start <amount>"


def list_games() -> list[dict]:
    """Returns all games sorted by newest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT session_id, buyin_amount, players_json, game_name, created_at FROM games ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for session_id, buyin_amount, players_json, game_name, created_at in rows:
        players = json.loads(players_json)
        all_out = bool(players) and all(
            p.get("checkout_chips") is not None for p in players.values()
        )
        total_in = sum(p["buyins"] * buyin_amount for p in players.values())
        total_out = sum(
            p["checkout_chips"] for p in players.values() if p.get("checkout_chips") is not None
        )
        if not players:
            status = "empty"
        elif all_out and total_in == total_out:
            status = "complete"
        elif all_out:
            status = "unbalanced"
        else:
            status = "active"
        result.append(
            {
                "session_id": session_id,
                "buyin_amount": buyin_amount,
                "game_name": game_name or "",
                "created_at": created_at or "",
                "player_count": len(players),
                "total_pot": total_in,
                "status": status,
            }
        )
    return result


def get_game_state(session_id: str) -> Optional[dict]:
    """Returns full game state as a dict for the web API."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT buyin_amount, players_json, game_name, created_at FROM games WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    buyin_amount, players_json, game_name, created_at = row
    players_raw = json.loads(players_json)

    players = []
    for pid, data in players_raw.items():
        invested = data["buyins"] * buyin_amount
        checkout = data.get("checkout_chips")
        delta = (checkout - invested) if checkout is not None else None
        players.append(
            {
                "id": pid,
                "name": data["name"],
                "buyins": data["buyins"],
                "invested": invested,
                "checkout_chips": checkout,
                "delta": delta,
                "status": "out" if checkout is not None else "in",
            }
        )

    players.sort(
        key=lambda p: (
            p["status"] == "out",
            -(p["delta"] or 0) if p["status"] == "out" else 0,
        )
    )

    all_out = bool(players) and all(p["status"] == "out" for p in players)
    total_in = sum(p["invested"] for p in players)
    total_out = sum(p["checkout_chips"] for p in players if p["checkout_chips"] is not None)
    balanced = all_out and total_in == total_out

    return {
        "session_id": session_id,
        "buyin_amount": buyin_amount,
        "game_name": game_name or "",
        "created_at": created_at or "",
        "players": players,
        "total_pot": total_in,
        "all_checked_out": all_out,
        "balanced": balanced,
        "total_out": total_out,
        "status": "complete" if (all_out and balanced) else ("active" if players else "empty"),
    }


def get_regulars() -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT name FROM regular_players ORDER BY name").fetchall()
    return [r[0] for r in rows]


def add_regular(name: str) -> None:
    name = name.strip()
    if name:
        with _get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO regular_players (name) VALUES (?)", (name,))


def remove_regular(name: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM regular_players WHERE name = ?", (name,))
