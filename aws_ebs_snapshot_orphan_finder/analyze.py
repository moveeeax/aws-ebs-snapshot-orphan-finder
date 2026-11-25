"""Reference graph and classification.

A snapshot is orphaned when nothing real points at it: its source volume is gone
from the volumes dump *and* no AMI block device mapping references it. Everything
else is a warning about the snapshot itself (public, unencrypted, stale).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .loader import Inventory

CHECKS = ("orphaned", "public", "unencrypted", "stale")
DEFAULT_PRICE_PER_GB_MONTH = 0.05


def parse_time(value: Any) -> datetime | None:
    """Parse an AWS timestamp. Naive values are read as UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Finding:
    snapshot_id: str
    volume_id: str
    size_gb: int
    age_days: int | None
    encrypted: bool
    public: bool
    reasons: list[str] = field(default_factory=list)
    referenced_by: list[str] = field(default_factory=list)
    description: str = ""
    monthly_cost_usd: float = 0.0

    @property
    def status(self) -> str:
        if "orphaned" in self.reasons:
            return "orphaned"
        if any(ref.startswith("ami:") for ref in self.referenced_by):
            return "ami-backed"
        if any(ref.startswith("volume:") for ref in self.referenced_by):
            return "volume-backed"
        return "unreferenced"

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "volume_id": self.volume_id,
            "size_gb": self.size_gb,
            "age_days": self.age_days,
            "encrypted": self.encrypted,
            "public": self.public,
            "status": self.status,
            "reasons": list(self.reasons),
            "referenced_by": list(self.referenced_by),
            "description": self.description,
            "monthly_cost_usd": round(self.monthly_cost_usd, 4),
        }


def _ami_references(images: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for image in images:
        image_id = image.get("ImageId") or "?"
        for mapping in image.get("BlockDeviceMappings") or []:
            snapshot_id = (mapping.get("Ebs") or {}).get("SnapshotId")
            if snapshot_id:
                refs.setdefault(snapshot_id, []).append(f"ami:{image_id}")
    return refs


def is_public(snapshot: dict[str, Any]) -> bool:
    for entry in snapshot.get("CreateVolumePermissions") or []:
        if isinstance(entry, dict) and entry.get("Group") == "all":
            return True
    return bool(snapshot.get("Public"))


def analyze(
    inv: Inventory,
    *,
    max_age_days: int = 90,
    min_size_gb: int = 0,
    only: Iterable[str] | None = None,
    price_per_gb_month: float = DEFAULT_PRICE_PER_GB_MONTH,
    now: datetime | None = None,
) -> list[Finding]:
    now = now or datetime.now(timezone.utc)
    wanted = set(only) if only else set(CHECKS)
    live_volumes = {v.get("VolumeId") for v in inv.volumes if v.get("VolumeId")}
    ami_refs = _ami_references(inv.images)

    findings: list[Finding] = []
    for snapshot in inv.snapshots:
        snapshot_id = snapshot.get("SnapshotId")
        if not snapshot_id:
            continue
        size_gb = int(snapshot.get("VolumeSize") or 0)
        volume_id = snapshot.get("VolumeId") or ""
        started = parse_time(snapshot.get("StartTime"))
        age_days = (now - started).days if started else None
        public = is_public(snapshot)
        encrypted = bool(snapshot.get("Encrypted"))

        referenced_by = list(ami_refs.get(snapshot_id, []))
        if volume_id and volume_id in live_volumes:
            referenced_by.append(f"volume:{volume_id}")

        reasons: list[str] = []
        if not referenced_by:
            reasons.append("orphaned")
        if public:
            reasons.append("public")
        if not encrypted:
            reasons.append("unencrypted")
        if age_days is not None and age_days > max_age_days:
            reasons.append("stale")

        # A public snapshot is always reported: it is a readable disk image of
        # production data, so no size or check filter may hide it.
        selected = [r for r in reasons if r in wanted]
        if public:
            if "public" not in selected:
                selected.insert(0, "public")
        elif not selected or size_gb < min_size_gb:
            continue

        findings.append(
            Finding(
                snapshot_id=snapshot_id,
                volume_id=volume_id,
                size_gb=size_gb,
                age_days=age_days,
                encrypted=encrypted,
                public=public,
                reasons=selected,
                referenced_by=referenced_by,
                description=(snapshot.get("Description") or "").strip(),
                monthly_cost_usd=size_gb * price_per_gb_month,
            )
        )

    findings.sort(key=lambda f: (-f.monthly_cost_usd, f.snapshot_id))
    return findings


def total_cost(findings: Iterable[Finding]) -> float:
    return sum(f.monthly_cost_usd for f in findings)
