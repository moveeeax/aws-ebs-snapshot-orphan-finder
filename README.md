# aws-ebs-snapshot-orphan-finder

[![ci](https://github.com/moveeeax/aws-ebs-snapshot-orphan-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/moveeeax/aws-ebs-snapshot-orphan-finder/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Finds the EBS snapshots nothing points at any more — source volume deleted, no AMI
referencing them — plus the ones that are public, unencrypted or ancient, and prices
the whole pile per month.

`describe-snapshots --owner-ids self` gives you 4000 rows and no column that separates
a snapshot backing a live AMI from a 500 GiB copy of a machine that was decommissioned in
2019. This reads snapshots, volumes and images, builds the reference graph, and prints only
what is actually unaccounted for.

## How it works

1. Load the three inventories: `describe-snapshots`, `describe-volumes`, `describe-images`.
   Either live through boto3, or from saved JSON with `--from-files`. Dumps are recognised by
   their top-level key (`Snapshots` / `Volumes` / `Images`), so order does not matter and you
   can pass a directory.
2. Build references per snapshot: `snapshot -> source VolumeId` (does the volume still exist?)
   and `AMI BlockDeviceMappings[].Ebs.SnapshotId` (does an image depend on it?).
3. Classify: `orphaned` (no reference at all), `public` (`createVolumePermission` contains
   `all`), `unencrypted`, `stale` (older than `--max-age-days`). Referenced snapshots are
   labelled `ami-backed` or `volume-backed` and never called orphaned.
4. Cost = `VolumeSize * --price-per-gb-month` (default `0.05` USD, us-east-1 standard),
   summed over everything reported.
5. Exit `1` when there are findings, `0` when clean, `2` on bad input — usable as a cron or
   CI gate.

Nothing is ever deleted. `--print-cleanup` emits the `aws ec2 delete-snapshot` commands for
unreferenced snapshots only, for a human to read before running.

## Install

```bash
pip install git+https://github.com/moveeeax/aws-ebs-snapshot-orphan-finder

# live mode against a real account also needs boto3
pip install 'aws-ebs-snapshot-orphan-finder[aws] @ git+https://github.com/moveeeax/aws-ebs-snapshot-orphan-finder'
```

## Usage

Offline, from the dumps in `examples/`:

```console
$ aws-ebs-snapshot-orphan-finder --from-files examples/ --max-age-days 90
SNAPSHOT             SIZE  AGE    STATUS         FLAGS                     USD/MO  REFERENCED BY            DESCRIPTION
snap-0abandoned2019  500G  2794d  orphaned       unencrypted,stale         25.00   -                        pre-migration copy of the old monolith disk
snap-0amibacked      100G  1924d  ami-backed     stale                     5.00    ami:ami-0golden          Created by CreateImage(i-05f2) for ami-0gold
snap-0publicoops     8G    662d   volume-backed  public,unencrypted,stale  0.40    volume:vol-0staginghost  shared with a contractor, never unshared
snap-0tinyold        1G    2515d  orphaned       stale                     0.05    -                        1 GiB test volume from a 2020 experiment

4 finding(s) of 5 snapshot(s): 2 orphaned, 1 public.
Estimated waste: 30.45 USD/month.
```

Live account, only the unaccounted ones, as JSON:

```bash
aws-ebs-snapshot-orphan-finder --region eu-central-1 --only orphaned --json
```

Your own dumps, then a reviewable delete list:

```bash
aws ec2 describe-snapshots --owner-ids self > dumps/snapshots.json
aws ec2 describe-volumes                   > dumps/volumes.json
aws ec2 describe-images --owners self      > dumps/images.json

aws-ebs-snapshot-orphan-finder --from-files dumps/ --min-size-gb 50
aws-ebs-snapshot-orphan-finder --from-files dumps/ --print-cleanup --region eu-central-1
```

### Flags

| Flag | Meaning |
| --- | --- |
| `--from-files PATHS` | comma-separated JSON dumps or a directory; offline mode |
| `--region` | region for live mode, and for the emitted cleanup commands |
| `--owner` | owner id for live `describe-snapshots` / `describe-images` (default `self`) |
| `--max-age-days` | stale threshold, default `90` |
| `--min-size-gb` | drop findings below this size (public snapshots are never dropped) |
| `--only` | subset of `orphaned,public,unencrypted,stale` |
| `--price-per-gb-month` | storage price for the estimate, default `0.05` |
| `--json` | one JSON object per finding |
| `--print-cleanup` | only `aws ec2 delete-snapshot` lines, unreferenced snapshots only |

## Public snapshots are never filtered out

A snapshot with `createVolumePermission` set to `all` is a readable disk image of your data
for anyone on AWS. It is reported even when `--only orphaned` or `--min-size-gb 4096` would
otherwise hide it — the 8 GiB one in the example above is still attached to a live volume and
still shows up.

## CI gate

```yaml
- name: EBS snapshot hygiene
  run: |
    aws ec2 describe-snapshots --owner-ids self > snapshots.json
    aws ec2 describe-volumes                    > volumes.json
    aws ec2 describe-images --owners self       > images.json
    aws-ebs-snapshot-orphan-finder --from-files snapshots.json,volumes.json,images.json \
      --only public --max-age-days 365
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Tests run entirely over the JSON fixtures in `examples/`; no AWS credentials are needed.

## License

MIT
