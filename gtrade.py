#!/usr/bin/env python3
"""gtrade: the command line behind the Groww trader skills.

  python3 gtrade.py check                               verify Groww credentials (read-only)
  python3 gtrade.py ltp RELIANCE SBIN                   last traded prices
  python3 gtrade.py fetch RELIANCE SBIN --days 60       cache 5-minute candles to trader/data/
  python3 gtrade.py scan --setup orb --write            find setups -> trader/scan.json
  python3 gtrade.py plan --write                        stop/target/flat-by -> trader/plan.json
  python3 gtrade.py size --write                        quantities -> trader/orders.json
  python3 gtrade.py risk --write                        PASS/BLOCK each order
  python3 gtrade.py show                                orders in plain words
  python3 gtrade.py backtest SBIN --setup orb --write   replay past sessions -> trader/backtest.json
  python3 gtrade.py sweep --source csv                  many rule variations, judged on unseen data
  python3 gtrade.py swing --source csv                  multi-day (delivery) rules on daily candles
  python3 gtrade.py portfolio --universe nifty100       momentum / low-vol / dual momentum vs the index
  python3 gtrade.py paper run | once | report | replay  paper trading on live data (simulated fills)
  python3 gtrade.py pause | resume                      stop / allow new paper positions
  python3 gtrade.py telegram setup | test               optional Telegram alerts and commands
  python3 gtrade.py mongo check | sync                  optional MongoDB mirror

Nothing here places an order. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from groww_trader import backtest as bt  # noqa: E402
from groww_trader.config import (exit_rules, load_config, override_exit, read_json,  # noqa: E402
                                  setup_params, write_json)  # noqa: E402
from groww_trader.data import (CSVSource, csv_path, get_source, load_csv,  # noqa: E402
                               lookback_window, merge_candles, save_csv)
from groww_trader.market import IST, by_session, now_ist, parse_hhmm  # noqa: E402
from groww_trader.plan import make_plan  # noqa: E402
from groww_trader.risk import check as risk_check  # noqa: E402
from groww_trader.setups import SETUPS, detect  # noqa: E402
from groww_trader.sizing import size  # noqa: E402
from groww_trader.store import get_store  # noqa: E402


def out(obj):
    print(json.dumps(obj, indent=2, default=str))


def symbols_arg(args, cfg):
    return [s.upper() for s in (args.symbols or cfg["watchlist"])]


def get_candles(src, symbol, interval, days, until=None):
    if src.name == "csv" and until is None:
        # Offline: "latest" means the last session in the cached file.
        p = csv_path(symbol, interval, src.folder)
        rows = load_csv(p) if p.exists() else []
        until = rows[-1].ts.date() if rows else None
    start, end = lookback_window(days, until)
    candles = src.candles(symbol, interval, start, end)
    if src.name == "groww":  # keep a local cache so scans/backtests are repeatable
        p = csv_path(symbol, interval)
        old = load_csv(p) if p.exists() else []
        save_csv(merge_candles(old, candles), p)
    return candles


# ---------------------------------------------------------------- commands

def cmd_check(args, cfg):
    src = get_source("groww", cfg["exchange"])
    sym = cfg["watchlist"][0]
    out({"ok": True, "source": "groww", "ltp": src.ltp([sym])})


def cmd_ltp(args, cfg):
    out(get_source(args.source, cfg["exchange"]).ltp(symbols_arg(args, cfg)))


def cmd_fetch(args, cfg):
    src = get_source("groww", cfg["exchange"])
    res = {}
    symbols = symbols_arg(args, cfg)
    if args.universe:
        from groww_trader import universe
        symbols, _desc = universe.load(args.universe)
        symbols += [s.upper() for s in (args.symbols or []) if s.upper() not in symbols]
    for n, s in enumerate(symbols, 1):
        if len(symbols) > 15:
            print(f"[{n}/{len(symbols)}] {s}", file=sys.stderr, flush=True)
        try:
            c = get_candles(src, s, args.interval, args.days)
            p = csv_path(s, args.interval)
            cached = load_csv(p) if p.exists() else []
            res[s] = {"candles": len(c), "rows_from_groww": getattr(src, "raw_rows", None),
                      "first_day": str(c[0].ts.date()) if c else None,
                      "last_day": str(c[-1].ts.date()) if c else None,
                      "cached_from": str(cached[0].ts.date()) if cached else None,
                      "file": str(p)}
            st = getattr(src, "parse_stats", {})
            if st and set(st) - {"kept"}:
                res[s]["skipped_rows"] = {k: v for k, v in st.items() if k != "kept"}
            failed = getattr(src, "failed_windows", [])
            if failed:
                res[s]["failed_windows"] = len(failed)
                res[s]["first_failure"] = failed[0]
        except Exception as e:  # keep going across symbols
            res[s] = {"error": str(e)}
    if len(symbols) > 15:  # summary instead of a page of JSON
        ok = {k: v for k, v in res.items() if "error" not in v}
        errs = {k: v["error"][:120] for k, v in res.items() if "error" in v}
        firsts = sorted(v["first_day"] for v in ok.values() if v.get("first_day"))
        lasts = sorted(v["last_day"] for v in ok.values() if v.get("last_day"))
        out({"symbols": len(symbols), "fetched": len(ok), "errors": errs,
             "earliest_first_day": firsts[0] if firsts else None, "latest_first_day": firsts[-1] if firsts else None,
             "last_day_range": [lasts[0], lasts[-1]] if lasts else None,
             "short_history": sorted(k for k, v in ok.items() if v.get("candles", 0) < 300)})
        return
    out(res)


def cmd_inspect(args, cfg):
    """Show what Groww actually returns for one symbol, to debug missing candles."""
    from groww_trader.data import parse_candle_rows
    src = get_source("groww", cfg["exchange"])
    end = now_ist()
    start = end - timedelta(days=args.days)
    c = src.client
    resp = c.get_historical_candles(
        exchange=src._const("EXCHANGE", src.exchange), segment=src._const("SEGMENT", src.segment),
        groww_symbol=f"{src.exchange.upper()}-{args.symbol.upper()}",
        start_time=start.strftime("%Y-%m-%d %H:%M:%S"), end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
        candle_interval=src._interval_const(args.interval))
    rows = (resp.get("candles") or []) if isinstance(resp, dict) else (resp or [])
    stats = {}
    kept = parse_candle_rows(rows, stats)
    out({"symbol": args.symbol.upper(), "interval_min": args.interval,
         "asked": [str(start)[:19], str(end)[:19]],
         "response_type": type(resp).__name__,
         "response_keys": sorted(resp.keys()) if isinstance(resp, dict) else None,
         "rows": len(rows), "parse": stats,
         "first_rows": rows[:3], "last_rows": rows[-3:],
         "first_kept": str(kept[0].ts) if kept else None, "last_kept": str(kept[-1].ts) if kept else None})


def cmd_scan(args, cfg):
    interval = args.interval or cfg["interval_min"]
    src = get_source(args.source, cfg["exchange"])
    until = date.fromisoformat(args.date) if args.date else None
    setups = [args.setup] if args.setup else [s for s in cfg["setups"] if s in SETUPS]
    results = []
    for s in symbols_arg(args, cfg):
        try:
            sessions = by_session(get_candles(src, s, interval, 7, until))
        except Exception as e:
            results.append({"symbol": s, "status": "error", "reason": str(e)})
            continue
        days = sorted(sessions)
        if until:
            days = [d for d in days if d <= until]
        if not days:
            results.append({"symbol": s, "status": "no_data"})
            continue
        day = days[-1]
        prev = sessions[days[-2]] if len(days) > 1 else None
        at = None
        if args.at:
            at = datetime.combine(day, parse_hhmm(args.at), tzinfo=IST)
        elif day == now_ist().date():
            at = now_ist()
        for setup in setups:
            results.append(detect(setup, s, sessions[day], cfg, interval, at=at, prev_bars=prev))
    triggered = [r for r in results if r.get("status") == "triggered"]
    report = {"scanned_at": now_ist().isoformat(), "interval_min": interval,
              "triggered": len(triggered), "results": results}
    if args.write:
        write_json("scan.json", report)
    out(report)


def cmd_plan(args, cfg):
    scan = read_json("scan.json")
    if not scan:
        sys.exit("No trader/scan.json. Run: gtrade.py scan --write")
    plans, errors = [], []
    for sig in scan["results"]:
        if sig.get("status") != "triggered":
            continue
        if args.symbol and sig["symbol"] != args.symbol.upper():
            continue
        override_exit(cfg, sig["setup"], args.stop, args.target)
        exit_cfg = exit_rules(cfg, sig["setup"])
        bars = None
        if exit_cfg["stop"].lower().startswith("atr:"):
            p = csv_path(sig["symbol"], scan["interval_min"])
            bars = [c for c in load_csv(p) if c.ts.isoformat() <= sig["trigger_bar"]] if p.exists() else None
        try:
            plans.append(make_plan(sig, exit_cfg, bars))
        except ValueError as e:
            errors.append({"symbol": sig["symbol"], "error": str(e)})
    res = {"plans": plans, "errors": errors}
    if args.write:
        write_json("plan.json", res)
    out(res)


def cmd_size(args, cfg):
    plans = (read_json("plan.json") or {}).get("plans")
    if not plans:
        sys.exit("No plans in trader/plan.json. Run: gtrade.py plan --write")
    orders = [size(p, cfg) for p in plans]
    if args.write:
        write_json("orders.json", {"orders": orders})
    out({"orders": orders})


def cmd_risk(args, cfg):
    orders = (read_json("orders.json") or {}).get("orders")
    if not orders:
        sys.exit("No orders in trader/orders.json. Run: gtrade.py size --write")
    now = datetime.fromisoformat(args.now).replace(tzinfo=IST) if args.now else (None if args.no_clock else now_ist())
    checked = risk_check(orders, cfg, read_json("journal.json", []), now=now)
    if args.write:
        write_json("orders.json", {"orders": checked, "checked_at": (now or now_ist()).isoformat()})
    out({"orders": checked})


def cmd_show(args, cfg):
    orders = (read_json("orders.json") or {}).get("orders") or []
    if not orders:
        print("No orders yet.")
        return
    for o in orders:
        verb = "Buy" if o["side"] == "BUY" else "Sell short"
        mode = "PAPER" if o.get("paper", True) else "LIVE"
        status = o.get("risk_check", "NOT CHECKED")
        print(f"[{status}] [{mode}] {verb} {o['qty']} {o['symbol']} ({o['product']}) at about ₹{o['entry']}")
        print(f"    stop ₹{o['stop']}  target ₹{o['target']}  flat by {o['flat_by'][11:16]} IST")
        if o.get("qty"):
            print(f"    if stopped: ₹{o['loss_at_stop']}   if target: ₹{o['profit_at_target']}"
                  f"   (charges ~₹{o['charges_est']})")
        for r in o.get("risk_reasons", []):
            print(f"    blocked: {r}")


def cmd_backtest(args, cfg):
    interval = args.interval or cfg["interval_min"]
    src = get_source(args.source, cfg["exchange"])
    override_exit(cfg, args.setup, args.stop, args.target)
    if args.shorts:
        cfg["allow_short"] = True
    if not args.symbol:
        return _backtest_account(args, cfg, src, interval)
    symbol = args.symbol.upper()
    candles = get_candles(src, symbol, interval, args.days)
    res = bt.run(symbol, candles, args.setup, cfg, interval)
    res["rules"] = {"setup": args.setup, "shorts": bool(cfg.get("allow_short")), **exit_rules(cfg, args.setup),
                    "setup_params": setup_params(cfg, args.setup)}
    res["outlook"] = bt.bootstrap(res["trades"], next_n=args.next)
    if args.baseline:
        from groww_trader import baseline
        res["vs_random_entries"] = baseline.compare(res["trades"], {symbol: candles}, cfg, args.setup,
                                                    interval, runs=args.baseline)
    if args.write:
        write_json("backtest.json", res)
        get_store().save_backtest(res)
    if args.trades:
        out(res)
    else:
        out({k: v for k, v in res.items() if k != "trades"})


def account_backtest(cfg, src, interval, setup, days, symbols=None, baseline_runs=0, next_n=20):
    """Whole watchlist, one account: per-stock trades merged in time order
    with the account limits from config (open positions, trades per day,
    daily loss). Returns (result, kept_trades, calendar_days)."""
    every, per_stock, errors, candles = [], {}, {}, {}
    for s in [w.upper() for w in (symbols or cfg["watchlist"])]:
        try:
            candles[s] = get_candles(src, s, interval, days)
            res = bt.run(s, candles[s], setup, cfg, interval)
        except Exception as e:
            errors[s] = str(e)
            continue
        every += res["trades"]
        per_stock[s] = {"signals": len(res["trades"])}
    if not candles:
        sys.exit(f"error: no data for any symbol: {errors}")
    kept, skipped = bt.apply_account_limits(every, cfg)
    for t in kept:
        per_stock[t["symbol"]].setdefault("taken", 0)
        per_stock[t["symbol"]]["taken"] += 1
        per_stock[t["symbol"]]["net"] = round(per_stock[t["symbol"]].get("net", 0) + t["net"], 2)
    kept.sort(key=lambda t: t["entry_time"])
    calendar = sorted({str(d) for cs in candles.values() for d in by_session(cs)})
    r = cfg["risk"]
    res = {
        "mode": "watchlist as one account",
        "setup": setup, "interval_min": interval, "capital": cfg["capital"],
        "rules": {**exit_rules(cfg, setup), "setup_params": setup_params(cfg, setup),
                  "shorts": bool(cfg.get("allow_short")),
                  "max_loss_per_trade": r["max_loss_per_trade"], "daily_loss_limit": r["daily_loss_limit"],
                  "max_trades_per_day": r["max_trades_per_day"], "max_open_positions": r["max_open_positions"],
                  "max_position_pct": r["max_position_pct"]},
        "first_day": calendar[0] if calendar else None, "last_day": calendar[-1] if calendar else None,
        "sessions": len(calendar),
        "signals": len(every), "skipped_by_limits": skipped,
        "stats": bt.stats(kept),
        "return_on_capital_pct": round(100 * sum(t["net"] for t in kept) / cfg["capital"], 2) if kept else 0,
        "per_stock": per_stock,
        "outlook": bt.bootstrap(kept, next_n=next_n),
        "data_errors": errors,
    }
    if baseline_runs:
        from groww_trader import baseline
        res["vs_random_entries"] = baseline.compare(kept, candles, cfg, setup, interval, runs=baseline_runs)
    return res, kept, calendar


def cmd_evaluate(args, cfg):
    """Test an idea end to end and print the scorecard: whole watchlist as one
    account, random-entry baseline, both halves of the period, drawdown."""
    from groww_trader import scorecard
    interval = args.interval or cfg["interval_min"]
    override_exit(cfg, args.setup, args.stop, args.target)
    if args.shorts:
        cfg["allow_short"] = True
    src = get_source(args.source, cfg["exchange"])
    symbols = [x.upper() for x in args.symbols] if args.symbols else None
    res, kept, calendar = account_backtest(cfg, src, interval, args.setup, args.days, symbols=symbols,
                                           baseline_runs=args.baseline)
    card = scorecard.build(res, kept, calendar)
    res["scorecard"] = card
    if args.write:
        write_json("evaluate.json", res)
        get_store().save_backtest(res)
    if args.json:
        out(res)
        return
    rules = res["rules"]
    sp = rules["setup_params"]
    names = list(res["per_stock"]) or (symbols or cfg["watchlist"])
    header = (f"Idea: {args.setup} on {len(names)} stocks, {interval}-min bars, "
              f"{res['first_day']} to {res['last_day']} ({res['sessions']} sessions)\n"
              f"Exits: stop {rules['stop']}, target {rules['target']}, out by {rules['flat_by']}"
              f"{' | shorts allowed' if rules['shorts'] else ''}\n"
              f"Setup: " + ", ".join(f"{k} {v}" for k, v in sp.items() if k != "exit") + "\n"
              f"Account: Rs {cfg['capital']:,.0f}, max Rs {rules['max_loss_per_trade']} loss a trade, "
              f"Rs {rules['daily_loss_limit']} a day, {rules['max_open_positions']} open, "
              f"{rules['max_trades_per_day']} trades a day\n")
    print(scorecard.render(card, header))
    if res["data_errors"]:
        print(f"\ndata errors (left out): {res['data_errors']}")


def _backtest_account(args, cfg, src, interval):
    res, kept, _ = account_backtest(cfg, src, interval, args.setup, args.days,
                                    baseline_runs=args.baseline, next_n=args.next)
    if args.trades:
        res["trades"] = kept
    if args.write:
        write_json("backtest.json", res)
    out(res)


# Live candles kept in memory during `paper run`: the first step fetches a
# week per symbol, later steps fetch only today's bars and merge them in.
_LIVE: dict = {}


def _paper_data(src, symbols, interval, until=None):
    data, errors = {}, {}
    for s in symbols:
        try:
            key = (s, interval, src.name)
            if src.name == "groww" and until is None and key in _LIVE:
                now = now_ist()
                start = datetime.combine(now.date(), parse_hhmm("09:00"), tzinfo=IST)
                fresh = src.candles(s, interval, start, now)
                _LIVE[key] = merge_candles(_LIVE[key], fresh)
                p = csv_path(s, interval)
                save_csv(merge_candles(load_csv(p) if p.exists() else [], fresh), p)
            else:
                _LIVE[key] = get_candles(src, s, interval, 7, until)
            data[s] = _LIVE[key]
        except Exception as e:  # one bad symbol must not stop the loop
            errors[s] = str(e)
    return data, errors


def _paper_status(journal, day):
    today = [e for e in journal if e.get("day") == str(day)]
    n = lambda st: sum(1 for e in today if e["status"] == st)
    net = round(sum(e.get("net", 0) for e in today if e["status"] == "closed"), 2)
    return f"open {n('open')}, pending {n('pending')}, closed {n('closed')}, today's net ₹{net}"


def cmd_paper(args, cfg):
    import time
    from groww_trader import paper

    interval = args.interval or cfg["interval_min"]
    symbols = [s.upper() for s in (args.symbols or cfg["watchlist"])]

    if args.action == "report":
        name = "journal_replay.json" if args.replay else "journal.json"
        out(paper.report(read_json(name, []), day=args.date))
        return

    if args.action == "replay":
        if not args.date:
            sys.exit("replay needs --date YYYY-MM-DD")
        day = date.fromisoformat(args.date)
        src = get_source(args.source, cfg["exchange"])
        data, errors = _paper_data(src, symbols, interval, until=day)
        journal, log = paper.replay(cfg, data, day, interval)
        for line in log:
            print(line)
        if errors:
            print(f"data errors: {errors}")
        if args.write:
            old = [e for e in read_json("journal_replay.json", []) if e.get("day") != str(day)]
            write_json("journal_replay.json", old + journal)
        out(paper.report(journal))
        return

    # Connect to Groww only once we know this copy will actually trade: the
    # cron safety net starts a copy every 10 minutes, and each Groww login
    # counts against the rate limit the running copy needs.
    src_box = []

    def source():
        if not src_box:
            src_box.append(get_source(args.source, cfg["exchange"]))
        return src_box[0]

    if not cfg.get("paper", True):
        print("note: config has paper=false, but this command only ever simulates. No orders are sent.")
    from groww_trader import notify, runner
    tg = notify.Telegram()
    seen_errors = set()  # (day, symbol, error): alert each data problem once a day

    def one_step(now):
        journal = read_json("journal.json", [])
        data, errors = _paper_data(source(), symbols, interval)
        paused = notify.is_paused()
        journal, events = paper.step(cfg, data, now, journal, interval, paused=paused)
        write_json("journal.json", journal)
        runner.mark_step(now)
        status = _paper_status(journal, now.date()) + (" [PAUSED]" if paused else "")
        for ev in events:
            print(f"[{now:%H:%M}] {ev}", flush=True)
        for s, err in errors.items():
            print(f"[{now:%H:%M}] data error {s}: {err}", flush=True)
        print(f"[{now:%H:%M}] {status}", flush=True)
        # Optional outputs, after all trading work is done and saved.
        err_events = [f"DATAERR {s}: {e}" for s, e in errors.items()]
        store = get_store()
        if store.enabled:
            store.sync_journal(journal, day=str(now.date()))
            store.log_events(events + err_events, now)
            store.heartbeat(now, status, symbols, errors)
        if tg.enabled:
            new_errs = [e for e in err_events if (now.date(), e) not in seen_errors]
            seen_errors.update((now.date(), e) for e in err_events)
            tg.send_events(events + new_errs, now)

    def status_text():
        now = now_ist()
        return f"[{now:%H:%M}] {_paper_status(read_json('journal.json', []), now.date())}"

    def report_text(day=None):
        r = paper.report(read_json("journal.json", []), day=day)
        st = r["stats"]
        if not st.get("trades"):
            return f"Paper report{' ' + day if day else ''}: no closed trades yet. Ideas: {r['ideas'] or 'none'}"
        return (f"Paper report{' ' + day if day else ' (all days)'}\n"
                f"trades {st['trades']} | wins {st['wins']} | win rate {st['win_rate_pct']}%\n"
                f"net Rs {st['net_total']} (charges Rs {st['charges_total']})\n"
                f"max drawdown Rs {st['max_drawdown']}\nideas: {r['ideas']}")

    def serve_commands():
        if tg.enabled:
            for reply in notify.handle(tg.poll(), status_text, report_text):
                tg.send(reply)

    lock = runner.Lock("paper")
    if not lock.acquire():
        # Another copy is running (e.g. cron's). Don't touch the journal; just
        # check it isn't stuck.
        now = now_ist()
        msg = runner.alert_if_stuck(now, tg.send if tg.enabled else (lambda m: None))
        print(msg or "A paper run is already active; nothing to do.")
        return

    if args.action == "once":
        now = datetime.fromisoformat(args.now).replace(tzinfo=IST) if args.now else now_ist()
        try:
            serve_commands()
            one_step(now)
        finally:
            lock.release()
        return

    # run: loop until the close. Safe to start repeatedly from cron.
    now = now_ist()
    if now.weekday() >= 5:
        print("Market closed (weekend).")
        lock.release()
        return
    if runner.is_done(now) and not args.force:
        print("Today's paper run already finished. Use --force to run again.")
        lock.release()
        return
    log_path = runner.daily_log(now) if not args.no_log else None
    try:
        source()
    except Exception:
        lock.release()
        raise
    st = runner.mark_start(now)
    print(f"[{now:%H:%M}] Paper trading {', '.join(symbols)} on {interval}-minute bars. "
          f"No orders are sent.{' (restart)' if st['restart'] else ''}", flush=True)
    print(f"[{now:%H:%M}] Telegram alerts: "
          + ("on" if tg.enabled else "OFF (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set for this process)"),
          flush=True)
    if tg.enabled:
        if st["restart"]:
            last = st.get("last_step")
            tg.send(f"Paper bot RESTARTED at {now:%H:%M} after stopping unexpectedly"
                    + (f" (last completed step {last[11:16]})." if last else ".")
                    + " Any trigger it missed while down is recorded as missed.")
        else:
            tg.send(f"Paper trading started: {', '.join(symbols)} ({interval}-min bars)."
                    + (" Currently PAUSED, /resume to allow new positions." if notify.is_paused() else "")
                    + " /help for commands.")
    from groww_trader.market import MARKET_CLOSE
    try:
        while True:
            now = now_ist()
            close = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=IST)
            if now > close + timedelta(minutes=10):
                one_step(close + timedelta(minutes=1))
                out(paper.report(read_json("journal.json", []), day=str(now.date())))
                runner.mark_done(now)
                if tg.enabled:
                    tg.send("Market closed. " + report_text(str(now.date())))
                break
            wake = paper.next_boundary(now, interval)
            if now >= datetime.combine(now.date(), parse_hhmm("09:15"), tzinfo=IST):
                try:
                    one_step(now)
                except Exception as e:
                    print(f"[{now:%H:%M}] step failed, will retry next bar: {e}", flush=True)
                    if tg.enabled:
                        tg.send(f"[{now:%H:%M}] step failed, retrying next bar: {str(e)[:300]}")
            # sleep until the next bar, answering Telegram commands meanwhile
            while (left := (wake - now_ist()).total_seconds()) > 0:
                serve_commands()
                time.sleep(min(20.0, max(1.0, left)))
    except KeyboardInterrupt:
        print("\nStopped. Journal is saved in trader/journal.json; run again to resume.")
    finally:
        lock.release()
        if log_path and sys.stdout is not sys.__stdout__:
            sys.stdout.flush()
            sys.stdout = sys.__stdout__


def cmd_pause(args, cfg):
    from groww_trader import notify
    if args.cmd == "pause":
        notify.set_paused(True, "paused from the command line\n")
        print("Paused: no new positions; open ones are still managed. `gtrade.py resume` to undo.")
    else:
        notify.set_paused(False)
        print("Resumed: new positions allowed from the next bar.")


def cmd_telegram(args, cfg):
    from groww_trader import notify
    tg = notify.Telegram()
    if not tg.token:
        sys.exit("error: set TELEGRAM_BOT_TOKEN first (create a bot with @BotFather in Telegram)")
    if args.action == "setup":
        chats = tg.chats_seen()
        if not chats:
            print("No messages found. Open your bot in Telegram, send it any message (e.g. hi), then run this again.")
            return
        print("Chats that messaged your bot (put YOUR id in TELEGRAM_CHAT_ID):")
        for c in chats:
            print(f"  {c['chat_id']}  {c['name']} ({c['type']})")
        return
    if not tg.chat_id:
        sys.exit("error: set TELEGRAM_CHAT_ID (run: gtrade.py telegram setup)")
    ok = tg.send("Test from groww-trader-skills: alerts are working. /help for commands.")
    print("sent" if ok else "error: could not send (see warning above)")


def cmd_sweep(args, cfg):
    from groww_trader import sweep as sw

    if args.shorts:
        cfg["allow_short"] = True

    interval = args.interval or cfg["interval_min"]
    src = get_source(args.source, cfg["exchange"])
    data, errors = {}, {}
    for s in symbols_arg(args, cfg):
        try:
            data[s] = get_candles(src, s, interval, args.days)
        except Exception as e:
            errors[s] = str(e)
    if not data:
        sys.exit(f"error: no data for any symbol: {errors}")
    split = lambda x: [p.strip() for p in x.split(",") if p.strip()] if x else None
    vs = sw.variants(split(args.setups) or list(SETUPS), split(args.stops),
                     split(args.targets) or ["1R", "1.5R", "2R", "3R"],
                     [int(r) for r in split(args.ranges)] if args.ranges else None)
    try:
        res = sw.sweep(data, cfg, interval, vs, train_frac=args.train, min_trades=args.min_trades, top=args.top)
    except ValueError as e:
        sys.exit(f"error: {e}")
    res["data_errors"] = errors
    if args.write:
        write_json("sweep.json", res)
    if args.json:
        out(res if args.all else {k: v for k, v in res.items() if k != "all"})
        return

    sp = res["split"]
    print(f"Sweep: {res['variants_tested']} rule variations x {len(res['symbols'])} symbols, after charges"
          f"{', longs and shorts' if cfg.get('allow_short') else ', longs only'}")
    print(f"Train (choose): up to {sp['train_until']}   Test (unseen): from {sp['test_from']}")
    print(f"{res['profitable_on_train']} of {res['eligible']} variations with >= {res['min_trades']} train trades "
          f"made money on train.\n")
    head = f"{'rule':38} {'train trades':>12} {'train net':>11} {'test trades':>11} {'test net':>10}"
    print(head)
    print("-" * len(head))
    for r in res["top"]:
        v = r["rule"]
        name = f"{v['setup']} stop={v['stop']} tgt={v['target']}" + (f" rng={v['range_min']}" if v.get("range_min") else "")
        print(f"{name:38} {r['train']['trades']:>12} {r['train']['net_total']:>11.0f} "
              f"{r['test']['trades']:>11} {r['test']['net_total']:>10.0f}")
    print(f"\nVerdict: {res['verdict']}")
    if errors:
        print(f"Data errors: {errors}")


def cmd_swing(args, cfg):
    from groww_trader import swing

    src = get_source(args.source, cfg["exchange"])
    data, errors = {}, {}
    for s in symbols_arg(args, cfg):
        try:
            data[s] = get_candles(src, s, 1440, args.days)
        except Exception as e:
            errors[s] = str(e)
    if not data:
        sys.exit(f"error: no daily data for any symbol: {errors}\n"
                 "Fetch it first: gtrade.py fetch --interval 1440 --days 1100")
    from groww_trader import adjust
    data, events = adjust.adjust_all(data)
    if events:
        print(f"Adjusted for {len(events)} corporate actions (splits, bonuses, demergers).")
    lst = lambda x, conv=str: [conv(p.strip()) for p in x.split(",") if p.strip()]
    rules = swing.grid(lst(args.lookbacks, int), lst(args.stops), lst(args.targets),
                       lst(args.holds, int), lst(args.trends, int))
    try:
        res = swing.sweep(data, cfg, rules, train_frac=args.train, min_trades=args.min_trades, top=args.top)
    except ValueError as e:
        sys.exit(f"error: {e}")
    res["data_errors"] = errors
    if args.write:
        write_json("swing.json", res)
    if args.json:
        out(res if args.all else {k: v for k, v in res.items() if k != "all"})
        return
    sp = res["split"]
    print(f"Swing sweep (daily candles, delivery, longs): {res['variants_tested']} rule variations x "
          f"{len(res['symbols'])} symbols, after delivery charges")
    print(f"Train (choose): up to {sp['train_until']}   Test (unseen): from {sp['test_from']}")
    print(f"{res['profitable_on_train']} of {res['eligible']} variations with >= {res['min_trades']} train trades "
          f"made money on train.\n")
    head = f"{'rule':44} {'train trades':>12} {'train net':>11} {'test trades':>11} {'test net':>10}"
    print(head)
    print("-" * len(head))
    for r in res["top"]:
        v = r["rule"]
        name = f"hi{v['lookback']} stop={v['stop']} tgt={v['target']} hold={v['hold']}d" + \
            (f" sma{v['trend']}" if v["trend"] else "")
        print(f"{name:44} {r['train']['trades']:>12} {r['train']['net_total']:>11.0f} "
              f"{r['test']['trades']:>11} {r['test']['net_total']:>10.0f}")
    print(f"\nVerdict: {res['verdict']}")
    if errors:
        print(f"Data errors: {errors}")


def cmd_portfolio(args, cfg):
    from groww_trader import portfolio as pf
    from groww_trader import universe

    if args.universe:
        uni, udesc = universe.load(args.universe)
    else:
        uni, udesc = [s.upper() for s in cfg["watchlist"]], f"your watchlist ({len(cfg['watchlist'])} stocks)"
    bench = args.benchmark.upper() if args.benchmark else None
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    need = (assets + (uni if args.universe else []) if args.strategy == "dualmom" else uni) + ([bench] if bench else [])
    src = get_source(args.source, cfg["exchange"])
    data, errors = {}, {}
    for n, s in enumerate(dict.fromkeys(need), 1):
        if len(need) > 15 and src.name == "groww":
            print(f"[{n}/{len(need)}] {s}", file=sys.stderr, flush=True)
        try:
            data[s] = get_candles(src, s, 1440, args.days)
        except Exception as e:
            errors[s] = str(e)[:160]
    if bench and bench not in data:
        sys.exit(f"error: no daily data for the benchmark {bench}. Fetch it: gtrade.py fetch {bench} "
                 f"--interval 1440 --days {args.days}")
    events = []
    if not args.no_adjust:
        from groww_trader import adjust
        data, events = adjust.adjust_all(data)
    m = pf.build_market(data, bench, ew_universe=[s for s in uni if s in data])
    base = {"strategy": args.strategy, "universe": [s for s in uni if s in data], "assets": assets,
            "benchmark": bench, "lookback": args.lookback, "skip": args.skip, "top": args.top,
            "weight": args.weight, "regime": args.regime, "sma": args.sma, "rebalance": args.rebalance,
            "band": args.band, "cash_yield_pct": args.cash_yield, "rf_pct": args.rf}
    capital = float(args.capital or cfg["capital"])
    try:
        if args.sweep:
            res = pf.sweep(m, base, pf.grid(args.strategy), cfg, train_frac=args.train, capital=capital)
        else:
            res = pf.evaluate(m, base, cfg, train_frac=args.train, capital=capital)
    except ValueError as e:
        sys.exit(f"error: {e}")
    res.update(universe=udesc, data_errors=errors, adjustments=events, survivorship_note=(
        "Uses today's index members for past years, which flatters results (survivorship bias)."
        if args.universe and args.universe.lower().startswith("nifty") else None))
    if args.write:
        write_json("portfolio.json", res)
    if args.json:
        out(res if args.all else {k: v for k, v in res.items() if k != "all"})
        return

    pct = lambda v: "—" if v is None else f"{v:+.1f}%"
    print(f"{args.strategy} on {udesc}, rebalance {args.rebalance}, "
          f"after delivery charges and {cfg.get('slippage_pct', 0)}% slippage")
    if events:
        kinds = {}
        for e in events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"Adjusted for {len(events)} corporate actions ({', '.join(f'{v} {k}' for k, v in kinds.items())}); "
              "see `audit` for the list.")
    regime_sym = pf.regime_symbol(m, base) if args.regime == "cash" else None
    if regime_sym == pf.EQW:
        print(f"Regime filter uses the universe's equal-weight index ({bench} history is too short).")
    if args.sweep:
        sp = res["split"]
        print(f"Train (choose): {sp['train'][0]} to {sp['train'][1]}   Test (unseen): {sp['test'][0]} to {sp['test'][1]}")
        print(f"{res['beat_benchmark_on_train']} of {res['variants_tested']} variations beat the benchmark on train.\n")
        head = f"{'rule':40} {'train':>9} {'bench':>9} {'test':>9} {'bench':>9} {'test maxDD':>10}"
        print(head + "\n" + "-" * len(head))
        for r in res["top"]:
            v = r["rule"]
            name = " ".join(f"{k}={v[k]}" for k in ("lookback", "top", "regime", "weight") if k in v)
            tr, te = r["train"], r["test"]
            print(f"{name:40} {pct(tr['strategy']['total_return_pct']):>9} {pct(tr.get('benchmark', {}).get('total_return_pct')):>9} "
                  f"{pct(te['strategy']['total_return_pct']):>9} {pct(te.get('benchmark', {}).get('total_return_pct')):>9} "
                  f"{pct(te['strategy']['max_drawdown_pct']):>10}")
        bn = {r["train"].get("benchmark_name") for r in res["top"]} | {r["test"].get("benchmark_name") for r in res["top"]}
        print(f"\n(total returns over each period, after costs; bench = {', '.join(sorted(x for x in bn if x))})")
    else:
        head = f"{'period':7} {'dates':25} {'return':>8} {'CAGR':>7} {'bench':>8} {'maxDD':>7} {'Sharpe':>6} {'trades':>6} {'costs ₹':>9}"
        print(head + "\n" + "-" * len(head))
        for name in ("train", "test", "full"):
            r = res[name]
            s, b = r["strategy"], r.get("benchmark", {})
            print(f"{name:7} {s['start'] + ' to ' + s['end']:25} {pct(s['total_return_pct']):>8} {pct(s['cagr_pct']):>7} "
                  f"{pct(b.get('total_return_pct')):>8} {pct(s['max_drawdown_pct']):>7} "
                  f"{(s['sharpe'] if s['sharpe'] is not None else '—'):>6} {s['trades']:>6} {s['costs']:>9.0f}")
        held = res["full"]["last_holdings"]
        print(f"\nHolding at the end: {', '.join(f'{k} x{v}' for k, v in held.items()) or 'cash'}")
        for name in ("train", "test"):
            r = res[name]
            parts = []
            if "etf" in r:
                parts.append(f"{bench} {pct(r['etf']['total_return_pct'])}")
            if "universe_ew" in r:
                parts.append(f"universe equal-weight {pct(r['universe_ew']['total_return_pct'])} (no costs)")
            if parts:
                print(f"{name}: strategy {pct(r['strategy']['total_return_pct'])} vs " + ", ".join(parts)
                      + (f"  -> judged against {r['benchmark_name']}: {pct(r['excess_total_pct'])}" if "excess_total_pct" in r else ""))
    if res.get("verdict"):
        print(f"\nVerdict: {res['verdict']}")
    if res.get("survivorship_note"):
        print(f"Note: {res['survivorship_note']}")
    if args.cash_yield == 0:
        print("Note: idle cash earns nothing here; --cash-yield 6.5 models parking it in a liquid fund.")
    if errors:
        print(f"Data errors ({len(errors)}): {', '.join(list(errors)[:10])}{' ...' if len(errors) > 10 else ''}")


def cmd_audit(args, cfg):
    """Check cached daily data: history length and one-day jumps that look
    like unadjusted splits or bonus issues."""
    from groww_trader import universe
    syms = universe.load(args.universe)[0] if args.universe else symbols_arg(args, cfg)
    syms += [s.upper() for s in (args.symbols or []) if args.universe and s.upper() not in syms]
    rows, jumps, missing = [], [], []
    for s in syms:
        p = csv_path(s, args.interval)
        if not p.exists():
            missing.append(s)
            continue
        c = load_csv(p)
        if not c:
            missing.append(s)
            continue
        rows.append({"symbol": s, "first": str(c[0].ts.date()), "last": str(c[-1].ts.date()), "bars": len(c)})
        for a_, b_ in zip(c, c[1:]):
            r = b_.close / a_.close - 1 if a_.close else 0
            if abs(r) >= args.jump / 100:
                jumps.append({"symbol": s, "date": str(b_.ts.date()), "prev_close": a_.close,
                              "close": b_.close, "change_pct": round(100 * r, 1),
                              "ratio": round(a_.close / b_.close, 2) if b_.close else None})
    rows.sort(key=lambda r: r["first"])
    from groww_trader import adjust
    proposed = []
    if args.interval == 1440:
        ov = adjust.load_overrides()
        for s in syms:
            p = csv_path(s, args.interval)
            if p.exists():
                proposed += adjust.detect(s, load_csv(p), ov)
    out({"symbols": len(syms), "with_data": len(rows), "missing": missing,
         "adjustments_applied_in_tests": proposed,
         "first_day_spread": [rows[0]["first"], rows[-1]["first"]] if rows else None,
         "latest_starters": rows[-8:], "big_one_day_moves": jumps[: args.limit],
         "big_moves_total": len(jumps)})


def cmd_mongo(args, cfg):
    store = get_store()
    if args.action == "check":
        out(store.check())
        return
    # sync: push the whole local journal (e.g. after enabling MongoDB)
    journal = read_json("journal.json", [])
    ok = store.sync_journal(journal, full=True)
    out({"ok": ok, "journal_entries": len(journal), **({} if ok else {"reason": store.error})})


def cmd_costs(args, cfg):
    """Charges for one round trip and the move needed to break even."""
    from groww_trader.costs import break_even
    ch, slip = cfg["charges"], cfg.get("slippage_pct", 0.0)
    if args.price and args.qty:
        values = [args.price * args.qty]
    elif args.value:
        values = [args.value]
    else:
        values = [2000, 5000, 10000, 25000, 50000, 100000]
    products = [args.product] if args.product else ["MIS", "CNC"]
    rows = [break_even(v, ch, p, stop_pct=args.stop_pct or 0, slippage_pct=slip)
            for v in values for p in products]
    if args.json:
        out(rows)
        return
    print("Round trip = buy + sell at the same price. Groww charges as configured; re-check groww.in/pricing.")
    print(f"{'trade value':>12}  {'type':<15} {'charges':>9}  {'break-even move':>15}"
          + (f"  {'+ slippage':>10}" if slip else "") + (f"  {'costs vs risk':>13}" if args.stop_pct else ""))
    for r in rows:
        line = (f"Rs {r['trade_value']:>9,.0f}  {r['product']:<15} Rs {r['charges']['total']:>6.2f}"
                f"  {r['break_even_move_pct']:>14.3f}%")
        if slip:
            line += f"  {r.get('break_even_with_slippage_pct', r['break_even_move_pct']):>9.3f}%"
        if args.stop_pct:
            line += f"  {r['costs_as_pct_of_risk']:>12.1f}%"
        print(line)
    if args.stop_pct:
        print(f"\ncosts vs risk: charges (+ slippage) as a share of what you lose at a {args.stop_pct}% stop. "
              "Above about 20%, costs eat most of any edge.")
    if len(values) == 1:
        r = rows[0]
        print("\nbreakdown (" + r["product"] + "): "
              + ", ".join(f"{k} {v}" for k, v in r["charges"].items() if k != "total" and v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="config file (default trader/config.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, symbols=False):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        if symbols:
            p.add_argument("symbols", nargs="*")
        p.add_argument("--source", default="auto", choices=["auto", "csv", "groww"])
        return p

    add("check", cmd_check)
    p = add("evaluate", cmd_evaluate, symbols=True)
    p.description = "Test an idea on the whole watchlist (or the symbols given) and print a pass/fail scorecard."
    p.add_argument("--setup", default="orb", choices=SETUPS)
    p.add_argument("--interval", type=int)
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--stop")
    p.add_argument("--target")
    p.add_argument("--shorts", action="store_true")
    p.add_argument("--baseline", type=int, default=300, metavar="RUNS",
                   help="random-entry runs (default 300; 0 skips the check)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true", help="save to trader/evaluate.json (and MongoDB if set up)")
    p = sub.add_parser("costs", help="what a trade really costs, and the move needed to break even")
    p.set_defaults(fn=cmd_costs)
    p.add_argument("value", nargs="?", type=float, help="trade value in rupees (default: a table of sizes)")
    p.add_argument("--price", type=float)
    p.add_argument("--qty", type=int)
    p.add_argument("--product", choices=["MIS", "CNC"], type=str.upper, help="MIS intraday, CNC delivery (default both)")
    p.add_argument("--stop-pct", type=float, help="your stop distance in %%: shows costs as a share of the risk")
    p.add_argument("--json", action="store_true")
    add("ltp", cmd_ltp, symbols=True)
    p = add("fetch", cmd_fetch, symbols=True)
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--universe", help="nifty50|nifty100|nifty200|nifty500, a file, or A,B,C; symbols given are added")
    p = sub.add_parser("inspect", help="show raw Groww candles for one symbol (debugging)")
    p.set_defaults(fn=cmd_inspect)
    p.add_argument("symbol")
    p.add_argument("--interval", type=int, default=1440)
    p.add_argument("--days", type=int, default=90)
    p = add("scan", cmd_scan, symbols=True)
    p.add_argument("--setup", choices=SETUPS)
    p.add_argument("--interval", type=int)
    p.add_argument("--at", help="HH:MM, evaluate as of this time")
    p.add_argument("--date", help="YYYY-MM-DD, scan a past session")
    p.add_argument("--write", action="store_true")
    p = add("plan", cmd_plan)
    p.add_argument("--symbol")
    p.add_argument("--stop")
    p.add_argument("--target")
    p.add_argument("--write", action="store_true")
    p = add("size", cmd_size)
    p.add_argument("--write", action="store_true")
    p = add("risk", cmd_risk)
    p.add_argument("--now", help="YYYY-MM-DDTHH:MM, check as of this IST time")
    p.add_argument("--no-clock", action="store_true", help="skip time-of-day checks (for past sessions)")
    p.add_argument("--write", action="store_true")
    add("show", cmd_show)
    p = add("backtest", cmd_backtest)
    p.add_argument("symbol", nargs="?", help="one stock; leave out to test the whole watchlist as one account")
    p.add_argument("--setup", default="orb", choices=SETUPS)
    p.add_argument("--interval", type=int)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--stop")
    p.add_argument("--target")
    p.add_argument("--next", type=int, default=20, help="trades to project in the outlook")
    p.add_argument("--trades", action="store_true", help="include every trade in the output")
    p.add_argument("--shorts", action="store_true", help="also take short trades (intraday MIS only)")
    p.add_argument("--baseline", type=int, default=0, metavar="RUNS",
                   help="compare with RUNS sets of random-timed entries (try 500)")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("paper", help="simulated trading on live data; never sends orders")
    p.set_defaults(fn=cmd_paper)
    p.add_argument("action", choices=["run", "once", "replay", "report"])
    p.add_argument("symbols", nargs="*")
    p.add_argument("--source", default="auto", choices=["auto", "csv", "groww"])
    p.add_argument("--interval", type=int)
    p.add_argument("--date", help="replay: session to replay; report: only this day")
    p.add_argument("--now", help="once: YYYY-MM-DDTHH:MM, step as of this IST time")
    p.add_argument("--replay", action="store_true", help="report on replay journal")
    p.add_argument("--write", action="store_true", help="replay: save to trader/journal_replay.json")
    p.add_argument("--force", action="store_true", help="run: start even if today's run already finished")
    p.add_argument("--no-log", action="store_true", help="run: print to the terminal only, no daily log file")
    p = add("sweep", cmd_sweep, symbols=True)
    p.add_argument("--setups", help="comma list, default: all setups")
    p.add_argument("--stops", help="comma list, default: every stop that suits each setup")
    p.add_argument("--targets", help="comma list, default 1R,1.5R,2R,3R")
    p.add_argument("--ranges", help="opening-range minutes to try for orb/orb_fade, e.g. 15,30")
    p.add_argument("--interval", type=int)
    p.add_argument("--days", type=int, default=365, help="days of history to use (default 365)")
    p.add_argument("--train", type=float, default=0.6, help="fraction of sessions used to choose (default 0.6)")
    p.add_argument("--min-trades", type=int, default=10)
    p.add_argument("--shorts", action="store_true", help="also take short trades (intraday MIS only)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="with --json, include every variation")
    p.add_argument("--write", action="store_true", help="save to trader/sweep.json")
    p = add("swing", cmd_swing, symbols=True)
    p.add_argument("--lookbacks", default="20,55", help="N-day high to break (comma list)")
    p.add_argument("--stops", default="pct:3,pct:5,atr:2")
    p.add_argument("--targets", default="2R,3R,none")
    p.add_argument("--holds", default="10,20", help="max days in a trade")
    p.add_argument("--trends", default="0,50", help="only buy above this SMA; 0 = no filter")
    p.add_argument("--days", type=int, default=1100, help="calendar days of daily candles to use")
    p.add_argument("--train", type=float, default=0.6)
    p.add_argument("--min-trades", type=int, default=8)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--write", action="store_true", help="save to trader/swing.json")
    p = add("audit", cmd_audit, symbols=True)
    p.add_argument("--universe")
    p.add_argument("--interval", type=int, default=1440)
    p.add_argument("--jump", type=float, default=35, help="flag one-day moves at least this %% (default 35)")
    p.add_argument("--limit", type=int, default=60)
    p = sub.add_parser("portfolio", help="multi-stock strategies (momentum, low-vol, dual momentum) vs the index")
    p.set_defaults(fn=cmd_portfolio)
    p.add_argument("--strategy", default="momentum", choices=["momentum", "lowvol", "dualmom"])
    p.add_argument("--universe", help="nifty50|nifty100|nifty200|nifty500, a file, or A,B,C (default: watchlist)")
    p.add_argument("--benchmark", default="NIFTYBEES", help="ETF to compare with and for the regime filter")
    p.add_argument("--assets", default="NIFTYBEES,GOLDBEES", help="dualmom: assets to rotate between")
    p.add_argument("--lookback", type=int, default=252, help="trading days for the score")
    p.add_argument("--skip", type=int, default=21, help="momentum: skip the most recent N days")
    p.add_argument("--top", type=int, default=10, help="how many stocks to hold")
    p.add_argument("--weight", default="equal", choices=["equal", "invvol"])
    p.add_argument("--regime", default="off", choices=["off", "cash"], help="cash = hold cash when the benchmark is below its average")
    p.add_argument("--sma", type=int, default=200)
    p.add_argument("--rebalance", default="monthly", choices=["monthly", "weekly"])
    p.add_argument("--band", type=float, default=0.2, help="don't resize a holding for changes smaller than this")
    p.add_argument("--cash-yield", type=float, default=0.0, help="annual %% earned on idle cash")
    p.add_argument("--rf", type=float, default=6.5, help="risk-free %% for the Sharpe ratio")
    p.add_argument("--capital", type=float)
    p.add_argument("--days", type=int, default=2500, help="calendar days of daily history to use")
    p.add_argument("--train", type=float, default=0.6)
    p.add_argument("--sweep", action="store_true", help="try a small grid of variations, judged on unseen data")
    p.add_argument("--no-adjust", action="store_true", help="don't adjust for splits, bonuses and demergers")
    p.add_argument("--source", default="auto", choices=["auto", "csv", "groww"])
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--write", action="store_true", help="save to trader/portfolio.json")
    for name in ("pause", "resume"):
        p = sub.add_parser(name, help=f"{name} new paper positions (open ones are always managed)")
        p.set_defaults(fn=cmd_pause)
    p = sub.add_parser("telegram", help="optional Telegram alerts: find your chat id, or send a test")
    p.set_defaults(fn=cmd_telegram)
    p.add_argument("action", choices=["setup", "test"])
    p = sub.add_parser("mongo", help="optional MongoDB mirror: check the connection or push the journal")
    p.set_defaults(fn=cmd_mongo)
    p.add_argument("action", choices=["check", "sync"])

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        args.fn(args, cfg)
    except (RuntimeError, FileNotFoundError) as e:  # setup problems: one line, no traceback
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
