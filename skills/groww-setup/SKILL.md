---
name: groww-setup
description: Set up the Groww trader skills for a user - install the Groww SDK, connect their own Groww API credentials through environment variables, create trader/config.json with their capital and risk limits, and verify read-only access. Use when the user wants to start using these skills, connect Groww, or change their trading limits.
---

# Groww Setup

Gets one person running these tools against **their own** Groww account. Nothing is hosted; nothing leaves their machine except calls to Groww.

## Where things are

`gtrade.py` is in the repository root, two folders above this SKILL.md (`<repo>/gtrade.py`). Run every command from the user's project folder so files land in its `trader/` folder:

```
python3 <repo>/gtrade.py <command>
```

## Steps

1. **Python and SDK.** Python 3.9+ is needed. The analysis tools use only the standard library. Live data needs the official SDK:
   `pip install growwapi` (and `pip install pyotp` for the TOTP login flow).

2. **Groww API subscription.** The user needs an active Trading API subscription and keys from groww.in/trade-api. Point them there; do not do it for them.

3. **Credentials go in environment variables, never in files or the chat.** If the user pastes a key or secret into the chat, tell them to revoke it on Groww and make a new one. One of:
   - `GROWW_ACCESS_TOKEN`
   - `GROWW_API_KEY` + `GROWW_API_SECRET` (key/secret flow; Groww asks for a daily approval)
   - `GROWW_API_KEY` + `GROWW_TOTP_SECRET` (TOTP flow)

4. **Config.** Copy `<repo>/config.example.json` to `trader/config.json` and fill it in **with the user**. Ask for their capital, max loss per trade, daily loss limit, trades per day and watchlist. Don't invent limits for them; if they have no idea, start from the example's conservative values and say so. Keep `"paper": true`.

5. **Charges.** The `charges` block holds default NSE equity rates. Ask the user to check their current Groww pricing page and adjust. Backtest results are only as honest as these numbers.

6. **Verify (read-only):** `python3 <repo>/gtrade.py check` prints the last price of the first watchlist symbol. Then `gtrade.py fetch --days 60` caches 5-minute candles for the watchlist in `trader/data/`.

## Rules to repeat to the user

- These tools never place orders. A later broker skill will only ever do it after a risk PASS and the user typing yes for that exact order.
- SEBI's retail algo framework applies to API trading: their broker may require a static IP and strategy registration above certain order rates. Tell them to check Groww's API docs.
- Not financial advice. Most intraday traders lose money, mostly to costs.
