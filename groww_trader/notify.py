"""Optional Telegram alerts and remote pause, using YOUR OWN bot.

  TELEGRAM_BOT_TOKEN   from @BotFather (keep it in ~/.groww_env)
  TELEGRAM_CHAT_ID     your chat with the bot (`gtrade.py telegram setup` finds it)

Sends signals, fills, exits, blocks, data errors and a daily summary.
Accepts commands only from TELEGRAM_CHAT_ID:
  /status  /report  /pause  /resume  /help

/pause stops NEW positions (new triggers are blocked, unfilled ideas are
cancelled); open positions are still managed to their stop, target or
flat-by. The pause is a file, trader/PAUSED, so `gtrade.py pause` and
`gtrade.py resume` work too, with or without Telegram.

Everything here is best-effort: 5-second timeouts, errors become one-line
warnings with the token scrubbed, nothing raises into the trading loop.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .config import home, read_json, write_json

API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 5
PAUSE_FILE = "PAUSED"
ALERT_KINDS = ("SIGNAL", "FILLED", "CLOSED", "BLOCKED", "MISSED", "CANCEL", "DATAERR")


# ------------------------------------------------------------------ pause

def is_paused() -> bool:
    return (home() / PAUSE_FILE).exists()


def set_paused(on: bool, why: str = "") -> None:
    p = home() / PAUSE_FILE
    if on:
        p.write_text(why or "paused\n", encoding="utf-8")
    elif p.exists():
        p.unlink()


# ------------------------------------------------------------------ telegram

def _scrub(msg: str, token: str) -> str:
    s = str(msg)
    if token:
        s = s.replace(token, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", s)


class Telegram:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None,
                 log: Callable[[str], Any] = print, http=None):
        self.token = (token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
        self.log = log
        self._http = http or self._urllib
        self._warned = False

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _urllib(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - network
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(API.format(token=self.token, method=method), data=data)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode())

    def call(self, method: str, **params) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None
        try:
            res = self._http(method, params)
            if not res.get("ok"):
                raise RuntimeError(res.get("description", "Telegram error"))
            self._warned = False
            return res
        except Exception as e:
            if not self._warned:  # one warning per outage, not one per message
                self.log(f"warning: Telegram {method} failed: {_scrub(e, self.token)[:200]}")
                self._warned = True
            return None

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        return self.call("sendMessage", chat_id=self.chat_id, text=text[:4000],
                         disable_web_page_preview="true") is not None

    def send_events(self, events: List[str], when) -> bool:
        lines = [e for e in events if e.split(" ", 1)[0] in ALERT_KINDS]
        if not lines:
            return True
        return self.send(f"[{when:%H:%M}] paper\n" + "\n".join(lines))

    # -------------------------------------------------------------- commands

    def poll(self) -> List[str]:
        """Return command words (e.g. '/pause') sent by the owner since the
        last poll. Messages from any other chat are ignored."""
        if not self.enabled:
            return []
        state = read_json("telegram_state.json", {}) or {}
        res = self.call("getUpdates", offset=state.get("offset", 0), timeout=0)
        if not res:
            return []
        cmds, last = [], state.get("offset", 0) - 1
        for u in res.get("result", []):
            last = max(last, u.get("update_id", last))
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != self.chat_id:
                continue
            word = (msg.get("text") or "").strip().split(" ")[0].split("@")[0].lower()
            if word.startswith("/"):
                cmds.append(word)
        write_json("telegram_state.json", {"offset": last + 1})
        return cmds

    def chats_seen(self) -> List[Dict[str, Any]]:
        res = self.call("getUpdates", timeout=0) or {}
        seen = {}
        for u in res.get("result", []):
            chat = (u.get("message") or {}).get("chat") or {}
            if "id" in chat:
                seen[chat["id"]] = {"chat_id": chat["id"], "name": chat.get("username") or chat.get("first_name"),
                                    "type": chat.get("type")}
        return list(seen.values())


HELP = ("Commands:\n/status  what the bot is doing today\n/report  paper results so far\n"
        "/pause   no new positions (open ones are still managed)\n/resume  allow new positions again\n/help")


def handle(cmds: List[str], status_fn: Callable[[], str], report_fn: Callable[[], str]) -> List[str]:
    """Apply commands and return reply texts."""
    replies = []
    for c in cmds:
        if c == "/pause":
            set_paused(True, "paused from Telegram\n")
            replies.append("Paused. No new positions; open ones are still managed to stop/target/flat-by. "
                           "/resume to continue.")
        elif c == "/resume":
            set_paused(False)
            replies.append("Resumed. New positions allowed from the next bar.")
        elif c == "/status":
            replies.append(status_fn() + ("\nPAUSED" if is_paused() else ""))
        elif c == "/report":
            replies.append(report_fn())
        elif c in ("/help", "/start"):
            replies.append(HELP)
        else:
            replies.append(f"Unknown command {c}.\n{HELP}")
    return replies
