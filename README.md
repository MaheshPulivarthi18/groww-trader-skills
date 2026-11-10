# Groww Trader Skills

Open-source Claude skills for trading Indian markets (NSE) with **your own Groww account**: scan your watchlist for setups, plan the exit before you enter, size the position after Indian charges, check it against your own risk limits, backtest and sweep rules honestly, and paper trade them on live data before risking a rupee.

- **Runs on your machine, with your keys.** Nothing is hosted. The author never sees your account, keys or orders.
- **No order placement in this version.** Every tool is read-only, arithmetic or simulated. A future broker skill will only send an order after a risk PASS *and* you typing yes for that exact order.
- **Honest about costs.** Brokerage, STT, exchange fees, SEBI fee, stamp duty and GST are in every backtest, sweep and ticket. Defaults follow Groww's published pricing.
- **Standard-library Python.** Extra packages only for what you switch on: Groww's SDK for live data, `pymongo` for the optional MongoDB mirror.

Inspired by the design of [day-trader-skill](https://github.com/jakeschincariol/day-trader-skill) (MIT), rebuilt for Indian markets and Groww.

> **What we found so far:** on a full year of 5-minute data and three years of daily data for 10 NSE large-caps, none of 140 rule variations made money after Groww's charges, intraday or swing. Before costs the intraday rules were about break-even; swing breakouts showed a small edge that delivery costs ate. Full tables and method: [docs/results.md](docs/results.md).

> **Not financial advice.** This is software that reads market data and does arithmetic. It doesn't know your situation and can't see the future. Most intraday traders lose money, much of it to costs. You can lose money. Paper trade first and decide for yourself.

## Skills

| skill | job | writes |
|---|---|---|
| `groww-setup` | install, connect your Groww API credentials, set your limits | `trader/config.json` |
| `groww-scanner` | find opening-range and previous-day-high breakouts on your watchlist | `trader/scan.json` |
| `groww-exit` | stop, target and flat-by time, decided before entry | `trader/plan.json` |
| `groww-budget` | quantity so the loss at the stop, after charges, fits your limit | `trader/orders.json` |
| `groww-risk` | PASS or BLOCK every ticket against your rules | `trader/orders.json` |
| `groww-backtest` | replay one rule over past sessions after slippage and charges | `trader/backtest.json` |
| `groww-sweep` | try many intraday rule variations; choose on older data, judge on newer unseen data | `trader/sweep.json` |
| `groww-swing` | the same honest search for multi-day (delivery) breakout rules on daily candles | `trader/swing.json` |
| `groww-portfolio` | multi-stock strategies (momentum + regime filter, low volatility, dual momentum), monthly rebalance, vs holding the Nifty ETF | `trader/portfolio.json` |
| `groww-paper` | run the whole pipeline on live data and record simulated trades; never sends orders | `trader/journal.json` |
| `groww-review` | answer questions and build dashboards from the optional MongoDB mirror | reads only |

```
scanner -> exit -> budget -> risk           (one trade idea)
backtest, sweep                             (before you trust any rule)
paper                                       (weeks of forward testing on live data)
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

The skills call `gtrade.py` in the repo root, so keep the clone where it is. For live data you need Python 3.9+, an active Groww Trading API subscription ([groww.in/trade-api](https://groww.in/trade-api)) and `pip install growwapi pyotp`.

**Running it on a server:** see [docs/oracle-cloud.md](docs/oracle-cloud.md) for a step-by-step Oracle Cloud Always Free setup in Mumbai with a reserved IP, cron, and the pitfalls we hit.

## Credentials

Environment variables only. Never put keys in files, commits, chats or screenshots.

```
export GROWW_TOTP_TOKEN='...'  GROWW_TOTP_SECRET='...'      # TOTP flow (best for a server), or
export GROWW_API_KEY='...'     GROWW_API_SECRET='...'       # key + secret flow (daily approval), or
export GROWW_ACCESS_TOKEN='...'                             # a ready token (expires daily)
export GTRADE_HOME="$HOME/trading/trader"                   # where config, data and journal live
```

For TOTP: on Groww's API Keys page, open the dropdown next to **Generate API Key**, choose **TOTP**, and copy the **TOTP token** (long) and the **TOTP secret** (letters A–Z and digits 2–7 only). If what Groww shows as the secret has lowercase letters or symbols, scan the QR code with your phone camera and use the part after `secret=`. Without credentials, everything runs offline on cached candles in `trader/data/`.

## Quick start

```
mkdir -p trader && cp config.example.json trader/config.json    # then edit YOUR limits
python3 gtrade.py check                                         # read-only credential test
python3 gtrade.py fetch --days 60                               # cache 5-min candles for the watchlist
python3 gtrade.py backtest SBIN --setup orb --source csv        # how did one rule do, after costs?
python3 gtrade.py sweep --source csv                            # many rules, judged on unseen data
python3 gtrade.py scan --write && python3 gtrade.py plan --write
python3 gtrade.py size --write && python3 gtrade.py risk --write
python3 gtrade.py show                                          # tickets in plain words
```

Example ticket (synthetic test data, default config):

```
[PASS] [PAPER] Buy 246 DEMO (MIS) at about ₹101.6
    stop ₹100.5  target ₹103.25  flat by 15:10 IST
    if stopped: ₹-326.59   if target: ₹349.72   (charges ~₹56.18)
```

## Sweep: searching for rules without fooling yourself

Trying 50 variations and keeping the best one almost always finds something that looked good by luck. `sweep` splits history by date, **chooses on the earlier ~60% and reports the later ~40%** that played no part in the choice:

```
python3 gtrade.py sweep --setups orb --targets 1.5R,2R,3R --ranges 15,30 --source csv
python3 gtrade.py sweep --setups orb_fade,vwap_reclaim --shorts --source csv
```

It prints how many variations were tried, how many made money on the train period, the top five with their unseen-period results beside them, and a plain verdict. Judge by the test column.

Intraday setups: `orb` (opening-range breakout), `pdh_breakout` (previous-day high/low), `orb_fade` (a failed opening-range breakout, traded in reverse) and `vwap_reclaim` (price recovers the session VWAP after several bars away). `--shorts` adds short trades (intraday only).

More history makes every conclusion stronger: `python3 gtrade.py fetch --days 365` asks Groww for a year in 30-day windows, keeps whatever exists, and reports how far back it got and how many old windows Groww refused.

### Swing (multi-day, delivery)

Daily candles, held for days, longs only, with delivery charges (STT 0.1% both sides, stamp duty, DP charge on the sell):

```
python3 gtrade.py fetch --interval 1440 --days 1100        # ~3 years of daily candles
python3 gtrade.py swing --source csv                       # 72 variations, train/test split
python3 gtrade.py swing --lookbacks 20 --stops pct:5 --targets 3R --holds 20 --trends 50 --source csv
```

Rule: close above the highest high of the last N days (optionally only above an N-day average), buy next day's open; exit at the stop, the target, or after the holding period.

## Portfolio strategies: momentum, low volatility, dual momentum

The slower, multi-stock approaches with the most research behind them: rank a universe, hold the best handful, rebalance monthly, and compare with simply holding the index.

```
python3 gtrade.py fetch --universe nifty100 NIFTYBEES GOLDBEES --interval 1440 --days 2500
python3 gtrade.py portfolio --universe nifty100 --source csv                   # 12-1 momentum, top 10
python3 gtrade.py portfolio --universe nifty100 --regime cash --source csv     # cash when the index trends down
python3 gtrade.py portfolio --universe nifty100 --sweep --source csv           # 24 variations, train/test
python3 gtrade.py portfolio --strategy lowvol --universe nifty100 --source csv
python3 gtrade.py portfolio --strategy dualmom --assets NIFTYBEES,GOLDBEES --source csv
```

Orders fill at the next day's open after the decision, with delivery charges both ways and whole shares; every result is shown beside NIFTYBEES held over the same dates. Read the caveats it prints: index universes use today's members (survivorship bias flatters the past), taxes aren't modelled, and idle cash earns nothing unless you pass `--cash-yield`.

## Paper trading

```
python3 gtrade.py paper run          # start before 09:15, leave running; one step every 5-minute bar
python3 gtrade.py paper report       # results so far
python3 gtrade.py paper replay --date 2026-11-09   # rehearse a past session offline
python3 gtrade.py pause | resume     # stop / allow NEW positions; open ones are always managed
```

Each bar it scans, plans, sizes and risk-checks new triggers, fills them at the next bar's open plus slippage, and exits on stop, target or flat-by, with the same code as the backtest so the two compare directly. It only reads data, so it doesn't need a static IP. After the first step it fetches only today's new bars. Run it for a few weeks before reading anything into the results; real fills are usually a little worse than paper ones.

**Unattended:** only one copy can run at a time (a lock), so cron can start it every 10 minutes as a safety net: it's a no-op while the bot runs or after the day is done, restarts a crashed bot (and says so on Telegram), and alerts if a running bot hasn't completed a step for 15 minutes. Logs go to `trader/logs/paper-YYYY-MM-DD.log`, kept 30 days. See [docs/oracle-cloud.md](docs/oracle-cloud.md) for the cron lines.

## Optional: Telegram alerts and remote pause

Your own bot sends signals, fills, exits, blocked ideas, data errors and a closing summary, and accepts `/status`, `/report`, `/pause`, `/resume`, `/help`, only from your chat.

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. `export TELEGRAM_BOT_TOKEN='...'` in your env file, send your bot any message, then run `python3 gtrade.py telegram setup` to see your chat id.
3. `export TELEGRAM_CHAT_ID='...'`, then `python3 gtrade.py telegram test`.

`/pause` blocks new positions and cancels unfilled ones; open positions still run to their stop, target or flat-by. Commands are answered within about 20 seconds while `paper run` is running. Telegram problems never stop the bot.

## Optional: MongoDB mirror

To review activity from anywhere, or ask Claude about it through MongoDB's MCP server, the bot can copy its journal, daily summaries, events, a heartbeat and saved backtests to MongoDB (an Atlas free M0 cluster is plenty).

```
pip install pymongo
export GTRADE_MONGO_URI='mongodb+srv://USER:PASSWORD@your-cluster.mongodb.net/?retryWrites=true&w=majority'
export GTRADE_MONGO_DB='groww_trader'
python3 gtrade.py mongo check     # ping and collection counts
python3 gtrade.py mongo sync      # push the existing local journal once
```

After that, `paper run` / `paper once` sync every bar and `backtest --write` saves the run. The local `trader/` files stay the source of truth: MongoDB gets a best-effort copy with short timeouts, and if it's unreachable the bot prints one warning and carries on. Use a database user limited to `readWrite` on this one database, allow only your server's IP in Atlas, and if you connect Claude, enable AI client access in Atlas under **Organization Settings → App Connections**.

## Config

`trader/config.json` overrides the defaults in `config.example.json`.

- `capital`, `watchlist`, `product` (`MIS` intraday / `CNC` delivery), `allow_short` (off by default)
- `setups`: **only the setups you list run**, each filled in from its defaults. A setup can carry its own `exit` block, e.g. `"pdh_breakout": {"exit": {"stop": "level"}}` (that one is the default), so ORB and PDH can run together with suitable stops.
- `exit`: global `stop` (`or_mid`, `or_low`, `level`, `pct:0.8`, `atr:1.5`), `target` (`1.5R`), `flat_by` (keep this before Groww's intraday auto square-off)
- `risk`: max loss per trade, daily loss limit, trades per day, open positions, **one position per stock**, min reward:risk, max position %, entry window
- `charges`: percentage rates following [Groww's pricing](https://groww.in/pricing/stocks) as of Nov 2026 (brokerage 0.1% capped at ₹20 per order, min ₹5; delivery sells add a ₹20 DP charge plus GST). Re-check them. API subscription fees are not included.
- `fills`: how strict simulated fills are. Defaults: entry at the next bar's open plus slippage; a target (limit order) fills only if price trades a tick beyond it; stops (market orders) get 0.05% extra slippage. `"entry": "mid"` is a harsher stress test.

## Backtest fill model

Conservative on purpose: entry at the next bar's open plus slippage; targets need price to trade a tick beyond them (a touch isn't a fill) and fill without slippage; stops pay extra slippage; if a bar reaches both stop and target, the stop wins; gaps through the stop fill at the open; anything open at `flat_by` exits there; full charges every trade. The `outlook` resamples past trades 10,000 times (seeded) to show a range for the next 20 trades. It's history, not a forecast.

## Tests

```
python3 -m unittest discover -s tests -v
```

Offline, on synthetic candles (not real market data). They pin the charge math (intraday and delivery), every setup's triggers, per-setup exits, sizing, the risk gate, the fill model, the sweep's train/test separation, swing entries and exits, paper trading (no peeking at unfinished bars, restart-safe, identical to the backtest, pause behaviour), the single-instance lock, restart and stuck detection, long fetches with missing old windows, Telegram command handling and the MongoDB mirror's failure path.

## Fine print

- **Regulation.** SEBI's retail algo framework applies to API trading through brokers: orders must come from a static IP registered with your broker (Groww's deadline was 31 March 2026), plus 2FA, order-rate limits and strategy registration above certain thresholds. This project doesn't place orders yet; when it does, meeting your broker's requirements is your responsibility. Check Groww's API documentation and current SEBI/NSE circulars.
- **Personal use.** A toolkit for your own account. Don't use it to trade other people's accounts or to sell signals; that needs registrations this project doesn't have.
- **Data.** 5-minute candles, not ticks. Exchange holidays aren't modelled (Groww just returns no candles). Check anything that matters in the Groww app.
- **A stop is a plan, not a guarantee.** Fast markets and gaps fill worse than the stop.
- **Taxes.** Intraday profits are generally treated as speculative business income in India. Nothing here is tax advice.

## Roadmap

- `groww-broker`: live orders via `growwapi`, only after a rule survives sweep and weeks of paper trading; risk PASS and an explicit yes per order; from a static IP registered with Groww
- Swing and portfolio paper tracking (the paper engine is intraday only today)
- Pairs trading / statistical arbitrage (needs shorting and a stock-borrow model)
- More setups (gap-and-go, index-relative strength)
- `groww-news`: NSE/BSE corporate announcements for the watchlist

Contributions welcome. Keep the rules: no order without a PASS and a yes, paper by default, keys out of code.

## License

MIT. See [LICENSE](LICENSE).
