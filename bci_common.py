from __future__ import annotations

import csv
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BCI_DIRNAME = "bci"
DART_DISCLOSURES_FILE = "dart_disclosures.json"
DART_CORP_CODES_FILE = "dart_corp_codes.csv"
NAVER_NEWS_FILE = "naver_news.json"


def load_local_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def yyyymmdd(value: datetime) -> str:
    return value.strftime("%Y%m%d")


def recent_date_range(days: int) -> tuple[str, str]:
    end = datetime.now()
    start = end - timedelta(days=max(days - 1, 0))
    return yyyymmdd(start), yyyymmdd(end)


def bci_dir(data_dir: Path) -> Path:
    path = data_dir / BCI_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = (
        text.replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&apos;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def load_kr_tickers(data_dir: Path, limit: int | None = None) -> list[dict[str, str]]:
    path = data_dir / "metadata" / "kr_tickers.csv"
    if not path.exists():
        return []

    result: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker") or "").strip().zfill(6)
            if not ticker.isdigit():
                continue
            result.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker).strip(),
                    "market": str(row.get("market") or "").strip(),
                }
            )
            if limit and len(result) >= limit:
                break
    return result


def tail_lines(path: Path, max_lines: int) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        file_size = handle.tell()
        block_size = 8192
        blocks: list[bytes] = []
        lines_found = 0
        pos = file_size
        while pos > 0 and lines_found <= max_lines:
            read_size = min(block_size, pos)
            pos -= read_size
            handle.seek(pos)
            block = handle.read(read_size)
            blocks.append(block)
            lines_found += block.count(b"\n")

    data = b"".join(reversed(blocks))
    decoded = data.decode("utf-8-sig", errors="replace").splitlines()
    return decoded[-max_lines:]


def read_tail_records(path: Path, max_rows: int = 280) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = handle.readline().strip()
    if not header:
        return []

    lines = [line for line in tail_lines(path, max_rows + 1) if line.strip()]
    lines = [line for line in lines if line.strip() != header]
    reader = csv.DictReader([header, *lines[-max_rows:]])
    return [row for row in reader if row]


def pct_return(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    previous = closes[-period - 1]
    current = closes[-1]
    if previous <= 0:
        return None
    return current / previous - 1.0


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)
