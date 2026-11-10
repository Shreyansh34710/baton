"""Bounded, read-only collection of public GitHub repository evidence."""

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from app.services.github_client import (
    GitHubClient, GitHubIngestionError, GitHubRepositoryNotFound, GitHubResponseError,
)

MAX_COMMITS = 100
MAX_ISSUES = 100
MAX_PULL_REQUESTS = 100
MAX_CONTRIBUTORS = 100
MAX_TREE_ENTRIES = 200
MAX_SELECTED_FILES = 20
MAX_FILE_BYTES = 100 * 1024
MAX_EVIDENCE_BYTES = 100 * 1024

EXCLUDED_DIRS = {
    "node_modules", "vendor", "dist", "build", "coverage", "target", ".git",
    "__pycache__", ".venv", "venv", "env", "site-packages", "bower_components",
    ".next", ".nuxt", "out", "generated", "gen", "third_party", "pods",
}
EXCLUDED_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pdm.lock",
    "pipfile.lock", "cargo.lock", "composer.lock", "gemfile.lock", "go.sum",
}
SECRET_PATH = re.compile(
    r"(^|[/_.-])(secrets?|credentials?|private[_-]?key|id_rsa|\.env)([/_.-]|$)", re.I
)
SECRET_CONTENT = re.compile(
    r"(?im)(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:api[_-]?key|access[_-]?token|password|secret[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{12,})"
)
ALLOWED_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala",
    ".sh", ".bash", ".sql", ".html", ".css", ".scss", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".md", ".rst", ".txt", ".dockerfile",
}
ALLOWED_NAMES = {
    "dockerfile", "makefile", "cmakelists.txt", ".gitignore", ".editorconfig",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json",
}


@dataclass
class EvidenceDraft:
    evidence_type: str
    source_identifier: str
    source_url: str
    content: str
    repository_commit_sha: Optional[str] = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def parse_repository_url(repository_url: str) -> Tuple[str, str]:
    """Return owner/name only for canonical public HTTPS GitHub repository URLs."""
    try:
        parsed = urlsplit(repository_url)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com"
            or parsed.username or parsed.password or parsed.port
            or len(parts) != 2 or parsed.query or parsed.fragment
        ):
            raise ValueError
        owner, name = parts
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) or name in {".", "..", ".git"}:
            raise ValueError
        repository = name.removesuffix(".git")
        if not repository:
            raise ValueError
        return owner, repository
    except (ValueError, AttributeError):
        raise ValueError("Repository URL must be https://github.com/owner/repository")


