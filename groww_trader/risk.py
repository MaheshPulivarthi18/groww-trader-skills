"""Risk gate. Every order gets PASS or BLOCK with plain-language reasons.
Nothing downstream may act on an order that is not PASS.

Today's activity comes from trader/journal.json, a list of entries like
  {"day": "2026-11-10", "symbol": "SBIN", "status": "open"|"closed", "net": -212.5}
Only pending/open/closed entries count as trades; blocked, missed and
cancelled ideas are kept in the journal for the record but don't count.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .market import IST, parse_hhmm, parse_ts

LIVE_STATUSES = ("pending", "open", "closed")


def check(orders: List[Dict[str, Any]], cfg: Dict[str, Any], journal: Optional[List[Dict[str, Any]]] = None,
          now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    r = cfg["risk"]
    journal = journal or []
    out = []
    for o in orders:
        day = o.get("day")
        today = [j for j in journal if j.get("day") == day and j.get("status") in LIVE_STATUSES]
        realized = sum(float(j.get("net", 0)) for j in today if j.get("status") == "closed")
        passed_now = sum(1 for x in out if x["risk_check"] == "PASS" and x.get("day") == day)
        trades = len(today) + passed_now
        open_pos = sum(1 for j in today if j.get("status") in ("pending", "open")) + passed_now

        why = []
        qty = int(o.get("qty", 0))
        if qty <= 0:
            why.append(o.get("reason", "quantity is zero"))
        loss = -float(o.get("loss_at_stop", 0))
        if loss > r["max_loss_per_trade"]:
            why.append(f"loss at stop ₹{loss:.0f} exceeds per-trade limit ₹{r['max_loss_per_trade']}")
        if realized <= -r["daily_loss_limit"]:
            why.append(f"daily loss limit hit (₹{-realized:.0f} lost today)")
        elif qty > 0 and -realized + loss > r["daily_loss_limit"]:
            why.append(f"a stop-out would take today's loss to ₹{-realized + loss:.0f}, over ₹{r['daily_loss_limit']}")
        if trades >= r["max_trades_per_day"]:
            why.append(f"already {trades} trade(s) today, limit {r['max_trades_per_day']}")
        if open_pos >= r["max_open_positions"]:
            why.append(f"{open_pos} position(s) open, limit {r['max_open_positions']}")
        if float(o.get("reward_risk", 0)) < r["min_reward_risk"]:
            why.append(f"reward:risk {o.get('reward_risk')} below {r['min_reward_risk']}")
        if o.get("value", 0) > cfg["capital"] * r["max_position_pct"] / 100 + 0.01:
            why.append(f"position ₹{o['value']:.0f} over {r['max_position_pct']}% of capital")
        if o.get("side") == "SELL" and not cfg.get("allow_short"):
            why.append("short selling is off (allow_short: false)")
        if o.get("product") not in ("MIS", "CNC"):
            why.append(f"product {o.get('product')} not supported")

        if now is not None and day:
            t = now.astimezone(IST)
            if str(t.date()) != day:
                why.append(f"signal is from {day}, not today")
            else:
                late = datetime.combine(t.date(), parse_hhmm(r["no_entry_after"]), tzinfo=IST)
                early = datetime.combine(t.date(), parse_hhmm(r["no_entry_before"]), tzinfo=IST)
                if t > late:
                    why.append(f"past the entry window ({r['no_entry_after']})")
                if t < early:
                    why.append(f"before the entry window ({r['no_entry_before']})")
                if o.get("flat_by") and t >= parse_ts(o["flat_by"]):
                    why.append("already past this trade's flat-by time")

        out.append({**o, "risk_check": "BLOCK" if why else "PASS", "risk_reasons": why})
    return out
