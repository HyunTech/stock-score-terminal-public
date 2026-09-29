from __future__ import annotations

import csv
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bci_common import load_local_env
from bci_common import read_json as read_json, utc_now_iso as utc_now_iso, write_json as write_json


RESEARCH_DIRNAME = "research"
RAW_DIRNAME = "raw"
TELEGRAM_MESSAGES_FILE = "telegram_messages.json"
REPORTS_FILE = "reports.json"
LATEST_FILE = "latest.json"


def now_kst() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def today_kst() -> str:
    return now_kst().strftime("%Y-%m-%d")


def research_dir(data_dir: Path) -> Path:
    path = data_dir / RESEARCH_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_dir(data_dir: Path) -> Path:
    path = research_dir(data_dir) / RAW_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def site_research_dir(site_dir: Path) -> Path:
    path = site_dir / "data" / RESEARCH_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def clean_text(value: str | None, limit: int | None = None) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def split_env_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in re.split(r"[\n,]", value) if item.strip()]


def bootstrap_env() -> None:
    load_local_env()


def load_ticker_map(data_dir: Path) -> dict[str, dict[str, str]]:
    tickers: dict[str, dict[str, str]] = {}
    metadata = data_dir / "metadata" / "kr_tickers.csv"
    if metadata.exists():
        with metadata.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = str(row.get("ticker") or "").zfill(6)
                name = str(row.get("name") or ticker).strip()
                if ticker.isdigit():
                    tickers[ticker] = {"ticker": ticker, "name": name, "market": str(row.get("market") or "")}

    scores = Path("local-output/data/scores.json")
    if scores.exists():
        payload = read_json(scores, {})
        for row in payload.get("stocks", []):
            ticker = str(row.get("symbol") or "").zfill(6)
            if ticker.isdigit():
                tickers.setdefault(
                    ticker,
                    {
                        "ticker": ticker,
                        "name": str(row.get("name") or ticker),
                        "market": str(row.get("market") or ""),
                    },
                )
    return tickers


def mentioned_tickers(text: str, ticker_map: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    haystack = clean_text(text).lower()
    result: list[dict[str, str]] = []
    for ticker, item in ticker_map.items():
        name = item["name"].strip()
        lowered_name = name.lower()
        matched = ticker in haystack
        if not matched and lowered_name:
            is_ascii_name = bool(re.fullmatch(r"[a-z0-9&.\- ]+", lowered_name))
            if is_ascii_name:
                matched = len(lowered_name) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(lowered_name)}(?![a-z0-9])", haystack) is not None
            else:
                matched = len(lowered_name) >= 3 and lowered_name in haystack
        if matched:
            result.append(item)
            if len(result) == 20:
                break
    return result
