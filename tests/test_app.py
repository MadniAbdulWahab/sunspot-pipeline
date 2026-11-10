"""Smoke test: every page renders without an exception on a real (fixture) archived run."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from conftest import FIXED_NOW, RECENT, FakeFetcher

from sunspot_pipeline.config import Paths
from sunspot_pipeline.pipeline import run

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parent.parent
PAGES = ["app/pages/overview.py", "app/pages/quality.py", "app/pages/explorer.py", "app/pages/runs.py"]


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    run(Paths(root=tmp_path), fetcher=FakeFetcher(RECENT), now=FIXED_NOW)
    monkeypatch.setenv("SUNSPOT_HOME", str(tmp_path))
    import app.data

    importlib.reload(app.data)  # PATHS is read at import time
    yield tmp_path
    monkeypatch.delenv("SUNSPOT_HOME")
    importlib.reload(app.data)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(app_home, page):
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    if page != PAGES[0]:
        at.switch_page(page)
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.title) == 1
