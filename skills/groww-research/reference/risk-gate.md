# Groww Risk Gate

The last check before a paper trade, or a trade the user is thinking of placing themselves. This toolkit never places orders; a ticket that isn't `PASS` shouldn't be acted on.

`gtrade.py` is in the repository root, three folders above this file.

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
- not already holding (or about to hold) the same stock: one position per stock
- reward:risk at least `min_reward_risk`
- position value within `max_position_pct` of capital
- no shorts unless `allow_short`
- now inside `no_entry_before` .. `no_entry_after`, before the trade's flat-by, and the signal is from today

Today's history comes from `trader/journal.json` (written by `groww-paper`; entries with status pending, open or closed count, blocked/missed/cancelled ideas do not). If it doesn't exist, say so: the daily limits can't see trades made elsewhere.

## Rules for Claude

- Report every BLOCK with its reasons verbatim. **Never** loosen a limit, edit the config or rewrite an order to turn a BLOCK into a PASS unless the user explicitly asks to change that limit, and then point out that they're changing a rule they set for themselves.
- A PASS means "fits your rules", not "good trade".
