from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from bci_common import (
    DART_DISCLOSURES_FILE,
    NAVER_NEWS_FILE,
    bci_dir,
    clamp,
    read_json,
    read_tail_records,
    pct_return,
    stdev,
    to_float,
    write_json,
)


BCI_RECOMMENDATION_LIMIT = 100

POSITIVE_KEYWORDS = [
    "공급계약",
    "수주",
    "계약체결",
    "자사주",
    "취득",
    "합병",
    "전환",
    "영업이익",
    "실적개선",
    "흑자",
    "증가",
    "승인",
    "인수",
    "투자유치",
    "기술이전",
    "배당",
]
NEGATIVE_KEYWORDS = [
    "상장폐지",
    "관리종목",
    "횡령",
    "배임",
    "감사의견",
    "정정",
    "거절",
    "유상증자",
    "전환사채",
    "대주주매도",
    "적자",
    "소송",
    "불성실공시",
    "거래정지",
]
INSIDER_BUY_KEYWORDS = ["임원", "주요주주", "최대주주", "특수관계인", "장내매수", "매수", "취득"]
INSIDER_SELL_KEYWORDS = ["장내매도", "매도", "처분", "감소"]
ATTENTION_KEYWORDS = ["주요사항보고서", "조회공시", "풍문", "공시번복", "투자판단", "단일판매", "계약"]


def text_score(text: str, positive: list[str], negative: list[str]) -> tuple[float, list[str], list[str]]:
    pos = [word for word in positive if word in text]
    neg = [word for word in negative if word in text]
    return float(len(pos) - len(neg)), pos, neg


def parse_date(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def recency_weight(value: str | None, half_life_days: float = 7.0) -> float:
    parsed = parse_date(value)
    if parsed is None:
        return 0.4
    now = datetime.now(parsed.tzinfo or timezone.utc)
    age = max((now - parsed).days, 0)
    return 0.5 ** (age / half_life_days)


def read_price_rows(path: Path, max_rows: int = 260) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for row in read_tail_records(path, max_rows):
        close = to_float(row.get("close"))
        if close is None:
            continue
        rows.append(
            {
                "date": str(row.get("date") or ""),
                "ticker": str(row.get("ticker") or path.stem).zfill(6),
                "name": str(row.get("name") or path.stem),
                "market": str(row.get("market") or ""),
                "close": close,
                "volume": to_float(row.get("volume")) or 0.0,
            }
        )
    return rows


def build_disclosure_features(data_dir: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(bci_dir(data_dir) / DART_DISCLOSURES_FILE, {})
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "disclosureScore": 0.0,
            "insiderScore": 0.0,
            "riskPenalty": 0.0,
            "attentionScore": 0.0,
            "events": [],
            "riskEvents": [],
        }
    )
    for row in payload.get("disclosures", []):
        ticker = str(row.get("stock_code") or "").zfill(6)
        if not ticker or ticker == "000000":
            continue
        title = str(row.get("report_nm") or "")
        text = f"{title} {row.get('rm') or ''} {row.get('flr_nm') or ''}"
        polarity, positives, negatives = text_score(text, POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS)
        weight = recency_weight(str(row.get("rcept_dt") or ""))
        is_attention = any(word in text for word in ATTENTION_KEYWORDS)
        is_insider = any(word in text for word in INSIDER_BUY_KEYWORDS + INSIDER_SELL_KEYWORDS)

        item = grouped[ticker]
        event_score = polarity * 22.0 * weight
        if is_attention:
            item["attentionScore"] += 18.0 * weight
        if is_insider:
            buy_hit = any(word in text for word in INSIDER_BUY_KEYWORDS)
            sell_hit = any(word in text for word in INSIDER_SELL_KEYWORDS)
            item["insiderScore"] += (30.0 if buy_hit and not sell_hit else -24.0) * weight
        if negatives:
            item["riskPenalty"] += (24.0 + len(negatives) * 10.0) * weight
            item["riskEvents"].append(title)
        item["disclosureScore"] += event_score
        item["events"].append({"date": row.get("rcept_dt"), "title": title, "positive": positives, "negative": negatives})
    return grouped


