---
name: groww-review
description: Review the Groww trader bot's paper trading activity stored in MongoDB - today's status, trades, P&L by day, blocked or missed ideas, bot health and saved backtests - and build dashboards from it. Use when the user asks how trading went, what the bot is doing, why a trade was blocked, or wants a dashboard of their trading, and a MongoDB connection is available.
---

# Groww Review (MongoDB)

The bot mirrors its activity to MongoDB when `GTRADE_MONGO_URI` is set on the server (`gtrade.py mongo check` verifies it). Read it with the MongoDB MCP tools: find the project and cluster, connect, then query database `groww_trader` (or the user's `GTRADE_MONGO_DB`). **Read only.** Never insert, update or delete; the bot owns this data, and the local `trader/journal.json` on the server is the source of truth.

## Collections

| collection | one document per | key fields |
|---|---|---|
| `journal` | trade idea, `_id` = `day:SYMBOL:setup` | `day`, `symbol`, `setup`, `side`, `status` (pending, open, closed, blocked, missed, cancelled), `qty`, `entry`, `stop`, `target`, `fill_entry`, `fill_exit`, `exit_reason` (stop, target, time, session_end), `gross`, `charges`, `net`, `r`, `risk_reasons`, `signal_time`, `entry_time`, `exit_time` |
| `daily` | trading day, `_id` = `YYYY-MM-DD` | `trades`, `wins`, `losses`, `gross`, `charges`, `net`, `ideas` (count by status), `open_positions`, `symbols` |
| `events` | log line | `at` (UTC datetime), `day`, `time` (IST HH:MM), `kind` (SIGNAL, FILLED, CLOSED, BLOCKED, MISSED, CANCEL, DATAERR), `text` |
| `health` | one doc, `_id` = `bot` | `at` (last step), `status`, `symbols`, `data_errors` |
| `backtests` | saved backtest run | `symbol`, `setup`, `rules`, `stats`, `outlook`, `saved_at`, `trades_detail` |

Times: `day` strings and `time` are IST; `at`/`saved_at` are UTC datetimes.

## Common questions

- **"Is the bot running?"** `health` `bot`: if `at` is more than ~10 minutes old during market hours (09:15-15:30 IST, weekdays), say it looks stopped and suggest checking `~/trading/paper.log` on the server.
- **"How did today / this week go?"** `daily` for the days; list `journal` entries with `status: "closed"` for detail.
- **"Why was X blocked?"** `journal` with that symbol and `status: "blocked"`: quote `risk_reasons` exactly.
- **Missed ideas** mean the bot saw a trigger too late (usually started late or was down), not a bad trade.

## How to report

- Lead with **net after charges**, and show charges separately: for intraday they often decide the result.
- Give sample size. Under ~30 closed trades, call it early evidence.
- This is **paper** trading (`mode: "paper"`): fills are simulated and slightly kinder than real ones.
- For dashboards: equity curve from `daily.net` (cumulative), P&L by day, trades table, ideas by status, exits by reason. Build from the data you queried; don't invent numbers.
- Don't recommend going live or changing risk limits because results look good. Those are the user's decisions.
