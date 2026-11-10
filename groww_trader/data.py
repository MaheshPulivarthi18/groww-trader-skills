"""Market data sources.

GrowwSource  - the official `growwapi` SDK, using the user's OWN credentials
               from environment variables. Read-only calls only.
CSVSource    - cached candles in trader/data/<SYMBOL>_<interval>m.csv, so
               scanning and backtesting work offline and are repeatable.

Credentials (environment variables, never files or chat):
  GROWW_TOTP_TOKEN + GROWW_TOTP_SECRET    TOTP flow, best for unattended use (needs pyotp)
  GROWW_API_KEY + GROWW_API_SECRET        key/secret flow (needs daily approval), or
  GROWW_ACCESS_TOKEN                      a ready access token (expires daily)
"""

from __future__ import annotations

import csv
import os
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .config import data_dir
from .market import IST, Candle, parse_ts

# Groww SDK constant names per interval (minutes). Resolved at runtime so a
# renamed constant fails with a clear message instead of a silent default.
_INTERVAL_CONSTS = {
    1: "CANDLE_INTERVAL_MIN_1", 2: "CANDLE_INTERVAL_MIN_2", 3: "CANDLE_INTERVAL_MIN_3",
    5: "CANDLE_INTERVAL_MIN_5", 10: "CANDLE_INTERVAL_MIN_10", 15: "CANDLE_INTERVAL_MIN_15",
    30: "CANDLE_INTERVAL_MIN_30", 60: "CANDLE_INTERVAL_HOUR_1", 240: "CANDLE_INTERVAL_HOUR_4",
    1440: "CANDLE_INTERVAL_DAY", 10080: "CANDLE_INTERVAL_WEEK",
}


def max_days_per_request(interval_min: int) -> int:
    """Groww's documented per-request limits for historical candles."""
    if interval_min <= 5:
        return 30
    if interval_min <= 30:
        return 90
    return 180


def interval_tag(interval_min: int) -> str:
    return "1d" if interval_min == 1440 else f"{interval_min}m"


def csv_path(symbol: str, interval_min: int, folder: Optional[Path] = None) -> Path:
    return (folder or data_dir()) / f"{symbol.upper()}_{interval_tag(interval_min)}.csv"


def save_csv(candles: Sequence[Candle], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts.strftime("%Y-%m-%d %H:%M:%S"), c.open, c.high, c.low, c.close, c.volume])
    return path


def load_csv(path: Path) -> List[Candle]:
    out: List[Candle] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(Candle(parse_ts(row["timestamp"]), float(row["open"]), float(row["high"]),
                              float(row["low"]), float(row["close"]), float(row.get("volume") or 0)))
    out.sort(key=lambda c: c.ts)
    return out


def merge_candles(*lists: Iterable[Candle]) -> List[Candle]:
    seen: Dict[datetime, Candle] = {}
    for lst in lists:
        for c in lst:
            seen[c.ts] = c
    return [seen[k] for k in sorted(seen)]


class CSVSource:
    name = "csv"

    def __init__(self, folder: Optional[Path] = None):
        self.folder = Path(folder) if folder else data_dir()

    def candles(self, symbol: str, interval_min: int, start: datetime, end: datetime) -> List[Candle]:
        p = csv_path(symbol, interval_min, self.folder)
        if not p.exists():
            raise FileNotFoundError(
                f"No cached candles for {symbol} ({interval_tag(interval_min)}) at {p}. "
                f"Run: gtrade.py fetch {symbol} --interval {interval_min}")
        return [c for c in load_csv(p) if start <= c.ts <= end]

    def ltp(self, symbols: Sequence[str]) -> Dict[str, float]:
        out = {}
        for s in symbols:
            p = csv_path(s, 5, self.folder)
            if p.exists():
                rows = load_csv(p)
                if rows:
                    out[s.upper()] = rows[-1].close
        return out


