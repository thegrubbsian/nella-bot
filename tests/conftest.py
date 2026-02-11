"""Shared test fixtures."""

import pytest

from src.scratch import ScratchSpace


@pytest.fixture
def scratch(tmp_path):
    """Create a ScratchSpace rooted in a temporary directory."""
    ScratchSpace.reset()
    s = ScratchSpace(root=tmp_path / "scratch")
    ScratchSpace._instance = s
    yield s
    ScratchSpace.reset()
