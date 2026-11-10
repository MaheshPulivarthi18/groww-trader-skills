---
name: groww-sweep
description: Search for intraday rules honestly - try many setup, stop, target and opening-range variations across the watchlist, choose on the earlier part of the data and check the choice on the later part it never saw, after Indian charges. Use when the user wants to find better rules, optimise settings, or asks which stop or target works best.
---

# Groww Sweep

Trying 50 variations and keeping the best one almost always finds something that looks profitable by luck. The sweep guards against that by splitting the history by date: it **chooses on the train period** (earlier ~60%) and **reports the test period** (later ~40%), which played no part in the choice.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

```
python3 <repo>/gtrade.py sweep --source csv                                  # whole watchlist, default grid
python3 <repo>/gtrade.py sweep --setups orb --targets 1.5R,2R,3R --ranges 15,30 --source csv
python3 <repo>/gtrade.py sweep SBIN ICICIBANK --stops pct:0.5,pct:1 --json --write
```

Defaults: setups `orb,pdh_breakout`; every stop that suits each setup (`orb`: or_mid, or_low, pct:0.5, pct:1, atr:1.5; `pdh_breakout`: level, pct:0.5, pct:1, atr:1.5); targets `1R,1.5R,2R,3R`; train 60%; a variation needs at least `--min-trades 10` train trades to be ranked. Uses the same fill model, slippage and charges as `groww-backtest`. Fetch data first (`fetch --days 60` or more); `--source csv` reuses the cache.

## Output

How many variations were tested and how many made money on train; the top 5 by train net with their test results beside them; and a verdict:

- best variation lost on train -> no edge found
- won on train, lost on test -> most likely luck
- won on train, too few test trades -> need more data
- won on both -> worth paper trading, still not proof

## How to report

- Say how many variations were tried. The more tried, the more suspicious a good train result is.
- Judge by the **test** column, not train. Never recommend a rule on its train result alone.
- Small samples (under ~30 test trades) are weak evidence; suggest fetching more history.
- A rule that survives goes to `groww-paper` for 2-3 weeks before anything else. Don't suggest live trading.
