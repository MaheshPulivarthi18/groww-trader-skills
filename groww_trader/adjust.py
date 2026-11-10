"""Adjust daily candles for splits, bonus issues and demergers.

Groww's historical candles are not adjusted: a 1:1 bonus shows as a -50%
day, a 1:10 split as -90%. Left alone, those fake crashes wreck momentum
scores, volatility and portfolio values.

Detection (per symbol, close-to-close):
  * a one-day drop with prev_close / close >= 1.4 (about -29%) whose ratio is
    within 8% of a standard factor (1.5, 2, 2.5, 3, 4, 5, 6, 10, 20) is
    treated as a split or bonus and adjusted by that factor.
  * a drop with ratio >= 1.6 (about -37%) that matches no standard factor is
    treated as another corporate action (e.g. a demerger, where the value
    moved into a newly listed company) and adjusted by the observed ratio.
  * real one-day crashes that big are rare in large caps, but one would be
    smoothed away too. `audit` lists every event so you can check, and the
    overrides file below can cancel one.
  * trader/corporate_actions.csv overrides detection: lines of
    `SYMBOL,YYYY-MM-DD,factor` (factor 1 cancels a detected event).

Adjustment: prices before the event date are divided by the factor, volume
multiplied, so returns across the event are continuous.
"""

from __future__ import annotations

import csv
import math
from datetime import date
from typing import Dict, List, Optional, Tuple

from .config import home
from .market import Candle

STANDARD = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 10.0, 20.0)
MIN_RATIO = 1.4      # smallest drop considered a split/bonus
MIN_OTHER = 1.6      # smallest unexplained drop treated as a demerger etc.
SNAP = 0.08


def load_overrides() -> Dict[Tuple[str, date], float]:
    p = home() / "corporate_actions.csv"
    out: Dict[Tuple[str, date], float] = {}
    if not p.exists():
        return out
    for row in csv.reader(p.read_text(encoding="utf-8").splitlines()):
        if len(row) < 3 or row[0].strip().startswith("#") or row[0].strip().lower() == "symbol":
            continue
        try:
            out[(row[0].strip().upper(), date.fromisoformat(row[1].strip()))] = float(row[2])
        except ValueError:
            continue
    return out


def detect(symbol: str, candles: List[Candle], overrides: Optional[Dict] = None) -> List[Dict]:
    overrides = overrides or {}
    events = []
    for a, b in zip(candles, candles[1:]):
        d = b.ts.date()
        if (symbol, d) in overrides:
            continue
        if not a.close or not b.close:
            continue
        ratio = a.close / b.close
        if ratio < MIN_RATIO:
            continue
        snap = min(STANDARD, key=lambda f: abs(math.log(ratio / f)))
        if abs(ratio / snap - 1) <= SNAP:
            events.append({"symbol": symbol, "date": str(d), "factor": snap, "ratio": round(ratio, 3), "kind": "split/bonus"})
        elif ratio >= MIN_OTHER:
            events.append({"symbol": symbol, "date": str(d), "factor": round(ratio, 4), "ratio": round(ratio, 3), "kind": "other"})
    for (s, d), f in overrides.items():
        if s == symbol and f != 1:
            events.append({"symbol": symbol, "date": str(d), "factor": f, "ratio": None, "kind": "manual"})
    return sorted(events, key=lambda e: e["date"])


def apply(candles: List[Candle], events: List[Dict]) -> List[Candle]:
    if not events:
        return candles
    out = []
    for c in candles:
        f = 1.0
        for e in events:
            if c.ts.date() < date.fromisoformat(e["date"]):
                f *= e["factor"]
        if f == 1.0:
            out.append(c)
        else:
            out.append(Candle(c.ts, round(c.open / f, 4), round(c.high / f, 4), round(c.low / f, 4),
                              round(c.close / f, 4), c.volume * f))
    return out


def adjust_all(data: Dict[str, List[Candle]]) -> Tuple[Dict[str, List[Candle]], List[Dict]]:
    ov = load_overrides()
    out, all_events = {}, []
    for s, cs in data.items():
        ev = detect(s, cs, ov)
        all_events += ev
        out[s] = apply(cs, ev)
    return out, all_events
