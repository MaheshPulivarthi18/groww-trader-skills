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
    # Setups to run. If your config has a "setups" block, ONLY the setups
    # named there run (each filled in from SETUP_DEFAULTS). A setup may carry
    # its own "exit" block that overrides the global "exit" rules.
    "setups": {
        "orb": {"range_min": 15, "min_range_pct": 0.3, "max_range_pct": 3.0},
        "pdh_breakout": {"exit": {"stop": "level"}},
    },
    "exit": {
        "stop": "or_mid",        # or_mid | or_low | level | pct:0.8 | atr:1.5
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
    # Charge rates are percentages of turnover. Defaults follow Groww's
    # published equity pricing (groww.in/pricing/stocks, checked Nov 2026):
    # brokerage 0.1% capped at Rs 20 per order, min Rs 5. Re-check and override.
    "charges": {
        "brokerage_pct": 0.1,
        "brokerage_min": 5,
        "brokerage_max": 20,
        "exchange_txn_pct": 0.00307,
        "sebi_pct": 0.0001,
        "gst_pct": 18,
        "intraday": {"stt_sell_pct": 0.025, "stt_buy_pct": 0.0, "stamp_buy_pct": 0.003},
        "delivery": {"stt_sell_pct": 0.1, "stt_buy_pct": 0.1, "stamp_buy_pct": 0.015, "dp_per_sell": 20},
    },
    "slippage_pct": 0.03,      # per side, applied in backtests and paper trading
    "fills": {
        "entry": "open",                    # "open" or "mid" (stress test: halfway to the bar's worst price)
        "target_trade_through_ticks": 1,    # a target (limit order) fills only if price trades beyond it
        "stop_extra_slippage_pct": 0.05,    # stops are market orders: extra slippage on top
    },
    "paper_trading": {
        "max_signal_age_min": 10,  # ignore triggers older than this when first seen
    },
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


# Parameters for every setup the code knows; DEFAULTS["setups"] is only the
# list that runs when the config doesn't name any.
SETUP_DEFAULTS: Dict[str, Any] = {
    **copy.deepcopy(DEFAULTS["setups"]),
    "orb_fade": {"range_min": 15, "min_range_pct": 0.3, "max_range_pct": 3.0, "max_bars_outside": 3,
                 "exit": {"stop": "setup"}},
    "vwap_reclaim": {"min_bars_away": 3, "exit": {"stop": "setup"}},
}


def load_config(path: str | os.PathLike | None = None) -> Dict[str, Any]:
    p = Path(path) if path else home() / "config.json"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        user.pop("_comment", None)
        user_setups = user.pop("setups", None)
        cfg = _merge(DEFAULTS, user)
        if user_setups is not None:  # the user's list replaces the default list
            cfg["setups"] = {name: _merge(SETUP_DEFAULTS.get(name, {}), params or {})
                             for name, params in user_setups.items()}
        return cfg
    return copy.deepcopy(DEFAULTS)


def setup_params(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Parameters for one setup, even if it isn't in the active list (e.g.
    `backtest --setup pdh_breakout` with a config that only runs orb)."""
    return _merge(SETUP_DEFAULTS.get(name, {}), (cfg.get("setups") or {}).get(name) or {})


def exit_rules(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Global exit rules with the setup's own overrides applied."""
    return {**cfg["exit"], **(setup_params(cfg, name).get("exit") or {})}


def override_exit(cfg: Dict[str, Any], name: str, stop=None, target=None) -> None:
    """Command-line --stop/--target win over both global and per-setup rules."""
    for k, v in (("stop", stop), ("target", target)):
        if v:
            cfg["exit"][k] = v
            cfg.setdefault("setups", {}).setdefault(name, setup_params(cfg, name))
            cfg["setups"][name].setdefault("exit", {})[k] = v


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
