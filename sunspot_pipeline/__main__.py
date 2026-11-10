"""Command line: python -m sunspot_pipeline {run,list,verify}."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .archive import list_archived_runs, verify_run
from .config import Paths
from .ingest import directory_fetcher
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sunspot_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="fetch, validate, process, reconcile and archive")
    p_run.add_argument("--force", action="store_true", help="archive a new run even if inputs are unchanged")
    p_run.add_argument(
        "--from-dir", type=Path, help="read the three CSVs from a local folder instead of SILSO"
    )

    sub.add_parser("list", help="list archived runs")

    p_verify = sub.add_parser("verify", help="re-hash archived files against their manifest")
    p_verify.add_argument("run_id", nargs="?", help="defaults to the latest run")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = Paths.default()

    if args.command == "run":
        fetcher = directory_fetcher(args.from_dir) if args.from_dir else None
        result = run(paths, fetcher=fetcher, force=args.force)
        summary = {
            k: result.record.get(k)
            for k in (
                "run_id",
                "status",
                "archive_path",
                "quality_status",
                "reconciliation_passed",
                "error",
                "previous_run_id",
            )
        }
        print(json.dumps({k: v for k, v in summary.items() if v is not None}, indent=2))
        return 1 if result.status == "failed" else 0

    runs = list_archived_runs(paths)
    if args.command == "list":
        for m in runs:
            print(
                f"{m['run_id']}  v{m['pipeline_version']}  "
                f"quality={m['quality_status']}  reconciled={m['reconciliation_passed']}"
            )
        return 0

    if not runs:
        print("no archived runs", file=sys.stderr)
        return 1
    manifest = next((m for m in runs if m["run_id"] == args.run_id), None) if args.run_id else runs[0]
    if manifest is None:
        print(f"run {args.run_id} not found", file=sys.stderr)
        return 1
    results = verify_run(paths, manifest)
    for r in results:
        print(f"{'OK ' if r['ok'] else 'BAD'} {r['file']}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
