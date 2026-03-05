import logging
import os
import re

from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import game as g

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


def get_session_id(event: MessageEvent) -> str:
    """Return group_id for group chats, user_id for 1-on-1."""
    src = event.source
    if hasattr(src, "group_id") and src.group_id:
        return src.group_id
    if hasattr(src, "room_id") and src.room_id:
        return src.room_id
    return src.user_id


def parse_command(text: str) -> tuple[str, list[str]]:
    """Normalise text into (command, args). Strips leading slash/dot."""
    text = text.strip()
    # allow /start, .start, or just start
    text = re.sub(r"^[/.]", "", text)
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]
    return cmd, args


def handle_text(session_id: str, user_id: str, user_name: str, text: str) -> str:
    cmd, args = parse_command(text)

    # start <amount>
    if cmd == "start":
        if not args or not args[0].isdigit():
            return "Usage: start <buy-in amount>  e.g. start 100"
        return g.cmd_start(session_id, int(args[0]))

    # buy  /  buy*3  /  buy Alice  /  buy*3 Alice
    if cmd.startswith("buy"):
        # buy*3 form
        m = re.match(r"buy\*(\d+)$", cmd)
        if m:
            times = int(m.group(1))
            target = args[0] if args and not args[0].isdigit() else None
        elif args and args[0].isdigit():
            times = int(args[0])
            target = args[1] if len(args) > 1 and not args[1].isdigit() else None
        elif args and not args[0].isdigit():
            # buy Alice  or  buy*3 Alice (already handled above)
            times = 1
            target = args[0]
        else:
            times = 1
            target = None
        return g.cmd_buyin(session_id, user_id, user_name, times, target_name=target)

    # checkout <chips>  /  checkout Alice <chips>
    if cmd in ("checkout", "cashout", "out"):
        # checkout Alice 2500  — name first, then chips
        if len(args) == 2 and not args[0].lstrip("-").isdigit() and args[1].lstrip("-").isdigit():
            return g.cmd_checkout(session_id, user_id, user_name, int(args[1]), target_name=args[0])
        # checkout 2500
        if not args or not args[0].lstrip("-").isdigit():
            return "Usage: checkout <chips>  or  checkout <name> <chips>"
        return g.cmd_checkout(session_id, user_id, user_name, int(args[0]))

    # revise <chips>  /  revise <name> <chips>
    if cmd in ("revise", "fix", "correct"):
        if len(args) == 2 and not args[0].lstrip("-").isdigit() and args[1].lstrip("-").isdigit():
            return g.cmd_revise(session_id, user_id, user_name, int(args[1]), target_name=args[0])
        if not args or not args[0].lstrip("-").isdigit():
            return "Usage: revise <chips>  or  revise <name> <chips>"
        return g.cmd_revise(session_id, user_id, user_name, int(args[0]))

    # result / settle / final
    if cmd in ("result", "settle", "final", "results"):
        return g.cmd_result(session_id)

    # status
    if cmd in ("status", "info"):
        return g.cmd_status(session_id)

    # reset
    if cmd in ("reset", "restart", "newgame"):
        return g.cmd_reset(session_id)

    # help
    if cmd in ("help", "?"):
        return (
            "Hold'em Cash Game Helper\n"
            "------------------------\n"
            "start <amount>        — start game, set buy-in unit\n"
            "buy                   — buy in once (yourself)\n"
            "buy*N                 — buy in N times (yourself)\n"
            "buy <name>            — buy in once for another player\n"
            "buy*N <name>          — buy in N times for another player\n"
            "checkout <chips>      — cash out yourself\n"
            "checkout <name> <chips> — cash out another player\n"
            "revise <chips>        — fix your checkout amount\n"
            "revise <name> <chips> — fix another player's checkout\n"
            "result                — show final P&L\n"
            "status                — show current game state\n"
            "reset                 — clear game and start fresh"
        )

    return ""  # ignore unknown messages silently


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    logger.debug("=== /callback ===")
    logger.debug("Signature header: %r", signature)
    logger.debug("Body: %s", body)

    if not signature:
        logger.error("Missing X-Line-Signature header")
        abort(400)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError as e:
        logger.error("InvalidSignatureError: %s", e)
        logger.error(
            "Check that LINE_CHANNEL_SECRET (%r...) matches the channel secret in LINE Developers Console.",
            CHANNEL_SECRET[:6],
        )
        abort(400)
    except Exception as e:
        logger.exception("Unexpected error handling webhook: %s", e)
        abort(500)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def on_message(event: MessageEvent):
    session_id = get_session_id(event)
    user_id = event.source.user_id
    text = event.message.text

    # Fetch display name
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            profile = line_bot_api.get_profile(user_id)
            user_name = profile.display_name
    except Exception as e:
        logger.warning("Could not fetch profile for %s: %s", user_id, e)
        user_name = user_id  # fallback

    logger.info("session=%s user=%s text=%r", session_id, user_name, text)
    reply = handle_text(session_id, user_id, user_name, text)
    if not reply:
        logger.debug("No reply generated for text=%r — ignoring", text)
        return  # ignore unrecognised messages

    logger.info("Replying: %r", reply)
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)],
                )
            )
    except Exception as e:
        logger.exception("Failed to send reply: %s", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
