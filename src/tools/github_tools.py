"""GitHub tools — read-only repository exploration and code search."""

import asyncio
import logging

from github import Github, GithubException
from pydantic import Field

from src.config import settings
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_FILE_CHARS = 100_000
MAX_PATCH_CHARS = 5_000
MAX_ISSUE_BODY_CHARS = 10_000
MAX_COMMENT_CHARS = 2_000
MAX_COMMENTS = 20

_github_client: Github | None = None


def _get_github() -> Github:
    """Lazily create and cache a PyGithub client."""
    global _github_client  # noqa: PLW0603
    if _github_client is None:
        token = settings.github_token
        if not token:
            msg = "GITHUB_TOKEN is not configured."
            raise ValueError(msg)
        _github_client = Github(token)
    return _github_client


def _parse_repo(repo: str) -> str:
    """Validate 'owner/repo' format and return it."""
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = f"Invalid repo format '{repo}'. Expected 'owner/repo'."
        raise ValueError(msg)
    return repo


def _github_error_message(exc: GithubException) -> str:
    """Extract a human-readable message from a GithubException."""
    if exc.data and isinstance(exc.data, dict):
        return exc.data.get("message", str(exc))
    return str(exc)


def _author_date_iso(commit_author) -> str:  # noqa: ANN001
    """Safely extract an ISO date string from a commit author."""
    if commit_author and commit_author.date:
        return commit_author.date.isoformat()
    return ""


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------


class GetRepoParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")


class ListDirectoryParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    path: str = Field(default="", description="Directory path (empty for root)")
    ref: str | None = Field(default=None, description="Branch, tag, or commit SHA")


class ReadFileParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    path: str = Field(description="File path within the repository")
    ref: str | None = Field(default=None, description="Branch, tag, or commit SHA")


class SearchCodeParams(ToolParams):
    query: str = Field(description="Code search query (GitHub search syntax)")
    repo: str | None = Field(default=None, description="Scope search to this repo ('owner/repo')")
    max_results: int = Field(
        default=10, description="Maximum results to return (1-30)", ge=1, le=30
    )


class ListCommitsParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    sha: str | None = Field(
        default=None, description="Branch name or commit SHA to start listing from"
    )
    path: str | None = Field(default=None, description="Only commits touching this file path")
    max_results: int = Field(
        default=10, description="Maximum commits to return (1-30)", ge=1, le=30
    )


class GetCommitParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    sha: str = Field(description="Full or short commit SHA")


class ListIssuesParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    state: str = Field(default="open", description="Filter by state: 'open', 'closed', or 'all'")
    labels: str | None = Field(default=None, description="Comma-separated label names to filter by")
    max_results: int = Field(default=10, description="Maximum issues to return (1-30)", ge=1, le=30)


