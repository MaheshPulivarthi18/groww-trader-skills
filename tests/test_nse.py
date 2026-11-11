import io
import zipfile
from datetime import date

from groww_trader import nse


def _zip(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


OLD = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
       "ABC,EQ,100,110,95,105,105,100,1000,105000,01-JUL-2024,10,INE1,\n"
       "ABC,N1,1,1,1,1,1,1,1,1,01-JUL-2024,1,INE2,\n")
NEW = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
       "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
       "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
       "2024-07-08,2024-07-08,CM,NSE,STK,1,INE1,ABC,EQ,,,,,ABC LTD,53,56,52,55,55,52.5,,,,,2000,1,1,F1,1,,,,,\n")


def test_urls_switch_format_in_july_2024():
    assert "BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip" in nse.urls(date(2024, 7, 8))[0]
    assert nse.urls(date(2024, 7, 5))[0].endswith("/2024/JUL/cm05JUL2024bhav.csv.zip")


def test_parse_both_formats_keeps_equity_only():
    old = nse.parse_bhav(_zip("cm01JUL2024bhav.csv", OLD))
    assert old == [{"symbol": "ABC", "series": "EQ", "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
                    "prev": 100.0, "volume": 1000.0}]
    new = nse.parse_bhav(_zip("x.csv", NEW))
    assert new[0]["close"] == 55.0 and new[0]["prev"] == 52.5


def test_fetch_caches_skips_holidays_and_build_adjusts_split(tmp_path):
    # 1 Jul (old format) close 105; 8 Jul (new format) after a 1:2 split: NSE's adjusted prev close 52.5
    files = {nse.urls(date(2024, 7, 1))[0]: _zip("a.csv", OLD), nse.urls(date(2024, 7, 8))[0]: _zip("b.csv", NEW)}
    calls = []

    def fake_get(url):
        calls.append(url)
        return (200, files[url]) if url in files else (404, b"")

    res = nse.fetch(tmp_path, date(2024, 7, 1), date(2024, 7, 8), pause=0, get=fake_get, log=lambda *_: None)
    assert res["downloaded"] == 2 and res["holidays"] == 4 and not res["failed"]
    n = len(calls)
    again = nse.fetch(tmp_path, date(2024, 7, 1), date(2024, 7, 8), pause=0, get=fake_get, log=lambda *_: None)
    assert again["already_cached"] == 6 and len(calls) == n       # days and known holidays aren't re-asked
    candles, actions = nse.build(tmp_path, ["ABC"])
    c = candles["ABC"]
    assert [x.ts.date() for x in c] == [date(2024, 7, 1), date(2024, 7, 8)]
    assert actions[0]["factor"] == 2.0
    assert c[0].close == 52.5 and c[1].close == 55.0          # pre-split prices halved


def test_fetch_stops_when_refused(tmp_path):
    res = nse.fetch(tmp_path, date(2024, 1, 1), date(2024, 3, 1), pause=0, get=lambda u: (403, b""),
                    log=lambda *_: None)
    assert "stopped" in res and len(res["failed"]) == 5
