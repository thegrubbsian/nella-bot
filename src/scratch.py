"""ScratchSpace — sandboxed local filesystem for temporary working files."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.config import settings

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file
MAX_TOTAL_SIZE = 500 * 1024 * 1024  # 500 MB total
DEFAULT_CLEANUP_HOURS = 72  # 3 days

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._\-]")


class ScratchSpace:
    """Sandboxed local filesystem for temporary working files.

    Singleton accessed via ``ScratchSpace.get()``.  Pass an explicit *root*
    for test isolation (e.g. ``tmp_path / "scratch"``).

    All methods are synchronous — local file I/O is fast enough that
    wrapping in ``asyncio.to_thread()`` isn't worth the complexity.
    """

    _instance: ScratchSpace | None = None

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or settings.scratch_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get(cls) -> ScratchSpace:
        """Return the shared ScratchSpace instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Clear the singleton (for tests)."""
        cls._instance = None

    # -- Path helpers ----------------------------------------------------------

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Replace unsafe characters, strip leading dots, truncate to 255 chars.

        Raises ``ValueError`` if the result is empty.
        """
        sanitized = _SAFE_FILENAME_RE.sub("_", name)
        sanitized = sanitized.lstrip(".")
        sanitized = sanitized[:255]
        if not sanitized:
            msg = f"Filename is empty after sanitization: {name!r}"
            raise ValueError(msg)
        return sanitized

    def resolve(self, name: str) -> Path:
        """Resolve a relative path to an absolute path inside the scratch root.

        Splits on ``/``, sanitizes each component, and verifies the resolved
        path is inside ``self._root`` (prevents directory traversal).
        """
        parts = name.split("/")
        sanitized_parts = [self.sanitize_filename(p) for p in parts if p]
        if not sanitized_parts:
            msg = f"Path resolves to empty after sanitization: {name!r}"
            raise ValueError(msg)
        target = self._root.joinpath(*sanitized_parts).resolve()
        # Traversal check: resolved path must be inside root
        if not str(target).startswith(str(self._root)):
            msg = f"Path traversal detected: {name!r}"
            raise ValueError(msg)
        return target

    # -- File operations -------------------------------------------------------

    def write(self, name: str, content: str | bytes) -> Path:
        """Write content to a file in the scratch space.

        Creates subdirectories as needed. Enforces per-file and total size limits.
        Returns the absolute path of the written file.
        """
        data = content.encode("utf-8") if isinstance(content, str) else content
        if len(data) > MAX_FILE_SIZE:
            msg = f"File too large: {len(data)} bytes (max {MAX_FILE_SIZE})"
            raise ValueError(msg)

        # Check total quota (excluding the target file if it already exists)
        target = self.resolve(name)
        existing_size = target.stat().st_size if target.exists() else 0
        new_total = self.total_size() - existing_size + len(data)
        if new_total > MAX_TOTAL_SIZE:
            msg = f"Total scratch space quota exceeded: {new_total} bytes (max {MAX_TOTAL_SIZE})"
            raise ValueError(msg)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def read(self, name: str) -> str:
        """Read a text file from the scratch space.

        Raises ``FileNotFoundError`` if the file doesn't exist, or
        ``ValueError`` if the file contains binary data.
        """
        target = self.resolve(name)
        if not target.exists():
            msg = f"File not found: {name}"
            raise FileNotFoundError(msg)
        try:
            return target.read_text("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"File is binary (not UTF-8 text): {name}"
            raise ValueError(msg) from exc

    def read_bytes(self, name: str) -> bytes:
        """Read raw bytes from a file in the scratch space."""
        target = self.resolve(name)
        if not target.exists():
            msg = f"File not found: {name}"
            raise FileNotFoundError(msg)
        return target.read_bytes()

    def delete(self, name: str) -> bool:
        """Delete a file. Returns True if deleted, False if not found."""
        target = self.resolve(name)
        if not target.exists():
            return False
        target.unlink()
        return True

    def exists(self, name: str) -> bool:
        """Check if a file exists in the scratch space."""
        target = self.resolve(name)
        return target.exists()

    def list_files(self) -> list[dict]:
        """List all files in the scratch space.

        Returns a list of dicts with keys: name, size, modified_iso, age_hours.
        """
        now = datetime.now(UTC)
        files = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            age_hours = (now - mtime).total_seconds() / 3600
            relative = str(path.relative_to(self._root))
            files.append(
                {
                    "name": relative,
                    "size": stat.st_size,
                    "modified_iso": mtime.isoformat(),
                    "age_hours": round(age_hours, 1),
                }
            )
        return files

    def total_size(self) -> int:
        """Sum of all file sizes in the scratch space."""
        return sum(p.stat().st_size for p in self._root.rglob("*") if p.is_file())

    def cleanup(self, max_age_hours: float = DEFAULT_CLEANUP_HOURS) -> int:
        """Remove files older than *max_age_hours* and empty subdirectories.

        Returns the number of files removed.
        """
        now = datetime.now(UTC)
        removed = 0
        for path in list(self._root.rglob("*")):
            if not path.is_file():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            age_hours = (now - mtime).total_seconds() / 3600
            if age_hours > max_age_hours:
                path.unlink()
                removed += 1
                logger.debug("Scratch cleanup: removed %s (%.1fh old)", path.name, age_hours)

        # Remove empty subdirectories (bottom-up)
        for path in sorted(self._root.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
                logger.debug("Scratch cleanup: removed empty dir %s", path)

        return removed

    def wipe(self) -> int:
        """Remove all files and subdirectories. Returns the number of files removed."""
        return self.cleanup(max_age_hours=0)
