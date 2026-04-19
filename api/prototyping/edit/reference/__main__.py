"""
`python -m api.prototyping.edit.reference <subcommand>`.

Subcommands:
    ingest        — download a viral AMV, run analyses, write store JSON
    consolidate   — single LLM call over all stored refs → references.md
    list          — list stored refs
    show <ref_id> — print a stored ref's meta + metrics
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .consolidate import (
    ConsolidationValidationError,
    consolidate as run_consolidate,
    DEFAULT_MODEL,
)
from .download import ReferenceDownloadError
from .ingest import AlreadyIngestedError, ingest as run_ingest

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STORE_DIR = PACKAGE_DIR / "store"
DEFAULT_REFS_MD = PACKAGE_DIR.parent / "knowledge" / "references.md"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="python -m api.prototyping.edit.reference",
        description="Reference-AMV ingestion + consolidation (Phase 2).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest one viral AMV")
    p_ingest.add_argument("--url", required=True,
                          help="YouTube or Instagram Reel URL")
    p_ingest.add_argument("--likes", type=int, default=0,
                          help="curator-supplied like count (default 0)")
    p_ingest.add_argument("--views", type=int, default=0,
                          help="curator-supplied view count (default 0)")
    p_ingest.add_argument("--store-dir", type=Path, default=DEFAULT_STORE_DIR)
    p_ingest.add_argument("--force", action="store_true",
                          help="overwrite an existing ref_id")

    p_cons = sub.add_parser("consolidate", help="rewrite references.md via LLM")
    p_cons.add_argument("--store-dir", type=Path, default=DEFAULT_STORE_DIR)
    p_cons.add_argument("--references-md", type=Path, default=DEFAULT_REFS_MD)
    p_cons.add_argument("--model", default=DEFAULT_MODEL)
    p_cons.add_argument("--dry-run", action="store_true",
                        help="build prompt + validate inputs, skip LLM + write")

    p_list = sub.add_parser("list", help="list stored references")
    p_list.add_argument("--store-dir", type=Path, default=DEFAULT_STORE_DIR)

    p_show = sub.add_parser("show", help="print one reference's meta + metrics")
    p_show.add_argument("ref_id", help="stored <ref_id>")
    p_show.add_argument("--store-dir", type=Path, default=DEFAULT_STORE_DIR)

    args = parser.parse_args(argv)

    if args.cmd == "ingest":
        return _cmd_ingest(args)
    if args.cmd == "consolidate":
        return _cmd_consolidate(args)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "show":
        return _cmd_show(args)
    parser.error(f"unknown command {args.cmd!r}")
    return 2


def _cmd_ingest(args: argparse.Namespace) -> int:
    try:
        out = run_ingest(
            args.url,
            likes=args.likes,
            views=args.views,
            store_dir=args.store_dir,
            force=args.force,
        )
    except AlreadyIngestedError as exc:
        print(str(exc), file=sys.stderr)
        return 0
    except ReferenceDownloadError as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 1

    print(f"ingested → {out}")
    return 0


def _cmd_consolidate(args: argparse.Namespace) -> int:
    try:
        out = run_consolidate(
            store_dir=args.store_dir,
            references_md_path=args.references_md,
            model=args.model,
            dry_run=args.dry_run,
        )
    except ConsolidationValidationError as exc:
        print(f"LLM output rejected: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"dry-run complete (would write {out})")
    else:
        print(f"consolidated → {out}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    store_dir = Path(args.store_dir)
    if not store_dir.exists():
        print(f"(empty — no {store_dir})")
        return 0
    for p in sorted(store_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            meta = data.get("meta", {})
            metrics = data.get("metrics", {})
            print(
                f"{data.get('ref_id', p.stem):12s}  "
                f"{metrics.get('n_cuts', 0):4d} cuts  "
                f"{meta.get('views', 0):>10d} views  "
                f"{meta.get('title', '')[:60]}"
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{p.name}: unreadable ({exc})", file=sys.stderr)
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    store_dir = Path(args.store_dir)
    path = store_dir / f"{args.ref_id}.json"
    if not path.exists():
        print(f"no reference at {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    slim = {
        "ref_id": data.get("ref_id"),
        "meta": data.get("meta", {}),
        "metrics": data.get("metrics", {}),
    }
    print(json.dumps(slim, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
