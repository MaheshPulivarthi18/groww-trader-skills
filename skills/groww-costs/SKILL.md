---
name: groww-costs
description: Work out what an Indian stock trade really costs on Groww - brokerage, STT, exchange and SEBI fees, stamp duty, GST, DP charge - for intraday or delivery, and how far the price must move just to break even. Use when the user asks about charges, fees, whether a small trade is worth it, or why trading profits disappear.
---

# Groww Costs

Most small traders lose to costs before they lose to the market. This shows the cost of one round trip (buy and sell at the same price) and the **break-even move**: how far the price has to go in your favour before you make a rupee.

`gtrade.py` is in the repository root, two folders above this SKILL.md. No Groww login needed.

```
python3 <repo>/gtrade.py costs                              # table: Rs 2k to 1L, intraday and delivery
python3 <repo>/gtrade.py costs 10000 --product MIS          # one trade value, with the breakdown
python3 <repo>/gtrade.py costs --price 1342.8 --qty 18      # an exact trade
python3 <repo>/gtrade.py costs 10000 --stop-pct 0.5         # costs as a share of the money at risk
```

Rates come from the config's `charges` block (Groww's published equity pricing, checked Nov 2026: brokerage 0.1% per order, min Rs 5, max Rs 20; STT, stamp duty and fees as set by the exchange and government). The "+ slippage" column adds the configured slippage (0.03% each way) as an estimate of a worse fill. Ask the user to confirm the rates on groww.in/pricing before relying on them.

## What to point out

- **Break-even move** in %: an intraday trade of Rs 10,000 needs about 0.27% (about 0.33% with slippage) just to cover costs.
- **Small trades are dearer in %**: the Rs 5 minimum brokerage per order hurts below about Rs 5,000. Above about Rs 20,000 per order the Rs 20 cap makes intraday cheaper in %.
- **Delivery costs more per trade** (STT 0.1% on both sides plus a Rs 20 + GST DP charge on each sell) but is paid far less often if trades are held for weeks.
- **Costs vs risk** (`--stop-pct`): if charges are more than about 20% of what you'd lose at the stop, the costs will eat most of any edge. Tight stops make this worse.
- Taxes are not included: gains are also taxed (short-term rates are higher than long-term).

Facts, not advice. No orders are placed.
