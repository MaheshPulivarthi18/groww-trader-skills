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
from groww_trader.config import load_config, read_json, write_json  # noqa: E402
from groww_trader.data import (CSVSource, csv_path, get_source, load_csv,  # noqa: E402
                               lookback_window, merge_candles, save_csv)
from groww_trader.market import IST, by_session, now_ist, parse_hhmm  # noqa: E402
from groww_trader.plan import make_plan  # noqa: E402
from groww_trader.risk import check as risk_check  # noqa: E402
from groww_trader.setups import SETUPS, detect  # noqa: E402
from groww_trader.sizing import size  # noqa: E402


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
    for s in symbols_arg(args, cfg):
        try:
            c = get_candles(src, s, args.interval, args.days)
            res[s] = {"candles": len(c), "file": str(csv_path(s, args.interval))}
        except Exception as e:  # keep going across symbols
            res[s] = {"error": str(e)}
    out(res)


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
    exit_cfg = dict(cfg["exit"])
    if args.stop:
        exit_cfg["stop"] = args.stop
    if args.target:
        exit_cfg["target"] = args.target
    plans, errors = [], []
    for sig in scan["results"]:
        if sig.get("status") != "triggered":
            continue
        if args.symbol and sig["symbol"] != args.symbol.upper():
            continue
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
    symbol = args.symbol.upper()
    if args.stop:
        cfg["exit"]["stop"] = args.stop
    if args.target:
        cfg["exit"]["target"] = args.target
    candles = get_candles(src, symbol, interval, args.days)
    res = bt.run(symbol, candles, args.setup, cfg, interval)
    res["rules"] = {"setup": args.setup, **cfg["exit"], "setup_params": cfg["setups"].get(args.setup, {})}
    res["outlook"] = bt.bootstrap(res["trades"], next_n=args.next)
    if args.write:
        write_json("backtest.json", res)
    if args.trades:
        out(res)
    else:
        out({k: v for k, v in res.items() if k != "trades"})


def _paper_data(src, symbols, interval, until=None):
    data, errors = {}, {}
    for s in symbols:
        try:
            data[s] = get_candles(src, s, interval, 7, until)
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

    src = get_source(args.source, cfg["exchange"])
    if not cfg.get("paper", True):
        print("note: config has paper=false, but this command only ever simulates. No orders are sent.")

    def one_step(now):
        journal = read_json("journal.json", [])
        data, errors = _paper_data(src, symbols, interval)
        journal, events = paper.step(cfg, data, now, journal, interval)
        write_json("journal.json", journal)
        for ev in events:
            print(f"[{now:%H:%M}] {ev}", flush=True)
        for s, err in errors.items():
            print(f"[{now:%H:%M}] data error {s}: {err}", flush=True)
        print(f"[{now:%H:%M}] {_paper_status(journal, now.date())}", flush=True)

    if args.action == "once":
        now = datetime.fromisoformat(args.now).replace(tzinfo=IST) if args.now else now_ist()
        one_step(now)
        return

    # run: loop until the close
    print(f"Paper trading {', '.join(symbols)} on {interval}-minute bars. No orders are sent. Ctrl+C to stop.")
    from groww_trader.market import MARKET_CLOSE
    try:
        while True:
            now = now_ist()
            close = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=IST)
            if now.weekday() >= 5:
                print("Market closed (weekend).")
                break
            if now > close + timedelta(minutes=10):
                one_step(close + timedelta(minutes=1))
                out(paper.report(read_json("journal.json", []), day=str(now.date())))
                break
            wake = paper.next_boundary(now, interval)
            if now >= datetime.combine(now.date(), parse_hhmm("09:15"), tzinfo=IST):
                try:
                    one_step(now)
                except Exception as e:
                    print(f"[{now:%H:%M}] step failed, will retry next bar: {e}", flush=True)
            time.sleep(max(1.0, (wake - now_ist()).total_seconds()))
    except KeyboardInterrupt:
        print("\nStopped. Journal is saved in trader/journal.json; run again to resume.")


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
    add("ltp", cmd_ltp, symbols=True)
    p = add("fetch", cmd_fetch, symbols=True)
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--days", type=int, default=60)
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
    p.add_argument("symbol")
    p.add_argument("--setup", default="orb", choices=SETUPS)
    p.add_argument("--interval", type=int)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--stop")
    p.add_argument("--target")
    p.add_argument("--next", type=int, default=20, help="trades to project in the outlook")
    p.add_argument("--trades", action="store_true", help="include every trade in the output")
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

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
