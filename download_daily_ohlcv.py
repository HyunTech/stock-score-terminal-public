from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from tqdm import tqdm


STOOQ_US_DAILY_ZIP_URL = "https://static.stooq.com/db/h/d_us_txt.zip"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw_us_dir(self) -> Path:
        return self.root / "raw" / "us" / "stooq"

    @property
    def us_daily_dir(self) -> Path:
        return self.root / "daily" / "us" / "stooq"

    @property
    def us_yfinance_daily_dir(self) -> Path:
        return self.root / "daily" / "us" / "yfinance"

    def kr_daily_dir(self, source: str = "fdr") -> Path:
        return self.root / "daily" / "kr" / source

    @property
    def metadata_dir(self) -> Path:
        return self.root / "metadata"


def ensure_dirs(paths: Paths) -> None:
    for directory in [
        paths.raw_us_dir,
        paths.us_daily_dir,
        paths.us_yfinance_daily_dir,
        paths.kr_daily_dir(),
        paths.metadata_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def normalize_date(value: str) -> str:
    return value.replace("-", "")


def download_file(url: str, output_path: Path, force: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        print(f"US archive already exists: {output_path}")
        return

    temp_path = output_path.with_suffix(output_path.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()

    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", "0"))
        with temp_path.open("wb") as handle:
            progress = tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                desc=f"download {output_path.name}",
            )
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
                        progress.update(len(chunk))
            finally:
                progress.close()

    temp_path.replace(output_path)


def stooq_symbol_from_member(member_name: str) -> str:
    stem = Path(member_name).stem
    if stem.lower().endswith(".us"):
        stem = stem[:-3]
    return stem.upper()


def stooq_asset_group(member_name: str) -> str:
    parts = member_name.replace("\\", "/").split("/")
    # Expected: data/daily/us/<group>/<bucket>/<symbol>.txt
    if len(parts) >= 5:
        return parts[3]
    return ""


def normalize_stooq_us(zip_path: Path, output_dir: Path, metadata_path: Path, force: bool) -> int:
    rows: list[dict[str, str]] = []
    written = 0

    with zipfile.ZipFile(zip_path) as archive:
        members = [
            member
            for member in archive.namelist()
            if member.lower().endswith(".txt") and "/daily/us/" in member.replace("\\", "/").lower()
        ]

        for member in tqdm(members, desc="normalize US files"):
            symbol = stooq_symbol_from_member(member)
            if not symbol:
                continue

            output_path = output_dir / f"{symbol}.csv"
            if output_path.exists() and not force:
                rows.append(
                    {
                        "symbol": symbol,
                        "source_path": member,
                        "asset_group": stooq_asset_group(member),
                        "output_path": str(output_path),
                        "status": "skipped",
                    }
                )
                continue

            with archive.open(member) as source:
                text_stream = io.TextIOWrapper(source, encoding="utf-8", newline="")
                reader = csv.DictReader(text_stream)
                if not reader.fieldnames:
                    continue

                output_path.parent.mkdir(parents=True, exist_ok=True)
                with output_path.open("w", encoding="utf-8", newline="") as target:
                    writer = csv.DictWriter(
                        target,
                        fieldnames=[
                            "date",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "symbol",
                            "source",
                            "asset_group",
                        ],
                    )
                    writer.writeheader()
                    row_count = 0
                    for row in reader:
                        writer.writerow(
                            {
                                "date": normalize_date(row.get("Date", "")),
                                "open": row.get("Open", ""),
                                "high": row.get("High", ""),
                                "low": row.get("Low", ""),
                                "close": row.get("Close", ""),
                                "volume": row.get("Volume", ""),
                                "symbol": symbol,
                                "source": "stooq",
                                "asset_group": stooq_asset_group(member),
                            }
                        )
                        row_count += 1

            rows.append(
                {
                    "symbol": symbol,
                    "source_path": member,
                    "asset_group": stooq_asset_group(member),
                    "output_path": str(output_path),
                    "status": f"written:{row_count}",
                }
            )
            written += 1

    write_dict_rows(metadata_path, rows, ["symbol", "source_path", "asset_group", "output_path", "status"])
    return written


def write_dict_rows(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_pipe_table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    reader = csv.DictReader(lines, delimiter="|")
    return [dict(row) for row in reader if row]


def yahoo_symbol(symbol: str) -> str:
    value = symbol.strip()
    if "$" in value:
        return value.replace("$", "-P")
    if value.endswith(".W"):
        return value[:-2] + "-WT"
    if value.endswith(".U"):
        return value[:-2] + "-UN"
    if value.endswith(".R"):
        return value[:-2] + "-RT"
    return value.replace(".", "-")


def fetch_us_tickers(output_path: Path) -> list[dict[str, str]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    rows: list[dict[str, str]] = []

    nasdaq_text = session.get(NASDAQ_LISTED_URL, timeout=60).text
    for row in parse_pipe_table(nasdaq_text):
        symbol = row.get("Symbol", "").strip()
        if not symbol or row.get("Test Issue", "").strip().upper() == "Y":
            continue
        rows.append(
            {
                "symbol": symbol,
                "yahoo_symbol": yahoo_symbol(symbol),
                "name": row.get("Security Name", ""),
                "exchange": "NASDAQ",
                "etf": row.get("ETF", ""),
            }
        )

    other_text = session.get(OTHER_LISTED_URL, timeout=60).text
    exchange_map = {
        "A": "NYSE_MKT",
        "N": "NYSE",
        "P": "NYSE_ARCA",
        "Z": "BATS",
        "V": "IEXG",
    }
    for row in parse_pipe_table(other_text):
        symbol = row.get("ACT Symbol", "").strip()
        if not symbol or row.get("Test Issue", "").strip().upper() == "Y":
            continue
        exchange_code = row.get("Exchange", "").strip()
        rows.append(
            {
                "symbol": symbol,
                "yahoo_symbol": yahoo_symbol(symbol),
                "name": row.get("Security Name", ""),
                "exchange": exchange_map.get(exchange_code, exchange_code),
                "etf": row.get("ETF", ""),
            }
        )

    seen: set[str] = set()
    unique_rows: list[dict[str, str]] = []
    for row in rows:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        unique_rows.append(row)

    write_dict_rows(output_path, unique_rows, ["symbol", "yahoo_symbol", "name", "exchange", "etf"])
    return unique_rows


def normalize_yfinance_frame(df, symbol: str, item: dict[str, str]):
    if df is None or df.empty:
        return df
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        ticker_values = list(df.columns.get_level_values(-1).unique())
        ticker = item["yahoo_symbol"]
        if ticker in ticker_values:
            df = df.xs(ticker, axis=1, level=-1)
        elif len(ticker_values) == 1:
            df = df.xs(ticker_values[0], axis=1, level=-1)
        df.columns.name = None

    df = df.reset_index()
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    else:
        df = df.rename(columns={df.columns[0]: "date"})
    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename_map)
    df["date"] = df["date"].dt.strftime("%Y%m%d")
    df["symbol"] = symbol
    df["yahoo_symbol"] = item["yahoo_symbol"]
    df["name"] = item["name"]
    df["exchange"] = item["exchange"]
    df["etf"] = item["etf"]
    df["source"] = "yfinance"

    price_columns = [column for column in ["open", "high", "low", "close", "adj_close", "volume"] if column in df.columns]
    if price_columns:
        df = df.dropna(subset=price_columns, how="all")
    if df.empty:
        return df

    preferred = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "symbol",
        "yahoo_symbol",
        "name",
        "exchange",
        "etf",
        "source",
    ]
    columns = [column for column in preferred if column in df.columns]
    return df[columns]


def chunks(items: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def download_us_daily_yfinance(
    tickers: list[dict[str, str]],
    output_dir: Path,
    since: str,
    until: str,
    force: bool,
    sleep_seconds: float,
    limit: int | None,
    chunk_size: int,
) -> tuple[int, list[dict[str, str]]]:
    import yfinance as yf

    failures: list[dict[str, str]] = []
    written = 0
    selected = tickers[:limit] if limit else tickers
    pending: list[dict[str, str]] = []
    for item in selected:
        symbol = item["symbol"]
        output_path = output_dir / f"{symbol.replace('/', '-')}.csv"
        if output_path.exists() and output_path.stat().st_size > 0 and not force:
            continue
        pending.append(item)

    start = fdr_date(since)
    end = fdr_date(until)

    for batch in tqdm(list(chunks(pending, max(chunk_size, 1))), desc="download US batches"):
        batch_data = None
        batch_error = ""
        for attempt in range(1, 4):
            try:
                batch_data = yf.download(
                    [item["yahoo_symbol"] for item in batch],
                    start=start,
                    end=end,
                    auto_adjust=False,
                    actions=False,
                    progress=False,
                    threads=True,
                )
                batch_error = ""
                break
            except Exception as exc:
                batch_error = f"attempt {attempt}: {exc}"
                time.sleep(max(sleep_seconds, 0.5) * attempt)

        for item in batch:
            symbol = item["symbol"]
            output_path = output_dir / f"{symbol.replace('/', '-')}.csv"
            last_error = batch_error
            if not last_error:
                try:
                    normalized = normalize_yfinance_frame(batch_data, symbol, item)
                    if normalized is None or normalized.empty:
                        last_error = "empty dataframe"
                    else:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        normalized.to_csv(output_path, index=False, encoding="utf-8")
                        written += 1
                        last_error = ""
                except Exception as exc:
                    last_error = f"normalize: {exc}"

            if last_error:
                failures.append(
                    {
                        "symbol": symbol,
                        "yahoo_symbol": item["yahoo_symbol"],
                        "name": item["name"],
                        "exchange": item["exchange"],
                        "error": last_error,
                    }
                )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return written, failures


def fetch_kr_tickers_pykrx(markets: list[str], output_path: Path) -> list[dict[str, str]]:
    from pykrx import stock

    rows: list[dict[str, str]] = []
    asof = today_yyyymmdd()
    for market in markets:
        for ticker in stock.get_market_ticker_list(asof, market=market):
            rows.append(
                {
                    "ticker": ticker,
                    "name": stock.get_market_ticker_name(ticker),
                    "market": market,
                    "asof": asof,
                }
            )

    write_dict_rows(output_path, rows, ["ticker", "name", "market", "asof"])
    return rows


def fetch_kr_tickers_fdr(markets: list[str], output_path: Path) -> list[dict[str, str]]:
    import FinanceDataReader as fdr

    listing = fdr.StockListing("KRX")
    rows: list[dict[str, str]] = []
    asof = today_yyyymmdd()
    selected_markets = {market.upper() for market in markets}

    for _, row in listing.iterrows():
        market = str(row.get("Market", "")).upper()
        code = str(row.get("Code", "")).zfill(6)
        name = str(row.get("Name", ""))
        if not code or market not in selected_markets:
            continue
        rows.append(
            {
                "ticker": code,
                "name": name,
                "market": market,
                "asof": asof,
            }
        )

    write_dict_rows(output_path, rows, ["ticker", "name", "market", "asof"])
    return rows


def normalize_kr_ohlcv_frame(df, ticker: str, name: str, market: str, source: str):
    if df is None or df.empty:
        return df

    rename_map = {
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
        "거래대금": "value",
        "등락률": "change_pct",
    }
    df = df.rename(columns=rename_map).reset_index()
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "date"})
    df["date"] = df["date"].dt.strftime("%Y%m%d")
    df["ticker"] = ticker
    df["name"] = name
    df["market"] = market
    df["source"] = source

    preferred = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "value",
        "change_pct",
        "ticker",
        "name",
        "market",
        "source",
    ]
    columns = [column for column in preferred if column in df.columns]
    return df[columns]


