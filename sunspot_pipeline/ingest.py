"""Download the raw SILSO files, hash them and keep an immutable snapshot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import requests

from . import __version__
from .config import Paths, Source


@dataclass
class FetchResult:
    content: bytes
    retrieved_from: str
    http_status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)


Fetcher = Callable[[Source], FetchResult]


@dataclass
class FetchedFile:
    source: Source
    content: bytes
    fetched_at: str
    retrieved_from: str
    http_status: int | None
    etag: str | None
    last_modified: str | None

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.content)

    def manifest_entry(self) -> dict:
        return {
            "key": self.source.key,
            "url": self.source.url,
            "retrieved_from": self.retrieved_from,
            "filename": self.source.filename,
            "fetched_at": self.fetched_at,
            "sha256": self.sha256,
            "bytes": len(self.content),
            "http_status": self.http_status,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_fetcher(timeout: float = 60.0) -> Fetcher:
    """Fetch from the official SILSO URL."""

    session = requests.Session()
    session.headers["User-Agent"] = f"sunspot-pipeline/{__version__} (python-requests)"

    def fetch(source: Source) -> FetchResult:
        resp = session.get(source.url, timeout=timeout)
        resp.raise_for_status()
        return FetchResult(
            content=resp.content,
            retrieved_from=source.url,
            http_status=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
        )

    return fetch


def directory_fetcher(directory: Path) -> Fetcher:
    """Read the files from a local folder instead (offline runs and tests)."""

    directory = Path(directory)

    def fetch(source: Source) -> FetchResult:
        path = directory / source.filename
        return FetchResult(content=path.read_bytes(), retrieved_from=path.resolve().as_uri())

    return fetch


def fetch_all(sources: Iterable[Source], fetcher: Fetcher) -> list[FetchedFile]:
    files = []
    for source in sources:
        result = fetcher(source)
        files.append(
            FetchedFile(
                source=source,
                content=result.content,
                fetched_at=isoformat(utc_now()),
                retrieved_from=result.retrieved_from,
                http_status=result.http_status,
                etag=result.headers.get("etag"),
                last_modified=result.headers.get("last-modified"),
            )
        )
    return files


def input_fingerprint(files: Iterable[FetchedFile]) -> str:
    """One hash for the whole input set, independent of fetch order."""

    lines = sorted(f"{f.source.key}:{f.sha256}" for f in files)
    return sha256_bytes("\n".join(lines).encode())


def make_run_id(started: datetime, fingerprint: str) -> str:
    return f"{started.astimezone(UTC):%Y%m%dT%H%M%SZ}-{fingerprint[:8]}"


def save_raw_snapshot(paths: Paths, run_id: str, files: Iterable[FetchedFile]) -> Path:
    """Write the raw bytes exactly as downloaded. Refuses to reuse a folder."""

    target = paths.raw / run_id
    target.mkdir(parents=True, exist_ok=False)
    for f in files:
        dest = target / f.source.filename
        with dest.open("xb") as fh:
            fh.write(f.content)
        if sha256_file(dest) != f.sha256:
            raise OSError(f"checksum mismatch after writing {dest}")
    return target


def find_completed_run(paths: Paths, version: str, fingerprint: str) -> dict | None:
    """Latest completed run for this pipeline version and exactly these inputs, if any."""

    if not paths.runs.exists():
        return None
    matches = []
    for record_path in paths.runs.glob("*.json"):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if (
            record.get("status") == "completed"
            and record.get("pipeline_version") == version
            and record.get("input_fingerprint") == fingerprint
            and record.get("archive_path")
            and (paths.root / record["archive_path"]).is_dir()
        ):
            matches.append(record)
    return max(matches, key=lambda r: r["started_at"]) if matches else None
