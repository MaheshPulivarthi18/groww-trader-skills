"""Exit planning: stop, target and a time to be flat, decided BEFORE entry."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .indicators import atr
from .market import IST, Candle, parse_hhmm


def _round_tick(price: float, tick: float = 0.05) -> float:
    return round(round(price / tick) * tick, 2)


def stop_price(signal: Dict[str, Any], rule: str, bars: Optional[List[Candle]] = None) -> float:
    side, entry = signal["side"], signal["entry"]
    long = side == "BUY"
    rule = rule.strip().lower()
    if rule == "or_mid":
        if "or_mid" not in signal:
            raise ValueError("stop 'or_mid' needs an opening-range setup; use pct:<n> or atr:<n>")
        s = signal["or_mid"]
    elif rule in ("or_low", "or_high", "or_far"):
        if "or_low" not in signal:
            raise ValueError(f"stop '{rule}' needs an opening-range setup")
        s = signal["or_low"] if long else signal["or_high"]
    elif rule == "level":  # the level that was broken (pdh/pdl)
        s = signal.get("pdh" if long else "pdl")
        if s is None:
            raise ValueError("stop 'level' needs a pdh_breakout signal")
    elif rule.startswith("pct:"):
        p = float(rule[4:]) / 100
        s = entry * (1 - p) if long else entry * (1 + p)
    elif rule.startswith("atr:"):
        k = float(rule[4:])
        vals = [v for v in atr(bars or [], 14) if v is not None]
        if not vals:
            raise ValueError("not enough bars for ATR(14); fetch more history or use pct:<n>")
        s = entry - k * vals[-1] if long else entry + k * vals[-1]
    else:
        raise ValueError(f"unknown stop rule {rule!r}")
    s = _round_tick(s)
    if (long and s >= entry) or (not long and s <= entry):
        raise ValueError(f"stop {s} is on the wrong side of entry {entry}")
    return s


def make_plan(signal: Dict[str, Any], exit_cfg: Dict[str, Any],
              bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    if signal.get("status") != "triggered":
        raise ValueError(f"{signal.get('symbol')}: no triggered signal to plan (status {signal.get('status')})")
    side, entry = signal["side"], float(signal["entry"])
    stop = stop_price(signal, exit_cfg["stop"], bars)
    risk = abs(entry - stop)
    t = str(exit_cfg["target"]).upper()
    if not t.endswith("R"):
        raise ValueError("target must look like '1.5R'")
    r_mult = float(t[:-1])
    target = _round_tick(entry + r_mult * risk if side == "BUY" else entry - r_mult * risk)
    day = date.fromisoformat(signal["day"])
    flat_by = datetime.combine(day, parse_hhmm(exit_cfg["flat_by"]), tzinfo=IST)
    return {
        "symbol": signal["symbol"], "setup": signal["setup"], "day": signal["day"],
        "side": side, "entry": entry, "stop": stop, "target": target,
        "risk_per_share": round(risk, 2), "reward_risk": r_mult,
        "flat_by": flat_by.isoformat(), "trigger_time": signal.get("trigger_time"),
        "rules": {"stop": exit_cfg["stop"], "target": exit_cfg["target"]},
    }
