"""Candles, Indian market hours (IST) and session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# NSE cash market, normal session.
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


@dataclass(frozen=True)
class Candle:
    ts: datetime  # candle START time, timezone-aware IST
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def day(self) -> date:
        return self.ts.date()


def parse_ts(value) -> datetime:
    """Parse Groww / CSV timestamps into an IST-aware datetime.

    Accepts epoch seconds, "yyyy-MM-dd HH:mm:ss", "yyyy-MM-ddTHH:mm:ss"
    (with or without an offset). Naive times are taken as IST, which is
    what Groww returns.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=IST)
    else:
        s = str(value).strip()
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=IST)
        dt = datetime.fromisoformat(s.replace(" ", "T", 1))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def parse_hhmm(value: str) -> time:
    h, m = str(value).split(":")[:2]
    return time(int(h), int(m))


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def by_session(candles: Iterable[Candle]) -> Dict[date, List[Candle]]:
    """Group candles by trading day, keeping only regular-session bars."""
    out: Dict[date, List[Candle]] = {}
    for c in sorted(candles, key=lambda c: c.ts):
        t = c.ts.timetz().replace(tzinfo=None)
        if MARKET_OPEN <= t < MARKET_CLOSE:
            out.setdefault(c.day, []).append(c)
    return out


def bar_end(c: Candle, interval_min: int) -> datetime:
    return c.ts + timedelta(minutes=interval_min)


def is_weekday(d: date) -> bool:
    # Exchange holidays are not modelled; Groww simply returns no candles.
    return d.weekday() < 5
