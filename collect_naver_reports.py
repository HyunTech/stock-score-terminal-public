from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from research_common import (
    REPORTS_FILE,
    bootstrap_env,
    clean_text,
    raw_dir,
    read_json,
    sha_id,
    split_env_list,
    today_kst,
    utc_now_iso,
    write_json,
)


BASE_URL = "https://finance.naver.com"
RESEARCH_BASE = f"{BASE_URL}/research/"
USER_AGENT = "StockScoreResearchBot/0.2 (+local research brief)"

CATEGORIES = {
    "company": {
        "list": "company_list.naver",
        "read_marker": "company_read.naver",
        "label": "company",
    },
    "industry": {
        "list": "industry_list.naver",
        "read_marker": "industry_read.naver",
        "label": "industry",
    },
    "market": {
        "list": "market_info_list.naver",
        "read_marker": "market_info_read.naver",
        "label": "market",
    },
    "invest": {
        "list": "invest_list.naver",
        "read_marker": "invest_read.naver",
        "label": "investment",
    },
    "economy": {
        "list": "economy_list.naver",
        "read_marker": "economy_read.naver",
        "label": "economy",
    },
    "debenture": {
        "list": "debenture_list.naver",
        "read_marker": "debenture_read.naver",
        "label": "debenture",
    },
}


def fetch(session: requests.Session, url: str, *, timeout: int = 30) -> requests.Response:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response


def parse_naver_date(value: str) -> str:
    text = clean_text(value)
    match = re.search(r"(\d{2,4})[.](\d{1,2})[.](\d{1,2})", text)
    if not match:
        return ""
    year = int(match.group(1))
    if year < 100:
        year += 2000
    month = int(match.group(2))
    day = int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def is_recent(date_text: str, recent_days: int) -> bool:
    if recent_days <= 0 or not date_text:
        return True
    try:
        report_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        today = datetime.strptime(today_kst(), "%Y-%m-%d").date()
    except ValueError:
        return True
    return report_date >= today - timedelta(days=recent_days)


def first_link(links: list[str], marker: str) -> str:
    for link in links:
        if marker in link:
            return urljoin(RESEARCH_BASE, link)
    return ""


def first_pdf(links: list[str]) -> str:
    for link in links:
        if ".pdf" in link.lower():
            return urljoin(RESEARCH_BASE, link)
    return ""


def code_from_links(links: list[str]) -> str:
    for link in links:
        parsed = urlparse(urljoin(BASE_URL, link))
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        if re.fullmatch(r"\d{6}", code or ""):
            return code
    return ""


def parse_list_row(tr: Any, category: str) -> dict[str, Any] | None:
    config = CATEGORIES[category]
    cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("td")]
    links = [str(a.get("href") or "") for a in tr.select("a[href]")]
    detail_url = first_link(links, config["read_marker"])
    if not detail_url:
        return None

    pdf_url = first_pdf(links)
    ticker = code_from_links(links)
    name = ""
    sector = ""
    title = ""
    broker = ""
    report_date = ""
    views = ""

    if category == "company":
        if len(cells) >= 6:
            name, title, broker, _blank, raw_date, views = cells[:6]
            report_date = parse_naver_date(raw_date)
    elif category == "industry":
        if len(cells) >= 6:
            sector, title, broker, _blank, raw_date, views = cells[:6]
            report_date = parse_naver_date(raw_date)
    else:
        if len(cells) >= 5:
            title, broker, _blank, raw_date, views = cells[:5]
            report_date = parse_naver_date(raw_date)

    if not title:
        title = clean_text(tr.get_text(" ", strip=True), 180)

    return {
        "category": config["label"],
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "title": title,
        "broker": broker,
        "date": report_date,
        "views": views,
        "url": detail_url,
        "pdfUrl": pdf_url,
    }


def parse_detail(session: requests.Session, report: dict[str, Any]) -> dict[str, Any]:
    response = fetch(session, str(report["url"]))
    soup = BeautifulSoup(response.content, "html.parser", from_encoding="euc-kr")
    table = soup.select_one("table.type_1")
    if not table:
        return report

    title_node = table.select_one("th.view_sbj")
    info_node = table.select_one("div.view_info")
    body_node = table.select_one("td.view_cnt")
    detail_links = [str(a.get("href") or "") for a in table.select("a[href]")]

    if title_node:
        title_text = clean_text(title_node.get_text(" ", strip=True), 300)
        if title_text and not report.get("title"):
            report["title"] = title_text
    if info_node:
        info_text = info_node.get_text("\n", strip=True)
        parts = [clean_text(part) for part in info_text.split("\n") if clean_text(part)]
        for index, part in enumerate(parts):
            if part == "목표가" and index + 1 < len(parts):
                report["targetPrice"] = parts[index + 1]
            if part == "투자의견" and index + 1 < len(parts):
                report["opinion"] = parts[index + 1]
    if body_node:
        report["detailText"] = clean_text(body_node.get_text(" ", strip=True), 6000)
    if not report.get("pdfUrl"):
        report["pdfUrl"] = first_pdf(detail_links)
    return report


def extract_pdf_text(session: requests.Session, pdf_url: str, max_pages: int) -> str:
    if not pdf_url or max_pages <= 0:
        return ""
    response = fetch(session, pdf_url, timeout=45)
    reader = PdfReader(BytesIO(response.content))
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    return clean_text("\n".join(parts), 12000)


