#!/usr/bin/env python3
"""DSH bridge for WeFlow Assistant.

This is a thin, stdlib-only adapter between DeepSeek Harness (DSH) and the
local WeFlow Assistant HTTP service. It does not touch WeChat/QQ, does not
log in, and does not inject into any client. It only calls the local API.

Examples:
    python dsh_bridge.py status
    python dsh_bridge.py daily
    python dsh_bridge.py daily --out reports/daily.md
    python dsh_bridge.py watch --id wxid_teacher --name 陈老师
    python dsh_bridge.py import-chats --file sample/sample-chats.json
    python dsh_bridge.py import-moments --file sample/sample-moments.json
    python dsh_bridge.py summarize --conversation "项目协作群" --range all
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


CST = timezone(timedelta(hours=8))
DEFAULT_BASE = os.environ.get("WEFLOW_BASE_URL", "http://127.0.0.1:8765").rstrip("/")


class BridgeError(RuntimeError):
    """A readable error raised by the bridge."""


def _request_json(base: str, path: str, method: str = "GET", payload=None, timeout: int = 20):
    url = base.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("error", body)
        except (ValueError, AttributeError):
            message = body
        raise BridgeError(f"{method} {path} -> HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"无法连接 {base}: {exc.reason}。请先启动 server.py。") from exc


def _upload_file(base: str, path: str, file_path: str, timeout: int = 60):
    source = Path(file_path)
    if not source.is_file():
        raise BridgeError(f"文件不存在：{source}")
    boundary = "----DSHBridge" + uuid.uuid4().hex
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body = head + source.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body_text).get("error", body_text)
        except (ValueError, AttributeError):
            message = body_text
        raise BridgeError(f"上传失败 HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"无法连接 {base}: {exc.reason}。请先启动 server.py。") from exc


def _parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CST)


def _fmt_time(value):
    parsed = _parse_time(value)
    return parsed.strftime("%m-%d %H:%M") if parsed else str(value or "")


def _truncate(value, limit=240):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _local_date(value):
    parsed = _parse_time(value)
    return parsed.date() if parsed else None


def _target_date(value):
    if not value:
        return None
    if value == "today":
        return datetime.now(CST).date()
    if value == "yesterday":
        return (datetime.now(CST) - timedelta(days=1)).date()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BridgeError("日期格式应为 YYYY-MM-DD、today 或 yesterday") from exc


def _match_watch(message, watch_ids, watch_names):
    candidates = {
        str(message.get("sender_id") or ""),
        str(message.get("sender_name") or ""),
        str(message.get("original_name") or ""),
    }
    return bool(candidates & (watch_ids | watch_names))


def _optional_json(base: str, path: str):
    try:
        return _request_json(base, path)
    except BridgeError:
        return None


def _latest_summaries(summaries, day=None):
    latest = {}
    for summary in summaries or []:
        conversation_id = summary.get("conversation_id")
        if not conversation_id:
            continue
        if day and _local_date(summary.get("created_at")) != day:
            continue
        if conversation_id not in latest:
            latest[conversation_id] = summary
    return list(latest.values())


def collect(base: str, day=None):
    state = _request_json(base, "/api/state")
    watchlist = state.get("watchlist", [])
    watch_ids = {str(item.get("author_id")) for item in watchlist if item.get("author_id")}
    watch_names = {str(item.get("display_name")) for item in watchlist if item.get("display_name")}

    messages = []
    for conversation in state.get("conversations", []):
        conversation_id = conversation.get("id")
        if not conversation_id:
            continue
        quoted = urllib.parse.quote(str(conversation_id), safe="")
        try:
            offset = 0
            while True:
                page = _request_json(
                    base,
                    f"/api/conversations/{quoted}/messages?range=all&limit=200&offset={offset}",
                )
                rows = page.get("messages") if isinstance(page, dict) else page
                if not isinstance(rows, list):
                    raise BridgeError("消息接口返回格式错误")
                for row in rows:
                    row["_conversation_title"] = conversation.get("title") or conversation_id
                    messages.append(row)
                total = int(page.get("total", len(rows))) if isinstance(page, dict) else len(rows)
                offset += len(rows)
                if not rows or offset >= total:
                    break
        except BridgeError:
            continue

    mentor_messages = [item for item in messages if _match_watch(item, watch_ids, watch_names)]
    moments = [item for item in state.get("moments", []) if str(item.get("author_id")) in watch_ids]
    summaries = _latest_summaries(_request_json(base, "/api/summaries"), day)
    mentor_report = _optional_json(base, "/api/reports/mentor")
    reply_outline = _optional_json(base, "/api/reply-outline")
    open_todos = _optional_json(base, "/api/todos?status=open") or []

    if day:
        mentor_messages = [item for item in mentor_messages if _local_date(item.get("sent_at")) == day]
        moments = [item for item in moments if _local_date(item.get("created_at")) == day]

    mentor_messages.sort(key=lambda item: str(item.get("sent_at") or ""))
    moments.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

    todos = []
    for summary in summaries:
        result = summary.get("result") or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        for todo in result.get("todos", []) or []:
            todos.append(
                {
                    "task": todo.get("task", ""),
                    "owner": todo.get("owner", ""),
                    "deadline": todo.get("deadline", ""),
                    "source": summary.get("conversation_title")
                    or summary.get("title")
                    or summary.get("conversation_id", ""),
                }
            )

    return {
        "state": state,
        "watchlist": watchlist,
        "messages": messages,
        "mentor_messages": mentor_messages,
        "moments": moments,
        "summaries": summaries,
        "todos": todos,
        "mentor_report": mentor_report,
        "reply_outline": reply_outline,
        "open_todos": open_todos,
    }


def render_daily(data, day_label=None):
    state = data["state"]
    watchlist = data["watchlist"]
    new_count = state.get("newMomentCount", 0)
    lines = [
        "# Mentor Brief · 每日沟通摘要",
        "",
        f"- 生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M')}",
        f"- 数据范围：{day_label or '当前全部数据'}",
        f"- 关注对象：{'、'.join(item.get('display_name', '') for item in watchlist) or '未设置'}",
        f"- 新动态：{new_count} 条",
        "",
    ]

    lines.append("## 一、导师消息")
    if data["mentor_messages"]:
        for message in data["mentor_messages"][-20:]:
            sender = message.get("original_name") or message.get("sender_name") or "未知"
            content = _truncate(message.get("content"))
            lines.append(
                f"- **{_fmt_time(message.get('sent_at'))} · {sender}**"
                f"（{message.get('_conversation_title', '')}）：{content}"
            )
    else:
        lines.append("- 暂无导师消息。先添加关注对象并导入聊天记录。")

    lines.extend(["", "## 二、导师简报"])
    brief_wrap = data.get("mentor_report") or {}
    brief = brief_wrap.get("result") or {}
    if brief:
        if brief.get("headline"):
            lines.append(f"- **{_truncate(brief.get('headline'), 220)}**")
        for signal in (brief.get("signals") or [])[:5]:
            lines.append(f"- {signal.get('label', '')}：{_truncate(signal.get('text'), 200)}")
        actions = brief.get("actions") or []
        if actions:
            lines.append(
                "- 行动项：" + "；".join(_truncate(item.get("task"), 100) for item in actions[:5])
            )
    else:
        lines.append("- 暂无导师简报。")

    lines.extend(["", "## 三、下次回复提纲"])
    outline_wrap = data.get("reply_outline") or {}
    outline = outline_wrap.get("result") or {}
    if outline:
        lines.append(f"- 目标：{_truncate(outline.get('goal'), 200)}")
        must_answer = outline.get("mustAnswer") or []
        if must_answer:
            lines.append(
                "- 必须回应：" + "；".join(_truncate(item, 120) for item in must_answer[:4])
            )
        for section in (outline.get("structure") or [])[:4]:
            points = "；".join(
                _truncate(item, 100) for item in (section.get("points") or [])[:3]
            )
            lines.append(f"  - {section.get('section', '')}：{points}")
        if outline.get("draft"):
            lines.append(f"- 草稿：{_truncate(outline.get('draft'), 320)}")
    else:
        lines.append("- 暂无回复提纲。")

    lines.extend(["", "## 四、导师动态"])
    if data["moments"]:
        for moment in data["moments"][:20]:
            marker = "新增 · " if moment.get("is_new") else ""
            lines.append(
                f"- **{_fmt_time(moment.get('created_at'))} · {moment.get('author_name', '')}**"
                f"（{marker}）：{_truncate(moment.get('content'), 300)}"
            )
    else:
        lines.append("- 暂无关注对象的新动态。")

    lines.extend(["", "## 五、群聊摘要"])
    if data["summaries"]:
        for summary in data["summaries"][:5]:
            result = summary.get("result") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    result = {}
            title = (
                summary.get("conversation_title")
                or summary.get("title")
                or summary.get("conversation_id", "")
            )
            lines.append(f"### {title}（{summary.get('message_count', 0)} 条）")
            highlights = result.get("highlights", []) or []
            todos = result.get("todos", []) or []
            agreements = result.get("agreements", []) or []
            if highlights:
                lines.append("- 要点：" + "；".join(_truncate(item.get("text"), 120) for item in highlights[:4]))
            if todos:
                lines.append("- 待办：" + "；".join(_truncate(item.get("task"), 100) for item in todos[:4]))
            if agreements:
                lines.append("- 约定：" + "；".join(_truncate(item.get("text"), 100) for item in agreements[:3]))
            if not (highlights or todos or agreements):
                lines.append("- 暂无结构化摘要。")
            lines.append("")
    else:
        lines.append("- 暂无群聊摘要。先在消息总结页生成一次总结。")

    lines.extend(["", "## 六、行动清单"])
    open_todos = data.get("open_todos") or []
    if open_todos:
        for todo in open_todos:
            owner = f"（{todo['owner']}）" if todo.get("owner") else ""
            due = f" · {todo['due']}" if todo.get("due") else ""
            lines.append(
                f"- [ ] {_truncate(todo.get('title'), 160)}{owner}{due}"
                f" · 来源：{todo.get('conversation_title', '')}"
            )
    elif data["todos"]:
        for todo in data["todos"]:
            owner = f"（{todo['owner']}）" if todo.get("owner") else ""
            deadline = f" · 截止 {todo['deadline']}" if todo.get("deadline") else ""
            lines.append(f"- [ ] {_truncate(todo.get('task'), 160)}{owner}{deadline} · 来源：{todo.get('source', '')}")
    else:
        lines.append("- 暂无待办。")

    lines.extend(
        [
            "",
            "## 七、数据说明",
            f"- 会话 {len(state.get('conversations', []))} 个，消息 {len(data['messages'])} 条，关注动态 {len(data['moments'])} 条。",
            "- 本报告由 DSH bridge 调用本地 Mentor Brief 服务生成；原始数据默认不出本机。",
            "- 该工具不登录微信/QQ、不注入客户端、不自动发送消息。",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_status(base, _args):
    state = _request_json(base, "/api/state")
    conversations = state.get("conversations", [])
    open_todos = _optional_json(base, "/api/todos?status=open") or []
    payload = {
        "ok": True,
        "conversations": len(conversations),
        "messages": sum(int(item.get("messageCount", 0)) for item in conversations),
        "watchlist": len(state.get("watchlist", [])),
        "moments": len(state.get("moments", [])),
        "newMomentCount": state.get("newMomentCount", 0),
        "openTodos": len(open_todos),
        "provider": state.get("settings", {}).get("provider", ""),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_watch(base, args):
    payload = {"authorId": args.id, "displayName": args.name or args.id}
    result = _request_json(base, "/api/watchlist", "POST", payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_import_chats(base, args):
    result = _upload_file(base, "/api/import/chats", args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_import_moments(base, args):
    result = _upload_file(base, "/api/import/moments", args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_summarize(base, args):
    state = _request_json(base, "/api/state")
    conversations = state.get("conversations", [])
    selected = None
    for conversation in conversations:
        if args.conversation in (conversation.get("id"), conversation.get("title")):
            selected = conversation
            break
    if not selected:
        titles = "、".join(item.get("title", "") for item in conversations) or "无"
        raise BridgeError(f"找不到会话「{args.conversation}」。现有会话：{titles}")
    result = _request_json(
        base,
        "/api/summaries",
        "POST",
        {"conversationId": selected["id"], "range": args.range},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_daily(base, args):
    day = _target_date(args.date)
    data = collect(base, day)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    report = render_daily(data, day.isoformat() if day else None)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"已写入 {output}")
    else:
        print(report)


def build_parser():
    parser = argparse.ArgumentParser(description="DSH bridge for WeFlow Assistant")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="WeFlow Assistant 地址")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="查看服务状态")
    status.set_defaults(func=cmd_status)

    daily = subparsers.add_parser("daily", help="生成导师雷达日报")
    daily.add_argument("--date", help="YYYY-MM-DD、today 或 yesterday；默认全部数据")
    daily.add_argument("--out", help="写入 Markdown 文件")
    daily.add_argument("--json", action="store_true", help="输出结构化 JSON")
    daily.set_defaults(func=cmd_daily)

    watch = subparsers.add_parser("watch", help="添加关注对象")
    watch.add_argument("--id", required=True, help="wxid 或稳定 ID")
    watch.add_argument("--name", help="显示名")
    watch.set_defaults(func=cmd_watch)

    chats = subparsers.add_parser("import-chats", help="导入聊天 JSON/CSV")
    chats.add_argument("--file", required=True)
    chats.set_defaults(func=cmd_import_chats)

    moments = subparsers.add_parser("import-moments", help="导入朋友圈 JSON/CSV")
    moments.add_argument("--file", required=True)
    moments.set_defaults(func=cmd_import_moments)

    summary = subparsers.add_parser("summarize", help="总结一个群聊")
    summary.add_argument("--conversation", required=True, help="会话标题或 ID")
    summary.add_argument("--range", default="all", choices=["all", "7", "30"])
    summary.set_defaults(func=cmd_summarize)

    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args.base_url.rstrip("/"), args)
        return 0
    except BridgeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
