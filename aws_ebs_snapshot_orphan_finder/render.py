"""Output modes: table, JSON, and a cleanup command list."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from .analyze import Finding, total_cost

HEADERS = ("SNAPSHOT", "SIZE", "AGE", "STATUS", "FLAGS", "USD/MO", "REFERENCED BY", "DESCRIPTION")


def _row(f: Finding) -> tuple[str, ...]:
    flags = ",".join(r for r in f.reasons if r != "orphaned") or "-"
    age = "-" if f.age_days is None else f"{f.age_days}d"
    return (
        f.snapshot_id,
        f"{f.size_gb}G",
        age,
        f.status,
        flags,
        f"{f.monthly_cost_usd:.2f}",
        ",".join(f.referenced_by) or "-",
        f.description[:44],
    )


def table(findings: Sequence[Finding], *, snapshots_scanned: int) -> str:
    if not findings:
        return f"No findings. {snapshots_scanned} snapshot(s) scanned, all referenced and clean."

    rows = [HEADERS] + [_row(f) for f in findings]
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEADERS))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]

    orphans = sum(1 for f in findings if f.status == "orphaned")
    public = sum(1 for f in findings if f.public)
    lines.append("")
    lines.append(
        f"{len(findings)} finding(s) of {snapshots_scanned} snapshot(s): "
        f"{orphans} orphaned, {public} public."
    )
    lines.append(f"Estimated waste: {total_cost(findings):.2f} USD/month.")
    return "\n".join(lines)


def as_json(findings: Iterable[Finding]) -> str:
    return json.dumps([f.to_dict() for f in findings], indent=2, sort_keys=True)


def cleanup(findings: Iterable[Finding], *, region: str | None = None) -> str:
    """Only `aws ec2 delete-snapshot` lines, and only for unreferenced snapshots.

    Anything still referenced by a volume or an AMI is deliberately left out:
    deleting an AMI-backed snapshot silently breaks the AMI.
    """
    region_arg = f" --region {region}" if region else ""
    return "\n".join(
        f"aws ec2 delete-snapshot --snapshot-id {f.snapshot_id}{region_arg}"
        for f in findings
        if not f.referenced_by
    )
