from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def example_candidates_root(project_root: Path) -> Path:
    return project_root / "candidates"


@pytest.fixture
def copied_candidates_root(tmp_path: Path, example_candidates_root: Path) -> Path:
    root = tmp_path / "candidates"
    shutil.copytree(example_candidates_root, root)
    return root


def rewrite_json(path: Path, update: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    update(data)
    path.write_text(json.dumps(data), encoding="utf-8")
