"""Config and working-folder handling.

Everything a skill writes lands in a `trader/` folder in the user's current
project (override with GTRADE_HOME). Each skill reads what the previous one
wrote: scan.json -> plan.json -> orders.json.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "paper": True,
    "capital": 100000,
    "watchlist": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN"],
    "exchange": "NSE",
    "product": "MIS",            # MIS = intraday, CNC = delivery
    "allow_short": False,
    "interval_min": 5,
    "setups": {
        "orb": {"range_min": 15, "min_range_pct": 0.3, "max_range_pct": 3.0},
        "pdh_breakout": {},
    },
    "exit": {
        "stop": "or_mid",        # or_mid | or_low | pct:0.8 | atr:1.5
        "target": "1.5R",        # <n>R
        "flat_by": "15:10",      # be flat well before Groww's MIS auto square-off
    },
    "risk": {
        "max_loss_per_trade": 500,     # rupees, at the stop, incl. charges
        "daily_loss_limit": 1500,      # rupees; no new trades once hit
        "max_trades_per_day": 3,
        "max_open_positions": 2,
        "min_reward_risk": 1.0,
        "max_position_pct": 25,        # of capital, per position
        "no_entry_before": "09:30",
        "no_entry_after": "14:30",
    },
    # Charge rates are percentages of turnover. Defaults reflect common NSE
    # equity rates; CHECK YOUR BROKER'S CURRENT PRICING PAGE and override.
    "charges": {
        "brokerage_pct": 0.05,
        "brokerage_min": 5,
        "brokerage_max": 20,
        "exchange_txn_pct": 0.00297,
        "sebi_pct": 0.0001,
        "gst_pct": 18,
        "intraday": {"stt_sell_pct": 0.025, "stt_buy_pct": 0.0, "stamp_buy_pct": 0.003},
        "delivery": {"stt_sell_pct": 0.1, "stt_buy_pct": 0.1, "stamp_buy_pct": 0.015},
    },
    "slippage_pct": 0.02,      # per side, applied in backtests
}


def home() -> Path:
    p = Path(os.environ.get("GTRADE_HOME", "trader"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = home() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None) -> Dict[str, Any]:
    p = Path(path) if path else home() / "config.json"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        user.pop("_comment", None)
        return _merge(DEFAULTS, user)
    return copy.deepcopy(DEFAULTS)


def read_json(name: str, default=None):
    p = home() / name
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(name: str, obj) -> Path:
    p = home() / name
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
        f.write("\n")
    return p
