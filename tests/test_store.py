import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import orb_day, random_days  # noqa: E402
from groww_trader import paper  # noqa: E402
from groww_trader.config import load_config  # noqa: E402
from groww_trader.market import IST  # noqa: E402
from groww_trader.store import Store, _scrub, daily_summary  # noqa: E402

DAY = date(2026, 10, 20)


class FakeColl:
    def __init__(self, fail=False):
        self.docs, self.fail, self.calls = {}, fail, 0

    def _check(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("cannot reach mongodb+srv://bot:s3cret@cluster0.example.net")

    def replace_one(self, flt, doc, upsert=False):
        self._check()
        self.docs[flt["_id"]] = doc

    def insert_many(self, docs):
        self._check()
        for d in docs:
            self.docs[len(self.docs)] = d

    def insert_one(self, doc):
        self.insert_many([doc])

    def count_documents(self, flt):
        self._check()
        return len(self.docs)


class FakeDB:
    name = "groww_trader"

    def __init__(self, fail=False):
        self.fail, self.colls = fail, {}

    def __getitem__(self, k):
        return self.colls.setdefault(k, FakeColl(self.fail))

    def command(self, c):
        if self.fail:
            raise ConnectionError("down")
        return {"ok": 1}


def journal():
    c = load_config("/nonexistent")
    c["setups"] = {"orb": c["setups"]["orb"]}
    bars = random_days(DAY - timedelta(days=1), 1, seed=3, price=100) + orb_day(DAY)
    j, _ = paper.replay(c, {"TEST": bars}, DAY, 5)
    j.append({"id": f"{DAY}:X:orb", "mode": "paper", "day": str(DAY), "symbol": "X",
              "status": "blocked", "risk_reasons": ["daily loss limit hit"]})
    return j


class StoreTests(unittest.TestCase):
    def test_disabled_without_uri(self):
        os.environ.pop("GTRADE_MONGO_URI", None)
        s = Store()
        self.assertFalse(s.enabled)
        self.assertFalse(s.sync_journal(journal()))
        self.assertFalse(s.check()["ok"])

    def test_sync_writes_journal_daily_events_health(self):
        db = FakeDB()
        s = Store(db=db, log=lambda *_: None)
        j = journal()
        self.assertTrue(s.sync_journal(j, day=str(DAY)))
        self.assertEqual(set(db["journal"].docs), {e["id"] for e in j})
        d = db["daily"].docs[str(DAY)]
        self.assertEqual((d["trades"], d["wins"], d["ideas"]), (1, 1, {"closed": 1, "blocked": 1}))
        self.assertGreater(d["net"], 0)
        when = datetime(2026, 10, 20, 9, 40, tzinfo=IST)
        self.assertTrue(s.log_events(["SIGNAL TEST orb BUY x246"], when))
        self.assertEqual(db["events"].docs[0]["kind"], "SIGNAL")
        self.assertTrue(s.heartbeat(when, "open 1", ["TEST"]))
        self.assertEqual(db["health"].docs["bot"]["status"], "open 1")
        self.assertTrue(s.check()["ok"])

    def test_incremental_after_first_full_sync(self):
        db = FakeDB()
        s = Store(db=db, log=lambda *_: None)
        j = journal() + [{"id": "2026-10-19:OLD:orb", "day": "2026-10-19", "status": "closed", "net": 5}]
        s.sync_journal(j, day=str(DAY))
        n = db["journal"].calls
        s.sync_journal(j, day=str(DAY))
        self.assertEqual(db["journal"].calls - n, len(j) - 1)  # old day not re-sent

    def test_failure_never_raises_and_backs_off(self):
        logs = []
        s = Store(db=FakeDB(fail=True), log=logs.append)
        self.assertFalse(s.sync_journal(journal()))
        self.assertFalse(s.heartbeat(datetime.now(tz=IST), "x", []))  # skipped during backoff
        self.assertEqual(len(logs), 1)
        self.assertNotIn("s3cret", logs[0])  # credentials scrubbed

    def test_scrub(self):
        self.assertEqual(_scrub("x mongodb+srv://u:p@h.net/db"), "x mongodb+srv://***@h.net/db")

    def test_daily_summary_empty_day(self):
        self.assertEqual(daily_summary([], "2026-01-01")["trades"], 0)


if __name__ == "__main__":
    unittest.main()
