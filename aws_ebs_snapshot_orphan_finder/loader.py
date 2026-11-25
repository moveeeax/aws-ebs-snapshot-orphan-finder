"""Load snapshot/volume/image inventories from JSON dumps or a live account.

Dump files are identified by their top-level key, not by filename or argument
order, so ``--from-files a.json,b.json`` works in any order and a directory can
be passed instead of a list.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable


class LoadError(Exception):
    """A dump file is missing, unreadable, or not a recognised AWS shape."""


@dataclass
class Inventory:
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    volumes: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    # SnapshotId -> createVolumePermission list, from describe-snapshot-attribute
    permissions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def merge_permissions(self) -> None:
        """Fold standalone attribute dumps onto the snapshot objects."""
        for snap in self.snapshots:
            extra = self.permissions.get(snap.get("SnapshotId", ""))
            if extra:
                merged = list(snap.get("CreateVolumePermissions") or [])
                merged.extend(extra)
                snap["CreateVolumePermissions"] = merged


def _expand(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in paths:
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            if os.path.isdir(part):
                for name in sorted(os.listdir(part)):
                    if name.endswith(".json"):
                        out.append(os.path.join(part, name))
            else:
                out.append(part)
    return out


def _absorb(inv: Inventory, doc: Any, where: str) -> bool:
    """Absorb one JSON document. Returns True if anything was recognised."""
    if isinstance(doc, list):
        # Absorb every page, so do not let any() short-circuit on the first hit.
        return any([_absorb(inv, item, where) for item in doc])
    if not isinstance(doc, dict):
        raise LoadError(f"{where}: expected a JSON object or array, got {type(doc).__name__}")

    known = False
    if isinstance(doc.get("Snapshots"), list):
        inv.snapshots.extend(doc["Snapshots"])
        known = True
    if isinstance(doc.get("Volumes"), list):
        inv.volumes.extend(doc["Volumes"])
        known = True
    if isinstance(doc.get("Images"), list):
        inv.images.extend(doc["Images"])
        known = True
    # describe-snapshot-attribute --attribute createVolumePermission
    perms = doc.get("CreateVolumePermissions")
    if isinstance(perms, list) and doc.get("SnapshotId"):
        inv.permissions.setdefault(doc["SnapshotId"], []).extend(perms)
        known = True
    # describe-stack-style single resources, e.g. a lone snapshot object
    if not known and doc.get("SnapshotId") and "VolumeSize" in doc:
        inv.snapshots.append(doc)
        known = True
    return known


def load_files(paths: Iterable[str]) -> Inventory:
    files = _expand(paths)
    if not files:
        raise LoadError("--from-files matched no JSON files")

    inv = Inventory()
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except FileNotFoundError as exc:
            raise LoadError(f"{path}: no such file") from exc
        except json.JSONDecodeError as exc:
            raise LoadError(f"{path}: invalid JSON ({exc})") from exc
        if not _absorb(inv, doc, path):
            raise LoadError(
                f"{path}: no Snapshots/Volumes/Images/CreateVolumePermissions key found"
            )

    if not inv.snapshots:
        raise LoadError("no snapshots found in the supplied dumps")
    inv.merge_permissions()
    return inv


def load_live(region: str | None, owner: str = "self") -> Inventory:
    """Read the three inventories from the AWS API. Requires boto3."""
    try:
        import boto3  # noqa: PLC0415 - optional dependency, only needed live
    except ImportError as exc:  # pragma: no cover - exercised only without boto3
        raise LoadError(
            "live mode needs boto3: pip install 'aws-ebs-snapshot-orphan-finder[aws]'"
        ) from exc

    ec2 = boto3.client("ec2", region_name=region)
    inv = Inventory()
    for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=[owner]):
        inv.snapshots.extend(page.get("Snapshots", []))
    for page in ec2.get_paginator("describe_volumes").paginate():
        inv.volumes.extend(page.get("Volumes", []))
    for page in ec2.get_paginator("describe_images").paginate(Owners=[owner]):
        inv.images.extend(page.get("Images", []))

    for snap in inv.snapshots:
        attr = ec2.describe_snapshot_attribute(
            SnapshotId=snap["SnapshotId"], Attribute="createVolumePermission"
        )
        snap["CreateVolumePermissions"] = attr.get("CreateVolumePermissions", [])
    return inv