class GrowwSource:
    name = "groww"

    def __init__(self, exchange: str = "NSE", segment: str = "CASH"):
        try:
            from growwapi import GrowwAPI  # type: ignore
        except ImportError as e:  # pragma: no cover - depends on user env
            raise RuntimeError("The official Groww SDK is not installed: pip install growwapi") from e
        self._GrowwAPI = GrowwAPI
        self.client = GrowwAPI(self._access_token(GrowwAPI))
        self.exchange = exchange
        self.segment = segment

    @staticmethod
    def _access_token(GrowwAPI) -> str:  # pragma: no cover - needs real credentials
        tok = os.environ.get("GROWW_ACCESS_TOKEN", "").strip()
        if tok:
            return tok
        if os.environ.get("GROWW_TOTP_SECRET", "").strip():
            # TOTP flow: Groww's "TOTP token" goes in as the api_key.
            token = (os.environ.get("GROWW_TOTP_TOKEN") or os.environ.get("GROWW_API_KEY") or "").strip()
            if not token:
                raise RuntimeError("TOTP flow needs GROWW_TOTP_TOKEN (the 'TOTP token' Groww shows) "
                                   "alongside GROWW_TOTP_SECRET.")
            code = current_totp(os.environ["GROWW_TOTP_SECRET"])  # validates the secret first
            return GrowwAPI.get_access_token(api_key=token, totp=code)
        key = os.environ.get("GROWW_API_KEY", "").strip()
        secret = os.environ.get("GROWW_API_SECRET", "").strip()
        if key and secret:
            return GrowwAPI.get_access_token(api_key=key, secret=secret)
        raise RuntimeError(
            "No usable Groww credentials. Set one of: GROWW_ACCESS_TOKEN; "
            "GROWW_TOTP_TOKEN + GROWW_TOTP_SECRET; or GROWW_API_KEY + GROWW_API_SECRET.")

    def _interval_const(self, interval_min: int):
        name = _INTERVAL_CONSTS.get(interval_min)
        if name and hasattr(self.client, name):
            return getattr(self.client, name)
        have = sorted(a for a in dir(self.client) if a.startswith("CANDLE_INTERVAL"))
        raise ValueError(f"Interval {interval_min}m not available in this growwapi version. Have: {have}")

    def _const(self, prefix: str, value: str):
        return getattr(self.client, f"{prefix}_{value.upper()}", value.upper())

    def candles(self, symbol: str, interval_min: int, start: datetime, end: datetime) -> List[Candle]:  # pragma: no cover
        step = timedelta(days=max_days_per_request(interval_min))
        out: List[Candle] = []
        t0 = start
        while t0 < end:
            t1 = min(t0 + step, end)
            resp = self.client.get_historical_candles(
                exchange=self._const("EXCHANGE", self.exchange),
                segment=self._const("SEGMENT", self.segment),
                groww_symbol=f"{self.exchange.upper()}-{symbol.upper()}",
                start_time=t0.strftime("%Y-%m-%d %H:%M:%S"),
                end_time=t1.strftime("%Y-%m-%d %H:%M:%S"),
                candle_interval=self._interval_const(interval_min),
            )
            for row in (resp or {}).get("candles") or []:
                ts, o, h, l, c = row[:5]
                v = row[5] if len(row) > 5 and row[5] is not None else 0
                out.append(Candle(parse_ts(ts), float(o), float(h), float(l), float(c), float(v)))
            t0 = t1
            _time.sleep(0.25)  # be polite to the API
        return merge_candles(out)

    def ltp(self, symbols: Sequence[str]) -> Dict[str, float]:  # pragma: no cover
        out: Dict[str, float] = {}
        keys = [f"{self.exchange.upper()}_{s.upper()}" for s in symbols]
        for i in range(0, len(keys), 50):  # documented limit: 50 per call
            chunk = tuple(keys[i:i + 50])
            resp = self.client.get_ltp(segment=self._const("SEGMENT", self.segment),
                                       exchange_trading_symbols=chunk if len(chunk) > 1 else chunk[0])
            for k, v in (resp or {}).items():
                out[k.split("_", 1)[1]] = float(v)
        return out


_B32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def normalize_totp_secret(raw: str) -> str:
    """Clean a TOTP secret as copied from a website: drop spaces, dashes,
    quotes and '=' padding, uppercase it, and check it's valid base32.
    Errors never include the secret itself."""
    s = "".join(ch for ch in str(raw) if ch not in " \t\r\n-'\"=").upper()
    if not s:
        raise RuntimeError("GROWW_TOTP_SECRET is empty.")
    bad = sorted({ch for ch in s if ch not in _B32})
    if bad:
        hint = ""
        if any(ch in "._" for ch in bad):
            hint = (" It contains '.' or '_' , so it looks like the TOTP *token* or a placeholder, "
                    "not the secret. Check you didn't swap GROWW_TOTP_TOKEN and GROWW_TOTP_SECRET.")
        elif set(bad) <= set("0189"):
            hint = " It contains 0, 1, 8 or 9, which never appear in a TOTP secret; re-copy it from Groww."
        raise RuntimeError(f"GROWW_TOTP_SECRET is not a valid TOTP secret ({len(s)} chars, "
                           f"{len(bad)} kind(s) of invalid character).{hint} A TOTP secret uses only "
                           "letters A-Z and digits 2-7.")
    return s + "=" * (-len(s) % 8)


def current_totp(raw_secret: str) -> str:
    secret = normalize_totp_secret(raw_secret)
    try:
        import pyotp  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("The TOTP flow needs pyotp: pip install pyotp") from e
    return pyotp.TOTP(secret).now()


def has_groww_credentials() -> bool:
    return any(os.environ.get(k, "").strip() for k in
               ("GROWW_ACCESS_TOKEN", "GROWW_API_KEY", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET"))


def get_source(kind: str = "auto", exchange: str = "NSE"):
    if kind == "csv" or (kind == "auto" and not has_groww_credentials()):
        return CSVSource()
    return GrowwSource(exchange=exchange)


def lookback_window(days: int, until: Optional[date] = None):
    end_d = until or datetime.now(tz=IST).date()
    end = datetime.combine(end_d, datetime.max.time().replace(microsecond=0), tzinfo=IST)
    start = datetime.combine(end_d - timedelta(days=days), datetime.min.time(), tzinfo=IST)
    return start, end
