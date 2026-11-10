from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sunspot_pipeline.config import Paths, Source
from sunspot_pipeline.ingest import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"
HISTORIC = FIXTURES / "silso_1823_1825"  # contains Feb 1824, the one month without daily data
RECENT = FIXTURES / "silso_recent"  # 2024 to the latest month, ends in provisional values

FIXED_NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(root=tmp_path)


def read_lines(folder: Path, filename: str) -> list[str]:
    return (folder / filename).read_text(encoding="ascii").splitlines()


def to_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("ascii")


class FakeFetcher:
    """Serves files from a fixture folder, as if downloaded from SILSO. Counts calls."""

    def __init__(self, folder: Path, overrides: dict[str, bytes] | None = None):
        self.folder = folder
        self.overrides = overrides or {}
        self.calls = 0

    def __call__(self, source: Source) -> FetchResult:
        self.calls += 1
        content = self.overrides.get(source.key) or (self.folder / source.filename).read_bytes()
        return FetchResult(
            content=content,
            retrieved_from=source.url,
            http_status=200,
            headers={"etag": '"fixture"', "last-modified": "Sun, 01 Nov 2026 09:45:08 GMT"},
        )
