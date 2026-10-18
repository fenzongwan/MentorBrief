#!/usr/bin/env python3
"""Parse WeChat text exports like:

    2026-09-01 09:12:00 '示例科技 周老师'
    你好，我是……

    2026-09-01 09:15:00 '我'
    老师好……

The parser is deliberately local-only. It does not connect to WeChat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


CST = timezone(timedelta(hours=8))
HEADER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+'(.+?)'\s*$")
IMAGE_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)$", re.IGNORECASE)

PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
ADDRESS_RE = re.compile(r"(?:江苏省)?南京市[^\n]*(?:大学|学院)[^\n]*")
# 中性示例：按自己的情况替换这些词。不要把真实姓名、单位、学校写进仓库。
KNOWN_NAMES = ["示例同学", "示例企业", "示例大学"]


def redact_text(text: str) -> str:
    text = PHONE_RE.sub("[手机号]", text)
    text = ADDRESS_RE.sub("[地址]", text)
    text = text.replace("示例同学", "同学")
    text = text.replace("示例企业", "某企业")
    text = text.replace("示例大学", "高校")
    return text


def parse_messages(path: Path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    messages = []
    current = None
    for line in lines:
        match = HEADER_RE.match(line)
        if match:
            if current and any(line.strip() for line in current["lines"]):
                messages.append(current)
            current = {
                "time": match.group(1),
                "sender": match.group(2),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current and current["lines"]:
        messages.append(current)

    parsed = []
    for index, message in enumerate(messages):
        content = "\n".join(message["lines"]).strip()
        if not content:
            continue
        parsed.append(
            {
                "index": index,
                "time": message["time"],
                "sender": message["sender"],
                "content": content,
            }
        )
    return parsed


def message_type(content: str) -> str:
    stripped = content.strip()
    if IMAGE_RE.search(stripped) and ("/" in stripped or "\\" in stripped):
        return "image"
    if stripped.startswith("[") and stripped.endswith("]") and len(stripped) <= 12:
        return "emoji"
    return "text"


def to_app_export(messages, chat_id="mentor_demo", chat_name="导师 · 周老师", redact=True):
    output = []
    for index, message in enumerate(messages):
        sender = message["sender"]
        is_self = sender == "我"
        content = redact_text(message["content"]) if redact else message["content"]
        kind = message_type(content)
        if kind == "image":
            content = "[图片]"
        stamp = datetime.strptime(message["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        msg_id = hashlib.sha1(
            f"{chat_id}|{stamp.isoformat()}|{sender}|{content}".encode("utf-8")
        ).hexdigest()[:20]
        output.append(
            {
                "msgId": f"txt_{msg_id}",
                "senderName": "我" if is_self else sender,
                "wxid": "self" if is_self else chat_id,
                "time": stamp.isoformat(timespec="seconds"),
                "type": kind,
                "content": content,
            }
        )
    return [
        {
            "chatId": chat_id,
            "chatName": chat_name,
            "chatType": "direct",
            "messages": output,
        }
    ]


def build_parser():
    parser = argparse.ArgumentParser(description="把微信文本导出转换为 WeFlow Assistant JSON")
    parser.add_argument("input", help="微信导出的 .txt 文件")
    parser.add_argument("--out", required=True, help="输出 JSON")
    parser.add_argument("--chat-id", default="mentor_demo")
    parser.add_argument("--chat-name", default="导师 · 周老师")
    parser.add_argument("--no-redact", action="store_true", help="不脱敏（仅本地使用）")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    source = Path(args.input)
    if not source.is_file():
        print(f"错误：文件不存在 {source}", file=sys.stderr)
        return 1
    messages = parse_messages(source)
    export = to_app_export(
        messages,
        chat_id=args.chat_id,
        chat_name=args.chat_name,
        redact=not args.no_redact,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"已写入 {output}：{len(export[0]['messages'])} 条消息，"
        f"类型 {sorted(set(item['type'] for item in export[0]['messages']))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
