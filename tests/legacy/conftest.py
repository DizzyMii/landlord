"""Conftest for legacy tests. Makes the tmp_work_dir fixture available here too."""
from tests.conftest import tmp_work_dir  # re-export

__all__ = ["tmp_work_dir"]
