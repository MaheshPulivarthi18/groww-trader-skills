"""Keeping the unattended paper run healthy.

- One copy at a time: `paper run` and `paper once` take an exclusive lock
  (trader/paper.lock). A second copy exits quietly.
- Restart-safe: run_state.json records today's start, last completed step
  and whether the day finished. Cron can start `paper run` every few
  minutes: if a copy is running it's a no-op, if the day is done it's a
  no-op, otherwise it (re)starts and says so.
- Stuck detection: when a copy is running but hasn't finished a step for
  `stale_min` minutes during market hours, the would-be second copy sends
  one alert per stuck episode.
- Logs: one file per day in trader/logs/, kept for `keep_days`.
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .config import home, read_json, write_json
from .market import IST, MARKET_CLOSE, MARKET_OPEN

STATE = "run_state.json"


# ------------------------------------------------------------------ lock

class Lock:
    """Exclusive, non-blocking lock released automatically when the
    process exits (even on a crash)."""

    def __init__(self, name: str = "paper"):
        self.path = home() / f"{name}.lock"
        self._fh = None

    def acquire(self) -> bool:
        import fcntl
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


# ------------------------------------------------------------------ state

def state_for(day: str) -> dict:
    s = read_json(STATE, {}) or {}
    return s if s.get("day") == day else {"day": day}


def save_state(s: dict) -> None:
    write_json(STATE, s)


def mark_start(now: datetime) -> dict:
    """Record a start. Returns the state, with 'restart' True if an earlier
    run today stopped before finishing."""
    s = state_for(str(now.date()))
    s["restart"] = bool(s.get("started")) and not s.get("done")
    if s["restart"]:
        s["restarts"] = s.get("restarts", 0) + 1
    s.setdefault("started", now.isoformat())
    s["this_start"] = now.isoformat()
    save_state(s)
    return s


def mark_step(now: datetime) -> None:
    s = state_for(str(now.date()))
    s["last_step"] = now.isoformat()
    save_state(s)


def mark_done(now: datetime) -> None:
    s = state_for(str(now.date()))
    s["done"] = True
    s["finished"] = now.isoformat()
    save_state(s)


def is_done(now: datetime) -> bool:
    return bool(state_for(str(now.date())).get("done"))


def stale_since(now: datetime, stale_min: int = 15) -> Optional[datetime]:
    """If we're in market hours and the last completed step (or the start,
    if no step yet) is older than stale_min, return that time."""
    open_dt = datetime.combine(now.date(), MARKET_OPEN, tzinfo=IST)
    close_dt = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=IST)
    if not (open_dt + timedelta(minutes=stale_min) <= now <= close_dt):
        return None
    s = state_for(str(now.date()))
    ref = s.get("last_step") or s.get("this_start")
    if not ref:
        return open_dt  # nothing ran today at all
    t = datetime.fromisoformat(ref)
    t = max(t, open_dt)
    return t if now - t > timedelta(minutes=stale_min) else None


def alert_if_stuck(now: datetime, send: Callable[[str], object], stale_min: int = 15) -> Optional[str]:
    """Called by a second copy that found the lock taken. Alerts once per
    stuck episode."""
    since = stale_since(now, stale_min)
    if not since:
        return None
    marker = read_json("stale_alert.json", {}) or {}
    if marker.get("since") == since.isoformat():
        return None
    msg = (f"Paper bot is running but hasn't completed a step since {since:%H:%M} IST. "
           "It may be stuck (network or Groww). Check ~/trading/trader/logs or restart it.")
    send(msg)
    write_json("stale_alert.json", {"since": since.isoformat(), "alerted_at": now.isoformat()})
    return msg


# ------------------------------------------------------------------ logs

class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def daily_log(now: datetime, keep_days: int = 30, interactive: Optional[bool] = None) -> Path:
    """Send stdout to trader/logs/paper-YYYY-MM-DD.log (and the terminal
    too when run interactively). Deletes logs older than keep_days."""
    d = home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    cutoff = (now - timedelta(days=keep_days)).date().isoformat()
    for f in d.glob("paper-*.log"):
        if f.stem[6:] < cutoff:
            try:
                f.unlink()
            except OSError:
                pass
    path = d / f"paper-{now:%Y-%m-%d}.log"
    fh = open(path, "a", buffering=1, encoding="utf-8")
    if interactive is None:
        interactive = sys.stdout.isatty()
    sys.stdout = _Tee(sys.__stdout__, fh) if interactive else fh
    return path
