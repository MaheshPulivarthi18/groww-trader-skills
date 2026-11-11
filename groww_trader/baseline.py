"""Random-entry baseline: does the signal beat entering at a random time?

For every real trade, a "twin" is simulated on the same stock and side,
with the same rupee size, the same stop distance (as a % of price) and the
same target in R, but on a RANDOMLY CHOSEN OTHER SESSION of that stock in
the tested period, entered at a random bar inside the allowed entry window
(or, time-matched, near the same time of day as the real entry). Exits,
fills and charges follow exactly the backtest's rules. Repeating that many
times gives the range of results that chance produces. If the real rule
doesn't land clearly above that range, its entry signal adds nothing.

Why another day and not the same day: a random entry earlier on the real
trade's own day would "know" a breakout was coming (the real trade only
exists because one happened), which flatters the random side. Twins on
unrelated days can't see the future.

This isolates the ENTRY signal. A rule can beat random and still lose money
after charges; a rule that doesn't beat random has no edge to build on.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from .backtest import TICK, entry_price, exit_price, fill_params, walk_exit
from .config import exit_rules
from .costs import net_pnl
from .market import IST, Candle, by_session, parse_hhmm, parse_ts


def _window(cfg: Dict[str, Any], setup: str, day) -> tuple:
    r = cfg["risk"]
    flat = exit_rules(cfg, setup).get("flat_by", "15:10")
    at = lambda hhmm: datetime.combine(day, parse_hhmm(hhmm), tzinfo=IST)
    return at(r["no_entry_before"]), at(r["no_entry_after"]), at(flat)


def _minutes(ts) -> int:
    return ts.hour * 60 + ts.minute


def twin(trade: Dict[str, Any], bars: List[Candle], cfg: Dict[str, Any], setup: str,
         interval_min: int, rng: random.Random, window_min: Optional[int] = None) -> Optional[Dict[str, float]]:
    """One random-timed copy of `trade` on the session `bars` (another day)."""
    side = trade["side"]
    entry0, stop0, target0 = trade["entry"], trade["stop"], trade["target"]
    risk = abs(entry0 - stop0)
    if not risk or not entry0 or not bars:
        return None
    stop_pct = risk / entry0
    r_mult = abs(target0 - entry0) / risk
    first_ok, last_ok, flat = _window(cfg, setup, bars[0].ts.date())
    # the signal bar must close inside the window; we enter on the next bar
    choices = [k for k in range(len(bars) - 1)
               if first_ok <= bars[k].ts < last_ok and bars[k + 1].ts < flat]
    if window_min:  # time-matched: entries near the real entry's time of day
        real = _minutes(parse_ts(trade["entry_time"]))
        choices = [k for k in choices if abs(_minutes(bars[k + 1].ts) - real) <= window_min]
    if not choices:
        return None
    k = rng.choice(choices) + 1
    entry = entry_price(bars[k], side, cfg)
    long = side == "BUY"
    stop = entry * (1 - stop_pct) if long else entry * (1 + stop_pct)
    target = entry + r_mult * (entry - stop) if long else entry - r_mult * (stop - entry)
    through = fill_params(cfg)["target_trade_through_ticks"] * TICK
    hit = walk_exit(side, stop, target, flat, bars, k, interval_min, through=through)
    if hit is None:
        hit = (bars[-1].close, "session_end", bars[-1].ts)
    px, reason, _ = hit
    real_fill = trade.get("fill_entry") or entry0
    qty = max(1, round(trade["qty"] * real_fill / entry))  # same rupee size
    pnl = net_pnl(side, entry, exit_price(px, reason, side, cfg), qty, cfg["charges"],
                  cfg.get("product", "MIS"))
    return {"net": pnl["net"], "gross": pnl["gross"]}


def compare(trades: List[Dict[str, Any]], candles_by_symbol: Dict[str, List[Candle]],
            cfg: Dict[str, Any], setup: str, interval_min: int,
            runs: int = 500, seed: int = 11, window_min: Optional[int] = None) -> Dict[str, Any]:
    """Compare the real trades with `runs` sets of random twins on other days."""
    if len(trades) < 10:
        return {"note": "fewer than 10 trades: too few to compare with random entries"}
    first = min(t["day"] for t in trades)
    last = max(t["day"] for t in trades)
    pools = {}
    for s, c in candles_by_symbol.items():
        ses = by_session(c)
        pools[s] = [ses[d] for d in sorted(ses) if first <= str(d) <= last]
    rng = random.Random(seed)
    jobs = []
    for t in trades:
        pool = [b for b in pools.get(t["symbol"], []) if str(b[0].ts.date()) != t["day"]]
        if pool:
            jobs.append((t, pool))
    if len(jobs) < 10:
        return {"note": "price data for the trades' days is missing"}
    real_net = sum(t["net"] for t, _ in jobs)
    real_gross = sum(t["gross"] for t, _ in jobs)
    nets, grosses = [], []
    for _ in range(runs):
        n = g = 0.0
        for t, pool in jobs:
            r = None
            for _try in range(5):  # a random other day with a usable entry bar
                r = twin(t, rng.choice(pool), cfg, setup, interval_min, rng, window_min)
                if r is not None:
                    break
            if r is None:  # no other entry bar that day: count the real trade
                r = {"net": t["net"], "gross": t["gross"]}
            n += r["net"]
            g += r["gross"]
        nets.append(n)
        grosses.append(g)
    nets.sort()
    grosses.sort()
    pct = lambda xs, q: round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)
    as_good = sum(1 for x in nets if x >= real_net) / runs
    beat = as_good <= 0.05
    worse = sum(1 for x in nets if x <= real_net) / runs <= 0.05
    if beat:
        verdict = ("The rule beat random entry timing (only {:.0%} of random runs did as well). "
                   "Its entry signal carries information; whether that survives charges is "
                   "the net figure.".format(as_good))
    elif worse:
        verdict = ("The rule did WORSE than random entry timing ({:.0%} of random runs did "
                   "as well or better). Its entries are systematically badly timed.".format(as_good))
    else:
        verdict = ("No evidence the rule beats random entry timing: {:.0%} of random runs "
                   "did as well or better. The entry signal adds nothing measurable; results "
                   "come from the exits, the costs and chance.".format(as_good))
    return {
        "trades_compared": len(jobs),
        "runs": runs,
        "seed": seed,
        "real": {"net": round(real_net, 2), "gross": round(real_gross, 2)},
        "random_net": {"p05": pct(nets, 0.05), "median": pct(nets, 0.5), "p95": pct(nets, 0.95)},
        "random_gross": {"p05": pct(grosses, 0.05), "median": pct(grosses, 0.5), "p95": pct(grosses, 0.95)},
        "share_of_random_runs_as_good_pct": round(100 * as_good, 1),
        "beats_random": beat,
        "verdict": verdict,
        "time_matched_min": window_min,
        "method": "each real trade replayed on a random other session of the same stock in the period, "
                  "same side, rupee size, stop % and target R, entered at a random bar "
                  + (f"within {window_min} minutes of the real entry's time of day" if window_min
                     else "in the entry window")
                  + "; same fills and charges",
    }
