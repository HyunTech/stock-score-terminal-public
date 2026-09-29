from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import requests

from research_common import (
    TELEGRAM_MESSAGES_FILE,
    bootstrap_env,
    clean_text,
    raw_dir,
    read_json,
    split_env_list,
    utc_now_iso,
    write_json,
)


def api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def message_text(message: dict[str, Any]) -> str:
    parts = [
        message.get("text"),
        message.get("caption"),
        (message.get("document") or {}).get("file_name"),
    ]
    return clean_text(" ".join(str(part or "") for part in parts), 5000)


def normalize_update(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or update.get("channel_post")
    if not message:
        return None
    chat = message.get("chat") or {}
    text = message_text(message)
    if not text:
        return None
    document = message.get("document") or {}
    return {
        "updateId": update.get("update_id"),
        "messageId": message.get("message_id"),
        "date": message.get("date"),
        "chatId": str(chat.get("id") or ""),
        "chatTitle": chat.get("title") or chat.get("username") or "",
        "text": text,
        "document": {
            "fileId": document.get("file_id"),
            "fileName": document.get("file_name"),
            "mimeType": document.get("mime_type"),
        }
        if document
        else None,
    }


def fetch_updates(token: str, offset: int | None, timeout: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "channel_post"]}
    if offset is not None:
        params["offset"] = offset
    response = requests.get(api_url(token, "getUpdates"), params=params, timeout=timeout + 10)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload.get("result") or []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect accessible Telegram messages for daily research.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--reset-offset", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bootstrap_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    output = raw_dir(Path(args.data_dir)) / TELEGRAM_MESSAGES_FILE
    existing = read_json(output, {"messages": [], "lastUpdateId": None})
    if not token:
        existing["generatedAt"] = utc_now_iso()
        existing["status"] = "missing TELEGRAM_BOT_TOKEN"
        write_json(output, existing)
        print("TELEGRAM_BOT_TOKEN is not set. Keeping Telegram research cache.")
        return 0

    allowed_chats = set(split_env_list("TELEGRAM_CHAT_IDS"))
    offset = None if args.reset_offset else existing.get("lastUpdateId")
    if offset is not None:
        offset = int(offset) + 1

    updates = fetch_updates(token, offset, args.timeout)
    messages = existing.get("messages") or []
    seen = {(str(item.get("chatId")), str(item.get("messageId"))) for item in messages}
    last_update_id = existing.get("lastUpdateId")
    added = 0
    for update in updates:
        last_update_id = max(int(last_update_id or 0), int(update.get("update_id") or 0))
        item = normalize_update(update)
        if not item:
            continue
        if allowed_chats and item["chatId"] not in allowed_chats:
            continue
        key = (str(item.get("chatId")), str(item.get("messageId")))
        if key in seen:
            continue
        messages.append(item)
        seen.add(key)
        added += 1

    payload = {
        "generatedAt": utc_now_iso(),
        "source": "Telegram Bot API",
        "status": "ok",
        "lastUpdateId": last_update_id,
        "messages": messages[-1000:],
    }
    write_json(output, payload)
    print(f"collected Telegram messages: +{added}, total {len(payload['messages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
