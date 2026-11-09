# Groww Trader Skills

Open-source Claude skills for trading Indian markets (NSE) with **your own Groww account**: scan your watchlist for setups, plan the exit before you enter, size the position after Indian charges, check it against your own risk limits, and backtest the rule on past sessions before risking a rupee.

- **Runs on your machine, with your keys.** Nothing is hosted. The author never sees your account, keys or orders.
- **No order placement in this version.** Every tool here is read-only or arithmetic. A future broker skill will only send an order after a risk PASS *and* you typing yes for that exact order, paper mode by default.
- **Honest about costs.** Brokerage, STT, exchange fees, SEBI fee, stamp duty and GST are in every backtest and every ticket.
- **Standard-library Python.** The only extra package is Groww's official SDK, for live data.

Inspired by the design of [day-trader-skill](https://github.com/jakeschincariol/day-trader-skill) (MIT), rebuilt for Indian markets and Groww.

> **Not financial advice.** This is software that reads market data and does arithmetic. It doesn't know your situation and can't see the future. Most intraday traders lose money, much of it to costs. You can lose money. Paper trade first and decide for yourself.

## Skills

| skill | job | writes |
|---|---|---|
| `groww-setup` | install, connect your Groww API credentials, set your limits | `trader/config.json` |
| `groww-scanner` | find opening-range and previous-day-high breakouts on your watchlist | `trader/scan.json` |
| `groww-exit` | stop, target and flat-by time, decided before entry | `trader/plan.json` |
| `groww-budget` | quantity so the loss at the stop, after charges, fits your limit | `trader/orders.json` |
| `groww-risk` | PASS or BLOCK every ticket against your rules | `trader/orders.json` |
| `groww-backtest` | replay the rule over past sessions after slippage and charges | `trader/backtest.json` |

Each skill reads what the previous one wrote:

```
scanner -> exit -> budget -> risk           (one trade idea)
backtest                                    (before you trust any rule)
```

## Install

In Claude Code, as a plugin:

```
/plugin marketplace add MaheshPulivarthi18/groww-trader-skills
/plugin install groww-trader-skills@groww-trader-skills
```

Or clone and copy the skills:

```
git clone https://github.com/MaheshPulivarthi18/groww-trader-skills.git
cp -r groww-trader-skills/skills/* ~/.claude/skills/
```

The skills call `gtrade.py` in the repo root, so keep the clone where it is.

For live data you need Python 3.9+, an active Groww Trading API subscription ([groww.in/trade-api](https://groww.in/trade-api)) and:

```
pip install growwapi        # official Groww SDK
pip install pyotp           # only for the TOTP login flow
```

## Credentials

Environment variables only. Never put keys in files, commits or chat.

```
export GROWW_ACCESS_TOKEN=...                                 # or
export GROWW_API_KEY=...  GROWW_API_SECRET=...                # key + secret flow, or
export GROWW_API_KEY=...  GROWW_TOTP_SECRET=...               # TOTP flow
```

Without credentials, everything runs offline on cached candles in `trader/data/`.

## Quick start

```
mkdir -p trader && cp config.example.json trader/config.json    # then edit YOUR limits
python3 gtrade.py check                                         # read-only credential test
python3 gtrade.py fetch --days 60                               # cache 5-min candles for the watchlist
python3 gtrade.py backtest SBIN --setup orb                     # how did the rule do, after costs?
python3 gtrade.py scan --write                                  # what is setting up right now
python3 gtrade.py plan --write
python3 gtrade.py size --write
python3 gtrade.py risk --write
python3 gtrade.py show                                          # tickets in plain words
```

Example ticket (from the synthetic test data, with the default config):

```
[PASS] [PAPER] Buy 246 DEMO (MIS) at about ₹101.6
    stop ₹100.5  target ₹103.25  flat by 15:10 IST
    if stopped: ₹-308.66   if target: ₹367.24   (charges ~₹38.66)
```

## Config

`trader/config.json` overrides `config.example.json`'s defaults. Key parts:

- `capital`, `watchlist`, `product` (`MIS` intraday / `CNC` delivery), `allow_short` (off by default)
- `setups.orb`: `range_min` (opening-range length), min/max range %
- `exit`: `stop` (`or_mid`, `or_low`, `level`, `pct:0.8`, `atr:1.5`), `target` (`1.5R`), `flat_by` (keep this before Groww's intraday auto square-off)
- `risk`: max loss per trade, daily loss limit, trades per day, open positions, min reward:risk, max position %, entry window
- `charges`: percentage rates. **Defaults are typical NSE equity rates, not a quote. Match them to your broker's pricing page.** DP charges and API subscription fees are not included.

## Backtest fill model

Conservative on purpose: entry at the next bar's open plus slippage; if a bar touches both stop and target, the stop wins; gaps through the stop fill at the open; anything open at `flat_by` exits there; full charges every trade. The `outlook` resamples past trades 10,000 times (seeded) to show a range for the next 20 trades. It's history, not a forecast.

## Tests

```
python3 -m unittest discover -s tests -v
```

Offline, on synthetic candles (not real market data). They pin the charge math, setup triggers, sizing, the risk gate, the backtest fill model and the full CLI pipeline.

## Fine print

- **Regulation.** SEBI's retail algo framework (in force from April 2026) applies to API trading through brokers: things like static IP, 2FA, order-rate limits and strategy registration above certain thresholds. You are responsible for meeting your broker's requirements. Check Groww's API documentation and current SEBI circulars.
- **Personal use.** This is a toolkit for running on your own account. Don't use it to trade other people's accounts or to sell signals; that needs registrations this project doesn't have.
- **Data.** 5-minute candles, not ticks. Exchange holidays aren't modelled (Groww just returns no candles). Check anything that matters in the Groww app.
- **A stop is a plan, not a guarantee.** Fast markets and gaps fill worse than the stop.
- **Taxes.** Intraday profits are generally treated as speculative business income in India. Nothing here is tax advice.

## Roadmap

- `groww-broker`: paper-mode order journal first; live orders via `growwapi` only after risk PASS and an explicit yes per order
- `groww-alerts`: stop, target and flat-by reminders
- `groww-news`: NSE/BSE corporate announcements for the watchlist
- More setups (VWAP reclaim, gap-and-go), delivery (CNC) swing backtests

Contributions welcome. Keep the rules: no order without a PASS and a yes, paper by default, keys out of code.

## License

MIT. See [LICENSE](LICENSE).
