"""Deterministic synthetic candles for offline tests. Not real market data."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import List

from groww_trader.market import IST, Candle

BARS_PER_DAY = 75  # 09:15 .. 15:25 start times, 5-minute bars


def session_times(day: date, interval: int = 5):
    t = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    for _ in range(BARS_PER_DAY):
        yield t
        t += timedelta(minutes=interval)


def random_days(start: date, n_days: int, seed: int = 1, price: float = 500.0) -> List[Candle]:
    rng = random.Random(seed)
    out: List[Candle] = []
    d = start
    made = 0
    while made < n_days:
        if d.weekday() < 5:
            for ts in session_times(d):
                o = price
                c = max(1.0, o * (1 + rng.gauss(0, 0.002)))
                h = max(o, c) * (1 + abs(rng.gauss(0, 0.001)))
                l = min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
                out.append(Candle(ts, round(o, 2), round(h, 2), round(l, 2), round(c, 2), rng.randint(1000, 9000)))
                price = c
            price *= 1 + rng.gauss(0, 0.004)  # overnight gap
            made += 1
        d += timedelta(days=1)
    return out


def orb_day(day: date) -> List[Candle]:
    """A hand-built session: opening range 100.00-101.00, the 09:35 bar closes
    at 101.60 (breakout, trigger at 09:40), price then rallies to 103.40."""
    bars = []
    path = {
        "09:15": (100.5, 101.0, 100.2, 100.8),
        "09:20": (100.8, 100.9, 100.0, 100.3),
        "09:25": (100.3, 100.7, 100.1, 100.6),
        "09:30": (100.6, 100.95, 100.5, 100.9),
        "09:35": (100.9, 101.7, 100.85, 101.6),
    }
    price = 101.6
    for ts in session_times(day):
        key = ts.strftime("%H:%M")
        if key in path:
            o, h, l, c = path[key]
        else:
            o = price
            c = min(o + 0.12, 103.4) if ts.hour < 11 else o
            h, l = max(o, c) + 0.02, min(o, c) - 0.02
        bars.append(Candle(ts, o, round(h, 2), round(l, 2), round(c, 2), 5000))
        price = c
    return bars
