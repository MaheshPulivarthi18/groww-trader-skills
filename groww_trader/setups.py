"""Intraday setups. Each one looks at a single session's candles (plus the
previous session when it needs it) and returns a signal or a status.

Setups only describe what happened on the chart. They never place orders.

  orb           Opening-range breakout: the first close outside the high/low
                of the first `range_min` minutes.
  pdh_breakout  Previous-day-high breakout (or previous-day-low breakdown for
                shorts): the first close beyond yesterday's extreme.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .market import IST, MARKET_OPEN, Candle, bar_end, parse_hhmm

SETUPS = ("orb", "pdh_breakout")


def _window(cfg: Dict[str, Any], day: date):
    r = cfg["risk"]
    start = datetime.combine(day, parse_hhmm(r["no_entry_before"]), tzinfo=IST)
    stop = datetime.combine(day, parse_hhmm(r["no_entry_after"]), tzinfo=IST)
    return start, stop


def _first_break(bars: List[Candle], interval_min: int, up: float, down: float,
                 allow_short: bool, not_before: datetime, not_after: datetime,
                 at: Optional[datetime]):
    """Scan closed bars in order; return (side, bar) for the first close
    beyond `up` (BUY) or below `down` (SELL)."""
    for b in bars:
        end = bar_end(b, interval_min)
        if at is not None and end > at:
            break  # bar still forming at `at`
        if end <= not_before:
            continue
        if end > not_after:
            return "expired", None
        if b.close > up:
            return "BUY", b
        if allow_short and b.close < down:
            return "SELL", b
    return "waiting", None


def orb(symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
        at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    p = cfg["setups"]["orb"]
    if not bars:
        return {"symbol": symbol, "setup": "orb", "status": "no_data"}
    day = bars[0].day
    open_dt = datetime.combine(day, MARKET_OPEN, tzinfo=IST)
    range_end = open_dt + timedelta(minutes=p["range_min"])
    rng = [b for b in bars if b.ts < range_end]
    base = {"symbol": symbol, "setup": "orb", "day": str(day)}
    if (at is not None and at < range_end) or not rng or bar_end(rng[-1], interval_min) < range_end:
        return {**base, "status": "waiting", "reason": "opening range still forming"}

    hi, lo = max(b.high for b in rng), min(b.low for b in rng)
    pct = (hi - lo) / lo * 100
    levels = {"or_high": hi, "or_low": lo, "or_mid": round((hi + lo) / 2, 2), "range_pct": round(pct, 2)}
    base.update(levels)
    if pct < p["min_range_pct"] or pct > p["max_range_pct"]:
        return {**base, "status": "skipped",
                "reason": f"range {pct:.2f}% outside {p['min_range_pct']}-{p['max_range_pct']}%"}

    not_before, not_after = _window(cfg, day)
    not_before = max(not_before, range_end)
    after = [b for b in bars if b.ts >= range_end]
    side, bar = _first_break(after, interval_min, hi, lo, cfg.get("allow_short", False),
                             not_before, not_after, at)
    if bar is None:
        return {**base, "status": side}
    return {**base, "status": "triggered", "side": side, "entry": bar.close,
            "trigger_time": bar_end(bar, interval_min).isoformat(), "trigger_bar": bar.ts.isoformat()}


def pdh_breakout(symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
                 at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    if not bars:
        return {"symbol": symbol, "setup": "pdh_breakout", "status": "no_data"}
    day = bars[0].day
    base = {"symbol": symbol, "setup": "pdh_breakout", "day": str(day)}
    if not prev_bars:
        return {**base, "status": "no_data", "reason": "previous session not available"}
    pdh, pdl = max(b.high for b in prev_bars), min(b.low for b in prev_bars)
    base.update({"pdh": pdh, "pdl": pdl, "prev_close": prev_bars[-1].close})
    first = bars[0]
    if first.open > pdh or first.open < pdl:
        # Gapped beyond the level: not a clean breakout of it.
        return {**base, "status": "skipped", "reason": "opened beyond previous day's range"}
    not_before, not_after = _window(cfg, day)
    side, bar = _first_break(bars, interval_min, pdh, pdl, cfg.get("allow_short", False),
                             not_before, not_after, at)
    if bar is None:
        return {**base, "status": side}
    return {**base, "status": "triggered", "side": side, "entry": bar.close,
            "trigger_time": bar_end(bar, interval_min).isoformat(), "trigger_bar": bar.ts.isoformat()}


DETECTORS = {"orb": orb, "pdh_breakout": pdh_breakout}


def detect(setup: str, symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
           at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    if setup not in DETECTORS:
        raise ValueError(f"Unknown setup {setup!r}. Choose from {', '.join(SETUPS)}")
    return DETECTORS[setup](symbol, bars, cfg, interval_min, at=at, prev_bars=prev_bars)
