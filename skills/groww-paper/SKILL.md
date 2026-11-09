---
name: groww-paper
description: Paper trade on live Groww data - run the scanner, exit planner, sizing and risk gate during market hours and record simulated fills and exits in trader/journal.json without sending any order. Also replays past sessions and reports paper results. Use when the user wants to forward-test a setup, see what would happen if they traded it now, or review their paper trading results.
---

# Groww Paper Trading

Forward testing: the full pipeline runs on today's live market and records what *would* have happened. **It never sends an order.** Read-only data calls only, so no static IP is needed.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

## Commands

```
python3 <repo>/gtrade.py paper run                     # loop every 5 min until the close (leave running)
python3 <repo>/gtrade.py paper once                    # a single step now
python3 <repo>/gtrade.py paper report                  # results across all paper days
python3 <repo>/gtrade.py paper report --date 2026-11-10
python3 <repo>/gtrade.py paper replay --date 2026-11-09 --write   # rehearse a past day
```

`run` prints one line per event and a status line per bar. It's safe to stop (Ctrl+C) and restart: all state is in `trader/journal.json`. `run` blocks until the close, so tell the user to start it in their own terminal or on a server rather than running it inside a chat turn. Use `once` and `report` from chat.

## What each step does

1. **Scan** closed bars for new triggers -> plan -> size -> risk gate (with today's paper journal) -> `pending` or `blocked`.
2. **Fill** a pending idea at the open of the bar after the trigger bar, plus slippage.
3. **Manage** open positions: stop, target or flat-by, judged only on bars that have closed. The rules are identical to the backtest's (shared code).

Journal statuses: `pending`, `open`, `closed`, `blocked` (risk gate said no, reasons kept), `missed` (trigger older than `paper_trading.max_signal_age_min` when first seen, e.g. the user started late), `cancelled` (no fill before flat-by). Only pending/open/closed count toward daily limits.

## How to report

- From `paper report`: number of paper days, trades, win rate, net after charges, charges paid, max drawdown, P&L by day, and how many ideas were blocked or missed.
- Under ~2 weeks or ~30 trades, say plainly that it's too early to conclude anything.
- Compare with `groww-backtest` over the same dates. If paper is clearly worse, the backtest was flattering the rule.
- Paper fills are still kinder than real ones: real orders can fill late, partially or worse in fast moves. Paper profits are a best case.
- Don't suggest switching to live trading because paper results look good. That decision is the user's, and live orders will need a static IP registered with Groww and a separate broker step that asks for a yes on every order.
