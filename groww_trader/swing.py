"""Swing trading on daily candles, held for days (delivery / CNC), tested
with the same honest train/test split as the intraday sweep.

Rule ("breakout"): the day's close is above the highest high of the
previous `lookback` days (and, if `trend` > 0, above its `trend`-day simple
moving average). Buy at the NEXT day's open plus slippage.

Exits, checked each following day in this order:
  * stop    low reaches the stop (a gap below fills at the open); market order,
            normal + extra stop slippage
  * target  high trades beyond the target by a tick (a gap above fills at the
            open); limit order, no slippage. Target "none" = no target.
  * time    after `hold` days in the trade, sell at that day's close

Longs only (delivery can't be shorted). Delivery charges apply: STT 0.1% on
both sides, stamp duty, brokerage, exchange/SEBI fees, GST and the DP
charge on the sell. One position per symbol at a time.
"""

from __future__ import annotations

import copy
import itertools
from datetime import date
from typing import Any, Dict, List, Optional

from .backtest import TICK, fill_params, slipped, stats
from .costs import net_pnl
from .indicators import atr
from .market import Candle
from .sizing import size
from .sweep import verdict


def daily(candles: List[Candle]) -> List[Candle]:
    """One candle per date (the last one if duplicated), sorted."""
    by_day: Dict[date, Candle] = {}
    for c in sorted(candles, key=lambda c: c.ts):
        by_day[c.ts.date()] = c
    return [by_day[d] for d in sorted(by_day)]


def _stop(entry: float, rule: str, atr_val: Optional[float]) -> Optional[float]:
    if rule.startswith("pct:"):
        return round(entry * (1 - float(rule[4:]) / 100), 2)
    if rule.startswith("atr:"):
        if not atr_val:
            return None
        return round(entry - float(rule[4:]) * atr_val, 2)
    raise ValueError(f"swing stop must be pct:<n> or atr:<n>, not {rule!r}")


def run(symbol: str, candles: List[Candle], rule: Dict[str, Any], cfg: Dict[str, Any],
        from_day: Optional[date] = None, to_day: Optional[date] = None) -> Dict[str, Any]:
    days = daily(candles)
    c = copy.deepcopy(cfg)
    c["product"] = "CNC"
    slip = c.get("slippage_pct", 0.0) / 100
    extra = fill_params(c)["stop_extra_slippage_pct"] / 100
    lb, trend, hold = int(rule["lookback"]), int(rule.get("trend", 0) or 0), int(rule["hold"])
    atrs = atr(days, 14)
    trades: List[Dict[str, Any]] = []
    i = max(lb, trend, 1)
    while i < len(days) - 1:
        d = days[i]
        if (from_day and d.ts.date() < from_day) or (to_day and d.ts.date() > to_day):
            i += 1
            continue
        hh = max(x.high for x in days[i - lb:i])
        sma_ok = trend == 0 or d.close > sum(x.close for x in days[i - trend + 1:i + 1]) / trend
        if not (d.close > hh and sma_ok):
            i += 1
            continue
        stop = _stop(d.close, rule["stop"], atrs[i])
        if stop is None or stop >= d.close:
            i += 1
            continue
        risk = d.close - stop
        tgt_rule = str(rule["target"]).upper()
        target = None if tgt_rule == "NONE" else round(d.close + float(tgt_rule[:-1]) * risk, 2)
        plan = {"symbol": symbol, "side": "BUY", "entry": d.close, "stop": stop,
                "target": target if target is not None else round(d.close + 100 * risk, 2),
                "risk_per_share": round(risk, 2), "reward_risk": float(tgt_rule[:-1]) if target else 99}
        order = size(plan, c)
        qty = order["qty"]
        if qty <= 0:
            i += 1
            continue
        e_bar = days[i + 1]
        entry = slipped(e_bar.open, "BUY", "entry", slip)
        exit_px, reason, exit_i = None, None, None
        for k in range(i + 1, min(i + 1 + hold, len(days))):
            b = days[k]
            if b.low <= stop:
                exit_px, reason = slipped(min(b.open, stop), "BUY", "exit", slip + extra), "stop"
            elif target is not None and b.high >= target + TICK:
                exit_px, reason = round(max(b.open, target), 2), "target"
            elif k == i + hold or k == len(days) - 1:
                exit_px, reason = slipped(b.close, "BUY", "exit", slip), ("time" if k == i + hold else "data_end")
            if reason:
                exit_i = k
                break
        if reason is None:
            break
        pnl = net_pnl("BUY", entry, exit_px, qty, c["charges"], "CNC")
        trades.append({"symbol": symbol, "signal_day": str(d.ts.date()), "entry_day": str(e_bar.ts.date()),
                       "exit_day": str(days[exit_i].ts.date()), "days_held": exit_i - i, "qty": qty,
                       "fill_entry": entry, "fill_exit": exit_px, "stop": stop, "target": target,
                       "exit_reason": reason, **pnl,
                       "r": round(pnl["net"] / (risk * qty), 2) if risk * qty else 0})
        i = exit_i + 1  # one position at a time
    return {"symbol": symbol, "rule": rule, "trades": trades, "stats": stats(trades)}


def grid(lookbacks, stops, targets, holds, trends) -> List[Dict[str, Any]]:
    return [{"lookback": lb, "stop": s, "target": t, "hold": h, "trend": tr}
            for lb, s, t, h, tr in itertools.product(lookbacks, stops, targets, holds, trends)]


def _summ(trades):
    s = stats(trades)
    keys = ("trades", "win_rate_pct", "net_total", "charges_total", "avg_net", "profit_factor", "max_drawdown")
    return {k: s.get(k) for k in keys} if s.get("trades") else {"trades": 0, "net_total": 0.0}


def sweep(candles_by_symbol: Dict[str, List[Candle]], cfg: Dict[str, Any], rules: List[Dict[str, Any]],
          train_frac: float = 0.6, min_trades: int = 8, top: int = 5) -> Dict[str, Any]:
    all_days = sorted({c.ts.date() for cs in candles_by_symbol.values() for c in daily(cs)})
    if len(all_days) < 120:
        raise ValueError(f"only {len(all_days)} days of daily data; fetch more "
                         "(gtrade.py fetch --interval 1440 --days 1100)")
    cut = all_days[int(len(all_days) * train_frac)]
    train_end = all_days[all_days.index(cut) - 1]
    rows = []
    for rule in rules:
        tr_t, te_t = [], []
        for sym, cs in candles_by_symbol.items():
            tr_t += run(sym, cs, rule, cfg, to_day=train_end)["trades"]
            te_t += run(sym, cs, rule, cfg, from_day=cut)["trades"]
        rows.append({"rule": rule, "train": _summ(tr_t), "test": _summ(te_t)})
    eligible = [r for r in rows if r["train"]["trades"] >= min_trades]
    ranked = sorted(eligible, key=lambda r: r["train"]["net_total"], reverse=True)
    best = ranked[0] if ranked else None
    held = sum(1 for r in ranked[:top] if r["test"]["net_total"] > 0)
    return {"symbols": sorted(candles_by_symbol),
            "split": {"train_until": str(train_end), "test_from": str(cut), "train_frac": train_frac},
            "variants_tested": len(rows), "eligible": len(eligible), "min_trades": min_trades,
            "profitable_on_train": sum(1 for r in eligible if r["train"]["net_total"] > 0),
            "top": ranked[:top], "pick": best,
            "verdict": verdict(best, held, min(top, len(ranked)),
                               next_step="Worth tracking on paper for a few months (swing trades take weeks)."),
            "all": rows}
