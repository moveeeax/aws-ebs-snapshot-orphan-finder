"""Command line entry point.

Exit codes: 0 clean, 1 findings, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__, render
from .analyze import CHECKS, DEFAULT_PRICE_PER_GB_MONTH, analyze
from .loader import LoadError, load_files, load_live

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aws-ebs-snapshot-orphan-finder",
        description=(
            "Find EBS snapshots nothing references any more (source volume gone, no AMI), "
            "plus public, unencrypted and stale ones, with the monthly cost of keeping them."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--from-files",
        metavar="PATHS",
        help=(
            "comma-separated describe-snapshots/describe-volumes/describe-images JSON dumps, "
            "or a directory of them; dumps are recognised by their top-level key, in any order"
        ),
    )
    parser.add_argument("--region", help="AWS region for live mode and cleanup commands")
    parser.add_argument(
        "--owner", default="self", help="owner id for live describe-snapshots/describe-images"
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=90,
        help="snapshots older than this are reported as stale",
    )
    parser.add_argument(
        "--min-size-gb", type=int, default=0, help="ignore findings smaller than this (public never)"
    )
    parser.add_argument(
        "--only",
        metavar="CHECKS",
        help=f"comma-separated subset of checks to report: {','.join(CHECKS)}",
    )
    parser.add_argument(
        "--price-per-gb-month",
        type=float,
        default=DEFAULT_PRICE_PER_GB_MONTH,
        help="snapshot storage price used for the cost estimate (USD)",
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument(
        "--print-cleanup",
        action="store_true",
        help="emit only aws ec2 delete-snapshot lines for unreferenced snapshots",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.json and args.print_cleanup:
        print("error: --json and --print-cleanup are mutually exclusive", file=sys.stderr)
        return EXIT_USAGE
    if args.max_age_days < 0 or args.min_size_gb < 0 or args.price_per_gb_month < 0:
        print("error: --max-age-days, --min-size-gb and --price-per-gb-month must be >= 0",
              file=sys.stderr)
        return EXIT_USAGE

    only = None
    if args.only:
        only = [c.strip() for c in args.only.split(",") if c.strip()]
        unknown = [c for c in only if c not in CHECKS]
        if unknown:
            print(
                f"error: unknown check(s) {','.join(unknown)}; known: {','.join(CHECKS)}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    try:
        inv = load_files([args.from_files]) if args.from_files else load_live(args.region, args.owner)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    findings = analyze(
        inv,
        max_age_days=args.max_age_days,
        min_size_gb=args.min_size_gb,
        only=only,
        price_per_gb_month=args.price_per_gb_month,
    )

    if args.print_cleanup:
        lines = render.cleanup(findings, region=args.region)
        if lines:
            print(lines)
    elif args.json:
        print(render.as_json(findings))
    else:
        print(render.table(findings, snapshots_scanned=len(inv.snapshots)))

    return EXIT_FINDINGS if findings else EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
