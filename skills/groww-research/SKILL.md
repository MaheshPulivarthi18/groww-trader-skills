---
name: groww-research
description: Look at the market with the user's own Groww data - scan their NSE watchlist for intraday setups now or on a past day, plan a hypothetical trade's stop, target and size after charges, check it against their own risk rules, and inspect or audit the price data. Use when the user asks what is breaking out, where a stop should go, how many shares fit their risk, whether a trade fits their rules, or whether the data is right. Read-only; never places orders.
---

# Groww Research

Looks, plans and checks; never trades. Every output is information for the user, who decides everything.

`gtrade.py` is in the repository root, two folders above this SKILL.md.

## Quick commands

```
python3 <repo>/gtrade.py scan --write                  # what has triggered on the watchlist right now
python3 <repo>/gtrade.py scan --date 2026-11-11 --source csv     # a past session
python3 <repo>/gtrade.py plan --write                  # stop, target, flat-by for what the scan found
python3 <repo>/gtrade.py size --write                  # shares that fit the user's loss limit after charges
python3 <repo>/gtrade.py risk --write                  # PASS / BLOCK against the user's own rules
python3 <repo>/gtrade.py show                          # the tickets in plain words
python3 <repo>/gtrade.py ltp RELIANCE SBIN             # last prices
python3 <repo>/gtrade.py inspect SBIN --interval 5 --days 3      # raw Groww candles
python3 <repo>/gtrade.py audit                         # splits/bonuses and data gaps in daily data
```

The chain is scan -> plan -> size -> risk; each step writes a file in `trader/` that the next one reads.

## Read the reference before going deep

- `reference/scan.md`: setups, statuses and how to report a scan
- `reference/exits.md`: stop rules (`or_mid`, `or_low`, `level`, `pct:`, `atr:`), targets in R, flat-by
- `reference/sizing.md`: how quantity is chosen so the loss at the stop, after charges, fits the limit
- `reference/risk-gate.md`: every rule checked, and why Claude must never loosen one to turn a BLOCK into a PASS

## Rules

- A trigger is a chart event, not a recommendation. A PASS means "fits your rules", not "good trade".
- Before the user acts on any setup with real money, suggest testing it with `groww-check-idea`: most simple setups don't beat random entries after charges.
- Candles are 5-minute bars, not ticks; prices in the Groww app are the real ones.
- This toolkit cannot place orders: the Groww client it uses is wrapped so that only market-data calls work.
