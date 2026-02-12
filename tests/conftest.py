"""Shared test fixtures."""

import pytest

from src.scratch import ScratchSpace


@pytest.fixture
def scratch(tmp_path):
    """Create a ScratchSpace rooted in a temporary directory."""
    ScratchSpace._reset()
    s = ScratchSpace(root=tmp_path / "scratch")
    ScratchSpace._instance = s
    yield s
    ScratchSpace._reset()


@pytest.fixture(autouse=False)
def _no_turso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests use local file, not remote Turso."""
    monkeypatch.setattr("src.config.settings.turso_database_url", "")