class GetIssueParams(ToolParams):
    repo: str = Field(description="Repository in 'owner/repo' format")
    number: int = Field(description="Issue or pull request number")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@registry.tool(
    name="github_get_repo",
    description=(
        "Get metadata about a GitHub repository: description, language, stars, "
        "forks, open issues, default branch, and timestamps."
    ),
    category="github",
    params_model=GetRepoParams,
)
async def github_get_repo(repo: str) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)
        return ToolResult(
            data={
                "full_name": r.full_name,
                "description": r.description or "",
                "language": r.language or "",
                "default_branch": r.default_branch,
                "stars": r.stargazers_count,
                "forks": r.forks_count,
                "open_issues": r.open_issues_count,
                "private": r.private,
                "url": r.html_url,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_list_directory",
    description=(
        "List files and directories at a given path in a GitHub repo. "
        "Returns name, type (file/dir), size, and path for each entry."
    ),
    category="github",
    params_model=ListDirectoryParams,
)
async def github_list_directory(repo: str, path: str = "", ref: str | None = None) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)

        kwargs: dict = {"path": path}
        if ref:
            kwargs["ref"] = ref
        contents = await asyncio.to_thread(r.get_contents, **kwargs)

        # get_contents returns a single item for files, list for directories
        if not isinstance(contents, list):
            contents = [contents]

        entries = [
            {
                "name": c.name,
                "type": "dir" if c.type == "dir" else "file",
                "size": c.size,
                "path": c.path,
            }
            for c in contents
        ]
        return ToolResult(data={"entries": entries, "count": len(entries)})
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_read_file",
    description=(
        "Read the contents of a file from a GitHub repository. Returns the file "
        "content as UTF-8 text, truncated at 100K characters for large files."
    ),
    category="github",
    params_model=ReadFileParams,
)
async def github_read_file(repo: str, path: str, ref: str | None = None) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)

        kwargs: dict = {"path": path}
        if ref:
            kwargs["ref"] = ref
        content_file = await asyncio.to_thread(r.get_contents, **kwargs)

        if isinstance(content_file, list):
            return ToolResult(
                error=f"Path '{path}' is a directory. Use github_list_directory instead."
            )

        decoded = await asyncio.to_thread(content_file.decoded_content.decode, "utf-8")
        truncated = False
        if len(decoded) > MAX_FILE_CHARS:
            decoded = decoded[:MAX_FILE_CHARS]
            truncated = True

        return ToolResult(
            data={
                "path": content_file.path,
                "name": content_file.name,
                "size": content_file.size,
                "sha": content_file.sha,
                "content": decoded + (" [Content truncated]" if truncated else ""),
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_search_code",
    description=(
        "Search for code across GitHub repositories using GitHub's code search syntax. "
        "Optionally scope to a specific repo. Returns file names, paths, and repos."
    ),
    category="github",
    params_model=SearchCodeParams,
)
async def github_search_code(
    query: str, repo: str | None = None, max_results: int = 10
) -> ToolResult:
    try:
        gh = _get_github()
        search_query = query
        if repo:
            _parse_repo(repo)
            search_query = f"{query} repo:{repo}"

        results_page = await asyncio.to_thread(gh.search_code, search_query)

        results = []
        for item in results_page[:max_results]:
            results.append(
                {
                    "name": item.name,
                    "path": item.path,
                    "repo": item.repository.full_name,
                    "sha": item.sha,
                    "url": item.html_url,
                }
            )

        return ToolResult(data={"results": results, "count": len(results)})
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_list_commits",
    description=(
        "List recent commits in a GitHub repository. Optionally filter by branch/SHA "
        "or file path. Returns commit SHA, message, author, date, and URL."
    ),
    category="github",
    params_model=ListCommitsParams,
)
async def github_list_commits(
    repo: str,
    sha: str | None = None,
    path: str | None = None,
    max_results: int = 10,
) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)

        kwargs: dict = {}
        if sha:
            kwargs["sha"] = sha
        if path:
            kwargs["path"] = path

        commits_page = await asyncio.to_thread(r.get_commits, **kwargs)

        commits = []
        for c in commits_page[:max_results]:
            commits.append(
                {
                    "sha": c.sha,
                    "short_sha": c.sha[:7],
                    "message": c.commit.message,
                    "author": c.commit.author.name if c.commit.author else "",
                    "date": _author_date_iso(c.commit.author),
                    "url": c.html_url,
                }
            )

        return ToolResult(data={"commits": commits, "count": len(commits)})
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_get_commit",
    description=(
        "Get detailed information about a specific commit: message, author, stats, "
        "and changed files with patches (truncated at 5K chars per file)."
    ),
    category="github",
    params_model=GetCommitParams,
)
async def github_get_commit(repo: str, sha: str) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)
        c = await asyncio.to_thread(r.get_commit, sha)

        files = []
        for f in c.files or []:
            patch = f.patch or ""
            if len(patch) > MAX_PATCH_CHARS:
                patch = patch[:MAX_PATCH_CHARS] + " [Patch truncated]"
            files.append(
                {
                    "filename": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch": patch,
                }
            )

        return ToolResult(
            data={
                "sha": c.sha,
                "message": c.commit.message,
                "author": c.commit.author.name if c.commit.author else "",
                "date": _author_date_iso(c.commit.author),
                "stats": {
                    "additions": c.stats.additions,
                    "deletions": c.stats.deletions,
                    "total": c.stats.total,
                },
                "files": files,
                "url": c.html_url,
            }
        )
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_list_issues",
    description=(
        "List issues and pull requests in a GitHub repository. Filter by state "
        "(open/closed/all) and labels. Returns number, title, author, labels, and URL."
    ),
    category="github",
    params_model=ListIssuesParams,
)
async def github_list_issues(
    repo: str,
    state: str = "open",
    labels: str | None = None,
    max_results: int = 10,
) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)

        kwargs: dict = {"state": state}
        if labels:
            label_list = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]
            if label_list:
                kwargs["labels"] = [await asyncio.to_thread(r.get_label, lbl) for lbl in label_list]

        issues_page = await asyncio.to_thread(r.get_issues, **kwargs)

        issues = []
        for issue in issues_page[:max_results]:
            issues.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "is_pull_request": issue.pull_request is not None,
                    "author": issue.user.login if issue.user else "",
                    "labels": [lbl.name for lbl in issue.labels],
                    "created_at": issue.created_at.isoformat() if issue.created_at else "",
                    "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
                    "comments": issue.comments,
                    "url": issue.html_url,
                }
            )

        return ToolResult(data={"issues": issues, "count": len(issues)})
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))


