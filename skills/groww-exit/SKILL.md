---
name: groww-exit
description: Plan the stop-loss, target and flat-by time for triggered setups BEFORE any entry, from trader/scan.json, writing trader/plan.json. Use when the user asks where to put the stop, what the target is, or how to exit a setup the scanner found.
---

# Groww Exit Planner

Every trade gets its exit decided before entry. Reads `trader/scan.json`, writes `trader/plan.json`.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
python3 <repo>/gtrade.py plan --write                          # rules from config "exit"
python3 <repo>/gtrade.py plan --symbol SBIN --stop or_low --target 2R --write
```

## Stop rules

| rule | stop at | for |
|---|---|---|
| `or_mid` | middle of the opening range | `orb` |
| `or_low` | far side of the opening range (low for longs, high for shorts) | `orb` |
| `level` | the level that broke (PDH for longs, PDL for shorts) | `pdh_breakout` |
| `pct:0.8` | 0.8 % from entry | any |
| `atr:1.5` | 1.5 x ATR(14) of 5-min bars from entry | any (needs cached candles) |

Target is a multiple of the risk: `1.5R` means 1.5 x (entry - stop). Prices round to a 0.05 tick.

## Flat-by

`exit.flat_by` (default 15:10 IST). Groww auto squares off intraday (MIS) positions in the afternoon and may charge for it; the user should check Groww's current cut-off and keep `flat_by` comfortably before it.

## How to report

For each plan: side, entry, stop, target, risk per share, reward:risk, flat-by. Remind the user a stop is a plan, not a guarantee: in a fast market or a gap, the fill can be worse. Next step: `groww-budget` to size it.
