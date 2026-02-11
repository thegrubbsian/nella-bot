"""Tests for ScratchSpace — sandboxed local filesystem."""

import os
import time

import pytest

from src.scratch import DEFAULT_CLEANUP_HOURS, MAX_FILE_SIZE, ScratchSpace


@pytest.fixture()
def scratch(tmp_path):
    """Create a ScratchSpace rooted in a temporary directory."""
    ScratchSpace.reset()
    s = ScratchSpace(root=tmp_path / "scratch")
    yield s
    ScratchSpace.reset()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_root_dir_created_on_construction(tmp_path) -> None:
    root = tmp_path / "new_scratch"
    assert not root.exists()
    ScratchSpace(root=root)
    assert root.is_dir()


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def test_sanitize_basic_chars() -> None:
    assert ScratchSpace.sanitize_filename("hello.txt") == "hello.txt"
    assert ScratchSpace.sanitize_filename("my-file_01.md") == "my-file_01.md"


def test_sanitize_special_chars_replaced() -> None:
    assert ScratchSpace.sanitize_filename("hello world!.txt") == "hello_world_.txt"
    assert ScratchSpace.sanitize_filename("a@b#c$d") == "a_b_c_d"


def test_sanitize_leading_dots_stripped() -> None:
    assert ScratchSpace.sanitize_filename(".hidden") == "hidden"
    assert ScratchSpace.sanitize_filename("...dots") == "dots"


def test_sanitize_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty after sanitization"):
        ScratchSpace.sanitize_filename("")

    with pytest.raises(ValueError, match="empty after sanitization"):
        ScratchSpace.sanitize_filename("...")


def test_sanitize_path_separators_replaced() -> None:
    # Path separators within a single component get replaced
    assert ScratchSpace.sanitize_filename("foo\\bar") == "foo_bar"


def test_sanitize_truncation() -> None:
    long_name = "a" * 300 + ".txt"
    result = ScratchSpace.sanitize_filename(long_name)
    assert len(result) <= 255


# ---------------------------------------------------------------------------
# Read / Write
# ---------------------------------------------------------------------------


def test_text_round_trip(scratch) -> None:
    scratch.write("hello.txt", "Hello, world!")
    assert scratch.read("hello.txt") == "Hello, world!"


def test_bytes_round_trip(scratch) -> None:
    data = b"\x00\x01\x02\xff"
    scratch.write("binary.bin", data)
    assert scratch.read_bytes("binary.bin") == data


def test_subdirectory_creation(scratch) -> None:
    scratch.write("sub/dir/file.txt", "nested")
    assert scratch.read("sub/dir/file.txt") == "nested"


def test_overwrite_existing(scratch) -> None:
    scratch.write("file.txt", "version 1")
    scratch.write("file.txt", "version 2")
    assert scratch.read("file.txt") == "version 2"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_read_nonexistent_raises(scratch) -> None:
    with pytest.raises(FileNotFoundError, match="File not found"):
        scratch.read("nope.txt")


def test_read_binary_raises_value_error(scratch) -> None:
    scratch.write("binary.bin", b"\x80\x81\x82\x83")
    with pytest.raises(ValueError, match="binary"):
        scratch.read("binary.bin")


def test_read_bytes_nonexistent_raises(scratch) -> None:
    with pytest.raises(FileNotFoundError, match="File not found"):
        scratch.read_bytes("nope.bin")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_existing(scratch) -> None:
    scratch.write("delete_me.txt", "bye")
    assert scratch.delete("delete_me.txt") is True
    assert not scratch.exists("delete_me.txt")


def test_delete_nonexistent(scratch) -> None:
    assert scratch.delete("nope.txt") is False


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_empty_scratch(scratch) -> None:
    assert scratch.list_files() == []


def test_list_files_metadata(scratch) -> None:
    scratch.write("a.txt", "aaa")
    scratch.write("b.txt", "bbbbb")
    files = scratch.list_files()
    assert len(files) == 2
    names = {f["name"] for f in files}
    assert names == {"a.txt", "b.txt"}
    for f in files:
        assert "size" in f
        assert "modified_iso" in f
        assert "age_hours" in f


