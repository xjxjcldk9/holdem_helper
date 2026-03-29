import uuid

from flask import Flask, jsonify, redirect, render_template, request, url_for

import game as g

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    games = g.list_games()
    leaderboard = g.get_monthly_leaderboard()
    return render_template("index.html", games=games, leaderboard=leaderboard)


@app.get("/game/<session_id>")
def game_view(session_id):
    state = g.get_game_state(session_id)
    if state is None:
        return redirect(url_for("index"))
    return render_template("game.html", state=state)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.post("/api/games")
def create_game():
    data = request.json or {}
    try:
        buyin_amount = int(data.get("buyin_amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid buy-in amount"}), 400
    if buyin_amount <= 0:
        return jsonify({"error": "Buy-in amount must be positive"}), 400
    game_name = str(data.get("game_name", "")).strip()
    session_id = str(uuid.uuid4())
    g.cmd_start(session_id, buyin_amount, game_name=game_name)
    return jsonify(
        {"session_id": session_id, "redirect": url_for("game_view", session_id=session_id)}
    )


@app.post("/api/games/<session_id>/buy")
def buy_in(session_id):
    data = request.json or {}
    player_name = str(data.get("player_name", "")).strip()
    if not player_name:
        return jsonify({"error": "Player name required"}), 400
    try:
        times = max(1, int(data.get("times", 1)))
    except (ValueError, TypeError):
        times = 1
    player_id = f"web:{player_name.lower()}"
    msg = g.cmd_buyin(session_id, player_id, player_name, times)
    g.add_regular(player_name)  # auto-register every player typed in
    state = g.get_game_state(session_id)
    return jsonify({"message": msg, "state": state})


@app.post("/api/games/<session_id>/checkout")
def checkout(session_id):
    data = request.json or {}
    player_name = str(data.get("player_name", "")).strip()
    if not player_name:
        return jsonify({"error": "Player name required"}), 400
    try:
        chips = int(data.get("chips", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid chip count"}), 400
    if chips < 0:
        return jsonify({"error": "Chip count cannot be negative"}), 400

    state = g.get_game_state(session_id)
    if state is None:
        return jsonify({"error": "Game not found"}), 404
    player = next((p for p in state["players"] if p["name"].lower() == player_name.lower()), None)
    if player is None:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404

    msg = g.cmd_checkout(session_id, player["id"], player["name"], chips)
    state = g.get_game_state(session_id)
    return jsonify({"message": msg, "state": state})


@app.post("/api/games/<session_id>/revise")
def revise(session_id):
    data = request.json or {}
    player_name = str(data.get("player_name", "")).strip()
    if not player_name:
        return jsonify({"error": "Player name required"}), 400
    try:
        chips = int(data.get("chips", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid chip count"}), 400
    if chips < 0:
        return jsonify({"error": "Chip count cannot be negative"}), 400

    state = g.get_game_state(session_id)
    if state is None:
        return jsonify({"error": "Game not found"}), 404
    player = next((p for p in state["players"] if p["name"].lower() == player_name.lower()), None)
    if player is None:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404

    msg = g.cmd_revise(session_id, player["id"], player["name"], chips)
    state = g.get_game_state(session_id)
    return jsonify({"message": msg, "state": state})


@app.post("/api/games/<session_id>/set-buyins")
def set_buyins(session_id):
    data = request.json or {}
    player_name = str(data.get("player_name", "")).strip()
    if not player_name:
        return jsonify({"error": "Player name required"}), 400
    try:
        count = int(data.get("count", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid count"}), 400
    if count <= 0:
        return jsonify({"error": "Buy-in count must be at least 1"}), 400
    msg = g.cmd_set_buyins(session_id, player_name, count)
    state = g.get_game_state(session_id)
    return jsonify({"message": msg, "state": state})


@app.post("/api/games/<session_id>/remove")
def remove_player(session_id):
    data = request.json or {}
    player_name = str(data.get("player_name", "")).strip()
    if not player_name:
        return jsonify({"error": "Player name required"}), 400
    msg = g.cmd_remove(session_id, player_name)
    state = g.get_game_state(session_id)
    return jsonify({"message": msg, "state": state})


@app.delete("/api/games/<session_id>")
def delete_game(session_id):
    g.cmd_reset(session_id)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Regulars
# ---------------------------------------------------------------------------


@app.get("/api/regulars")
def list_regulars():
    return jsonify(g.get_regulars())


@app.post("/api/regulars")
def add_regular():
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    g.add_regular(name)
    return jsonify(g.get_regulars())


@app.put("/api/regulars/<name>")
def rename_regular(name):
    data = request.json or {}
    new_name = str(data.get("name", "")).strip()
    if not new_name:
        return jsonify({"error": "Name required"}), 400
    g.rename_regular(name, new_name)
    return jsonify(g.get_regulars())


@app.delete("/api/regulars/<name>")
def remove_regular(name):
    g.remove_regular(name)
    return jsonify(g.get_regulars())


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
