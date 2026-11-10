"""Optional MongoDB mirror of the bot's activity, for dashboards and for
asking Claude questions about your trading.

  GTRADE_MONGO_URI   connection string (keep it in ~/.groww_env, never in files)
  GTRADE_MONGO_DB    database name (default "groww_trader")

The local files in trader/ stay the source of truth. MongoDB only gets a
copy, and every call here is best-effort: short timeouts, and errors are
reported as one-line warnings, never raised. A database problem can never
stop a scan, a fill or an exit.

Collections
  journal    one document per trade idea (_id "day:symbol:setup"), all
             statuses: pending, open, closed, blocked, missed, cancelled
  daily      one summary per trading day (_id "YYYY-MM-DD")
  events     one document per event line (SIGNAL, FILLED, CLOSED, ...)
  health     one document (_id "bot") with the latest heartbeat
  backtests  one document per saved backtest run
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .market import IST

_TIMEOUT_MS = 4000


def _scrub(msg: str) -> str:
    """Remove credentials from any message before printing it."""
    return re.sub(r"(mongodb(?:\+srv)?://)[^@/\s]+@", r"\1***@", str(msg))


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def daily_summary(journal: List[Dict[str, Any]], day: str) -> Dict[str, Any]:
    rows = [e for e in journal if e.get("day") == day]
    closed = [e for e in rows if e.get("status") == "closed"]
    statuses: Dict[str, int] = {}
    for e in rows:
        statuses[e["status"]] = statuses.get(e["status"], 0) + 1
    wins = [e for e in closed if e.get("net", 0) > 0]
    return {
        "_id": day,
        "day": day,
        "ideas": statuses,
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "gross": round(sum(e.get("gross", 0) for e in closed), 2),
        "charges": round(sum(e.get("charges", 0) for e in closed), 2),
        "net": round(sum(e.get("net", 0) for e in closed), 2),
        "open_positions": statuses.get("open", 0) + statuses.get("pending", 0),
        "symbols": sorted({e["symbol"] for e in rows if "symbol" in e}),
    }


class Store:
    """Thin wrapper; `db` can be injected for tests."""

    def __init__(self, db=None, uri: Optional[str] = None, name: Optional[str] = None, log=print):
        self.log = log
        self.db = db
        self.error: Optional[str] = None
        self._synced_all = False
        if db is not None:
            return
        uri = uri or os.environ.get("GTRADE_MONGO_URI", "").strip()
        if not uri:
            return
        try:
            from pymongo import MongoClient  # type: ignore
        except ImportError:
            self.error = "GTRADE_MONGO_URI is set but pymongo isn't installed: pip install pymongo"
            self.log(f"warning: {self.error}")
            return
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=_TIMEOUT_MS,
                                 connectTimeoutMS=_TIMEOUT_MS, socketTimeoutMS=_TIMEOUT_MS * 2,
                                 appname="groww-trader-skills", tz_aware=True)
            self.db = client[name or os.environ.get("GTRADE_MONGO_DB", "groww_trader") or "groww_trader"]
        except Exception as e:  # bad URI etc.
            self.error = _scrub(e)
            self.log(f"warning: MongoDB disabled: {self.error}")

    @property
    def enabled(self) -> bool:
        return self.db is not None

    _down_until: Optional[datetime] = None
    BACKOFF_S = 120

    def _safe(self, what: str, fn) -> bool:
        if not self.enabled:
            return False
        if self._down_until is not None and _now() < self._down_until:
            return False  # recently unreachable: don't slow the bot down retrying
        try:
            fn()
            self._down_until = None
            return True
        except Exception as e:
            self.error = _scrub(e)
            from datetime import timedelta
            self._down_until = _now() + timedelta(seconds=self.BACKOFF_S)
            self.log(f"warning: MongoDB {what} skipped (retrying in {self.BACKOFF_S}s): {self.error[:200]}")
            return False

    # ------------------------------------------------------------------ writes

    def sync_journal(self, journal: List[Dict[str, Any]], day: Optional[str] = None,
                     full: bool = False) -> bool:
        """Upsert journal entries. The first call (or full=True) sends
        everything, later calls only `day`'s entries. Daily summaries are
        rebuilt for every day sent."""
        send_all = full or not self._synced_all
        rows = journal if send_all or day is None else [e for e in journal if e.get("day") == day]

        def run():
            stamp = _now()
            for e in rows:
                if "id" not in e:
                    continue
                self.db["journal"].replace_one({"_id": e["id"]}, {**e, "_id": e["id"], "synced_at": stamp},
                                               upsert=True)
            for d in sorted({e.get("day") for e in rows if e.get("day")}):
                doc = daily_summary(journal, d)
                self.db["daily"].replace_one({"_id": d}, {**doc, "synced_at": stamp}, upsert=True)

        ok = self._safe("journal sync", run)
        if ok and send_all:
            self._synced_all = True
        return ok

    def log_events(self, events: Iterable[str], when: datetime, mode: str = "paper") -> bool:
        docs = [{"at": when, "day": str(when.astimezone(IST).date()), "time": f"{when.astimezone(IST):%H:%M}",
                 "kind": ev.split()[0] if ev.split() else "", "text": ev, "mode": mode} for ev in events]
        if not docs:
            return True
        return self._safe("event log", lambda: self.db["events"].insert_many(docs))

    def heartbeat(self, when: datetime, status: str, symbols: List[str],
                  errors: Optional[Dict[str, str]] = None, mode: str = "paper") -> bool:
        doc = {"_id": "bot", "at": when, "mode": mode, "status": status, "symbols": symbols,
               "data_errors": errors or {}, "synced_at": _now()}
        return self._safe("heartbeat", lambda: self.db["health"].replace_one({"_id": "bot"}, doc, upsert=True))

    def save_backtest(self, result: Dict[str, Any]) -> bool:
        doc = {k: v for k, v in result.items() if k != "trades"}
        doc.update(trades_detail=result.get("trades", []), saved_at=_now())
        return self._safe("backtest save", lambda: self.db["backtests"].insert_one(doc))

    # ------------------------------------------------------------------ check

    def check(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": self.error or "GTRADE_MONGO_URI is not set"}
        out: Dict[str, Any] = {"ok": False, "database": getattr(self.db, "name", "?")}

        def run():
            self.db.command("ping")
            out["collections"] = {c: self.db[c].count_documents({})
                                  for c in ("journal", "daily", "events", "health", "backtests")}
            out["ok"] = True

        if not self._safe("check", run):
            out["reason"] = self.error
        return out


_STORE: Optional[Store] = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
