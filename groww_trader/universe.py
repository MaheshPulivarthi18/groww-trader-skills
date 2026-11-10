"""Stock universes for portfolio strategies.

  nifty50 / nifty100 / nifty200 / nifty500   NSE's current constituent list,
        downloaded from niftyindices.com and cached in trader/universe_<name>.csv
  path/to/file.csv                           a CSV with a "Symbol" column (NSE's
        own download format), or a .txt file with one symbol per line
  RELIANCE,TCS,INFY                          a comma-separated list

These are TODAY's index members. Testing them over past years leaves out
companies that dropped out of the index (often after falling), which makes
past results look better than they were: survivorship bias. Reports say so.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from pathlib import Path
from typing import List, Tuple

from .config import home

NSE_LISTS = {
    "nifty50": "ind_nifty50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv",
}
NSE_URL = "https://www.niftyindices.com/IndexConstituent/{file}"


def parse_symbols(text: str) -> List[str]:
    """Symbols from NSE's CSV (column "Symbol") or one-per-line text."""
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    if "symbol" in first.lower() and "," in first:
        rows = csv.DictReader(io.StringIO(text))
        key = next((k for k in rows.fieldnames or [] if k.strip().lower() == "symbol"), None)
        syms = [r[key].strip().upper() for r in rows if key and r.get(key)]
    else:
        syms = [ln.split(",")[0].strip().upper() for ln in text.splitlines()]
    seen, out = set(), []
    for s in syms:
        if s and not s.startswith("#") and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _download(file: str) -> str:  # pragma: no cover - network
    req = urllib.request.Request(NSE_URL.format(file=file), headers={
        "User-Agent": "Mozilla/5.0 (groww-trader-skills)", "Accept": "text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def load(spec: str) -> Tuple[List[str], str]:
    """Return (symbols, description)."""
    spec = spec.strip()
    key = spec.lower()
    if key in NSE_LISTS:
        cache = home() / f"universe_{key}.csv"
        if not cache.exists():
            try:
                cache.write_text(_download(NSE_LISTS[key]), encoding="utf-8")
            except Exception as e:
                raise RuntimeError(
                    f"Couldn't download the {key} list ({e}). Download {NSE_LISTS[key]} from "
                    f"niftyindices.com yourself and save it as {cache}, or pass --universe path/to/file.csv"
                ) from e
        syms = parse_symbols(cache.read_text(encoding="utf-8"))
        if len(syms) < 10:
            raise RuntimeError(f"{cache} doesn't look like an NSE constituent list; delete it and retry")
        return syms, f"{key} (today's members, {len(syms)} stocks)"
    p = Path(spec).expanduser()
    if p.suffix.lower() in (".csv", ".txt") or p.exists():
        if not p.exists():
            raise RuntimeError(f"universe file {p} not found")
        syms = parse_symbols(p.read_text(encoding="utf-8"))
        return syms, f"{p.name} ({len(syms)} stocks)"
    syms = [s.strip().upper() for s in spec.split(",") if s.strip()]
    return syms, f"{len(syms)} listed stocks"
