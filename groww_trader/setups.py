"""Intraday setups. Each one looks at a single session's candles (plus the
previous session when it needs it) and returns a signal or a status.

Setups only describe what happened on the chart. They never place orders.

  orb           Opening-range breakout: the first close outside the high/low
                of the first `range_min` minutes.
  pdh_breakout  Previous-day-high breakout (or previous-day-low breakdown for
                shorts): the first close beyond yesterday's extreme.
  orb_fade      Failed opening-range breakout: price closes outside the range,
                then closes back inside within `max_bars_outside` bars. Trade
                the reversal: BUY after a failed breakdown, SELL (shorts only)
                after a failed breakout. Stop: beyond the failed move's extreme.
  vwap_reclaim  After `min_bars_away` closes below the session VWAP, the first
                close back above it: BUY (mirror for SELL with shorts on).
                Stop: the extreme of the stretch away from VWAP.

Setups that define their own stop put it in `setup_stop`; the exit rule
`stop: "setup"` uses it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import setup_params
from .market import IST, MARKET_OPEN, Candle, bar_end, parse_hhmm

SETUPS = ("orb", "pdh_breakout", "orb_fade", "vwap_reclaim")


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


def _opening_range(name: str, symbol: str, bars: List[Candle], p: Dict[str, Any], interval_min: int,
                   at: Optional[datetime]):
    """Return (base, None, range_end) with OR levels, or (None, status_dict, None)."""
    if not bars:
        return None, {"symbol": symbol, "setup": name, "status": "no_data"}, None
    day = bars[0].day
    open_dt = datetime.combine(day, MARKET_OPEN, tzinfo=IST)
    range_end = open_dt + timedelta(minutes=p["range_min"])
    rng = [b for b in bars if b.ts < range_end]
    base = {"symbol": symbol, "setup": name, "day": str(day)}
    if (at is not None and at < range_end) or not rng or bar_end(rng[-1], interval_min) < range_end:
        return None, {**base, "status": "waiting", "reason": "opening range still forming"}, None
    hi, lo = max(b.high for b in rng), min(b.low for b in rng)
    pct = (hi - lo) / lo * 100
    base.update({"or_high": hi, "or_low": lo, "or_mid": round((hi + lo) / 2, 2), "range_pct": round(pct, 2)})
    if pct < p["min_range_pct"] or pct > p["max_range_pct"]:
        return None, {**base, "status": "skipped",
                      "reason": f"range {pct:.2f}% outside {p['min_range_pct']}-{p['max_range_pct']}%"}, None
    return base, None, range_end


def _closed(bars: List[Candle], interval_min: int, at: Optional[datetime]):
    for b in bars:
        if at is not None and bar_end(b, interval_min) > at:
            return
        yield b


def _trigger(base: Dict[str, Any], side: str, bar: Candle, interval_min: int, **extra) -> Dict[str, Any]:
    return {**base, **extra, "status": "triggered", "side": side, "entry": bar.close,
            "trigger_time": bar_end(bar, interval_min).isoformat(), "trigger_bar": bar.ts.isoformat()}


def orb(symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
        at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    p = setup_params(cfg, "orb")
    base, status, range_end = _opening_range("orb", symbol, bars, p, interval_min, at)
    if status:
        return status
    hi, lo, day = base["or_high"], base["or_low"], bars[0].day
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


def orb_fade(symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
             at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    p = setup_params(cfg, "orb_fade")
    base, status, range_end = _opening_range("orb_fade", symbol, bars, p, interval_min, at)
    if status:
        return status
    hi, lo = base["or_high"], base["or_low"]
    not_before, not_after = _window(cfg, bars[0].day)
    allow_short = cfg.get("allow_short", False)
    direction, start_i, extreme = None, 0, 0.0
    after = [b for b in bars if b.ts >= range_end]
    for i, b in enumerate(_closed(after, interval_min, at)):
        end = bar_end(b, interval_min)
        if end > not_after:
            return {**base, "status": "expired"}
        if direction is None:
            if b.close > hi:
                direction, start_i, extreme = "up", i, b.high
            elif b.close < lo:
                direction, start_i, extreme = "down", i, b.low
            continue
        extreme = max(extreme, b.high) if direction == "up" else min(extreme, b.low)
        back_inside = b.close < hi if direction == "up" else b.close > lo
        if back_inside:
            side = "SELL" if direction == "up" else "BUY"
            if i - start_i <= p["max_bars_outside"] and end > not_before and (side == "BUY" or allow_short):
                return _trigger(base, side, b, interval_min, setup_stop=extreme, failed=direction)
            direction = None  # too slow, too early, or a short we can't take: watch for the next one
        elif i - start_i > p["max_bars_outside"]:
            return {**base, "status": "skipped", "reason": f"breakout {direction} held"}
    return {**base, "status": "waiting"}


def vwap_series(bars: List[Candle]) -> List[float]:
    """Session VWAP from typical price; equal weights if volume is missing."""
    use_vol = any(b.volume for b in bars)
    pv = vol = 0.0
    out = []
    for b in bars:
        w = b.volume if use_vol else 1.0
        pv += (b.high + b.low + b.close) / 3 * w
        vol += w
        out.append(pv / vol if vol else b.close)
    return out


def vwap_reclaim(symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
                 at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    p = setup_params(cfg, "vwap_reclaim")
    if not bars:
        return {"symbol": symbol, "setup": "vwap_reclaim", "status": "no_data"}
    base = {"symbol": symbol, "setup": "vwap_reclaim", "day": str(bars[0].day)}
    not_before, not_after = _window(cfg, bars[0].day)
    closed = list(_closed(bars, interval_min, at))
    vw = vwap_series(closed)
    allow_short = cfg.get("allow_short", False)
    below = above = 0
    low_ext, high_ext = float("inf"), float("-inf")
    for b, v in zip(closed, vw):
        end = bar_end(b, interval_min)
        if end > not_after:
            return {**base, "status": "expired"}
        if b.close < v:
            if above >= p["min_bars_away"] and allow_short and end > not_before:
                return _trigger(base, "SELL", b, interval_min, setup_stop=high_ext, vwap=round(v, 2))
            below, above = below + 1, 0
            low_ext = min(low_ext, b.low) if below > 1 else b.low
        elif b.close > v:
            if below >= p["min_bars_away"] and end > not_before:
                return _trigger(base, "BUY", b, interval_min, setup_stop=low_ext, vwap=round(v, 2))
            above, below = above + 1, 0
            high_ext = max(high_ext, b.high) if above > 1 else b.high
    return {**base, "status": "waiting"}


DETECTORS = {"orb": orb, "pdh_breakout": pdh_breakout, "orb_fade": orb_fade, "vwap_reclaim": vwap_reclaim}


def detect(setup: str, symbol: str, bars: List[Candle], cfg: Dict[str, Any], interval_min: int,
           at: Optional[datetime] = None, prev_bars: Optional[List[Candle]] = None) -> Dict[str, Any]:
    if setup not in DETECTORS:
        raise ValueError(f"Unknown setup {setup!r}. Choose from {', '.join(SETUPS)}")
    return DETECTORS[setup](symbol, bars, cfg, interval_min, at=at, prev_bars=prev_bars)
