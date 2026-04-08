import pytest
from pathlib import Path


@pytest.fixture
def tmp_work_dir(tmp_path: Path) -> Path:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    return work_dir
