#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path


def bootstrap_runtime_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.is_dir():
        sys.path.insert(0, str(src_root))


bootstrap_runtime_path()

from gh_address_cr.core.reply_templates import clarify_reply, defer_reply, fix_reply  # noqa: E402


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Markdown reply template for a CR item.")
    parser.add_argument("--severity", default="P2", help="P1, P2, or P3 for fix mode.")
    parser.add_argument("--mode", default="fix", choices=["fix", "clarify", "defer"])
    parser.add_argument("output_md")
    parser.add_argument("args", nargs="*")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_md)
    if args.mode == "fix":
        content = fix_reply(args.severity, args.args)
    elif args.mode == "clarify":
        content = clarify_reply(args.args)
    else:
        content = defer_reply(args.args)

    write_text(output_path, content)
    print(f"Wrote reply template ({args.mode} mode): {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
