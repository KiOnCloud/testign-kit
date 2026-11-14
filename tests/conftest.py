import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from make_repo import make_repo  # noqa: E402


@pytest.fixture
def demo_repo(tmp_path):
    return make_repo(tmp_path)