def fdr_date(value: str) -> str:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def download_kr_daily(
    tickers: list[dict[str, str]],
    output_dir: Path,
    since: str,
    until: str,
    force: bool,
    sleep_seconds: float,
    limit: int | None,
    source: str,
) -> tuple[int, list[dict[str, str]]]:
    if source == "pykrx":
        from pykrx import stock
    elif source == "fdr":
        import FinanceDataReader as fdr
    else:
        raise ValueError(f"unsupported source: {source}")

    failures: list[dict[str, str]] = []
    written = 0
    selected = tickers[:limit] if limit else tickers
    start, end = fdr_date(since), fdr_date(until)

    for item in tqdm(selected, desc="download KR files"):
        ticker = item["ticker"]
        output_path = output_dir / f"{ticker}.csv"
        if output_path.exists() and output_path.stat().st_size > 0 and not force:
            continue

        last_error = ""
        for attempt in range(1, 4):
            try:
                if source == "pykrx":
                    df = stock.get_market_ohlcv_by_date(since, until, ticker, adjusted=True)
                else:
                    df = fdr.DataReader(ticker, start, end)
                normalized = normalize_kr_ohlcv_frame(df, ticker, item["name"], item["market"], source)
                if normalized is None or normalized.empty:
                    last_error = "empty dataframe"
                else:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    normalized.to_csv(output_path, index=False, encoding="utf-8")
                    written += 1
                    last_error = ""
                break
            except Exception as exc:  # pykrx raises mixed network/parser exceptions
                last_error = f"attempt {attempt}: {exc}"
                time.sleep(max(sleep_seconds, 0.5) * attempt)

        if last_error:
            failures.append(
                {
                    "ticker": ticker,
                    "name": item["name"],
                    "market": item["market"],
                    "error": last_error,
                }
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return written, failures


def run_us_stooq(paths: Paths, force: bool) -> None:
    zip_path = paths.raw_us_dir / "d_us_txt.zip"
    download_file(STOOQ_US_DAILY_ZIP_URL, zip_path, force=force)
    written = normalize_stooq_us(
        zip_path=zip_path,
        output_dir=paths.us_daily_dir,
        metadata_path=paths.metadata_dir / "us_stooq_manifest.csv",
        force=force,
    )
    print(f"US Stooq normalization complete. Written files: {written}")


def run_us_yfinance(
    paths: Paths,
    since: str,
    until: str,
    force: bool,
    sleep_seconds: float,
    limit: int | None,
    chunk_size: int,
) -> None:
    tickers = fetch_us_tickers(paths.metadata_dir / "us_tickers.csv")
    written, failures = download_us_daily_yfinance(
        tickers=tickers,
        output_dir=paths.us_yfinance_daily_dir,
        since=since,
        until=until,
        force=force,
        sleep_seconds=sleep_seconds,
        limit=limit,
        chunk_size=chunk_size,
    )
    write_dict_rows(
        paths.metadata_dir / "us_failed.csv",
        failures,
        ["symbol", "yahoo_symbol", "name", "exchange", "error"],
    )
    print(f"US yfinance download complete. Written files: {written}. Failures: {len(failures)}")


def run_kr(
    paths: Paths,
    markets: list[str],
    since: str,
    until: str,
    force: bool,
    sleep_seconds: float,
    limit: int | None,
    source: str,
) -> None:
    if source == "pykrx":
        tickers = fetch_kr_tickers_pykrx(markets, paths.metadata_dir / "kr_tickers.csv")
    else:
        tickers = fetch_kr_tickers_fdr(markets, paths.metadata_dir / "kr_tickers.csv")
    written, failures = download_kr_daily(
        tickers=tickers,
        output_dir=paths.kr_daily_dir(source),
        since=since,
        until=until,
        force=force,
        sleep_seconds=sleep_seconds,
        limit=limit,
        source=source,
    )
    write_dict_rows(
        paths.metadata_dir / "kr_failed.csv",
        failures,
        ["ticker", "name", "market", "error"],
    )
    print(f"KR download complete. Written files: {written}. Failures: {len(failures)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download daily OHLCV files for US and Korean equities.")
    parser.add_argument("--data-dir", default="data", help="Base directory for downloaded data.")
    parser.add_argument("--since", default="19900101", help="Start date for Korean data, YYYYMMDD.")
    parser.add_argument("--until", default=today_yyyymmdd(), help="End date, YYYYMMDD.")
    parser.add_argument("--us-source", choices=["yfinance", "stooq"], default="yfinance")
    parser.add_argument("--us-sleep", type=float, default=0.05, help="Seconds to sleep between US ticker calls.")
    parser.add_argument("--us-limit", type=int, default=None, help="Limit US tickers for smoke tests.")
    parser.add_argument("--us-chunk-size", type=int, default=50, help="US symbols per yfinance batch.")
    parser.add_argument("--markets", nargs="+", default=["KOSPI", "KOSDAQ", "KONEX"])
    parser.add_argument("--kr-source", choices=["fdr", "pykrx"], default="fdr")
    parser.add_argument("--kr-sleep", type=float, default=0.25, help="Seconds to sleep between Korean ticker calls.")
    parser.add_argument("--kr-limit", type=int, default=None, help="Limit Korean tickers for smoke tests.")
    parser.add_argument("--us-only", action="store_true")
    parser.add_argument("--kr-only", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing archive/output files.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    paths = Paths(Path(args.data_dir))
    ensure_dirs(paths)

    if args.us_only and args.kr_only:
        raise SystemExit("Choose only one of --us-only or --kr-only.")

    if not args.kr_only:
        if args.us_source == "stooq":
            run_us_stooq(paths, force=args.force)
        else:
            run_us_yfinance(
                paths=paths,
                since=args.since,
                until=args.until,
                force=args.force,
                sleep_seconds=args.us_sleep,
                limit=args.us_limit,
                chunk_size=args.us_chunk_size,
            )
    if not args.us_only:
        run_kr(
            paths=paths,
            markets=args.markets,
            since=args.since,
            until=args.until,
            force=args.force,
            sleep_seconds=args.kr_sleep,
            limit=args.kr_limit,
            source=args.kr_source,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
