"""Replay a setup + exit plan over past sessions, after Indian charges.

Fill model (deliberately conservative):
  * entry at the OPEN of the bar after the trigger bar, plus slippage
  * stop and target are the planned price levels
  * if a bar touches both stop and target, the stop is assumed hit first
  * a gap through the stop fills at the bar's open, not at the stop
  * anything still open at flat_by exits at that bar's open
  * slippage is applied against you on both sides

It is a historical replay, not a prediction.
"""

from __future__ import annotations

import random
import statistics
from typing import Any, Dict, List, Optional

from datetime import datetime, timedelta

from .costs import net_pnl
from .market import Candle, by_session, parse_ts
from .plan import make_plan
from .setups import detect
from .sizing import size


def walk_exit(side: str, stop: float, target: float, flat: datetime, bars: List[Candle],
              start_idx: int, interval_min: int, until: Optional[datetime] = None):
    """Walk bars from `start_idx` and return (raw_exit_price, reason, bar_ts) for
    the first stop / target / flat-by hit, or None if nothing has hit yet.

    With `until` (live/paper use) only bars that have CLOSED by `until` are
    judged on their high/low; a bar that has merely opened can still trigger
    the flat-by exit at its open. Shared by backtest and paper trading so both
    follow identical rules."""
    long = side == "BUY"
    for b in bars[start_idx:]:
        if b.ts >= flat:
            if until is not None and b.ts > until:
                return None
            return b.open, "time", b.ts
        if until is not None and b.ts + timedelta(minutes=interval_min) > until:
            return None  # bar still forming
        if long:
            if b.low <= stop:
                return (b.open if b.open < stop else stop), "stop", b.ts
            if b.high >= target:
                return (b.open if b.open > target else target), "target", b.ts
        else:
            if b.high >= stop:
                return (b.open if b.open > stop else stop), "stop", b.ts
            if b.low <= target:
                return (b.open if b.open < target else target), "target", b.ts
    return None


def slipped(price: float, side: str, leg: str, slip: float) -> float:
    """Apply slippage against the trader. leg is 'entry' or 'exit'."""
    buying = (side == "BUY") == (leg == "entry")
    return round(price * (1 + slip if buying else 1 - slip), 2)


def _simulate(order: Dict[str, Any], bars: List[Candle], start_idx: int, slip: float,
              interval_min: int) -> Optional[Dict[str, Any]]:
    if start_idx >= len(bars):
        return None
    flat = parse_ts(order["flat_by"])
    first = bars[start_idx]
    if first.ts >= flat:
        return None
    entry = slipped(first.open, order["side"], "entry", slip)
    hit = walk_exit(order["side"], order["stop"], order["target"], flat, bars, start_idx, interval_min)
    if hit is None:
        hit = (bars[-1].close, "session_end", bars[-1].ts)
    px, reason, ts = hit
    return {"fill_entry": entry, "fill_exit": slipped(px, order["side"], "exit", slip),
            "exit_reason": reason, "exit_time": ts.isoformat()}


def run(symbol: str, candles: List[Candle], setup: str, cfg: Dict[str, Any], interval_min: int) -> Dict[str, Any]:
    sessions = by_session(candles)
    days = sorted(sessions)
    slip = cfg.get("slippage_pct", 0.0) / 100
    product = cfg.get("product", "MIS")
    trades: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {}

    for i, day in enumerate(days):
        bars = sessions[day]
        prev = sessions[days[i - 1]] if i > 0 else None
        sig = detect(setup, symbol, bars, cfg, interval_min, at=None, prev_bars=prev)
        st = sig["status"]
        if st != "triggered":
            status_counts[st] = status_counts.get(st, 0) + 1
            continue
        trig_ts = parse_ts(sig["trigger_bar"])
        idx = next(k for k, b in enumerate(bars) if b.ts == trig_ts)
        history = (prev or []) + bars[: idx + 1]
        try:
            plan = make_plan(sig, cfg["exit"], history)
        except ValueError as e:
            status_counts["plan_error"] = status_counts.get("plan_error", 0) + 1
            sig["reason"] = str(e)
            continue
        order = size(plan, cfg)
        if order["qty"] <= 0:
            status_counts["too_small"] = status_counts.get("too_small", 0) + 1
            continue
        sim = _simulate(order, bars, idx + 1, slip, interval_min)
        if sim is None:
            status_counts["no_fill"] = status_counts.get("no_fill", 0) + 1
            continue
        pnl = net_pnl(order["side"], sim["fill_entry"], sim["fill_exit"], order["qty"], cfg["charges"], product)
        planned_risk = order["risk_per_share"] * order["qty"]
        trades.append({"day": str(day), "side": order["side"], "qty": order["qty"],
                       "entry": order["entry"], "stop": order["stop"], "target": order["target"],
                       **sim, **pnl, "r": round(pnl["net"] / planned_risk, 2) if planned_risk else 0})
    return {"symbol": symbol, "setup": setup, "interval_min": interval_min,
            "sessions": len(days), "not_triggered": status_counts,
            "trades": trades, "stats": stats(trades)}


def stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"trades": 0}
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for n in nets:
        eq += n
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    reasons: Dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1),
        "exits": reasons,
        "net_total": round(sum(nets), 2),
        "gross_total": round(sum(t["gross"] for t in trades), 2),
        "charges_total": round(sum(t["charges"] for t in trades), 2),
        "avg_net": round(statistics.mean(nets), 2),
        "avg_r": round(statistics.mean(t["r"] for t in trades), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown": round(mdd, 2),
        "best": round(max(nets), 2),
        "worst": round(min(nets), 2),
    }


def bootstrap(trades: List[Dict[str, Any]], next_n: int = 20, runs: int = 10000, seed: int = 7) -> Dict[str, Any]:
    """Resample past trade results to show a RANGE of outcomes for the next
    `next_n` trades, if the future looked like this sample. Small samples
    make this range unreliable; it says so."""
    if len(trades) < 5:
        return {"note": "fewer than 5 trades: not enough to say anything"}
    rng = random.Random(seed)
    nets = [t["net"] for t in trades]
    totals = sorted(sum(rng.choice(nets) for _ in range(next_n)) for _ in range(runs))
    pct = lambda q: round(totals[min(runs - 1, int(q * runs))], 2)
    return {"next_trades": next_n, "runs": runs, "seed": seed,
            "p05": pct(0.05), "median": pct(0.5), "p95": pct(0.95),
            "prob_loss_pct": round(100 * sum(1 for x in totals if x < 0) / runs, 1),
            "sample_size": len(trades),
            "note": "resampled from past trades only; small samples and changing markets make this optimistic"}
