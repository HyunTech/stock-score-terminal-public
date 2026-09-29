import csv
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import bci_common
import download_daily_ohlcv as download
import research_common
from score_bci_recommendations import read_price_rows
from score_universe import score_one


class CleanupChecks(unittest.TestCase):
    def test_shared_csv_reader_and_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "005930.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["date", "close", "volume", "ticker", "name", "market"])
                writer.writerows([f"2025{i:04}", "100", "2000", "005930", "삼성전자", "KOSPI"] for i in range(600))
            self.assertEqual(len(bci_common.read_tail_records(path)), 280)
            self.assertEqual(len(read_price_rows(path)), 260)
            score = score_one(path, "KR")
            self.assertEqual((score.symbol, score.name, score.last_close, score.rows), ("005930", "삼성전자", 100, 280))
            self.assertEqual((score.momentum_raw, score.volatility_raw, score.drawdown_raw), (0, 0, 0))
            self.assertEqual(score.liquidity_raw, 200000)
            for ending in ("\n", "\r\n"):
                for trailing in (True, False):
                    lines = [f"{i} 한글 {'x' * 400}" for i in range(100)]
                    content = ending.join(lines) + (ending if trailing else "")
                    path.write_bytes(content.encode("utf-8-sig"))
                    for size in (1, 20, 100, 200):
                        self.assertEqual(bci_common.tail_lines(path, size), lines[-size:])

    def test_research_helpers_and_match_limit(self):
        self.assertIs(research_common.read_json, bci_common.read_json)
        tickers = {str(i).zfill(6): {"ticker": str(i).zfill(6), "name": f"기업명{i}"} for i in range(30)}
        self.assertEqual(research_common.mentioned_tickers(" ".join(tickers), tickers), list(tickers.values())[:20])
        names = {"123456": {"name": "TEST"}, "654321": {"name": "삼성전자"}}
        self.assertEqual(research_common.mentioned_tickers("contest 삼성전자", names), [names["654321"]])
        self.assertEqual(research_common.mentioned_tickers("TEST", names), [names["123456"]])

    def test_download_sources_keep_retry_skip_and_csv_behavior(self):
        frame = pd.DataFrame({"Open": [100], "Close": [110], "Volume": [200]}, index=pd.to_datetime(["2026-01-02"]))
        ticker = {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"}
        for source in ("pykrx", "fdr"):
            fetch = Mock(side_effect=[RuntimeError("temporary"), frame])
            providers = {
                "pykrx": SimpleNamespace(stock=SimpleNamespace(get_market_ohlcv_by_date=fetch)),
                "FinanceDataReader": SimpleNamespace(DataReader=fetch),
            }
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory, \
                 patch.dict(sys.modules, providers), \
                 patch.object(download.time, "sleep"), patch.object(download, "tqdm", side_effect=lambda items, **kw: items):
                args = ([ticker], Path(directory), "20260101", "20260103", False, 0, None, source)
                self.assertEqual(download.download_kr_daily(*args), (1, []))
                self.assertEqual(fetch.call_count, 2)
                if source == "pykrx":
                    fetch.assert_called_with("20260101", "20260103", "005930", adjusted=True)
                else:
                    fetch.assert_called_with("005930", "2026-01-01", "2026-01-03")
                row = pd.read_csv(Path(directory) / "005930.csv").iloc[0]
                self.assertEqual((row["close"], row["source"]), (110, source))
                fetch.reset_mock()
                self.assertEqual(download.download_kr_daily(*args), (0, []))
                fetch.assert_not_called()
                fetch.side_effect = RuntimeError("offline")
                retry_args = (*args[:4], True, *args[5:])
                written, failures = download.download_kr_daily(*retry_args)
                self.assertEqual((written, len(failures), fetch.call_count), (0, 1, 3))


if __name__ == "__main__":
    unittest.main()
