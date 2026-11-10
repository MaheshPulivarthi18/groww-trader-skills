"""Honest rule search: try many rule variations, choose on the EARLIER part
of the data (train), and report how the choices did on the LATER part they
never saw (test).

Trying many variations and keeping the best one finds something that looked
good by luck. Splitting by date is the simplest guard: a rule that only
worked by chance on the train period usually falls apart on the test period.
"""

from __future__ import annotations

import copy
import itertools
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from .backtest import run as run_backtest
from .backtest import stats
from .config import override_exit, setup_params
from .market import Candle, by_session

# Stops that make sense for each setup.
STOPS_FOR = {
    "orb": ("or_mid", "or_low", "pct:0.5", "pct:1", "atr:1.5"),
    "pdh_breakout": ("level", "pct:0.5", "pct:1", "atr:1.5"),
    "orb_fade": ("setup", "pct:0.5", "pct:1", "atr:1.5"),
    "vwap_reclaim": ("setup", "pct:0.5", "pct:1", "atr:1.5"),
}
RANGE_SETUPS = ("orb", "orb_fade")


def split_day(candles_by_symbol: Dict[str, List[Candle]], train_frac: float) -> date:
    days = sorted({d for cs in candles_by_symbol.values() for d in by_session(cs)})
    if len(days) < 10:
        raise ValueError(f"only {len(days)} sessions of data; fetch more (gtrade.py fetch --days 90)")
    k = min(len(days) - 1, max(1, int(len(days) * train_frac)))
    return days[k]


def variants(setups: Iterable[str], stops: Optional[List[str]], targets: List[str],
             ranges: Optional[List[int]]) -> List[Dict[str, Any]]:
    out = []
    for setup in setups:
        allowed = STOPS_FOR.get(setup, ())
        use_stops = [s for s in (stops or allowed) if s in allowed or s.startswith(("pct:", "atr:"))]
        use_ranges = ranges if (setup in RANGE_SETUPS and ranges) else [None]
        for stop, target, rng in itertools.product(use_stops, targets, use_ranges):
            out.append({"setup": setup, "stop": stop, "target": target, "range_min": rng})
    return out


def _apply(cfg: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
    c = copy.deepcopy(cfg)
    c.setdefault("setups", {})[v["setup"]] = setup_params(c, v["setup"])
    if v.get("range_min"):
        c["setups"][v["setup"]]["range_min"] = v["range_min"]
    override_exit(c, v["setup"], v["stop"], v["target"])
    return c


def _summ(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = stats(trades)
    keys = ("trades", "win_rate_pct", "net_total", "charges_total", "avg_net", "profit_factor", "max_drawdown")
    return {k: s.get(k) for k in keys} if s.get("trades") else {"trades": 0, "net_total": 0.0}


def sweep(candles_by_symbol: Dict[str, List[Candle]], cfg: Dict[str, Any], interval_min: int,
          variants_list: List[Dict[str, Any]], train_frac: float = 0.6, min_trades: int = 10,
          top: int = 5) -> Dict[str, Any]:
    cut = split_day(candles_by_symbol, train_frac)
    rows = []
    for v in variants_list:
        c = _apply(cfg, v)
        tr_trades, te_trades, errors = [], [], 0
        for sym, candles in candles_by_symbol.items():
            try:
                tr = run_backtest(sym, candles, v["setup"], c, interval_min, to_day=date.fromordinal(cut.toordinal() - 1))
                te = run_backtest(sym, candles, v["setup"], c, interval_min, from_day=cut)
            except ValueError:
                errors += 1
                continue
            tr_trades += [{**t, "symbol": sym} for t in tr["trades"]]
            te_trades += [{**t, "symbol": sym} for t in te["trades"]]
        rows.append({"rule": v, "train": _summ(tr_trades), "test": _summ(te_trades), "errors": errors})

    eligible = [r for r in rows if r["train"]["trades"] >= min_trades]
    ranked = sorted(eligible, key=lambda r: r["train"]["net_total"], reverse=True)
    best = ranked[0] if ranked else None
    profitable_train = sum(1 for r in eligible if r["train"]["net_total"] > 0)
    held_up = sum(1 for r in ranked[:top] if r["test"]["net_total"] > 0)
    return {
        "symbols": sorted(candles_by_symbol),
        "split": {"train_until": str(date.fromordinal(cut.toordinal() - 1)), "test_from": str(cut),
                  "train_frac": train_frac},
        "variants_tested": len(rows),
        "eligible": len(eligible),
        "min_trades": min_trades,
        "profitable_on_train": profitable_train,
        "top": ranked[:top],
        "pick": best,
        "verdict": verdict(best, held_up, min(top, len(ranked))),
        "all": rows,
    }


def verdict(best: Optional[Dict[str, Any]], held_up: int, shown: int,
            next_step: str = "Worth paper trading for 2-3 weeks.") -> str:
    if not best:
        return "No variation produced enough trades on the train period to judge."
    tr, te = best["train"], best["test"]
    if tr["net_total"] <= 0:
        return "Even the best variation lost money on the train period, after charges. No edge found."
    if te["trades"] < 10:
        return ("The pick made money on the train period but the test period has too few trades "
                f"({te['trades']}) to confirm it. Fetch more history before trusting it.")
    if te["net_total"] <= 0:
        return ("The pick made money on the train period but LOST on the unseen test period: "
                "most likely luck. Don't paper trade it on this evidence.")
    return (f"The pick made money on both periods ({held_up} of the top {shown} held up on test). "
            f"{next_step} Still not proof: markets change.")
