from dataclasses import dataclass, field
from typing import Optional


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


# In-memory store: group/user_id -> HoldemGame
# For group chats, key is group_id; for 1-on-1, key is user_id
games: dict[str, HoldemGame] = {}


def _get_game(session_id: str) -> Optional[HoldemGame]:
    return games.get(session_id)


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


def cmd_start(session_id: str, buyin_amount: int) -> str:
    if buyin_amount <= 0:
        return "Buy-in amount must be a positive number."
    games[session_id] = HoldemGame(buyin_amount)
    return f"Game started! Buy-in unit: {buyin_amount} chips.\nCommands:\n  buy / buy*N — buy in (N times)\n  checkout <chips> — cash out\n  result — show final results\n  reset — restart game"


def cmd_buyin(
    session_id: str,
    user_id: str,
    user_name: str,
    times: int = 1,
    target_name: Optional[str] = None,
) -> str:
    game = _get_game(session_id)
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
    return (
        f"{display_name} bought in x{times} "
        f"(total: {player.buyins}x = {total_invested} chips){actor_note}"
    )


def cmd_checkout(
    session_id: str,
    user_id: str,
    user_name: str,
    chips: int,
    target_name: Optional[str] = None,
) -> str:
    game = _get_game(session_id)
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

    msg = f"{display_name} checked out: {chips} chips (invested {invested}, {sign}{delta}){actor_note}"
    if remaining > 0:
        msg += f"\nWaiting for {remaining} more player(s) to check out."
    else:
        # All checked out — auto-validate
        total_in = game.total_bought_in()
        total_out = game.total_checked_out()
        if total_in == total_out:
            msg += "\nAll players checked out! Type 'result' to see final results."
        else:
            diff = total_out - total_in
            msg += (
                f"\nAll checked out, but totals don't match!\n"
                f"Total bought in: {total_in}  |  Total cashed out: {total_out}  |  Diff: {diff:+}\n"
                f"Please recheck chip counts."
            )
    return msg


def cmd_result(session_id: str) -> str:
    game = _get_game(session_id)
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

    lines = ["=== Final Results ===", f"Buy-in unit: {game.buyin_amount} chips\n"]
    sorted_players = sorted(
        game.players.values(),
        key=lambda p: (p.checkout_chips or 0) - p.buyins * game.buyin_amount,
        reverse=True,
    )
    for player in sorted_players:
        invested = player.buyins * game.buyin_amount
        delta = (player.checkout_chips or 0) - invested
        sign = "+" if delta >= 0 else ""
        bar = "#" * abs(delta // game.buyin_amount) if game.buyin_amount > 0 else ""
        lines.append(
            f"{player.name}: {sign}{delta} chips  (in: {invested} / out: {player.checkout_chips})"
        )

    lines.append(f"\nTotal pot: {total_in} chips")
    return "\n".join(lines)


def cmd_status(session_id: str) -> str:
    game = _get_game(session_id)
    if game is None:
        return "No game running."
    if not game.players:
        return f"Game active. Buy-in unit: {game.buyin_amount}. No players yet."

    lines = [f"=== Game Status === (buy-in: {game.buyin_amount})"]
    for player in game.players.values():
        invested = player.buyins * game.buyin_amount
        status = f"checked out: {player.checkout_chips}" if player.checkout_chips is not None else "in game"
        lines.append(f"  {player.name}: {player.buyins}x buy-in ({invested} chips) — {status}")
    lines.append(f"Total pot: {game.total_bought_in()} chips")
    return "\n".join(lines)


def cmd_revise(
    session_id: str,
    user_id: str,
    user_name: str,
    chips: int,
    target_name: Optional[str] = None,
) -> str:
    game = _get_game(session_id)
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
    return (
        f"{display_name} checkout revised: {old} → {chips} chips "
        f"(invested {invested}, {sign}{delta}){actor_note}"
    )


def cmd_reset(session_id: str) -> str:
    if session_id in games:
        del games[session_id]
    return "Game reset. Start a new game with: start <amount>"
