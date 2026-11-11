"""Free official daily data from NSE's bhavcopy files.

NSE publishes one file per trading day with every listed security's open,
high, low, close, previous close and volume, free, back to the 1990s. Using
it means daily strategies (swing, portfolio) can be tested over many years
without a Groww account and without Groww's history limits.

Two formats, both handled:
  * since 8 July 2024 (UDiFF): content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
    columns TckrSymb, SctySrs, OpnPric, HghPric, LwPric, ClsPric, PrvsClsgPric, TtlTradgVol
  * before that: content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
    columns SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, PREVCLOSE, TOTTRDQTY

Corporate actions come from NSE itself: on an ex-date (split, bonus,
rights), NSE publishes the previous close already ADJUSTED, so it differs
from the actual close of the day before. The ratio between the two is the
official adjustment factor; earlier prices are divided by it. Ordinary
dividends don't change the previous close, so they aren't adjusted (as in
most price series).

Downloads are polite (a pause between files) and cached per day as small
gzipped CSVs of equity rows, so each day is fetched once. NSE sometimes
refuses requests from scripts or cloud servers; the result says so.
"""

from __future__ import annotations

import csv
import gzip
import io
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .market import IST, Candle

BASE = "https://nsearchives.nseindia.com"
UDIFF_FROM = date(2024, 7, 8)
SERIES = ("EQ", "BE", "BZ")          # equity series kept (EQ normal, BE/BZ trade-for-trade)
MIN_ACTION = 0.02                    # previous-close differences under 2% are ignored
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

COLS = {
    "symbol": ("TckrSymb", "SYMBOL"),
    "series": ("SctySrs", "SERIES"),
    "open": ("OpnPric", "OPEN"),
    "high": ("HghPric", "HIGH"),
    "low": ("LwPric", "LOW"),
    "close": ("ClsPric", "CLOSE"),
    "prev": ("PrvsClsgPric", "PREVCLOSE"),
    "volume": ("TtlTradgVol", "TOTTRDQTY"),
}


def urls(d: date) -> List[str]:
    new = f"{BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    old = f"{BASE}/content/historical/EQUITIES/{d.year}/{MON[d.month - 1]}/cm{d.day:02d}{MON[d.month - 1]}{d.year}bhav.csv.zip"
    return [new, old] if d >= UDIFF_FROM else [old, new]