def test_list_files_nested_paths(scratch) -> None:
    scratch.write("sub/nested.txt", "deep")
    files = scratch.list_files()
    assert len(files) == 1
    # Should be a relative path using OS separator
    assert "nested.txt" in files[0]["name"]


# ---------------------------------------------------------------------------
# total_size / exists
# ---------------------------------------------------------------------------


def test_total_size(scratch) -> None:
    assert scratch.total_size() == 0
    scratch.write("a.txt", "12345")
    assert scratch.total_size() == 5
    scratch.write("b.txt", "67890")
    assert scratch.total_size() == 10


def test_exists(scratch) -> None:
    assert scratch.exists("nope.txt") is False
    scratch.write("here.txt", "present")
    assert scratch.exists("here.txt") is True


# ---------------------------------------------------------------------------
# Traversal prevention
# ---------------------------------------------------------------------------


def test_traversal_dotdot(scratch) -> None:
    with pytest.raises(ValueError, match="empty after sanitization"):
        scratch.resolve("../etc/passwd")


def test_traversal_nested(scratch) -> None:
    with pytest.raises(ValueError, match="empty after sanitization"):
        scratch.resolve("foo/../../etc/passwd")


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------


def test_per_file_size_limit(scratch) -> None:
    big_data = "x" * (MAX_FILE_SIZE + 1)
    with pytest.raises(ValueError, match="File too large"):
        scratch.write("big.txt", big_data)


def test_total_quota_exceeded(scratch, monkeypatch) -> None:
    # Temporarily lower the quota for testing
    monkeypatch.setattr("src.scratch.MAX_TOTAL_SIZE", 100)
    scratch.write("a.txt", "x" * 50)
    with pytest.raises(ValueError, match="quota exceeded"):
        scratch.write("b.txt", "x" * 60)


def test_overwrite_does_not_double_count_quota(scratch, monkeypatch) -> None:
    """Overwriting an existing file should not count the old size toward quota."""
    monkeypatch.setattr("src.scratch.MAX_TOTAL_SIZE", 100)
    scratch.write("a.txt", "x" * 80)
    # This should succeed because the old 80 bytes are subtracted
    scratch.write("a.txt", "y" * 90)
    assert scratch.read("a.txt") == "y" * 90


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_old_files_removed(scratch) -> None:
    path = scratch.write("old.txt", "stale")
    # Set mtime to 4 days ago
    old_time = time.time() - (4 * 24 * 3600)
    os.utime(path, (old_time, old_time))

    removed = scratch.cleanup(max_age_hours=DEFAULT_CLEANUP_HOURS)
    assert removed == 1
    assert not scratch.exists("old.txt")


def test_cleanup_recent_files_preserved(scratch) -> None:
    scratch.write("fresh.txt", "new")
    removed = scratch.cleanup(max_age_hours=DEFAULT_CLEANUP_HOURS)
    assert removed == 0
    assert scratch.exists("fresh.txt")


def test_cleanup_empty_subdirs_removed(scratch) -> None:
    path = scratch.write("sub/old.txt", "stale")
    old_time = time.time() - (4 * 24 * 3600)
    os.utime(path, (old_time, old_time))

    scratch.cleanup(max_age_hours=DEFAULT_CLEANUP_HOURS)
    # The file and its now-empty parent dir should both be gone
    assert not path.exists()
    assert not path.parent.exists()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_singleton_get_and_reset(tmp_path) -> None:
    ScratchSpace.reset()
    try:
        # Patch settings so get() uses our tmp_path
        s1 = ScratchSpace(root=tmp_path / "single")
        ScratchSpace._instance = s1
        assert ScratchSpace.get() is s1

        ScratchSpace.reset()
        assert ScratchSpace._instance is None
    finally:
        ScratchSpace.reset()
