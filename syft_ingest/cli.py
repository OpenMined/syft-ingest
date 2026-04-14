from __future__ import annotations

import argparse
from pathlib import Path

from syft_ingest import gather
from syft_ingest.setup import register_fetchers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="syft-ingest",
        description="Normalize local export directories into syft-ingest outputs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    local_export = subparsers.add_parser(
        "local-export",
        help="Auto-detect local export directories and export normalized output.",
    )
    local_export.add_argument(
        "--author",
        required=True,
        help="Author/creator name stamped onto normalized content items.",
    )
    local_export.add_argument(
        "--input-dir",
        dest="input_dirs",
        action="append",
        required=True,
        help="Input directory containing a Facebook or Instagram export. Repeatable.",
    )
    local_export.add_argument(
        "--format",
        choices=("jsonl", "json", "text"),
        default="jsonl",
        help="Output format.",
    )
    local_export.add_argument(
        "--output",
        required=True,
        help="Output file path (jsonl/json) or directory path (text).",
    )
    return parser


def _cmd_local_export(args: argparse.Namespace) -> int:
    corpus = gather(
        "local",
        urls=args.input_dirs,
        author=args.author,
    )
    output_path = Path(args.output).expanduser()
    corpus.export(str(output_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    register_fetchers()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "local-export":
        return _cmd_local_export(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
