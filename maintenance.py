#!/usr/bin/env python3
"""Small maintenance CLI for WeFlow Assistant.

Examples:
    python maintenance.py cleanup --days 30 --dry-run
    python maintenance.py cleanup --days 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from dsh_bridge import BridgeError, _request_json


DEFAULT_BASE = os.environ.get("WEFLOW_BASE_URL", "http://127.0.0.1:8765").rstrip("/")


def cleanup(base: str, days: int, dry_run: bool):
    return _request_json(
        base,
        "/api/maintenance/cleanup",
        "POST",
        {"retentionDays": int(days), "dryRun": bool(dry_run)},
        timeout=30,
    )


def build_parser():
    parser = argparse.ArgumentParser(description="WeFlow Assistant 维护工具")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    cleanup_parser = subparsers.add_parser("cleanup", help="删除超过保留期的原始消息")
    cleanup_parser.add_argument("--days", type=int, default=30)
    cleanup_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        result = cleanup(args.base_url.rstrip("/"), args.days, args.dry_run)
    except BridgeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
