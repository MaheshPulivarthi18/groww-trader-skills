# Groww Scanner

Finds setups on the user's watchlist. Writes `trader/scan.json`, which the exit planner (`reference/exits.md`) reads next.

`gtrade.py` is in the repository root, three folders above this file.

## Commands

```
python3 <repo>/gtrade.py scan --write                         # all setups, whole watchlist, as of now
python3 <repo>/gtrade.py scan RELIANCE SBIN --setup orb --write
python3 <repo>/gtrade.py scan --setup orb --at 10:15 --write  # as of 10:15 today
python3 <repo>/gtrade.py scan --date 2026-10-20 --source csv  # a past session, offline
```

`--source auto` (default) uses Groww when credentials are set, otherwise the cached CSVs in `trader/data/`.

## Setups

| setup | triggers when | parameters (config `setups`) |
|---|---|---|
| `orb` | first 5-min close above the high (or below the low, shorts only if `allow_short`) of the first `range_min` minutes | `range_min`, `min_range_pct`, `max_range_pct` |
| `pdh_breakout` | first close above yesterday's high (or below yesterday's low). Skipped if the stock opened beyond the level | none |

Statuses: `triggered`, `waiting` (range still forming, or no break yet), `expired` (past `no_entry_after`), `skipped` (filtered out, reason given), `no_data`, `error`.

## How to report

- Lead with what triggered: symbol, side, trigger time (IST), entry price and the levels (OR high/low/mid or PDH/PDL).
- Then a one-line count of waiting / expired / skipped.
- Only completed bars count; a bar still forming is never a trigger.
- A trigger is a chart event, not a recommendation. Offer the next step: plan the exit (the exit planner (`reference/exits.md`)) and, before any real money, backtest the setup on that stock (`groww-check-idea`).
- Candles are 5-minute bars, not ticks. Check prices in the Groww app before acting.
