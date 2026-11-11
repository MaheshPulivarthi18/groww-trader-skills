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
import math
import statistics
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


def t_stat(nets: List[float]) -> Optional[float]:
    """Average trade divided by its standard error: how many 'standard
    errors' the average is away from zero."""
    if len(nets) < 3:
        return None
    sd = statistics.stdev(nets)
    return round(statistics.mean(nets) / (sd / math.sqrt(len(nets))), 2) if sd else None


def luck_bar(n_variants: int) -> float:
    """Roughly how far the BEST of n variations with no edge at all lands by
    luck alone, in standard errors (expected maximum of n standard normals,
    about sqrt(2 ln n)). A pick has to clear this to stand out from chance."""
    return round(math.sqrt(2 * math.log(n_variants)), 2) if n_variants > 1 else 0.0


def luck_check(pick: Optional[Dict[str, Any]], n_variants: int) -> Dict[str, Any]:
    bar = luck_bar(n_variants)
    t = (pick or {}).get("train", {}).get("t_stat")
    out = {"variants_tried": n_variants, "luck_bar_t": bar, "pick_train_t": t}
    if t is None:
        out["note"] = "too few trades to judge"
    elif t <= 0:
        out["clears_luck_bar"] = False
        out["note"] = f"The pick lost money on the train period ({t} standard errors): there's no edge to test."
    else:
        out["clears_luck_bar"] = t > bar
        out["note"] = (f"With {n_variants} variations tried, the best one typically looks about {bar} standard "
                       f"errors better than zero by luck alone. The pick's train result is {t}: "
                       + ("it stands out from luck." if t > bar else "that's within what luck produces."))
    return out


def _summ(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = stats(trades)
    keys = ("trades", "win_rate_pct", "net_total", "charges_total", "avg_net", "profit_factor", "max_drawdown")
    if not s.get("trades"):
        return {"trades": 0, "net_total": 0.0}
    return {**{k: s.get(k) for k in keys}, "t_stat": t_stat([t["net"] for t in trades])}


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
        "luck_check": luck_check(best, len(rows)),
        "all": rows,
    }


def walk_forward(candles_by_symbol: Dict[str, List[Candle]], cfg: Dict[str, Any], interval_min: int,
                 variants_list: List[Dict[str, Any]], train_sessions: int = 120, test_sessions: int = 40,
                 min_trades: int = 10) -> Dict[str, Any]:
    """Re-run the whole 'pick the best variation' process again and again:
    choose on `train_sessions`, trade the pick on the next `test_sessions`,
    roll forward by `test_sessions`. The joined test results are what the
    search itself would have earned, never judged on data it chose from."""
    days = sorted({d for cs in candles_by_symbol.values() for d in by_session(cs)})
    if len(days) < train_sessions + test_sessions:
        raise ValueError(f"only {len(days)} sessions; walk-forward needs at least "
                         f"{train_sessions + test_sessions} (fetch more or use smaller windows)")
    by_variant = []
    for v in variants_list:  # each variation run once over everything
        c = _apply(cfg, v)
        trades = []
        for sym, candles in candles_by_symbol.items():
            try:
                trades += [{**t, "symbol": sym} for t in run_backtest(sym, candles, v["setup"], c, interval_min)["trades"]]
            except ValueError:
                continue
        by_variant.append((v, trades))
    folds, oos = [], []
    start = 0
    while start + train_sessions + test_sessions <= len(days):
        tr_days = days[start:start + train_sessions]
        te_days = days[start + train_sessions:start + train_sessions + test_sessions]
        tr_a, tr_b, te_a, te_b = str(tr_days[0]), str(tr_days[-1]), str(te_days[0]), str(te_days[-1])
        scored = []
        for v, trades in by_variant:
            tr = [t for t in trades if tr_a <= t["day"] <= tr_b]
            if len(tr) >= min_trades:
                scored.append((sum(t["net"] for t in tr), v, trades, len(tr)))
        if scored:
            net, v, trades, n = max(scored, key=lambda x: x[0])
            te = [t for t in trades if te_a <= t["day"] <= te_b]
            oos += te
            folds.append({"train": [tr_a, tr_b], "test": [te_a, te_b], "pick": v,
                          "train_net": round(net, 2), "train_trades": n,
                          "test_net": round(sum(t["net"] for t in te), 2), "test_trades": len(te)})
        start += test_sessions
    total = round(sum(t["net"] for t in oos), 2)
    positive = sum(1 for f in folds if f["test_net"] > 0)
    if not folds:
        verdict_wf = "No window had enough trades to choose a pick."
    elif total <= 0:
        verdict_wf = (f"Picking the best variation and trading it next LOST money overall out of sample "
                      f"(Rs {total:,.0f} over {len(folds)} windows, {positive} positive). The search finds no edge.")
    else:
        verdict_wf = (f"The search made Rs {total:,.0f} out of sample across {len(folds)} windows ({positive} "
                      "positive). Worth paper-tracking; check the picks are consistent rather than jumping around.")
    return {"windows": len(folds), "train_sessions": train_sessions, "test_sessions": test_sessions,
            "variants_tried": len(variants_list), "folds": folds,
            "out_of_sample": _summ(oos), "positive_windows": positive, "verdict": verdict_wf}


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
