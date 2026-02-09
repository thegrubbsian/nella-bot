"""Tests for settings parsing."""

from src.config import Settings


def test_parse_allowed_user_ids() -> None:
    """Should parse comma-separated IDs into a set of ints."""
    s = Settings(allowed_user_ids="111,222,333")
    assert s.get_allowed_user_ids() == {111, 222, 333}


def test_parse_allowed_user_ids_with_spaces() -> None:
    """Should handle whitespace in the ID list."""
    s = Settings(allowed_user_ids=" 111 , 222 , 333 ")
    assert s.get_allowed_user_ids() == {111, 222, 333}


def test_parse_allowed_user_ids_empty() -> None:
    """Empty string should return empty set."""
    s = Settings(allowed_user_ids="")
    assert s.get_allowed_user_ids() == set()


def test_parse_allowed_user_ids_single() -> None:
    """Single ID without commas should work."""
    s = Settings(allowed_user_ids="12345")
    assert s.get_allowed_user_ids() == {12345}