@registry.tool(
    name="github_get_issue",
    description=(
        "Get full details of a GitHub issue or pull request, including body and "
        "comments. For PRs, includes merge status, base/head branches, and diff stats."
    ),
    category="github",
    params_model=GetIssueParams,
)
async def github_get_issue(repo: str, number: int) -> ToolResult:
    try:
        slug = _parse_repo(repo)
        gh = _get_github()
        r = await asyncio.to_thread(gh.get_repo, slug)
        issue = await asyncio.to_thread(r.get_issue, number)

        body = issue.body or ""
        if len(body) > MAX_ISSUE_BODY_CHARS:
            body = body[:MAX_ISSUE_BODY_CHARS] + " [Body truncated]"

        data: dict = {
            "number": issue.number,
            "title": issue.title,
            "state": issue.state,
            "is_pull_request": issue.pull_request is not None,
            "author": issue.user.login if issue.user else "",
            "labels": [lbl.name for lbl in issue.labels],
            "body": body,
            "created_at": issue.created_at.isoformat() if issue.created_at else "",
            "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
            "url": issue.html_url,
        }

        # Fetch comments (up to MAX_COMMENTS)
        comments_page = await asyncio.to_thread(issue.get_comments)
        comments = []
        for comment in comments_page[:MAX_COMMENTS]:
            comment_body = comment.body or ""
            if len(comment_body) > MAX_COMMENT_CHARS:
                comment_body = comment_body[:MAX_COMMENT_CHARS] + " [Comment truncated]"
            comments.append(
                {
                    "author": comment.user.login if comment.user else "",
                    "body": comment_body,
                    "created_at": comment.created_at.isoformat() if comment.created_at else "",
                }
            )
        data["comments"] = comments

        # Add PR-specific fields
        if issue.pull_request is not None:
            pr = await asyncio.to_thread(r.get_pull, number)
            data["merged"] = pr.merged
            data["base"] = (pr.base.ref if pr.base else "",)
            data["head"] = (pr.head.ref if pr.head else "",)
            data["additions"] = pr.additions
            data["deletions"] = pr.deletions
            data["changed_files"] = pr.changed_files

        return ToolResult(data=data)
    except ValueError as exc:
        return ToolResult(error=str(exc))
    except GithubException as exc:
        return ToolResult(error=_github_error_message(exc))
