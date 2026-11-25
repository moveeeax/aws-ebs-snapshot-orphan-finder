from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

# Fixed clock so the ages in examples/ stay deterministic.
NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def examples_dir() -> pathlib.Path:
    return EXAMPLES


@pytest.fixture
def now() -> datetime:
    return NOW
