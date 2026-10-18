#!/usr/bin/env python3
"""Incrementally sync WeFlow's local cache into WeFlow Assistant.

WeFlow already writes decrypted session data to:

    %APPDATA%\\weflow\\cache\\session-messages.json
    %APPDATA%\\weflow\\cache\\contacts.json

This script watches those files, converts new messages to the Assistant import
format, uploads them to the local Assistant API, and optionally writes alerts
for watched mentors.

It does not log in, inject, decrypt WeChat databases, or send messages.

Examples:
    python weflow_sync.py --once
    python weflow_sync.py --loop --interval 30
    python weflow_sync.py --once --print-alerts
    python weflow_sync.py --once --alerts-out data/alerts.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import weflow_cache
from dsh_bridge import BridgeError, _request_json


CST = timezone(timedelta(hours=8))
DEFAULT_BASE = os.environ.get("WEFLOW_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
DEFAULT_STATE = Path(__file__).resolve().parent / "data" / "weflow_sync_state.json"


def now_iso():
    return datetime.now(CST).isoformat(timespec="seconds")


def load_state(path: Path):
    if not path.is_file():
        return {"version": 1, "seen": {}, "alerted": {}, "last_sync": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "seen": {}, "alerted": {}, "last_sync": None}
    if not isinstance(data, dict):
        return {"version": 1, "seen": {}, "alerted": {}, "last_sync": None}
    data.setdefault("seen", {})
    data.setdefault("alerted", {})
    return data


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def upload_export(base: str, conversations, timeout: int = 60):
    boundary = "----WeFlowSync" + uuid.uuid4().hex
    body_prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="weflow-cache.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode("utf-8")
    payload = json.dumps(conversations, ensure_ascii=False).encode("utf-8")
    body = body_prefix + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/api/import/chats",
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
        text = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(text).get("error", text)
        except (ValueError, AttributeError):
            message = text
        raise BridgeError(f"导入失败 HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"无法连接 {base}: {exc.reason}。请先启动 server.py。") from exc


def get_watchlist(base: str):
    try:
        state = _request_json(base, "/api/state", timeout=10)
    except BridgeError:
        return set(), set()
    watch_ids = {str(item.get("author_id")) for item in state.get("watchlist", []) if item.get("author_id")}
    watch_names = {str(item.get("display_name")) for item in state.get("watchlist", []) if item.get("display_name")}
    return watch_ids, watch_names


def cleanup_archive(base: str, days: int):
    if days <= 0:
        return None
    try:
        return _request_json(
            base,
            "/api/maintenance/cleanup",
            "POST",
            {"retentionDays": int(days), "dryRun": False},
            timeout=30,
        )
    except BridgeError as exc:
        return {"ok": False, "error": str(exc)}


def collect_new(conversations, state, watch_ids, watch_names, bootstrap: bool):
    seen = state.setdefault("seen", {})
    alerted = state.setdefault("alerted", {})
    new_messages = []
    all_ids = {}
    for conversation in conversations:
        session_id = conversation["chatId"]
        old_ids = set(seen.get(session_id, []))
        current_ids = []
        for message in conversation["messages"]:
            msg_id = message["msgId"]
            current_ids.append(msg_id)
            if msg_id not in old_ids:
                item = dict(message)
                item["chatId"] = session_id
                item["conversation"] = conversation.get("chatName")
                item["chatType"] = conversation.get("chatType")
                new_messages.append(item)
        # Keep the state bounded. 10k ids per conversation is plenty for a demo.
        all_ids[session_id] = current_ids[-10000:]
    state["seen"] = all_ids

    alerts = []
    if not bootstrap:
        for message in new_messages:
            if str(message.get("msgId")) in alerted.get(str(message.get("chatId")), []):
                continue
            if (
                str(message.get("wxid") or "") in watch_ids
                or str(message.get("senderName") or "") in watch_names
            ):
                alerts.append(message)
    # Alerted IDs are persisted separately from the rolling seen cache. A cache
    # truncation can remove IDs from seen, but it must not re-alert them.
    for conversation in conversations:
        session_id = conversation["chatId"]
        current = alerted.setdefault(session_id, [])
        alert_ids = {
            str(alert["msgId"])
            for alert in alerts
            if str(alert.get("chatId")) == str(session_id)
        }
        alerted[session_id] = list(set(current) | alert_ids)
    return new_messages, alerts


def sync_once(base: str, args, state):
    conversations = weflow_cache.build_export(
        Path(args.cache_dir),
        include_official=args.include_official,
        include_openim=args.include_openim,
        groups_only=args.groups_only,
        direct_only=args.direct_only,
        session_filter=args.session,
        since=args.since,
        max_per_session=args.max_per_session,
    )
    stats = weflow_cache.summarize_export(conversations)
    bootstrap = not state.get("seen")
    watch_ids, watch_names = get_watchlist(base)
    new_messages, alerts = collect_new(conversations, state, watch_ids, watch_names, bootstrap)

    uploaded = None
    if not args.dry_run and new_messages:
        uploaded = upload_export(base, conversations)

    if args.alerts_out and alerts:
        output = Path(args.alerts_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            for alert in alerts:
                handle.write(json.dumps(alert, ensure_ascii=False) + "\n")

    if args.print_alerts:
        for alert in alerts:
            print(
                f"[{alert.get('time')}] {alert.get('senderName')} "
                f"in {alert.get('conversation')}: {alert.get('content')}"
            )

    state["last_sync"] = now_iso()
    cache_mtime = Path(args.cache_dir, "session-messages.json").stat().st_mtime
    state["cache_mtime"] = cache_mtime
    save_state(Path(args.state), state)

    cleanup = cleanup_archive(base, args.cleanup_days)

    return {
        "ok": True,
        "bootstrap": bootstrap,
        "conversations": stats["conversations"],
        "messages": stats["messages"],
        "newMessages": len(new_messages),
        "alerts": len(alerts),
        "uploaded": uploaded,
        "cleanup": cleanup,
        "cacheUpdatedAt": datetime.fromtimestamp(cache_mtime, tz=CST).isoformat(timespec="seconds"),
        "cacheAgeSeconds": int(max(0, time.time() - cache_mtime)),
        "lastSync": state["last_sync"],
    }


def build_parser():
    parser = argparse.ArgumentParser(description="增量同步 WeFlow cache 到 WeFlow Assistant")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--cache-dir", default=str(weflow_cache.DEFAULT_CACHE_DIR))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--once", action="store_true", help="只同步一次（默认）")
    parser.add_argument("--loop", action="store_true", help="持续监听 cache 变化")
    parser.add_argument("--interval", type=int, default=30, help="轮询间隔秒数")
    parser.add_argument("--include-official", action="store_true")
    parser.add_argument("--include-openim", action="store_true")
    parser.add_argument("--groups-only", action="store_true")
    parser.add_argument("--direct-only", action="store_true")
    parser.add_argument("--session", action="append", help="只同步指定 session id，可重复")
    parser.add_argument("--since", help="只同步该时间之后的消息")
    parser.add_argument("--max-per-session", type=int, default=2000)
    parser.add_argument("--alerts-out", help="把关注对象的新消息写入 JSONL")
    parser.add_argument("--print-alerts", action="store_true", help="把关注对象的新消息打印到终端")
    parser.add_argument("--dry-run", action="store_true", help="只解析，不上传")
    parser.add_argument("--cleanup-days", type=int, default=0, help="同步后清理超过 N 天的消息；0 表示不清理")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    state = load_state(Path(args.state))
    if not args.loop:
        try:
            result = sync_once(args.base_url.rstrip("/"), args, state)
        except BridgeError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        except FileNotFoundError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"开始监听 {args.cache_dir}，每 {args.interval}s 检查一次；Ctrl-C 退出。", file=sys.stderr)
    last_mtime = None
    try:
        while True:
            messages_path = Path(args.cache_dir, "session-messages.json")
            try:
                mtime = messages_path.stat().st_mtime
            except OSError:
                mtime = None
            if mtime != last_mtime:
                try:
                    result = sync_once(args.base_url.rstrip("/"), args, state)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    last_mtime = mtime
                except (BridgeError, FileNotFoundError) as exc:
                    print(f"同步失败：{exc}", file=sys.stderr)
            time.sleep(max(5, args.interval))
    except KeyboardInterrupt:
        print("已停止。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
