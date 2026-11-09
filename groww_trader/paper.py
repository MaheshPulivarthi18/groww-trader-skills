"""Paper trading: run the full pipeline on LIVE data and record what would
have happened, without sending any order.

Each call to `step()` looks at the market as of `now`:

  1. scan     new triggers -> plan -> size -> risk gate -> "pending" or "blocked"
              (a trigger older than max_signal_age_min is recorded as "missed":
               if you started late, it does not pretend you caught it)
  2. fill     a pending idea fills at the OPEN of the bar after its trigger bar,
              plus slippage ("cancelled" if that bar is at/after flat-by)
  3. manage   open positions exit on stop / target / flat-by, judged only on
              bars that have CLOSED by `now`; same rules as the backtest

Everything lives in the journal (trader/journal.json), so stopping and
restarting is safe and the risk gate's daily limits see real paper history.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .backtest import slipped, stats, walk_exit
from .costs import net_pnl
from .market import IST, MARKET_CLOSE, MARKET_OPEN, Candle, by_session, parse_ts
from .plan import make_plan
from .risk import check as risk_check
from .setups import SETUPS, detect
from .sizing import size

Journal = List[Dict[str, Any]]


def _sessions(candles: List[Candle], now: datetime):
    known = [c for c in candles if c.ts <= now]  # never look at bars that haven't started
    s = by_session(known)
    day = now.date()
    today = s.get(day, [])
    prev_days = [d for d in s if d < day]
    prev = s[max(prev_days)] if prev_days else None
    return today, prev


def _fmt(e: Dict[str, Any]) -> str:
    return f"{e['symbol']} {e['setup']} {e['side']}"


def step(cfg: Dict[str, Any], data: Dict[str, List[Candle]], now: datetime, journal: Journal,
         interval_min: int) -> Tuple[Journal, List[str]]:
    now = now.astimezone(IST)
    day = now.date()
    events: List[str] = []
    slip = cfg.get("slippage_pct", 0.0) / 100
    product = cfg.get("product", "MIS")
    max_age = timedelta(minutes=cfg.get("paper_trading", {}).get("max_signal_age_min", 10))
    open_dt = datetime.combine(day, MARKET_OPEN, tzinfo=IST)
    close_dt = datetime.combine(day, MARKET_CLOSE, tzinfo=IST)
    known_ids = {e["id"] for e in journal}
    setups = [s for s in cfg["setups"] if s in SETUPS]

    # 1. scan for new ideas
    if open_dt < now <= close_dt:
        for symbol, candles in data.items():
            today, prev = _sessions(candles, now)
            if not today:
                continue
            for setup in setups:
                eid = f"{day}:{symbol}:{setup}"
                if eid in known_ids:
                    continue
                sig = detect(setup, symbol, today, cfg, interval_min, at=now, prev_bars=prev)
                if sig.get("status") != "triggered":
                    continue
                base = {"id": eid, "mode": "paper", "day": str(day), "symbol": symbol, "setup": setup,
                        "side": sig["side"], "signal_time": sig["trigger_time"],
                        "trigger_bar": sig["trigger_bar"], "seen_at": now.isoformat()}
                if now - parse_ts(sig["trigger_time"]) > max_age:
                    journal.append({**base, "status": "missed",
                                    "reason": f"triggered at {sig['trigger_time'][11:16]}, seen too late"})
                    events.append(f"MISSED  {_fmt(base)}: triggered {sig['trigger_time'][11:16]}, too late to act")
                    known_ids.add(eid)
                    continue
                try:
                    hist = (prev or []) + [b for b in today if b.ts <= parse_ts(sig["trigger_bar"])]
                    order = size(make_plan(sig, cfg["exit"], hist), cfg)
                except ValueError as e:
                    journal.append({**base, "status": "blocked", "risk_reasons": [str(e)]})
                    events.append(f"BLOCKED {_fmt(base)}: {e}")
                    known_ids.add(eid)
                    continue
                checked = risk_check([order], cfg, journal, now=now)[0]
                entry = {**base, **{k: checked[k] for k in (
                    "qty", "entry", "stop", "target", "flat_by", "risk_per_share", "reward_risk",
                    "product", "risk_reasons") if k in checked}}
                if checked["risk_check"] == "PASS":
                    entry["status"] = "pending"
                    events.append(f"SIGNAL  {_fmt(base)} x{entry['qty']} ~₹{entry['entry']} "
                                  f"stop ₹{entry['stop']} target ₹{entry['target']}")
                else:
                    entry["status"] = "blocked"
                    events.append(f"BLOCKED {_fmt(base)}: {'; '.join(checked['risk_reasons'])}")
                journal.append(entry)
                known_ids.add(eid)

    # 2. fill pending ideas, 3. manage open positions
    for e in journal:
        if e.get("day") != str(day) or e["status"] not in ("pending", "open"):
            continue
        today, _ = _sessions(data.get(e["symbol"], []), now)
        flat = parse_ts(e["flat_by"])
        if e["status"] == "pending":
            trig = parse_ts(e["trigger_bar"])
            nxt = next((b for b in today if b.ts > trig), None)
            if nxt is None:
                if now >= flat:
                    e["status"], e["reason"] = "cancelled", "no bar to fill before flat-by"
                    events.append(f"CANCEL  {_fmt(e)}: no fill before flat-by")
                continue
            if nxt.ts >= flat:
                e["status"], e["reason"] = "cancelled", "next bar was at/after flat-by"
                events.append(f"CANCEL  {_fmt(e)}: next bar at/after flat-by")
                continue
            e.update(status="open", entry_time=nxt.ts.isoformat(),
                     fill_entry=slipped(nxt.open, e["side"], "entry", slip))
            events.append(f"FILLED  {_fmt(e)} x{e['qty']} @ ₹{e['fill_entry']} ({nxt.ts:%H:%M})")

        if e["status"] == "open":
            et = parse_ts(e["entry_time"])
            idx = next((i for i, b in enumerate(today) if b.ts == et), None)
            if idx is None:
                continue
            hit = walk_exit(e["side"], e["stop"], e["target"], flat, today, idx, interval_min, until=now)
            if hit is None and now >= close_dt and today:
                hit = (today[-1].close, "session_end", today[-1].ts)
            if hit is None:
                continue
            px, reason, ts = hit
            fill_exit = slipped(px, e["side"], "exit", slip)
            pnl = net_pnl(e["side"], e["fill_entry"], fill_exit, e["qty"], cfg["charges"], product)
            risk_amt = e["risk_per_share"] * e["qty"]
            e.update(status="closed", fill_exit=fill_exit, exit_reason=reason, exit_time=ts.isoformat(),
                     **pnl, r=round(pnl["net"] / risk_amt, 2) if risk_amt else 0)
            events.append(f"CLOSED  {_fmt(e)} {reason} @ ₹{fill_exit}: net ₹{pnl['net']} "
                          f"(charges ₹{pnl['charges']})")
    return journal, events


def replay(cfg: Dict[str, Any], data: Dict[str, List[Candle]], day: date, interval_min: int,
           journal: Optional[Journal] = None) -> Tuple[Journal, List[str]]:
    """Run step() at every bar boundary of a past session, as the live loop
    would have. Used for offline testing and for rehearsing a day."""
    journal = journal if journal is not None else []
    log: List[str] = []
    t = datetime.combine(day, MARKET_OPEN, tzinfo=IST) + timedelta(minutes=interval_min)
    end = datetime.combine(day, MARKET_CLOSE, tzinfo=IST)
    while t <= end:
        journal, ev = step(cfg, data, t, journal, interval_min)
        log += [f"{t:%H:%M} {x}" for x in ev]
        t += timedelta(minutes=interval_min)
    return journal, log


def next_boundary(now: datetime, interval_min: int, lag_s: int = 20) -> datetime:
    """Next bar close after `now`, plus a small lag for the data to arrive."""
    base = datetime.combine(now.date(), MARKET_OPEN, tzinfo=IST)
    if now < base:
        return base + timedelta(minutes=interval_min, seconds=lag_s)
    k = int((now - base).total_seconds() // (interval_min * 60)) + 1
    return base + timedelta(minutes=k * interval_min, seconds=lag_s)


def report(journal: Journal, day: Optional[str] = None) -> Dict[str, Any]:
    rows = [e for e in journal if e.get("mode") == "paper" and (day is None or e.get("day") == day)]
    closed = [e for e in rows if e["status"] == "closed"]
    counts: Dict[str, int] = {}
    for e in rows:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    days: Dict[str, List[Dict[str, Any]]] = {}
    for e in closed:
        days.setdefault(e["day"], []).append(e)
    by_day = [{"day": d, "trades": len(v), "net": round(sum(x["net"] for x in v), 2)}
              for d, v in sorted(days.items())]
    return {"days": len({e["day"] for e in rows}), "ideas": counts, "by_day": by_day,
            "stats": stats(closed)}
