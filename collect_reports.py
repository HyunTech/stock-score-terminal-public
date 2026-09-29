from __future__ import annotations

import argparse
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from research_common import REPORTS_FILE, bootstrap_env, clean_text, raw_dir, read_json, sha_id, split_env_list, utc_now_iso, write_json


PDF_LINK_RE = re.compile(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def fetch_url(url: str) -> tuple[bytes, str]:
    response = requests.get(url, timeout=45, headers={"User-Agent": "StockScoreResearchBot/0.1"})
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "")


def extract_pdf_text(content: bytes, max_pages: int = 8) -> str:
    reader = PdfReader(BytesIO(content))
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    return clean_text("\n".join(parts), 12000)


def extract_html_text(content: bytes) -> tuple[str, list[str]]:
    html = content.decode("utf-8", errors="ignore")
    title_match = TITLE_RE.search(html)
    title = clean_text(title_match.group(1), 240) if title_match else ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = clean_text(re.sub(r"<[^>]+>", " ", text), 12000)
    links = [requests.compat.urljoin("about:blank", link) for link in PDF_LINK_RE.findall(html)]
    return title or text[:120], links


def report_from_url(url: str) -> dict[str, object]:
    content, content_type = fetch_url(url)
    parsed = urlparse(url)
    is_pdf = ".pdf" in parsed.path.lower() or "pdf" in content_type.lower()
    if is_pdf:
        text = extract_pdf_text(content)
        title = Path(parsed.path).name or "PDF report"
        kind = "pdf"
    else:
        title, _links = extract_html_text(content)
        text = title
        kind = "html"
    return {
        "id": sha_id(url),
        "url": url,
        "title": clean_text(title, 240),
        "kind": kind,
        "text": text,
        "fetchedAt": utc_now_iso(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect public securities report URLs configured in REPORT_SOURCE_URLS.")
    parser.add_argument("--data-dir", default="data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bootstrap_env()
    output = raw_dir(Path(args.data_dir)) / REPORTS_FILE
    existing = read_json(output, {"reports": []})
    existing_by_id = {str(item.get("id")): item for item in existing.get("reports", [])}

    urls = split_env_list("REPORT_SOURCE_URLS")
    if not urls:
        existing["generatedAt"] = utc_now_iso()
        existing["status"] = "missing REPORT_SOURCE_URLS"
        write_json(output, existing)
        print("REPORT_SOURCE_URLS is not set. Keeping report research cache.")
        return 0

    failures: list[dict[str, str]] = []
    for url in urls:
        try:
            report = report_from_url(url)
            existing_by_id[str(report["id"])] = report
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})

    reports = list(existing_by_id.values())[-500:]
    payload = {
        "generatedAt": utc_now_iso(),
        "source": "Configured report URLs",
        "status": "ok",
        "reports": reports,
        "failures": failures,
    }
    write_json(output, payload)
    print(f"collected reports: {len(reports)} failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