def build_text(report: dict[str, Any], pdf_text: str) -> str:
    parts = [
        report.get("name"),
        report.get("sector"),
        report.get("title"),
        report.get("broker"),
        report.get("opinion"),
        report.get("targetPrice"),
        report.get("detailText"),
        pdf_text,
    ]
    return clean_text(" ".join(str(part or "") for part in parts), 16000)


def collect_reports(
    *,
    data_dir: Path,
    categories: list[str],
    pages: int,
    max_reports: int,
    recent_days: int,
    max_pdf_pages: int,
    sleep: float,
) -> dict[str, Any]:
    output = raw_dir(data_dir) / REPORTS_FILE
    existing = read_json(output, {"reports": []})
    existing_by_id = {str(item.get("id")): item for item in existing.get("reports", [])}

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for category in categories:
        if category not in CATEGORIES:
            failures.append({"category": category, "url": "", "error": "unknown category"})
            continue
        list_name = CATEGORIES[category]["list"]
        for page in range(1, pages + 1):
            url = urljoin(RESEARCH_BASE, list_name)
            try:
                response = session.get(url, params={"page": page}, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "html.parser", from_encoding="euc-kr")
                for tr in soup.select("table.type_1 tr"):
                    item = parse_list_row(tr, category)
                    if item and is_recent(str(item.get("date") or ""), recent_days):
                        candidates.append(item)
            except Exception as exc:
                failures.append({"category": category, "url": f"{url}?page={page}", "error": str(exc)})
            if sleep > 0:
                time.sleep(sleep)

    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = str(item.get("url") or item.get("pdfUrl"))
        deduped[key] = item

    collected = 0
    for item in list(deduped.values())[:max_reports]:
        source_id = str(item.get("url") or item.get("pdfUrl"))
        report_id = sha_id(source_id)
        try:
            item = parse_detail(session, item)
            pdf_text = extract_pdf_text(session, str(item.get("pdfUrl") or ""), max_pdf_pages)
            report = {
                **existing_by_id.get(report_id, {}),
                "id": report_id,
                "sourceSystem": "Naver Finance Research",
                "kind": "naver-research",
                "category": item.get("category") or "",
                "ticker": item.get("ticker") or "",
                "name": item.get("name") or "",
                "sector": item.get("sector") or "",
                "title": clean_text(item.get("title"), 240),
                "broker": item.get("broker") or "",
                "date": item.get("date") or "",
                "targetPrice": item.get("targetPrice") or "",
                "opinion": item.get("opinion") or "",
                "url": item.get("url") or "",
                "pdfUrl": item.get("pdfUrl") or "",
                "text": build_text(item, pdf_text),
                "fetchedAt": utc_now_iso(),
            }
            existing_by_id[report_id] = report
            collected += 1
        except Exception as exc:
            failures.append({"category": str(item.get("category") or ""), "url": source_id, "error": str(exc)})
        if sleep > 0:
            time.sleep(sleep)

    reports = sorted(
        existing_by_id.values(),
        key=lambda row: str(row.get("date") or row.get("fetchedAt") or ""),
    )[-800:]

    payload = {
        "generatedAt": utc_now_iso(),
        "source": "Configured URLs + Naver Finance Research",
        "status": "ok",
        "naver": {
            "categories": categories,
            "pages": pages,
            "recentDays": recent_days,
            "maxReports": max_reports,
            "collected": collected,
            "candidateCount": len(deduped),
        },
        "reports": reports,
        "failures": failures[-100:],
    }
    write_json(output, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Korean securities reports from Naver Finance Research.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--categories", default="")
    parser.add_argument("--pages", type=int, default=int(os.getenv("NAVER_REPORT_PAGES", "2")))
    parser.add_argument("--max-reports", type=int, default=int(os.getenv("NAVER_REPORT_MAX_REPORTS", "80")))
    parser.add_argument("--recent-days", type=int, default=int(os.getenv("NAVER_REPORT_RECENT_DAYS", "14")))
    parser.add_argument("--max-pdf-pages", type=int, default=int(os.getenv("NAVER_REPORT_MAX_PDF_PAGES", "6")))
    parser.add_argument("--sleep", type=float, default=float(os.getenv("NAVER_REPORT_SLEEP", "0.15")))
    return parser.parse_args()


def main() -> int:
    bootstrap_env()
    args = parse_args()
    env_categories = split_env_list("NAVER_REPORT_CATEGORIES")
    categories = [item.strip() for item in (args.categories.split(",") if args.categories else env_categories) if item.strip()]
    if not categories:
        categories = ["company", "industry", "market", "invest", "economy"]

    payload = collect_reports(
        data_dir=Path(args.data_dir),
        categories=categories,
        pages=max(1, args.pages),
        max_reports=max(1, args.max_reports),
        recent_days=max(0, args.recent_days),
        max_pdf_pages=max(0, args.max_pdf_pages),
        sleep=max(0.0, args.sleep),
    )
    naver = payload.get("naver", {})
    print(
        "collected Naver reports: "
        f"{naver.get('collected', 0)} candidates: {naver.get('candidateCount', 0)} "
        f"failures: {len(payload.get('failures', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
