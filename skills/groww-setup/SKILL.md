---
name: groww-setup
description: Set up the Groww trader skills for a user - install the Groww SDK, connect their own Groww API credentials through environment variables, create trader/config.json with their capital and risk limits, and verify read-only access. Use when the user wants to start using these skills, connect Groww, or change their trading limits.
---

# Groww Setup

Gets one person running these tools against **their own** Groww account. Nothing is hosted; nothing leaves their machine except calls to Groww.

Not everything needs Groww: `groww-costs` works with no login; daily strategies (swing, portfolio) can use years of free official NSE data (`gtrade.py nse fetch --years 7`, then `nse build`, then `--source nse`); and cached data works offline (`--source csv`). Intraday 5-minute data, `fetch` and paper trading need the Groww API.

## Where things are

`gtrade.py` is in the repository root, two folders above this SKILL.md (`<repo>/gtrade.py`). Files land in `trader/` under the current folder, or wherever `GTRADE_HOME` points (recommended on a server: `export GTRADE_HOME="$HOME/trading/trader"`, so commands work from any folder):

```
python3 <repo>/gtrade.py <command>
```

## Steps

1. **Python and SDK.** Python 3.9+ is needed. The analysis tools use only the standard library. Live data needs the official SDK:
   `pip install growwapi` (and `pip install pyotp` for the TOTP login flow).

2. **Groww API subscription.** The user needs an active Trading API subscription and keys from groww.in/trade-api. Point them there; do not do it for them.

3. **Credentials go in environment variables, never in files or the chat.** If the user pastes a key or secret into the chat, tell them to revoke it on Groww and make a new one. One of:
   - `GROWW_TOTP_TOKEN` + `GROWW_TOTP_SECRET` (TOTP flow; best for a server. On Groww's API Keys page: dropdown next to "Generate API Key" -> TOTP. The token is long; the secret is only A-Z and 2-7.)
   - `GROWW_API_KEY` + `GROWW_API_SECRET` (key/secret flow; Groww asks for a daily approval)
   - `GROWW_ACCESS_TOKEN` (expires daily)

   If `check` says the TOTP secret is invalid, the token and secret are usually swapped, or a placeholder was left in.

4. **Config.** Copy `<repo>/config.example.json` to `trader/config.json` and fill it in **with the user**. Ask for their capital, max loss per trade, daily loss limit, trades per day and watchlist. Don't invent limits for them; if they have no idea, start from the example's conservative values and say so. Keep `"paper": true`.

5. **Charges.** The `charges` block follows Groww's published equity pricing (brokerage 0.1% capped at Rs 20 per order, min Rs 5; checked Nov 2026). Ask the user to confirm against groww.in/pricing/stocks. Backtest results are only as honest as these numbers.

6. **Verify (read-only):** `python3 <repo>/gtrade.py check` prints the last price of the first watchlist symbol. Then `gtrade.py fetch --days 365` caches a year of 5-minute candles for the watchlist in `trader/data/`, enough for `groww-check-idea`.

7. **Optional extras**, only if the user wants them:
   - A server that runs every market day: walk them through `<repo>/docs/oracle-cloud.md` (Oracle Always Free, reserved IP, cron).
   - Telegram alerts and `/pause`: `TELEGRAM_BOT_TOKEN`, then `gtrade.py telegram setup` to find `TELEGRAM_CHAT_ID`, then `gtrade.py telegram test`.
   - MongoDB mirror for dashboards and reviews (`groww-paper`): `pip install pymongo`, `GTRADE_MONGO_URI`, `GTRADE_MONGO_DB`, then `gtrade.py mongo check`. Use a DB user limited to `readWrite` on that database and allow only the server's IP.

   Env file rules: no spaces around `=`, single quotes around values, `chmod 600`. Never ask for or accept the values in chat.

## Rules to repeat to the user

- These tools never place orders. That's enforced in code: the Groww client is wrapped so only market-data calls work, and a test fails the build if order code ever appears.
- SEBI's retail algo framework applies to API trading: their broker may require a static IP and strategy registration above certain order rates. Tell them to check Groww's API docs.
- Not financial advice. Most intraday traders lose money, mostly to costs.