def parse_bhav(raw: bytes) -> List[Dict[str, object]]:
    """Equity rows from one bhavcopy (zip or plain CSV, either format)."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            raw = z.read(name)
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip(): f for f in (reader.fieldnames or [])}
    pick = {}
    for key, options in COLS.items():
        for o in options:
            if o in fields:
                pick[key] = fields[o]
                break
    missing = [k for k in ("symbol", "series", "open", "high", "low", "close") if k not in pick]
    if missing:
        raise ValueError(f"unrecognised bhavcopy columns (missing {missing}); NSE may have changed the format")
    out = []
    for row in reader:
        series = (row.get(pick["series"]) or "").strip().upper()
        if series not in SERIES:
            continue
        try:
            rec = {"symbol": row[pick["symbol"]].strip().upper(), "series": series,
                   **{k: float(row[pick[k]]) for k in ("open", "high", "low", "close")}}
            rec["prev"] = float(row[pick["prev"]]) if "prev" in pick and row.get(pick["prev"]) else None
            rec["volume"] = float(row[pick["volume"]]) if "volume" in pick and row.get(pick["volume"]) else 0.0
        except (ValueError, TypeError, KeyError):
            continue
        if rec["close"] > 0:
            out.append(rec)
    return out


def day_file(folder: Path, d: date) -> Path:
    return folder / f"{d:%Y%m%d}.csv.gz"


def save_day(folder: Path, d: date, rows: List[Dict[str, object]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with gzip.open(day_file(folder, d), "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "series", "open", "high", "low", "close", "prev", "volume"])
        for r in rows:
            w.writerow([r["symbol"], r["series"], r["open"], r["high"], r["low"], r["close"],
                        "" if r["prev"] is None else r["prev"], r["volume"]])


def load_day(folder: Path, d: date) -> List[Dict[str, object]]:
    with gzip.open(day_file(folder, d), "rt", encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({"symbol": r["symbol"], "series": r["series"],
                         **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")},
                         "prev": float(r["prev"]) if r["prev"] else None})
        return rows


def _http_get(url: str, timeout: float = 25.0) -> Tuple[int, bytes]:  # pragma: no cover - network
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return -1, str(e).encode()


def fetch(folder: Path, start: date, end: date, pause: float = 0.6,
          get: Callable[[str], Tuple[int, bytes]] = _http_get, log=print) -> Dict[str, object]:
    """Download every weekday's bhavcopy in [start, end] not already cached.
    404 on both URLs = no trading that day (holiday). Stops early if NSE
    keeps refusing (403/blocked), so it doesn't hammer the site."""
    got, cached, holidays, failed = 0, 0, 0, []
    refused_in_a_row = 0
    hol_file = folder / "no_trading_days.txt"   # weekdays NSE had no file for (holidays), not re-asked
    known_hol = set(hol_file.read_text().split()) if hol_file.exists() else set()
    today = datetime.now(tz=IST).date()
    d = start
    while d <= end:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        if day_file(folder, d).exists() or str(d) in known_hol:
            cached += 1
            d += timedelta(days=1)
            continue
        statuses = []
        for u in urls(d):
            status, body = get(u)
            statuses.append(status)
            if status == 200 and body:
                try:
                    save_day(folder, d, parse_bhav(body))
                    got += 1
                except (ValueError, zipfile.BadZipFile, StopIteration) as e:
                    failed.append({"date": str(d), "error": str(e)[:120]})
                break
            if pause:
                time.sleep(pause / 2)
        else:
            if all(s == 404 for s in statuses):
                holidays += 1
                refused_in_a_row = 0
                if d < today - timedelta(days=3):  # recent days may simply not be published yet
                    folder.mkdir(parents=True, exist_ok=True)
                    with open(hol_file, "a") as f:
                        f.write(f"{d}\n")
            else:
                failed.append({"date": str(d), "status": statuses})
                refused_in_a_row = refused_in_a_row + 1 if any(s in (401, 403, -1) for s in statuses) else 0
                if refused_in_a_row >= 5:
                    return {"downloaded": got, "already_cached": cached, "holidays": holidays, "failed": failed,
                            "stopped": "NSE refused 5 days in a row (blocked or offline). Try later, from "
                                       "another network, or download the files in a browser."}
        if got and got % 50 == 0:
            log(f"... {got} days downloaded (at {d})")
        if pause:
            time.sleep(pause)
        d += timedelta(days=1)
    return {"downloaded": got, "already_cached": cached, "holidays": holidays, "failed": failed}


def build(folder: Path, symbols: Iterable[str]) -> Tuple[Dict[str, List[Candle]], List[Dict[str, object]]]:
    """Daily candles per symbol from the cached days, adjusted for corporate
    actions with NSE's own previous close. Returns (candles, actions)."""
    want = {s.upper() for s in symbols}
    raw: Dict[str, List[Tuple[date, Dict[str, object]]]] = {s: [] for s in want}
    for p in sorted(folder.glob("*.csv.gz")):
        d = datetime.strptime(p.name[:8], "%Y%m%d").date()
        for r in load_day(folder, d):
            if r["symbol"] in want:
                raw[r["symbol"]].append((d, r))
    out: Dict[str, List[Candle]] = {}
    actions: List[Dict[str, object]] = []
    for sym, rows in raw.items():
        rows.sort(key=lambda x: x[0])
        events = []
        for (d0, a), (d1, b) in zip(rows, rows[1:]):
            if b["prev"] and a["close"]:
                factor = a["close"] / b["prev"]
                if abs(factor - 1) > MIN_ACTION:
                    events.append((d1, factor))
                    actions.append({"symbol": sym, "date": str(d1), "factor": round(factor, 4),
                                    "close_before": a["close"], "nse_adjusted_prev_close": b["prev"]})
        candles = []
        for d, r in rows:
            f = 1.0
            for ed, fac in events:
                if d < ed:
                    f *= fac
            ts = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
            candles.append(Candle(ts, round(r["open"] / f, 4), round(r["high"] / f, 4), round(r["low"] / f, 4),
                                  round(r["close"] / f, 4), r["volume"] * f))
        if candles:
            out[sym] = candles
    return out, actions
