from __future__ import annotations

import argparse
import csv
import io
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import requests

from bci_common import (
    DART_CORP_CODES_FILE,
    DART_DISCLOSURES_FILE,
    bci_dir,
    load_local_env,
    recent_date_range,
    utc_now_iso,
    write_json,
)


OPEN_DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
OPEN_DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


def sync_corp_codes(data_dir: Path, api_key: str) -> int:
    response = requests.get(OPEN_DART_CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=60)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_name = archive.namelist()[0]
        root = ElementTree.fromstring(archive.read(xml_name))

    path = bci_dir(data_dir) / DART_CORP_CODES_FILE
    rows: list[dict[str, str]] = []
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        if not stock_code:
            continue
        rows.append(
            {
                "corp_code": (item.findtext("corp_code") or "").strip(),
                "corp_name": (item.findtext("corp_name") or "").strip(),
                "stock_code": stock_code,
                "modify_date": (item.findtext("modify_date") or "").strip(),
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["corp_code", "corp_name", "stock_code", "modify_date"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def fetch_disclosures(data_dir: Path, api_key: str, begin: str, end: str, max_pages: int) -> list[dict[str, str]]:
    disclosures: list[dict[str, str]] = []
    for page_no in range(1, max_pages + 1):
        params = {
            "crtfc_key": api_key,
            "bgn_de": begin,
            "end_de": end,
            "page_no": page_no,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "desc",
        }
        response = requests.get(OPEN_DART_LIST_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status") or "")
        if status not in {"000", "013"}:
            raise RuntimeError(f"OpenDART list failed: {status} {payload.get('message')}")
        rows = payload.get("list") or []
        for row in rows:
            stock_code = str(row.get("stock_code") or "").strip()
            if not stock_code:
                continue
            disclosures.append(
                {
                    "corp_code": str(row.get("corp_code") or "").strip(),
                    "corp_name": str(row.get("corp_name") or "").strip(),
                    "stock_code": stock_code.zfill(6),
                    "report_nm": str(row.get("report_nm") or "").strip(),
                    "rcept_no": str(row.get("rcept_no") or "").strip(),
                    "flr_nm": str(row.get("flr_nm") or "").strip(),
                    "rcept_dt": str(row.get("rcept_dt") or "").strip(),
                    "rm": str(row.get("rm") or "").strip(),
                }
            )
        if len(rows) < 100:
            break
    return disclosures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Korean DART disclosures for the BCI model.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--begin")
    parser.add_argument("--end")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--skip-corp-codes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_local_env()
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        print("DART_API_KEY is not set. Keeping existing DART BCI cache.")
        return 0

    data_dir = Path(args.data_dir)
    begin, end = (args.begin, args.end) if args.begin and args.end else recent_date_range(args.days)

    corp_count = None
    if not args.skip_corp_codes:
        corp_count = sync_corp_codes(data_dir, api_key)

    disclosures = fetch_disclosures(data_dir, api_key, begin, end, args.max_pages)
    write_json(
        bci_dir(data_dir) / DART_DISCLOSURES_FILE,
        {
            "generatedAt": utc_now_iso(),
            "source": "OpenDART",
            "begin": begin,
            "end": end,
            "corpCodeRows": corp_count,
            "disclosures": disclosures,
        },
    )
    print(f"fetched DART disclosures: {len(disclosures)} ({begin}-{end})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
