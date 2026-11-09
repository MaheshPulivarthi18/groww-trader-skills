---
name: groww-risk
description: Check every order ticket in trader/orders.json against the user's own limits (loss per trade, daily loss limit, trades per day, open positions, reward:risk, position size, shorting, entry window) and mark it PASS or BLOCK with reasons. Use before any order is considered, or when the user asks whether a trade fits their rules.
---

# Groww Risk Gate

The last check before an order. Nothing may act on an order that is not `PASS`.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
python3 <repo>/gtrade.py risk --write        # checks against the clock now (IST)
python3 <repo>/gtrade.py risk --now 2026-10-20T09:41 --write
python3 <repo>/gtrade.py show                # tickets in plain words
```

## Checks (limits from config `risk`)

- quantity above zero
- loss at stop (incl. charges) within `max_loss_per_trade`
- today's realised loss plus this trade's possible loss within `daily_loss_limit`
- trades today below `max_trades_per_day`; open positions below `max_open_positions`
- reward:risk at least `min_reward_risk`
- position value within `max_position_pct` of capital
- no shorts unless `allow_short`
- now inside `no_entry_before` .. `no_entry_after`, before the trade's flat-by, and the signal is from today

Today's history comes from `trader/journal.json` (written by `groww-paper`; entries with status pending, open or closed count, blocked/missed/cancelled ideas do not). If it doesn't exist, say so: the daily limits can't see trades made elsewhere.

## Rules for Claude

- Report every BLOCK with its reasons verbatim. **Never** loosen a limit, edit the config or rewrite an order to turn a BLOCK into a PASS unless the user explicitly asks to change that limit, and then point out that they're changing a rule they set for themselves.
- A PASS means "fits your rules", not "good trade".
