"""Tests for the GitHub read-only repository tools."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from src.tools.github_tools import (
    MAX_COMMENT_CHARS,
    MAX_FILE_CHARS,
    MAX_ISSUE_BODY_CHARS,
    MAX_PATCH_CHARS,
    _parse_repo,
    github_get_commit,
    github_get_issue,
    github_get_repo,
    github_list_commits,
    github_list_directory,
    github_list_issues,
    github_read_file,
    github_search_code,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _configure_token(monkeypatch) -> None:
    """Ensure the GitHub token is set for most tests."""
    monkeypatch.setattr("src.config.settings.github_token", "ghp_test123")


@pytest.fixture()
def github_mock():
    """Patch _get_github and return (gh_client, repo_mock)."""
    with patch("src.tools.github_tools._get_github") as mock_get:
        gh = MagicMock()
        repo = MagicMock()
        gh.get_repo.return_value = repo
        mock_get.return_value = gh
        yield gh, repo


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_content_file(
    name: str = "README.md",
    path: str = "README.md",
    file_type: str = "file",
    size: int = 1024,
    content: bytes = b"Hello world",
    sha: str = "abc123",
) -> MagicMock:
    f = MagicMock()
    f.name = name
    f.path = path
    f.type = file_type
    f.size = size
    f.sha = sha
    f.decoded_content = content
    return f


def _make_commit(
    sha: str = "abc1234567890",
    message: str = "fix: some bug",
    author_name: str = "TestUser",
    date: datetime | None = None,
    html_url: str = "https://github.com/owner/repo/commit/abc1234567890",
    files: list | None = None,
    additions: int = 10,
    deletions: int = 5,
    total: int = 15,
) -> MagicMock:
    c = MagicMock()
    c.sha = sha
    c.html_url = html_url
    c.commit.message = message
    c.commit.author.name = author_name
    c.commit.author.date = date or datetime(2026, 1, 15, 12, 0, 0)
    c.stats.additions = additions
    c.stats.deletions = deletions
    c.stats.total = total
    c.files = files or []
    return c


def _make_issue(
    number: int = 1,
    title: str = "Test issue",
    state: str = "open",
    is_pr: bool = False,
    author: str = "testuser",
    labels: list[str] | None = None,
    body: str = "Issue body",
    comments_count: int = 0,
    html_url: str = "https://github.com/owner/repo/issues/1",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.state = state
    issue.pull_request = MagicMock() if is_pr else None
    issue.user.login = author
    issue.body = body
    issue.comments = comments_count
    issue.html_url = html_url
    issue.created_at = created_at or datetime(2026, 1, 10, 8, 0, 0)
    issue.updated_at = updated_at or datetime(2026, 1, 11, 9, 0, 0)

    label_mocks = []
    for lbl_name in labels or []:
        lbl = MagicMock()
        lbl.name = lbl_name
        label_mocks.append(lbl)
    issue.labels = label_mocks

    return issue


def _make_comment(
    author: str = "commenter",
    body: str = "Nice work!",
    created_at: datetime | None = None,
) -> MagicMock:
    c = MagicMock()
    c.user.login = author
    c.body = body
    c.created_at = created_at or datetime(2026, 1, 12, 10, 0, 0)
    return c


# ---------------------------------------------------------------------------
# TestParseRepo
# ---------------------------------------------------------------------------


class TestParseRepo:
    def test_valid_format(self) -> None:
        assert _parse_repo("owner/repo") == "owner/repo"

    def test_no_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid repo format"):
            _parse_repo("just-a-name")

    def test_empty_parts(self) -> None:
        with pytest.raises(ValueError, match="Invalid repo format"):
            _parse_repo("/repo")


# ---------------------------------------------------------------------------
# TestGetRepo
# ---------------------------------------------------------------------------


class TestGetRepo:
    async def test_success(self, github_mock) -> None:
        gh, repo = github_mock
        repo.full_name = "owner/repo"
        repo.description = "A test repo"
        repo.language = "Python"
        repo.default_branch = "main"
        repo.stargazers_count = 42
        repo.forks_count = 7
        repo.open_issues_count = 3
        repo.private = False
        repo.html_url = "https://github.com/owner/repo"
        repo.created_at = datetime(2025, 1, 1)
        repo.updated_at = datetime(2026, 1, 1)

        result = await github_get_repo(repo="owner/repo")
        assert result.success
        assert result.data["full_name"] == "owner/repo"
        assert result.data["stars"] == 42
        assert result.data["language"] == "Python"

    async def test_not_found(self, github_mock) -> None:
        gh, _ = github_mock
        gh.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)

        result = await github_get_repo(repo="owner/nonexistent")
        assert not result.success
        assert "Not Found" in result.error

    async def test_invalid_format(self, github_mock) -> None:
        result = await github_get_repo(repo="bad-format")
        assert not result.success
        assert "Invalid repo format" in result.error


# ---------------------------------------------------------------------------
# TestListDirectory
# ---------------------------------------------------------------------------


class TestListDirectory:
    async def test_root_listing(self, github_mock) -> None:
        _, repo = github_mock
        files = [
            _make_content_file(name="README.md", path="README.md"),
            _make_content_file(name="src", path="src", file_type="dir", size=0),
        ]
        repo.get_contents.return_value = files

        result = await github_list_directory(repo="owner/repo")
        assert result.success
        assert result.data["count"] == 2
        assert result.data["entries"][0]["name"] == "README.md"
        assert result.data["entries"][1]["type"] == "dir"

    async def test_subdirectory(self, github_mock) -> None:
        _, repo = github_mock
        files = [_make_content_file(name="main.py", path="src/main.py")]
        repo.get_contents.return_value = files

        result = await github_list_directory(repo="owner/repo", path="src")
        assert result.success
        assert result.data["entries"][0]["path"] == "src/main.py"

    async def test_with_ref(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_contents.return_value = []

        result = await github_list_directory(repo="owner/repo", path="", ref="dev")
        assert result.success
        repo.get_contents.assert_called_with(path="", ref="dev")

    async def test_single_file_path(self, github_mock) -> None:
        """get_contents returns a single item (not list) for file paths."""
        _, repo = github_mock
        repo.get_contents.return_value = _make_content_file(name="file.txt", path="file.txt")

        result = await github_list_directory(repo="owner/repo", path="file.txt")
        assert result.success
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# TestReadFile
# ---------------------------------------------------------------------------


class TestReadFile:
    async def test_success(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_contents.return_value = _make_content_file(content=b"print('hello')", size=14)

        result = await github_read_file(repo="owner/repo", path="main.py")
        assert result.success
        assert result.data["content"] == "print('hello')"
        assert result.data["name"] == "README.md"

    async def test_directory_path_error(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_contents.return_value = [
            _make_content_file(),
            _make_content_file(name="other.py"),
        ]

        result = await github_read_file(repo="owner/repo", path="src")
        assert not result.success
        assert "directory" in result.error.lower()

    async def test_not_found(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"}, None)

        result = await github_read_file(repo="owner/repo", path="missing.py")
        assert not result.success
        assert "Not Found" in result.error

    async def test_with_ref(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_contents.return_value = _make_content_file(content=b"v2 code")

        result = await github_read_file(repo="owner/repo", path="file.py", ref="v2")
        assert result.success
        repo.get_contents.assert_called_with(path="file.py", ref="v2")

    async def test_large_file_truncation(self, github_mock) -> None:
        _, repo = github_mock
        big_content = ("x" * (MAX_FILE_CHARS + 500)).encode()
        repo.get_contents.return_value = _make_content_file(content=big_content)

        result = await github_read_file(repo="owner/repo", path="big.txt")
        assert result.success
        assert result.data["content"].endswith("[Content truncated]")
        # Content before truncation marker should be exactly MAX_FILE_CHARS
        assert len(result.data["content"]) == MAX_FILE_CHARS + len(" [Content truncated]")


# ---------------------------------------------------------------------------
# TestSearchCode
# ---------------------------------------------------------------------------


class TestSearchCode:
    async def test_success(self, github_mock) -> None:
        gh, _ = github_mock
        item = MagicMock()
        item.name = "client.py"
        item.path = "src/llm/client.py"
        item.repository.full_name = "owner/repo"
        item.sha = "def456"
        item.html_url = "https://github.com/owner/repo/blob/main/src/llm/client.py"
        gh.search_code.return_value = [item]

        result = await github_search_code(query="generate_response")
        assert result.success
        assert result.data["count"] == 1
        assert result.data["results"][0]["path"] == "src/llm/client.py"

    async def test_scoped_to_repo(self, github_mock) -> None:
        gh, _ = github_mock
        gh.search_code.return_value = []

        result = await github_search_code(query="import asyncio", repo="owner/repo")
        assert result.success
        # Verify the query was scoped
        call_query = gh.search_code.call_args[0][0]
        assert "repo:owner/repo" in call_query

    async def test_empty_results(self, github_mock) -> None:
        gh, _ = github_mock
        gh.search_code.return_value = []

        result = await github_search_code(query="nonexistent_symbol_xyz")
        assert result.success
        assert result.data["count"] == 0

    async def test_unscoped(self, github_mock) -> None:
        gh, _ = github_mock
        gh.search_code.return_value = []

        result = await github_search_code(query="some query")
        assert result.success
        call_query = gh.search_code.call_args[0][0]
        assert "repo:" not in call_query


# ---------------------------------------------------------------------------
# TestListCommits
# ---------------------------------------------------------------------------


class TestListCommits:
    async def test_success(self, github_mock) -> None:
        _, repo = github_mock
        commits = [_make_commit(), _make_commit(sha="def9876543210", message="feat: add thing")]
        repo.get_commits.return_value = commits

        result = await github_list_commits(repo="owner/repo")
        assert result.success
        assert result.data["count"] == 2
        assert result.data["commits"][0]["short_sha"] == "abc1234"

    async def test_path_filter(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_commits.return_value = [_make_commit()]

        result = await github_list_commits(repo="owner/repo", path="src/main.py")
        assert result.success
        repo.get_commits.assert_called_with(path="src/main.py")

    async def test_sha_filter(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_commits.return_value = [_make_commit()]

        result = await github_list_commits(repo="owner/repo", sha="dev")
        assert result.success
        repo.get_commits.assert_called_with(sha="dev")

    async def test_empty(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_commits.return_value = []

        result = await github_list_commits(repo="owner/repo")
        assert result.success
        assert result.data["count"] == 0


# ---------------------------------------------------------------------------
# TestGetCommit
# ---------------------------------------------------------------------------


class TestGetCommit:
    async def test_success_with_files(self, github_mock) -> None:
        _, repo = github_mock
        file_mock = MagicMock()
        file_mock.filename = "src/main.py"
        file_mock.status = "modified"
        file_mock.additions = 5
        file_mock.deletions = 2
        file_mock.patch = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new"

        commit = _make_commit(files=[file_mock])
        repo.get_commit.return_value = commit

        result = await github_get_commit(repo="owner/repo", sha="abc123")
        assert result.success
        assert result.data["sha"] == "abc1234567890"
        assert len(result.data["files"]) == 1
        assert result.data["files"][0]["filename"] == "src/main.py"
        assert result.data["stats"]["total"] == 15

    async def test_patch_truncation(self, github_mock) -> None:
        _, repo = github_mock
        file_mock = MagicMock()
        file_mock.filename = "big.py"
        file_mock.status = "modified"
        file_mock.additions = 100
        file_mock.deletions = 0
        file_mock.patch = "x" * (MAX_PATCH_CHARS + 500)

        commit = _make_commit(files=[file_mock])
        repo.get_commit.return_value = commit

        result = await github_get_commit(repo="owner/repo", sha="abc123")
        assert result.success
        assert result.data["files"][0]["patch"].endswith("[Patch truncated]")

    async def test_not_found(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_commit.side_effect = GithubException(404, {"message": "No commit found"}, None)

        result = await github_get_commit(repo="owner/repo", sha="deadbeef")
        assert not result.success
        assert "No commit found" in result.error


# ---------------------------------------------------------------------------
# TestListIssues
# ---------------------------------------------------------------------------


class TestListIssues:
    async def test_success(self, github_mock) -> None:
        _, repo = github_mock
        issues = [
            _make_issue(number=1, title="Bug report", labels=["bug"]),
            _make_issue(number=2, title="Feature request", is_pr=True),
        ]
        repo.get_issues.return_value = issues

        result = await github_list_issues(repo="owner/repo")
        assert result.success
        assert result.data["count"] == 2
        assert result.data["issues"][0]["labels"] == ["bug"]
        assert result.data["issues"][1]["is_pull_request"] is True

    async def test_state_filter(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_issues.return_value = []

        result = await github_list_issues(repo="owner/repo", state="closed")
        assert result.success
        repo.get_issues.assert_called_with(state="closed")

    async def test_labels_filter(self, github_mock) -> None:
        _, repo = github_mock
        label_mock = MagicMock()
        label_mock.name = "bug"
        repo.get_label.return_value = label_mock
        repo.get_issues.return_value = []

        result = await github_list_issues(repo="owner/repo", labels="bug")
        assert result.success
        repo.get_label.assert_called_with("bug")

    async def test_empty(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_issues.return_value = []

        result = await github_list_issues(repo="owner/repo")
        assert result.success
        assert result.data["count"] == 0


# ---------------------------------------------------------------------------
# TestGetIssue
# ---------------------------------------------------------------------------


class TestGetIssue:
    async def test_issue_with_comments(self, github_mock) -> None:
        _, repo = github_mock
        issue = _make_issue(number=42, body="Detailed description")
        comments = [_make_comment(), _make_comment(author="reviewer", body="LGTM")]
        issue.get_comments.return_value = comments
        repo.get_issue.return_value = issue

        result = await github_get_issue(repo="owner/repo", number=42)
        assert result.success
        assert result.data["number"] == 42
        assert result.data["body"] == "Detailed description"
        assert len(result.data["comments"]) == 2

    async def test_pr_fields(self, github_mock) -> None:
        _, repo = github_mock
        issue = _make_issue(number=10, is_pr=True)
        issue.get_comments.return_value = []
        repo.get_issue.return_value = issue

        pr_mock = MagicMock()
        pr_mock.merged = True
        pr_mock.base.ref = "main"
        pr_mock.head.ref = "feature-branch"
        pr_mock.additions = 50
        pr_mock.deletions = 10
        pr_mock.changed_files = 3
        repo.get_pull.return_value = pr_mock

        result = await github_get_issue(repo="owner/repo", number=10)
        assert result.success
        assert result.data["is_pull_request"] is True
        assert result.data["merged"] is True
        assert result.data["additions"] == 50
        assert result.data["changed_files"] == 3

    async def test_comment_truncation(self, github_mock) -> None:
        _, repo = github_mock
        issue = _make_issue(number=1)
        long_comment = _make_comment(body="x" * (MAX_COMMENT_CHARS + 500))
        issue.get_comments.return_value = [long_comment]
        repo.get_issue.return_value = issue

        result = await github_get_issue(repo="owner/repo", number=1)
        assert result.success
        assert result.data["comments"][0]["body"].endswith("[Comment truncated]")

    async def test_not_found(self, github_mock) -> None:
        _, repo = github_mock
        repo.get_issue.side_effect = GithubException(404, {"message": "Not Found"}, None)

        result = await github_get_issue(repo="owner/repo", number=999)
        assert not result.success
        assert "Not Found" in result.error

    async def test_body_truncation(self, github_mock) -> None:
        _, repo = github_mock
        issue = _make_issue(number=1, body="x" * (MAX_ISSUE_BODY_CHARS + 500))
        issue.get_comments.return_value = []
        repo.get_issue.return_value = issue

        result = await github_get_issue(repo="owner/repo", number=1)
        assert result.success
        assert result.data["body"].endswith("[Body truncated]")


# ---------------------------------------------------------------------------
# TestTokenNotConfigured
# ---------------------------------------------------------------------------


class TestTokenNotConfigured:
    async def test_error_when_token_missing(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.settings.github_token", "")
        # Reset cached client so _get_github() re-checks token
        with patch("src.tools.github_tools._github_client", None):
            result = await github_get_repo(repo="owner/repo")
        assert not result.success
        assert "not configured" in result.error
