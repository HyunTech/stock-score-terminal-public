from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import requests

from bci_common import NAVER_NEWS_FILE, bci_dir, clean_html, load_kr_tickers, load_local_env, utc_now_iso, write_json


NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"


def fetch_one(client_id: str, client_secret: str, query: str, display: int) -> list[dict[str, str]]:
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": "date"}
    response = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return [
        {
            "title": clean_html(item.get("title")),
            "description": clean_html(item.get("description")),
            "originallink": str(item.get("originallink") or ""),
            "link": str(item.get("link") or ""),
            "pubDate": str(item.get("pubDate") or ""),
        }
        for item in payload.get("items", [])
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Korean stock news from Naver for the BCI model.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--display", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=0.1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_local_env()
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("NAVER_CLIENT_ID or NAVER_CLIENT_SECRET is not set. Keeping existing Naver BCI cache.")
        return 0

    data_dir = Path(args.data_dir)
    tickers = load_kr_tickers(data_dir, limit=args.limit)
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    for index, item in enumerate(tickers, 1):
        ticker = item["ticker"]
        name = item["name"]
        query = f"{name} {ticker}" if name and name != ticker else ticker
        try:
            articles = fetch_one(client_id, client_secret, query, args.display)
            results.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "market": item.get("market", ""),
                    "query": query,
                    "articles": articles,
                }
            )
        except Exception as exc:
            failures.append({"ticker": ticker, "query": query, "error": str(exc)})
        if index % 50 == 0:
            print(f"fetched Naver news: {index}/{len(tickers)}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    write_json(
        bci_dir(data_dir) / NAVER_NEWS_FILE,
        {
            "generatedAt": utc_now_iso(),
            "source": "Naver News Search API",
            "limit": args.limit,
            "display": args.display,
            "items": results,
            "failures": failures,
        },
    )
    print(f"fetched Naver news groups: {len(results)} failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
