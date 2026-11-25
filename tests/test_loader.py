from __future__ import annotations

import json

import pytest

from aws_ebs_snapshot_orphan_finder.analyze import is_public
from aws_ebs_snapshot_orphan_finder.loader import LoadError, load_files


def test_dumps_are_recognised_in_any_order(examples_dir):
    forward = load_files(
        [f"{examples_dir}/snapshots.json,{examples_dir}/volumes.json,{examples_dir}/images.json"]
    )
    backward = load_files(
        [f"{examples_dir}/images.json,{examples_dir}/volumes.json,{examples_dir}/snapshots.json"]
    )
    assert len(forward.snapshots) == len(backward.snapshots) == 5
    assert len(forward.volumes) == len(backward.volumes) == 2
    assert len(forward.images) == len(backward.images) == 1


def test_directory_loads_every_json_file(examples_dir):
    inv = load_files([str(examples_dir)])
    assert len(inv.snapshots) == 5
    assert inv.permissions == {"snap-0publicoops": [{"Group": "all"}]}


def test_attribute_dump_is_merged_onto_the_snapshot(examples_dir):
    inv = load_files([str(examples_dir)])
    snap = next(s for s in inv.snapshots if s["SnapshotId"] == "snap-0publicoops")
    assert is_public(snap)


def test_missing_file_is_a_load_error(tmp_path):
    with pytest.raises(LoadError, match="no such file"):
        load_files([str(tmp_path / "nope.json")])


def test_invalid_json_is_a_load_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoadError, match="invalid JSON"):
        load_files([str(bad)])


def test_unrecognised_shape_is_a_load_error(tmp_path):
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"Buckets": []}), encoding="utf-8")
    with pytest.raises(LoadError, match="no Snapshots"):
        load_files([str(odd)])


def test_empty_selection_is_a_load_error():
    with pytest.raises(LoadError, match="matched no JSON files"):
        load_files([" , "])


def test_dumps_without_snapshots_are_rejected(tmp_path):
    only_volumes = tmp_path / "volumes.json"
    only_volumes.write_text(json.dumps({"Volumes": []}), encoding="utf-8")
    with pytest.raises(LoadError, match="no snapshots found"):
        load_files([str(only_volumes)])


def test_paginated_dump_arrays_are_concatenated(tmp_path):
    page = tmp_path / "pages.json"
    page.write_text(
        json.dumps(
            [
                {"Snapshots": [{"SnapshotId": "snap-a", "VolumeSize": 1}]},
                {"Snapshots": [{"SnapshotId": "snap-b", "VolumeSize": 2}]},
            ]
        ),
        encoding="utf-8",
    )
    inv = load_files([str(page)])
    assert [s["SnapshotId"] for s in inv.snapshots] == ["snap-a", "snap-b"]
