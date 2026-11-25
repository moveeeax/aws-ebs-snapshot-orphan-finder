from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aws_ebs_snapshot_orphan_finder.analyze import analyze, parse_time, total_cost
from aws_ebs_snapshot_orphan_finder.loader import Inventory, load_files


@pytest.fixture
def inv(examples_dir) -> Inventory:
    return load_files([str(examples_dir)])


def by_id(findings):
    return {f.snapshot_id: f for f in findings}


def test_snapshot_without_volume_or_ami_is_orphaned(inv, now):
    found = by_id(analyze(inv, now=now))
    assert "orphaned" in found["snap-0abandoned2019"].reasons
    assert found["snap-0abandoned2019"].status == "orphaned"
    assert found["snap-0abandoned2019"].referenced_by == []


def test_ami_backed_snapshot_is_not_orphaned_even_without_its_volume(inv, now):
    found = by_id(analyze(inv, now=now))
    snap = found.get("snap-0amibacked")
    # Its source volume vol-0alsogone is absent from volumes.json, yet an AMI
    # block device mapping points at it, so it must never be called orphaned.
    assert snap is not None, "expected a stale finding for the AMI-backed snapshot"
    assert "orphaned" not in snap.reasons
    assert snap.status == "ami-backed"
    assert snap.referenced_by == ["ami:ami-0golden"]


def test_live_volume_snapshot_is_volume_backed_and_clean(inv, now):
    found = by_id(analyze(inv, max_age_days=90, now=now))
    assert "snap-0livevolume" not in found


def test_public_snapshot_always_reported_despite_filters(inv, now):
    findings = analyze(inv, only=["orphaned"], min_size_gb=4096, now=now)
    found = by_id(findings)
    assert "snap-0publicoops" in found
    snap = found["snap-0publicoops"]
    assert snap.public is True
    assert "public" in snap.reasons


def test_only_filter_restricts_other_checks(inv, now):
    findings = analyze(inv, only=["orphaned"], now=now)
    for finding in findings:
        assert set(finding.reasons) <= {"orphaned", "public"}


def test_min_size_filter_drops_small_findings(inv, now):
    small = by_id(analyze(inv, now=now))
    assert "snap-0tinyold" in small
    large = by_id(analyze(inv, min_size_gb=10, now=now))
    assert "snap-0tinyold" not in large


def test_stale_depends_on_max_age_days(inv, now):
    fresh = by_id(analyze(inv, only=["stale"], max_age_days=90, now=now))
    assert "snap-0abandoned2019" in fresh
    patient = by_id(analyze(inv, only=["stale"], max_age_days=10_000, now=now))
    # Nothing is stale against a 10000-day limit; the public snapshot survives
    # the filter on purpose, because public is never suppressed.
    assert set(patient) == {"snap-0publicoops"}


def test_total_cost_is_size_times_price(inv, now):
    findings = analyze(inv, price_per_gb_month=0.05, now=now)
    expected = sum(f.size_gb for f in findings) * 0.05
    assert total_cost(findings) == pytest.approx(expected)
    assert total_cost(findings) == pytest.approx(
        sum(f.monthly_cost_usd for f in findings)
    )


def test_price_override_scales_the_estimate(inv, now):
    cheap = total_cost(analyze(inv, price_per_gb_month=0.05, now=now))
    pricey = total_cost(analyze(inv, price_per_gb_month=0.10, now=now))
    assert pricey == pytest.approx(cheap * 2)


def test_age_days_uses_the_injected_clock(inv, now):
    found = by_id(analyze(inv, now=now))
    assert found["snap-0abandoned2019"].age_days == 2794


def test_findings_sorted_by_cost_descending(inv, now):
    costs = [f.monthly_cost_usd for f in analyze(inv, now=now)]
    assert costs == sorted(costs, reverse=True)


@pytest.mark.parametrize(
    "raw",
    ["2026-01-02T03:04:05.000Z", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05"],
)
def test_parse_time_accepts_aws_shapes(raw):
    assert parse_time(raw) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw", ["", None, "not-a-date", 42])
def test_parse_time_rejects_junk(raw):
    assert parse_time(raw) is None


def test_missing_start_time_yields_unknown_age(now):
    inv = Inventory(snapshots=[{"SnapshotId": "snap-x", "VolumeSize": 10}])
    finding = analyze(inv, now=now)[0]
    assert finding.age_days is None
    assert "stale" not in finding.reasons
