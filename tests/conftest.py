from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from genai_review.model import Review, load

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def loaded() -> Review:
    return load(REPO_ROOT / "data")


@pytest.fixture
def review(loaded: Review) -> Review:
    """A private copy of the loaded review that a test may change in memory."""
    return copy.deepcopy(loaded)


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A writable copy of data/, fixes/, evidence/ and the report, for tests that break the data on purpose."""
    root = tmp_path / "repo"
    for name in ("data", "fixes", "evidence"):
        shutil.copytree(REPO_ROOT / name, root / name, ignore=shutil.ignore_patterns(".terraform*"))
    shutil.copytree(REPO_ROOT / "report", root / "report", ignore=shutil.ignore_patterns("*.pdf"))
    return root