def build_news_features(data_dir: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(bci_dir(data_dir) / NAVER_NEWS_FILE, {})
    result: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"newsScore": 0.0, "newsCount": 0, "newsRiskPenalty": 0.0, "headlines": [], "riskHeadlines": []}
    )
    for group in payload.get("items", []):
        ticker = str(group.get("ticker") or "").zfill(6)
        if not ticker or ticker == "000000":
            continue
        articles = group.get("articles") or []
        item = result[ticker]
        item["newsCount"] += len(articles)
        for article in articles:
            text = f"{article.get('title') or ''} {article.get('description') or ''}"
            polarity, _positives, negatives = text_score(text, POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS)
            weight = recency_weight(str(article.get("pubDate") or ""), half_life_days=3.0)
            item["newsScore"] += (8.0 + polarity * 12.0) * weight
            if negatives:
                item["newsRiskPenalty"] += (12.0 + len(negatives) * 8.0) * weight
                item["riskHeadlines"].append(str(article.get("title") or ""))
            if len(item["headlines"]) < 3:
                item["headlines"].append(str(article.get("title") or ""))
    return result


def price_features(rows: list[dict[str, Any]]) -> dict[str, float]:
    closes = [float(row["close"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows]
    ret_1d = pct_return(closes, 1) or 0.0
    ret_5d = pct_return(closes, 5) or 0.0
    ret_20d = pct_return(closes, 20) or 0.0
    volume20 = median(volumes[-20:]) if len(volumes) >= 20 else 0.0
    volume_multiple = volumes[-1] / volume20 if volume20 > 0 else 0.0
    volume_window = volumes[-60:-1] if len(volumes) >= 61 else volumes[:-1]
    volume_z = 0.0
    vol_stdev = stdev(volume_window)
    if volume_window and vol_stdev and vol_stdev > 0:
        volume_z = (volumes[-1] - (sum(volume_window) / len(volume_window))) / vol_stdev

    price_volume_score = (
        clamp(ret_5d * 350.0, -35.0, 35.0)
        + clamp(ret_20d * 130.0, -25.0, 25.0)
        + clamp((volume_multiple - 1.0) * 18.0, -10.0, 35.0)
        + clamp(volume_z * 6.0, -10.0, 20.0)
        + 40.0
    )
    overheat = clamp(max(ret_20d - 0.25, 0.0) * 160.0 + max(volume_multiple - 4.0, 0.0) * 10.0)
    return {
        "ret1d": ret_1d,
        "ret5d": ret_5d,
        "ret20d": ret_20d,
        "volumeMultiple": volume_multiple,
        "volumeZ": volume_z,
        "priceVolumeScore": clamp(price_volume_score),
        "overheatScore": overheat,
    }


def identity(rows: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any]:
    last = rows[-1]
    ticker = str(last["ticker"])
    return {
        "id": f"KR:{ticker}",
        "symbol": ticker,
        "displaySymbol": ticker,
        "name": str(base.get("name") or last.get("name") or ticker),
        "market": str(base.get("market") or last.get("market") or ""),
        "lastDate": str(last.get("date") or ""),
        "lastClose": round(float(last["close"]), 4),
        "baseScore": round(float(base.get("score") or 0.0), 2),
    }


def make_item(
    rows: list[dict[str, Any]],
    base: dict[str, Any],
    score: float,
    setup: str,
    trigger: str,
    metric: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    item = identity(rows, base)
    item.update(
        {
            "recommendationScore": round(clamp(score), 2),
            "primarySignal": setup,
            "secondarySignal": trigger,
            "metricLabel": metric,
            "model": "BCI_MVP",
        }
    )
    item.update(extra)
    return item


def base_themes() -> list[dict[str, Any]]:
    return [
        {
            "id": "kr_bci_disclosure_momentum",
            "title": "공시 모멘텀",
            "description": "최근 긍정 공시와 거래량, 가격 반응이 함께 확인된 국내 종목입니다.",
            "items": [],
        },
        {
            "id": "kr_bci_insider_major_holder_buying",
            "title": "내부자/주요주주 매수",
            "description": "임원, 주요주주, 최대주주 매수 관련 공시가 감지된 국내 종목입니다.",
            "items": [],
        },
        {
            "id": "kr_bci_news_attention_spike",
            "title": "뉴스 관심도 급증",
            "description": "뉴스 노출과 긍정 키워드가 가격, 거래량 반응과 함께 나타난 국내 종목입니다.",
            "items": [],
        },
        {
            "id": "kr_bci_short_term_trend",
            "title": "BCI 단기 추세",
            "description": "공시, 뉴스, 거래량, 단기수익률이 동시에 몰린 국내 종목입니다.",
            "items": [],
        },
        {
            "id": "kr_bci_overheat_watch",
            "title": "BCI 과열 주의",
            "description": "관심도는 높지만 단기 과열과 중기 반전 위험이 있는 국내 종목입니다.",
            "items": [],
        },
        {
            "id": "kr_bci_negative_event_avoidance",
            "title": "악재 회피 감지",
            "description": "부정 공시나 뉴스 키워드가 감지되어 신규 진입 전 확인이 필요한 국내 종목입니다.",
            "items": [],
        },
    ]


def build_bci_recommendation_themes(
    data_dir: Path, score_lookup: dict[str, dict[str, Any]], limit: int = BCI_RECOMMENDATION_LIMIT
) -> list[dict[str, Any]]:
    disclosures = build_disclosure_features(data_dir)
    news = build_news_features(data_dir)
    themes = base_themes()
    by_id = {theme["id"]: theme for theme in themes}

    for path in sorted((data_dir / "daily" / "kr" / "fdr").glob("*.csv")):
        rows = read_price_rows(path)
        if len(rows) < 80:
            continue
        ticker = str(rows[-1]["ticker"])
        key = f"KR:{ticker}"
        if key not in score_lookup:
            continue
        base = score_lookup.get(key, {})
        base_score = float(base.get("score") or 0.0)
        disc = disclosures.get(ticker, {})
        item_news = news.get(ticker, {})
        px = price_features(rows)

        event_score = clamp(float(disc.get("disclosureScore") or 0.0) + float(disc.get("attentionScore") or 0.0), -100.0, 100.0)
        insider_score = clamp(float(disc.get("insiderScore") or 0.0), -100.0, 100.0)
        news_score = clamp(float(item_news.get("newsScore") or 0.0) + min(float(item_news.get("newsCount") or 0.0), 10.0) * 5.0, -100.0, 100.0)
        risk_penalty = clamp(float(disc.get("riskPenalty") or 0.0) + float(item_news.get("newsRiskPenalty") or 0.0))
        price_volume_score = float(px["priceVolumeScore"])
        attention_total = max(event_score, 0.0) + max(insider_score, 0.0) + max(news_score, 0.0)
        bci_score = clamp(
            max(event_score, 0.0) * 0.30
            + max(insider_score, 0.0) * 0.20
            + max(news_score, 0.0) * 0.20
            + price_volume_score * 0.20
            + base_score * 0.10
            - risk_penalty * 0.35
        )
        heat_score = clamp(bci_score * 0.55 + float(px["overheatScore"]) * 0.45)
        common_extra = {
            "bciScore": round(bci_score, 2),
            "eventScore": round(event_score, 2),
            "insiderScore": round(insider_score, 2),
            "newsScore": round(news_score, 2),
            "priceVolumeScore": round(price_volume_score, 2),
            "riskPenalty": round(risk_penalty, 2),
            "ret5d": round(px["ret5d"] * 100.0, 2),
            "ret20d": round(px["ret20d"] * 100.0, 2),
            "volumeMultiple": round(px["volumeMultiple"], 2),
            "latestEvents": [event["title"] for event in (disc.get("events") or [])[:3]],
            "latestHeadlines": (item_news.get("headlines") or [])[:3],
        }

        if attention_total > 0 and event_score >= 20 and price_volume_score >= 48 and risk_penalty < 45:
            by_id["kr_bci_disclosure_momentum"]["items"].append(
                make_item(
                    rows,
                    base,
                    bci_score + event_score * 0.20,
                    "긍정 공시 감지",
                    f"거래량 {px['volumeMultiple']:.2f}배",
                    f"BCI {bci_score:.1f} / 5D {px['ret5d'] * 100:.2f}%",
                    common_extra,
                )
            )
        if attention_total > 0 and insider_score >= 18 and risk_penalty < 50:
            by_id["kr_bci_insider_major_holder_buying"]["items"].append(
                make_item(
                    rows,
                    base,
                    bci_score + insider_score * 0.25,
                    "매수성 지분 공시",
                    f"내부자점수 {insider_score:.1f}",
                    f"거래량 {px['volumeMultiple']:.2f}배",
                    common_extra,
                )
            )
        if attention_total > 0 and news_score >= 28 and price_volume_score >= 42 and risk_penalty < 55:
            by_id["kr_bci_news_attention_spike"]["items"].append(
                make_item(
                    rows,
                    base,
                    bci_score + news_score * 0.16,
                    f"뉴스 {int(item_news.get('newsCount') or 0)}건",
                    f"거래량 {px['volumeMultiple']:.2f}배",
                    f"뉴스점수 {news_score:.1f}",
                    common_extra,
                )
            )
        if attention_total >= 20 and bci_score >= 45 and price_volume_score >= 50 and risk_penalty < 50:
            by_id["kr_bci_short_term_trend"]["items"].append(
                make_item(
                    rows,
                    base,
                    bci_score,
                    "공시/뉴스/거래량 집중",
                    f"5D {px['ret5d'] * 100:.2f}%",
                    f"BCI {bci_score:.1f}",
                    common_extra,
                )
            )
        if attention_total >= 20 and heat_score >= 55 and (px["ret20d"] >= 0.25 or px["volumeMultiple"] >= 4.0 or risk_penalty >= 30):
            by_id["kr_bci_overheat_watch"]["items"].append(
                make_item(
                    rows,
                    base,
                    heat_score,
                    "관심도 과열",
                    f"20D {px['ret20d'] * 100:.2f}%",
                    f"Heat {heat_score:.1f} / BCI {bci_score:.1f}",
                    {**common_extra, "heatScore": round(heat_score, 2)},
                )
            )
        if risk_penalty >= 24:
            by_id["kr_bci_negative_event_avoidance"]["items"].append(
                make_item(
                    rows,
                    base,
                    risk_penalty,
                    "부정 키워드 감지",
                    f"위험점수 {risk_penalty:.1f}",
                    f"BCI {bci_score:.1f}",
                    {
                        **common_extra,
                        "avoidanceOnly": True,
                        "riskEvents": (disc.get("riskEvents") or [])[:3],
                        "riskHeadlines": (item_news.get("riskHeadlines") or [])[:3],
                    },
                )
            )

    for theme in themes:
        theme["settings"] = {
            "model": "BCI_MVP",
            "weights": {
                "disclosureEvent": 0.30,
                "insiderMajorHolder": 0.20,
                "newsAttentionSentiment": 0.20,
                "priceVolumeConfirmation": 0.20,
                "baseTechnicalScore": 0.10,
                "riskPenaltyMultiplier": 0.35,
            },
        }
        theme["market"] = "KR"
        theme["items"].sort(key=lambda row: (row["recommendationScore"], row["baseScore"]), reverse=True)
        del theme["items"][limit:]
        for rank, row in enumerate(theme["items"], 1):
            row["recommendationRank"] = rank
    return themes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append BCI recommendation themes to site/data/scores.json.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--limit", type=int, default=BCI_RECOMMENDATION_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    scores_path = Path(args.site_dir) / "data" / "scores.json"
    payload = read_json(scores_path, {})
    stocks = payload.get("stocks") or []
    score_lookup = {str(row.get("id")): row for row in stocks if row.get("id")}
    bci_themes = build_bci_recommendation_themes(data_dir, score_lookup, args.limit)
    existing = [theme for theme in (payload.get("recommendations") or []) if not str(theme.get("id", "")).startswith("kr_bci_")]
    payload["recommendations"] = existing + bci_themes
    payload.setdefault("model", {})["bci"] = {
        "description": "BCI MVP: Korean disclosure, insider/major-holder signal, news attention/sentiment, and price-volume confirmation.",
        "sourceFiles": [str(bci_dir(data_dir) / DART_DISCLOSURES_FILE), str(bci_dir(data_dir) / NAVER_NEWS_FILE)],
    }
    write_json(scores_path, payload)
    print(f"appended BCI themes: {sum(len(theme['items']) for theme in bci_themes)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
