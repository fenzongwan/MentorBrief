#!/usr/bin/env python3
"""Seed the demo database with the sanitized mentor chat and a sample group.

Usage:
    python seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def remove_database():
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(server.DB_PATH) + suffix)
        if path.exists():
            path.unlink()


def import_json(path: Path, importer, label: str):
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    stats = importer(raw, path.name)
    print(f"{label}: {json.dumps(stats, ensure_ascii=False)}")
    return stats


def conversation_id(conn, title: str):
    row = conn.execute("SELECT id FROM conversations WHERE title=? ORDER BY created_at LIMIT 1", (title,)).fetchone()
    return row["id"] if row else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="初始化导师雷达演示数据")
    parser.add_argument("--reset", action="store_true", help="删除现有数据库后重新导入")
    args = parser.parse_args(argv)

    if args.reset:
        remove_database()
        print("已清空旧数据库")

    import_json(DATA / "mentor-chat.json", server.import_messages, "导师私聊")
    import_json(ROOT / "sample" / "sample-chats.json", server.import_messages, "示例群聊")

    with server.open_db() as conn:
        server.ensure_watch(conn, "mentor_demo", "周老师")
        mentor_id = conversation_id(conn, "导师 · 周老师")
        group_id = conversation_id(conn, "项目协作群")
        if not mentor_id:
            raise RuntimeError("导师会话导入失败")

        # Curated mentor report
        brief = json.loads((DATA / "mentor-brief.json").read_text(encoding="utf-8"))
        conn.execute("DELETE FROM mentor_reports WHERE conversation_id=?", (mentor_id,))
        conn.execute(
            "INSERT INTO mentor_reports(id, conversation_id, period_start, period_end, result, created_at) VALUES(?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                mentor_id,
                "2026-08-10",
                "2026-09-07",
                json.dumps(brief, ensure_ascii=False),
                server.utc_now(),
            ),
        )

        # A curated summary so the "消息总结" page has something to show immediately.
        mentor_count = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (mentor_id,)
        ).fetchone()["n"]
        mentor_summary = {
            "highlights": [
                {"text": item["text"], "message_ids": []} for item in brief.get("signals", [])
            ],
            "todos": [
                {
                    "task": item["task"],
                    "owner": item.get("owner", ""),
                    "deadline": item.get("due", ""),
                    "message_ids": [],
                }
                for item in brief.get("actions", [])
            ],
            "agreements": [
                {"text": item["conclusion"], "message_ids": []}
                for item in brief.get("technicalConclusions", [])[:4]
            ],
            "links": [],
        }
        conn.execute("DELETE FROM summaries WHERE conversation_id=? AND provider='demo'", (mentor_id,))
        conn.execute(
            "INSERT INTO summaries(id, conversation_id, range_start, range_end, message_count, masked, provider, model, result, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                mentor_id,
                "2026-08-10",
                "2026-09-07",
                mentor_count,
                1,
                "demo",
                "curated",
                json.dumps(mentor_summary, ensure_ascii=False),
                server.utc_now(),
            ),
        )

        # Curated reply outline
        reply_outline = json.loads((DATA / "reply-outline.json").read_text(encoding="utf-8"))
        conn.execute("DELETE FROM reply_outlines WHERE conversation_id=?", (mentor_id,))
        conn.execute(
            "INSERT INTO reply_outlines(id, conversation_id, title, result, created_at) VALUES(?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                mentor_id,
                "回复提纲 · 导师沟通",
                json.dumps(reply_outline, ensure_ascii=False),
                server.utc_now(),
            ),
        )

        # Action list from the curated brief
        conn.execute(
            "DELETE FROM todos WHERE conversation_id=? AND source_message_id='seed'",
            (mentor_id,),
        )
        for action in brief.get("actions", []):
            now = server.utc_now()
            conn.execute(
                "INSERT INTO todos(id, conversation_id, source_message_id, title, detail, owner, due, priority, status, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    mentor_id,
                    "seed",
                    action.get("task", ""),
                    "来自导师简报的下一步行动",
                    action.get("owner", ""),
                    action.get("due", ""),
                    action.get("priority", "medium"),
                    "open",
                    now,
                    now,
                ),
            )

        # A normal heuristic summary for the sample group.
        group_messages = server.get_messages_for_summary(conn, group_id) if group_id else []

    if group_id:
        group_summary = server.heuristic_summary(group_messages, True)
        with server.open_db() as conn:
            conn.execute("DELETE FROM summaries WHERE conversation_id=? AND provider='mock'", (group_id,))
            conn.execute(
                "INSERT INTO summaries(id, conversation_id, range_start, range_end, message_count, masked, provider, model, result, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    group_id,
                    None,
                    None,
                    len(group_messages),
                    1,
                    "mock",
                    "rules",
                    json.dumps(group_summary, ensure_ascii=False),
                    server.utc_now(),
                ),
            )

    import_json(DATA / "demo-moments.json", server.import_moments, "示例朋友圈")

    with server.open_db() as conn:
        conversations = conn.execute("SELECT id, title FROM conversations ORDER BY title").fetchall()
        messages = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        moments = conn.execute("SELECT COUNT(*) AS n FROM moments").fetchone()["n"]
        reports = conn.execute("SELECT COUNT(*) AS n FROM mentor_reports").fetchone()["n"]
        todos_count = conn.execute("SELECT COUNT(*) AS n FROM todos").fetchone()["n"]
        outlines = conn.execute("SELECT COUNT(*) AS n FROM reply_outlines").fetchone()["n"]
    print(
        json.dumps(
            {
                "conversations": [dict(row) for row in conversations],
                "messages": messages,
                "moments": moments,
                "mentorReports": reports,
                "todos": todos_count,
                "replyOutlines": outlines,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise
