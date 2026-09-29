from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd
from pykrx import stock
from tqdm import tqdm
from download_daily_ohlcv import fdr_date


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def next_day(value: str) -> str:
    dt = datetime.strptime(value, "%Y%m%d") + timedelta(days=1)
    return dt.strftime("%Y%m%d")


def load_ticker_rows(metadata_path: Path) -> list[dict[str, str]]:
    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [row for row in csv.DictReader(handle) if row.get("ticker")]

    rows: list[dict[str, str]] = []
    listing = fdr.StockListing("KRX")
    for _, row in listing.iterrows():
        code = str(row.get("Code", "")).zfill(6)
        if not code:
            continue
        rows.append(
            {
                "ticker": code,
                "name": str(row.get("Name", "")),
                "market": str(row.get("Market", "")),
                "asof": today_yyyymmdd(),
            }
        )

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "name", "market", "asof"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def normalize_frame(df, ticker: str, name: str, market: str, source: str):
    if df is None or df.empty:
        return df

    df = df.reset_index()
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    elif "날짜" in df.columns:
        df = df.rename(columns={"날짜": "date"})
    else:
        df = df.rename(columns={df.columns[0]: "date"})

    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Change": "change_pct",
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "등락률": "change_pct",
        }
    )
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
    df["ticker"] = ticker
    df["name"] = name
    df["market"] = market
    df["source"] = source

    columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "change_pct",
        "ticker",
        "name",
        "market",
        "source",
    ]
    return df[[column for column in columns if column in df.columns]]


def fetch_ohlcv(ticker: str, start: str, until: str, source: str):
    if source == "pykrx":
        return stock.get_market_ohlcv_by_date(start, until, ticker)
    if source == "fdr":
        return fdr.DataReader(ticker, fdr_date(start), fdr_date(until))
    raise ValueError(f"unsupported source: {source}")


def last_csv_date(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(path, usecols=["date"], dtype={"date": "string"})
    except Exception:
        return None
    if df.empty:
        return None
    dates = df["date"].dropna().astype(str)
    if dates.empty:
        return None
    return dates.max()


def update_one(
    row: dict[str, str],
    kr_dir: Path,
    default_start: str,
    until: str,
    source: str,
    fallback_source: str | None,
) -> tuple[str, int, str]:
    ticker = str(row["ticker"]).zfill(6)
    name = row.get("name", "")
    market = row.get("market", "")
    output_path = kr_dir / f"{ticker}.csv"

    last_date = last_csv_date(output_path)
    start = next_day(last_date) if last_date else default_start
    if start > until:
        return ticker, 0, "already_current"

    used_source = source
    try:
        df = fetch_ohlcv(ticker, start, until, source)
    except Exception:
        if not fallback_source:
            raise
        used_source = fallback_source
        df = fetch_ohlcv(ticker, start, until, fallback_source)

    normalized = normalize_frame(df, ticker, name, market, used_source)
    if normalized is None or normalized.empty:
        return ticker, 0, "no_new_rows"

    if output_path.exists() and output_path.stat().st_size > 0:
        existing = pd.read_csv(output_path, dtype={"date": "string", "ticker": "string"})
        combined = pd.concat([existing, normalized], ignore_index=True)
        combined["date"] = combined["date"].astype(str)
        combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    else:
        combined = normalized.sort_values("date")

    combined.to_csv(output_path, index=False, encoding="utf-8")
    return ticker, len(normalized), f"updated:{used_source}"


def write_log(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "rows", "status", "error"])
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally update Korean daily OHLCV CSV files.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--since", default="19900101")
    parser.add_argument("--until", default=today_yyyymmdd())
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", choices=["pykrx", "fdr"], default="pykrx")
    parser.add_argument("--fallback-source", choices=["pykrx", "fdr"], default="pykrx")
    parser.add_argument("--max-failure-rate", type=float, default=0.02)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    kr_dir = data_dir / "daily" / "kr" / "fdr"
    kr_dir.mkdir(parents=True, exist_ok=True)

    tickers = load_ticker_rows(data_dir / "metadata" / "kr_tickers.csv")
    if args.limit:
        tickers = tickers[: args.limit]
    fallback_source = args.fallback_source
    if fallback_source == args.source:
        fallback_source = None

    log_rows: list[dict[str, str]] = []
    updated = 0
    appended = 0
    for row in tqdm(tickers, desc="incremental KR update"):
        try:
            ticker, rows, status = update_one(row, kr_dir, args.since, args.until, args.source, fallback_source)
            log_rows.append({"ticker": ticker, "rows": str(rows), "status": status, "error": ""})
            if rows:
                updated += 1
                appended += rows
        except Exception as exc:
            log_rows.append(
                {
                    "ticker": str(row.get("ticker", "")).zfill(6),
                    "rows": "0",
                    "status": "failed",
                    "error": str(exc),
                }
            )
        if args.sleep > 0:
            time.sleep(args.sleep)

    write_log(data_dir / "metadata" / "kr_incremental_update_log.csv", log_rows)
    failures = sum(1 for row in log_rows if row["status"] == "failed")
    allowed_failures = max(1, int(len(log_rows) * args.max_failure_rate))
    print(f"KR incremental update complete. Updated files: {updated}. Appended rows: {appended}. Failures: {failures}.")
    if failures > allowed_failures:
        print(f"Failure count exceeds allowed threshold: {failures} > {allowed_failures}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
