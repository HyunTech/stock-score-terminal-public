from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from research_common import (
    LATEST_FILE,
    REPORTS_FILE,
    TELEGRAM_MESSAGES_FILE,
    clean_text,
    load_ticker_map,
    mentioned_tickers,
    raw_dir,
    read_json,
    site_research_dir,
    today_kst,
    utc_now_iso,
    write_json,
)


POSITIVE = ["상향", "매수", "buy", "outperform", "호조", "개선", "성장", "수주", "증가", "흑자", "회복", "강세"]
NEGATIVE = ["하향", "매도", "sell", "부진", "감소", "적자", "둔화", "리스크", "악화", "약세", "손실"]
THEMES = {
    "반도체": ["반도체", "메모리", "hbm", "dram", "낸드", "파운드리"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "전해액"],
    "자동차": ["자동차", "전기차", "완성차", "부품"],
    "바이오": ["바이오", "제약", "임상", "신약"],
    "조선": ["조선", "선박", "lng", "수주"],
    "방산": ["방산", "항공우주", "무기", "수출"],
    "전력기기": ["전력", "변압기", "전선", "전력기기"],
    "금융": ["은행", "증권", "보험", "배당"],
}


def sentiment_score(text: str) -> tuple[float, list[str], list[str]]:
    lower = text.lower()
    positives = [word for word in POSITIVE if word.lower() in lower]
    negatives = [word for word in NEGATIVE if word.lower() in lower]
    return float(len(positives) - len(negatives)), positives, negatives


def detect_themes(text: str) -> list[str]:
    lower = text.lower()
    result = []
    for theme, words in THEMES.items():
        if any(word.lower() in lower for word in words):
            result.append(theme)
    return result


def source_items(data_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    telegram = read_json(raw_dir(data_dir) / TELEGRAM_MESSAGES_FILE, {})
    for message in telegram.get("messages", [])[-300:]:
        items.append(
            {
                "type": "telegram",
                "title": clean_text(message.get("chatTitle") or "Telegram", 120),
                "text": clean_text(message.get("text"), 8000),
                "url": "",
            }
        )

    reports = read_json(raw_dir(data_dir) / REPORTS_FILE, {})
    for report in reports.get("reports", [])[-200:]:
        items.append(
            {
                "type": "report",
                "title": clean_text(report.get("title") or "증권 리포트", 180),
                "text": clean_text(report.get("text"), 12000),
                "url": report.get("url") or "",
                "ticker": str(report.get("ticker") or ""),
                "name": str(report.get("name") or ""),
                "broker": str(report.get("broker") or ""),
            }
        )
    return items


def build_analysis(data_dir: Path, site_dir: Path) -> dict[str, Any]:
    tickers = load_ticker_map(data_dir)
    items = source_items(data_dir)
    stock_scores: dict[str, dict[str, Any]] = {}
    theme_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()

    for item in items:
        text = f"{item.get('title')} {item.get('text')}"
        score, positives, negatives = sentiment_score(text)
        themes = detect_themes(text)
        for theme in themes:
            theme_counter[theme] += 1
        source_counter[str(item.get("type") or "unknown")] += 1

        explicit_ticker = str(item.get("ticker") or "").zfill(6)
        match_text = text
        broker = clean_text(item.get("broker"), 120)
        if broker:
            match_text = match_text.replace(broker, " ")

        explicit_matches = [tickers[explicit_ticker]] if explicit_ticker in tickers else []
        matched_stocks = explicit_matches + [
            stock for stock in mentioned_tickers(match_text, tickers) if stock["ticker"] != explicit_ticker
        ]

        for stock in matched_stocks:
            ticker = stock["ticker"]
            entry = stock_scores.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "name": stock["name"],
                    "market": stock.get("market", ""),
                    "mentions": 0,
                    "sentimentRaw": 0.0,
                    "positiveKeywords": Counter(),
                    "negativeKeywords": Counter(),
                    "themes": Counter(),
                    "sources": [],
                },
            )
            entry["mentions"] += 1
            entry["sentimentRaw"] += score
            entry["positiveKeywords"].update(positives)
            entry["negativeKeywords"].update(negatives)
            entry["themes"].update(themes)
            if len(entry["sources"]) < 5:
                entry["sources"].append(
                    {
                        "type": item.get("type"),
                        "title": clean_text(item.get("title"), 160),
                        "url": item.get("url") or "",
                    }
                )

    stocks = []
    for entry in stock_scores.values():
        sentiment_raw = float(entry["sentimentRaw"])
        impact = min(100.0, 35.0 + entry["mentions"] * 12.0 + max(sentiment_raw, 0.0) * 10.0)
        if sentiment_raw < 0:
            impact = max(0.0, impact + sentiment_raw * 8.0)
        stocks.append(
            {
                "ticker": entry["ticker"],
                "name": entry["name"],
                "market": entry["market"],
                "impactScore": round(impact, 2),
                "mentions": entry["mentions"],
                "sentiment": "positive" if sentiment_raw > 0 else "negative" if sentiment_raw < 0 else "neutral",
                "positiveKeywords": [word for word, _ in entry["positiveKeywords"].most_common(5)],
                "negativeKeywords": [word for word, _ in entry["negativeKeywords"].most_common(5)],
                "themes": [theme for theme, _ in entry["themes"].most_common(5)],
                "sources": entry["sources"],
            }
        )
    stocks.sort(key=lambda row: (row["impactScore"], row["mentions"]), reverse=True)

    issues = []
    for theme, count in theme_counter.most_common(8):
        related = [row for row in stocks if theme in row.get("themes", [])][:8]
        issues.append(
            {
                "title": f"{theme} 관련 리서치 관심",
                "category": "sector",
                "sentiment": "positive" if any(row["sentiment"] == "positive" for row in related) else "neutral",
                "mentionCount": count,
                "relatedTickers": [row["ticker"] for row in related],
                "summary": f"오늘 수집 자료에서 {theme} 키워드가 {count}회 감지되었습니다.",
            }
        )

    if items:
        market_summary = f"오늘 수집한 자료 {len(items)}건에서 주요 이슈 {len(issues)}개와 언급 종목 {len(stocks)}개를 추출했습니다."
    else:
        market_summary = "아직 수집된 텔레그램 자료나 증권 리포트가 없습니다. TELEGRAM_BOT_TOKEN 또는 REPORT_SOURCE_URLS를 설정하면 자동 분석이 채워집니다."

    documents = [
        {
            "type": item.get("type"),
            "title": clean_text(item.get("title"), 160),
            "url": item.get("url") or "",
            "preview": clean_text(item.get("text"), 220),
        }
        for item in items[-30:]
    ]

    return {
        "generatedAt": utc_now_iso(),
        "date": today_kst(),
        "sourceCounts": dict(source_counter),
        "marketSummary": market_summary,
        "issues": issues,
        "stocks": stocks[:100],
        "documents": documents,
        "model": {
            "description": "Heuristic MVP for Korean report and Telegram research. It maps text to KR tickers and scores impact from mentions and sentiment keywords.",
            "requiresOptionalEnv": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS", "REPORT_SOURCE_URLS"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze daily Telegram/report research and publish site JSON.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default="local-output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_analysis(Path(args.data_dir), Path(args.site_dir))
    output = site_research_dir(Path(args.site_dir)) / LATEST_FILE
    write_json(output, payload)
    print(f"research analysis published: {output} stocks={len(payload['stocks'])} issues={len(payload['issues'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
