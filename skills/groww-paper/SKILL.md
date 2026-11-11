---
name: groww-paper
description: Paper trade on live Groww data - run the scanner, exit planner, sizing and risk gate during market hours and record simulated fills and exits without sending any order; replay past sessions; report paper results; and review the bot's activity, health and P&L from MongoDB. Use when the user wants to forward-test a setup, asks how today or this week went, what the bot did and when, why a trade was blocked, or whether the bot is running.
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
python3 <repo>/gtrade.py pause                         # no NEW positions (open ones still managed)
python3 <repo>/gtrade.py resume
```

`run` writes one line per event and a status line per bar to `trader/logs/paper-YYYY-MM-DD.log` (kept 30 days; also to the terminal when interactive). It's safe to stop and restart: all state is in `trader/journal.json`. `run` blocks until the close, so tell the user to start it on a server or in their own terminal rather than inside a chat turn. Use `once` and `report` from chat.

Only one copy runs at a time (lock `trader/paper.lock`): a second `run` or `once` exits without touching the journal, and if the running copy hasn't completed a step for 15 minutes during market hours, it sends one "may be stuck" alert. `run_state.json` records the day's start, last step and whether the day finished, so cron can start `run` every 10 minutes as a safety net: no-op while running or after the day is done, otherwise a restart (announced on Telegram). `--force` reruns a finished day.

## What each step does

1. **Scan** closed bars for new triggers -> plan -> size -> risk gate (with today's paper journal) -> `pending` or `blocked`.
2. **Fill** a pending idea at the open of the bar after the trigger bar, plus slippage.
3. **Manage** open positions: stop, target or flat-by, judged only on bars that have closed. The rules are identical to the backtest's (shared code).

Journal statuses: `pending`, `open`, `closed`, `blocked` (risk gate said no, or paused; reasons kept), `missed` (trigger older than `paper_trading.max_signal_age_min` when first seen, e.g. the user started late), `cancelled` (no fill before flat-by, or paused before the fill). Only pending/open/closed count toward daily limits.

## Pause and alerts

- **Pause** (`gtrade.py pause`, or `/pause` in Telegram) is a file, `trader/PAUSED`. While it exists, new triggers are recorded as blocked with reason `paused`, unfilled ideas are cancelled, and open positions still run to their stop, target or flat-by. If the user asks to stop the bot taking trades, pausing is the safe first step.
- **Telegram** (optional, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`): alerts for signals, fills, exits, blocks, data errors and a closing summary; commands `/status`, `/report`, `/pause`, `/resume`, `/help`, accepted only from the owner's chat. Setup: `gtrade.py telegram setup`, then `gtrade.py telegram test`.
- **MongoDB** (optional, `GTRADE_MONGO_URI`): each step is mirrored to MongoDB. To answer questions from it ("how did today go", "is the bot running", "why was X blocked", dashboards), read `reference/review-mongodb.md` first and use the MongoDB tools read-only.

None of these can stop or slow the trading loop: they're best-effort with short timeouts.

## How to report

- From `paper report`: number of paper days, trades, win rate, net after charges, charges paid, max drawdown, P&L by day, and how many ideas were blocked or missed.
- Under ~2 weeks or ~30 trades, say plainly that it's too early to conclude anything.
- Compare with the backtest over the same dates (`groww-check-idea`). If paper is clearly worse, the backtest was flattering the rule.
- When asked what the bot did, give a timeline in IST: start, each signal, fill, block and exit with prices and reasons, data errors, and the close.
- Paper fills are still kinder than real ones: real orders can fill late, partially or worse in fast moves. Paper profits are a best case.
- Don't suggest switching to live trading because paper results look good. This toolkit has no way to place orders, by design.
