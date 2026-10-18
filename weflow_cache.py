#!/usr/bin/env python3
"""Read WeFlow's local cache and convert it to WeFlow Assistant import JSON.

This adapter deliberately reads only the cache files that WeFlow has already
produced:

    %APPDATA%\\weflow\\cache\\contacts.json
    %APPDATA%\\weflow\\cache\\session-messages.json

It does not read WeFlow-config.json (which contains the database key), does not
decrypt WeChat databases, does not log in, and does not touch WeChat/QQ.

Usage:
    python weflow_cache.py --stats
    python weflow_cache.py --out sample/weflow-real-chats.json
    python weflow_cache.py --out sample/weflow-groups.json --groups-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


CST = timezone(timedelta(hours=8))
DEFAULT_CACHE_DIR = Path(
    os.environ.get("WEFLOW_CACHE_DIR", Path(os.environ.get("APPDATA", "")) / "weflow" / "cache")
)

TYPE_NAMES = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "link",
    50: "call",
    10000: "system",
    10002: "system",
}

MEDIA_LABELS = {
    "image": "[图片]",
    "voice": "[语音]",
    "video": "[视频]",
    "emoji": "[表情]",
    "call": "[通话]",
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def base_type(value) -> int:
    try:
        return int(value or 0) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


def timestamp_to_iso(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 10_000_000_000:
        number /= 1000
    try:
        return datetime.fromtimestamp(number, tz=CST).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return None


def parse_since(value):
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        return float(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CST)
    return parsed.timestamp()


def message_kind(local_type: int, message: dict) -> str:
    kind = TYPE_NAMES.get(local_type, "text")
    if kind == "link" and not (message.get("linkUrl") or message.get("appMsgDesc")):
        return "file"
    return kind


def message_content(kind: str, message: dict) -> str:
    parsed = str(message.get("parsedContent") or "").strip()
    link_url = str(message.get("linkUrl") or "").strip()
    link_title = str(message.get("linkTitle") or "").strip()
    app_desc = str(message.get("appMsgDesc") or "").strip()

    if kind == "link":
        parts = [part for part in (link_title, app_desc, link_url) if part]
        if parts:
            return "\n".join(dict.fromkeys(parts))
    if kind in ("file", "system", "call") and app_desc:
        return app_desc
    if parsed:
        return parsed
    return MEDIA_LABELS.get(kind, "")


def sender_name(sender_username: str, message: dict, contacts: dict) -> str:
    if int(message.get("isSend") or 0) == 1:
        return "我"
    contact = contacts.get(sender_username) or {}
    name = str(contact.get("displayName") or "").strip()
    return name or sender_username or "未知成员"


def conversation_name(session_id: str, contacts: dict) -> str:
    contact = contacts.get(session_id) or {}
    name = str(contact.get("displayName") or "").strip()
    if name:
        return name
    if session_id.endswith("@chatroom"):
        return "群聊 " + session_id[:8]
    if session_id.startswith("gh_"):
        return "公众号 " + session_id[:8]
    if session_id.endswith("@openim"):
        return "开放会话 " + session_id[:8]
    return session_id


def is_group(session_id: str) -> bool:
    return session_id.endswith("@chatroom")


def is_official(session_id: str) -> bool:
    return session_id.startswith("gh_") or session_id.endswith("@opencustomerservicemsg")


def is_openim(session_id: str) -> bool:
    return session_id.endswith("@openim")


def normalize_message(session_id: str, message: dict, contacts: dict, index: int):
    local_type = base_type(message.get("localType"))
    kind = message_kind(local_type, message)
    sender_username = str(message.get("senderUsername") or "").strip()
    msg_id = (
        str(message.get("messageKey") or "").strip()
        or str(message.get("serverIdRaw") or "").strip()
        or str(message.get("serverId") or "").strip()
        or f"{session_id}:{index}"
    )
    content = message_content(kind, message)
    return {
        "msgId": msg_id,
        "senderName": sender_name(sender_username, message, contacts),
        "wxid": sender_username or None,
        "time": timestamp_to_iso(message.get("createTime")),
        "type": kind,
        "content": content,
    }


def build_export(
    cache_dir: Path,
    include_official: bool = False,
    include_openim: bool = False,
    groups_only: bool = False,
    direct_only: bool = False,
    session_filter=None,
    since=None,
    max_per_session: int = 2000,
):
    contacts_path = cache_dir / "contacts.json"
    messages_path = cache_dir / "session-messages.json"
    if not contacts_path.is_file():
        raise FileNotFoundError(f"未找到 {contacts_path}")
    if not messages_path.is_file():
        raise FileNotFoundError(f"未找到 {messages_path}")

    contacts = load_json(contacts_path)
    sessions = load_json(messages_path)
    since_ts = parse_since(since)
    filter_set = set(session_filter or [])

    conversations = []
    for session_id, payload in sessions.items():
        if filter_set and session_id not in filter_set:
            continue
        if is_official(session_id) and not include_official:
            continue
        if is_openim(session_id) and not include_openim:
            continue
        if groups_only and not is_group(session_id):
            continue
        if direct_only and (is_group(session_id) or is_official(session_id) or is_openim(session_id)):
            continue

        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        normalized = []
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            if since_ts is not None:
                try:
                    create_time = float(message.get("createTime") or 0)
                except (TypeError, ValueError):
                    create_time = 0
                if create_time and create_time < since_ts:
                    continue
            item = normalize_message(session_id, message, contacts, index)
            if not item["time"]:
                continue
            normalized.append(item)

        normalized.sort(key=lambda item: item["time"])
        if max_per_session and len(normalized) > max_per_session:
            normalized = normalized[-max_per_session:]
        if not normalized:
            continue
        conversations.append(
            {
                "chatId": session_id,
                "chatName": conversation_name(session_id, contacts),
                "chatType": "group" if is_group(session_id) else "direct",
                "messages": normalized,
            }
        )

    conversations.sort(key=lambda item: item["chatName"])
    return conversations


def summarize_export(conversations):
    total_messages = sum(len(item["messages"]) for item in conversations)
    type_counts = {}
    sender_count = 0
    first_time = None
    last_time = None
    for conversation in conversations:
        for message in conversation["messages"]:
            type_counts[message["type"]] = type_counts.get(message["type"], 0) + 1
            sender_count += 1
            if first_time is None or message["time"] < first_time:
                first_time = message["time"]
            if last_time is None or message["time"] > last_time:
                last_time = message["time"]
    return {
        "conversations": len(conversations),
        "messages": total_messages,
        "types": dict(sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))),
        "first": first_time,
        "last": last_time,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="把 WeFlow 本地缓存转换为 WeFlow Assistant 导入 JSON")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="WeFlow cache 目录")
    parser.add_argument("--out", help="输出 JSON 路径；不填则打印到 stdout")
    parser.add_argument("--stats", action="store_true", help="只打印统计，不输出消息内容")
    parser.add_argument("--include-official", action="store_true", help="包含公众号会话")
    parser.add_argument("--include-openim", action="store_true", help="包含 openim 会话")
    parser.add_argument("--groups-only", action="store_true", help="只导出群聊")
    parser.add_argument("--direct-only", action="store_true", help="只导出私聊")
    parser.add_argument("--session", action="append", help="只导出指定 session id，可重复")
    parser.add_argument("--since", help="只导出该时间之后的消息：epoch 秒或 ISO 时间")
    parser.add_argument("--max-per-session", type=int, default=2000)
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    cache_dir = Path(args.cache_dir)
    try:
        conversations = build_export(
            cache_dir,
            include_official=args.include_official,
            include_openim=args.include_openim,
            groups_only=args.groups_only,
            direct_only=args.direct_only,
            session_filter=args.session,
            since=args.since,
            max_per_session=args.max_per_session,
        )
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    stats = summarize_export(conversations)
    messages_path = cache_dir / "session-messages.json"
    if messages_path.is_file():
        mtime = messages_path.stat().st_mtime
        stats["cacheUpdatedAt"] = datetime.fromtimestamp(mtime, tz=CST).isoformat(timespec="seconds")
        stats["cacheAgeSeconds"] = int(max(0, time.time() - mtime))
    print(json.dumps(stats, ensure_ascii=False, indent=2), file=sys.stderr)
    if args.stats:
        return 0

    payload = json.dumps(conversations, ensure_ascii=False, indent=2)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"已写入 {output}（{stats['conversations']} 个会话 / {stats['messages']} 条消息）", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
