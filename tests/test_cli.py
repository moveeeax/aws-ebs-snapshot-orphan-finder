from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from aws_ebs_snapshot_orphan_finder.cli import EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, main


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_findings_exit_one_and_print_a_table(capsys, examples_dir):
    code, out, _ = run(capsys, "--from-files", str(examples_dir))
    assert code == EXIT_FINDINGS
    assert "SNAPSHOT" in out
    assert "snap-0abandoned2019" in out
    assert "USD/month" in out


def test_clean_account_exits_zero(capsys, tmp_path):
    dump = tmp_path / "snapshots.json"
    dump.write_text(
        json.dumps(
            {
                "Snapshots": [
                    {
                        "SnapshotId": "snap-ok",
                        "VolumeId": "vol-live",
                        "VolumeSize": 20,
                        "StartTime": (
                            datetime.now(timezone.utc) - timedelta(days=1)
                        ).isoformat(),
                        "Encrypted": True,
                    }
                ],
                "Volumes": [{"VolumeId": "vol-live"}],
            }
        ),
        encoding="utf-8",
    )
    code, out, _ = run(capsys, "--from-files", str(dump))
    assert code == EXIT_CLEAN
    assert "No findings" in out


def test_json_output_is_valid_and_one_object_per_finding(capsys, examples_dir):
    code, out, _ = run(capsys, "--from-files", str(examples_dir), "--json")
    assert code == EXIT_FINDINGS
    payload = json.loads(out)
    assert isinstance(payload, list) and payload
    for item in payload:
        assert {"snapshot_id", "status", "reasons", "monthly_cost_usd"} <= set(item)


def test_print_cleanup_emits_only_delete_snapshot_lines(capsys, examples_dir):
    code, out, _ = run(
        capsys, "--from-files", str(examples_dir), "--print-cleanup", "--region", "eu-central-1"
    )
    assert code == EXIT_FINDINGS
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert line.startswith("aws ec2 delete-snapshot --snapshot-id ")
        assert line.endswith("--region eu-central-1")
    assert not any("snap-0amibacked" in line for line in lines)
    assert not any("snap-0livevolume" in line for line in lines)


def test_json_and_cleanup_together_is_a_usage_error(capsys, examples_dir):
    code, _, err = run(capsys, "--from-files", str(examples_dir), "--json", "--print-cleanup")
    assert code == EXIT_USAGE
    assert "mutually exclusive" in err


def test_unknown_check_is_a_usage_error(capsys, examples_dir):
    code, _, err = run(capsys, "--from-files", str(examples_dir), "--only", "orphaned,banana")
    assert code == EXIT_USAGE
    assert "banana" in err


def test_negative_numbers_are_a_usage_error(capsys, examples_dir):
    code, _, err = run(capsys, "--from-files", str(examples_dir), "--max-age-days", "-1")
    assert code == EXIT_USAGE
    assert ">= 0" in err


def test_missing_dump_is_a_usage_error(capsys, tmp_path):
    code, _, err = run(capsys, "--from-files", str(tmp_path / "ghost.json"))
    assert code == EXIT_USAGE
    assert "no such file" in err


@pytest.mark.parametrize(
    "flag",
    [
        "--from-files",
        "--region",
        "--owner",
        "--max-age-days",
        "--min-size-gb",
        "--only",
        "--price-per-gb-month",
        "--json",
        "--print-cleanup",
        "--version",
    ],
)
def test_help_documents_every_flag(capsys, flag):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert flag in out