def _compact(value: Any, limit: int = 16000) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(content.encode("utf-8")) <= limit:
        return content
    return json.dumps(
        {"truncated": True, "excerpt": content[: max(0, limit // 8)]},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    )


class GitHubIngestionService:
    def __init__(self, client: Optional[GitHubClient] = None) -> None:
        self._owns_client = client is None
        self.client = client or GitHubClient()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def collect(
        self,
        repository_url: str,
        progress: Optional[Callable[[str, int], None]] = None,
    ) -> List[EvidenceDraft]:
        owner, repo = parse_repository_url(repository_url)
        base = "/repos/{}/{}".format(owner, repo)
        public_url = "https://github.com/{}/{}".format(owner, repo)
        drafts: List[EvidenceDraft] = []

        def stage(label: str, percent: int) -> None:
            if progress:
                progress(label, percent)

        def add(kind: str, identifier: str, url: str, content: str, sha: Optional[str] = None) -> None:
            bounded = content.encode("utf-8")[:MAX_EVIDENCE_BYTES].decode("utf-8", "ignore")
            drafts.append(EvidenceDraft(kind, identifier[:512], url[:2048], bounded, sha))

        stage("Fetching repository information", 5)
        repo_info = self.client.get_json(base)
        self._require_dict(repo_info)
        default_branch = repo_info.get("default_branch")
        add("repository", "repository", public_url, _compact({
            key: repo_info.get(key) for key in (
                "full_name", "description", "default_branch", "html_url", "created_at",
                "updated_at", "stargazers_count", "forks_count",
            )
        }))

        stage("Reading repository structure", 20)
        commit_sha = None
        if isinstance(default_branch, str) and default_branch:
            branch_ref = self.client.get_json(base + "/branches/" + self._quote_path(default_branch))
            self._require_dict(branch_ref)
            commit = branch_ref.get("commit")
            commit_sha = commit.get("sha") if isinstance(commit, dict) else None
            if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
                raise GitHubResponseError()
            tree_result = self.client.get_json(base + "/git/trees/" + commit_sha, {"recursive": 1})
            self._require_dict(tree_result)
            tree = tree_result.get("tree")
            if not isinstance(tree, list):
                raise GitHubResponseError()
            selected_tree = tree[:MAX_TREE_ENTRIES]
            tree_evidence = {
                "entries": selected_tree,
                "truncated": bool(tree_result.get("truncated")) or len(tree) > MAX_TREE_ENTRIES,
                "available": True,
            }
            add("tree", "tree:{}".format(commit_sha), public_url + "/tree/" + commit_sha,
                _compact(tree_evidence, MAX_EVIDENCE_BYTES), commit_sha)
            try:
                readme = self.client.get_json(base + "/readme")
            except GitHubRepositoryNotFound:
                readme = None
            if isinstance(readme, dict):
                readme_text = self._decode_blob(readme)
                if readme_text is not None and not SECRET_CONTENT.search(readme_text):
                    add("readme", "README", public_url + "/blob/" + commit_sha + "/" + str(readme.get("path", "README.md")), readme_text, commit_sha)
        elif default_branch is None or default_branch == "":
            # GitHub repositories with no commits have no default branch or tree.
            selected_tree = []
            add("tree", "tree:uninitialized", public_url,
                _compact({"entries": [], "truncated": False, "available": False}))
        else:
            raise GitHubResponseError()

        text_files = 0
        for entry in selected_tree:
            if text_files >= MAX_SELECTED_FILES:
                break
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            size = entry.get("size")
            sha = entry.get("sha")
            if not isinstance(path, str) or not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
                continue
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
                continue
            if not self._is_selected_text(path):
                continue
            blob = self.client.get_json(base + "/git/blobs/" + sha)
            self._require_dict(blob)
            text = self._decode_blob(blob)
            if text is None or SECRET_CONTENT.search(text):
                continue
            add("source_file", path, public_url + "/blob/" + commit_sha + "/" + self._quote_path(path), text, commit_sha)
            text_files += 1

        stage("Collecting commits", 45)
        commits = self.client.get_paginated(base + "/commits", {"sha": default_branch}, MAX_COMMITS) if default_branch else []
        for item in commits:
            if not isinstance(item, dict) or not isinstance(item.get("sha"), str):
                continue
            sha = item["sha"]
            if not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
                continue
            commit_data = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            message = commit_data.get("message")
            author = commit_data.get("author") if isinstance(commit_data.get("author"), dict) else {}
            committer = commit_data.get("committer") if isinstance(commit_data.get("committer"), dict) else {}
            github_author = item.get("author") if isinstance(item.get("author"), dict) else {}
            add("commit", sha, public_url + "/commit/" + sha, _compact({
                "sha": sha, "message": message,
                "author": {"name": author.get("name"), "date": author.get("date")},
                "author_login": github_author.get("login") if isinstance(github_author.get("login"), str) else None,
                "committer": {"name": committer.get("name"), "date": committer.get("date")},
            }), sha)

        stage("Collecting issues and pull requests", 65)
        issues = self.client.get_paginated(
            base + "/issues", {"state": "all", "sort": "updated", "direction": "desc"}, MAX_ISSUES,
            include=lambda item: isinstance(item, dict) and "pull_request" not in item,
        )
        for item in issues:
            self._add_discussion_item(add, item, "issue", public_url)
        pulls = self.client.get_paginated(
            base + "/pulls", {"state": "all", "sort": "updated", "direction": "desc"}, MAX_PULL_REQUESTS
        )
        for item in pulls:
            self._add_discussion_item(add, item, "pull_request", public_url)

        stage("Collecting contributors", 82)
        contributors = self.client.get_paginated(base + "/contributors", {}, MAX_CONTRIBUTORS)
        for item in contributors:
            if isinstance(item, dict):
                login = item.get("login")
                if isinstance(login, str):
                    add("contributor", login, public_url + "/graphs/contributors", _compact({"login": login, "contributions": item.get("contributions")}))

        stage("Saving repository evidence", 95)
        return drafts

    @staticmethod
    def _require_dict(value: Any) -> None:
        if not isinstance(value, dict):
            raise GitHubResponseError()

    @staticmethod
    def _quote_path(path: str) -> str:
        from urllib.parse import quote
        return quote(path, safe="/")

    @staticmethod
    def _decode_blob(blob: Dict[str, Any]) -> Optional[str]:
        encoded = blob.get("content")
        if not isinstance(encoded, str) or blob.get("encoding") != "base64":
            return None
        try:
            raw = base64.b64decode("".join(encoded.split()), validate=True)
            if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
                return None
            return raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None

    @staticmethod
    def _is_selected_text(path: str) -> bool:
        parts = path.replace("\\", "/").split("/")
        lowered_parts = [part.lower() for part in parts]
        name = lowered_parts[-1]
        if any(part in EXCLUDED_DIRS for part in lowered_parts[:-1]):
            return False
        if len(parts) == 1 and name.startswith("readme"):
            return False  # The canonical README endpoint is stored once above.
        if name in EXCLUDED_FILES or name.endswith((".min.js", ".min.css", ".map")):
            return False
        if name.endswith(".lock") or ".generated." in name or name.endswith("_generated.py"):
            return False
        if SECRET_PATH.search(path) or name.endswith((".zip", ".tar", ".gz", ".7z", ".rar", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".so", ".dll", ".exe")):
            return False
        if name in ALLOWED_NAMES:
            return True
        dot = name.rfind(".")
        return dot >= 0 and name[dot:] in ALLOWED_EXTENSIONS

    @staticmethod
    def _add_discussion_item(add: Callable[..., None], item: Any, kind: str, public_url: str) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("number"), int):
            return
        number = item["number"]
        assignees = item.get("assignees") if isinstance(item.get("assignees"), list) else []
        labels = item.get("labels") if isinstance(item.get("labels"), list) else []
        body = item.get("body") if isinstance(item.get("body"), str) else ""
        content = {
            "number": number, "title": item.get("title"), "state": item.get("state"),
            "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
            "merged_at": item.get("merged_at"),
            "draft": item.get("draft") is True,
            "user": (item.get("user") or {}).get("login") if isinstance(item.get("user"), dict) else None,
            "assignees": [assignee.get("login") for assignee in assignees
                          if isinstance(assignee, dict) and isinstance(assignee.get("login"), str)],
            "labels": [label.get("name") for label in labels
                       if isinstance(label, dict) and isinstance(label.get("name"), str)],
            "body": body[:8000],
        }
        add(kind, str(number), public_url + "/{}/{}".format("pull" if kind == "pull_request" else "issues", number), _compact(content, 12000))
