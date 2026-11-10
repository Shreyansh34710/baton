"""Deterministic tests for the bounded public GitHub integration."""

import base64
import json

import httpx
import pytest

from app.services.github_client import (
    MAX_GITHUB_RESPONSE_BYTES, GitHubClient, GitHubNetworkUnavailable,
    GitHubRateLimited, GitHubRepositoryNotFound, GitHubResponseError,
)
from app.services.github_ingestion import (
    MAX_COMMITS, MAX_FILE_BYTES, MAX_SELECTED_FILES, MAX_TREE_ENTRIES,
    GitHubIngestionService, parse_repository_url,
)


def _json_response(data, status=200, headers=None, request=None):
    request = request or httpx.Request("GET", "https://api.github.com/test")
    return httpx.Response(status, json=data, headers=headers, request=request)


def _blob(text):
    raw = text.encode("utf-8")
    return {"encoding": "base64", "content": base64.b64encode(raw).decode("ascii"), "size": len(raw)}


def _handler_for_repository(request):
    path = request.url.path
    if path.endswith("/branches/main"):
        return _json_response({"commit": {"sha": "a" * 40}}, request=request)
    if path.endswith("/git/trees/" + "a" * 40):
        return _json_response({"tree": [], "truncated": False}, request=request)
    if path.endswith("/readme"):
        return _json_response(_blob("# public readme\n"), request=request)
    if path.endswith("/commits"):
        return _json_response([{"sha": "b" * 40, "commit": {"message": "fix bug"}}], request=request)
    if path.endswith("/issues"):
        return _json_response([{
            "number": 5, "title": "Bug report", "state": "open", "body": "Details",
            "user": {"login": "reporter"}, "updated_at": "2026-01-01T00:00:00Z",
        }], request=request)
    if path.endswith("/pulls"):
        return _json_response([{
            "number": 8, "title": "Fix", "state": "open", "body": "Patch",
            "user": {"login": "author"}, "updated_at": "2026-01-02T00:00:00Z",
            "merged_at": None, "draft": True, "assignees": [{"login": "reviewer"}],
        }], request=request)
    if path.endswith("/contributors"):
        return _json_response([{"login": "maintainer", "contributions": 12}], request=request)
    if "/git/blobs/" in path:
        return _json_response(_blob("print('ok')\n"), request=request)
    if path.endswith("/example/project"):
        return _json_response({
            "full_name": "example/project", "description": "Example", "default_branch": "main",
            "html_url": "https://github.com/example/project", "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z", "stargazers_count": 3, "forks_count": 1,
        }, request=request)
    raise AssertionError("Unexpected API request: {}".format(request.url))


def test_collects_repository_readme_tree_activity_and_contributors():
    transport = httpx.MockTransport(_handler_for_repository)
    client = GitHubClient(httpx.Client(transport=transport), sleep=lambda _delay: None)
    service = GitHubIngestionService(client)
    try:
        evidence = service.collect("https://github.com/example/project")
    finally:
        service.close()
        client.close()
    indexed = {(item.evidence_type, item.source_identifier): item for item in evidence}
    assert "repository" in {item.evidence_type for item in evidence}
    assert "public readme" in indexed[("readme", "README")].content
    assert indexed[("tree", "tree:" + "a" * 40)].repository_commit_sha == "a" * 40
    assert "fix bug" in indexed[("commit", "b" * 40)].content
    assert indexed[("issue", "5")] and indexed[("pull_request", "8")]
    pull_data = json.loads(indexed[("pull_request", "8")].content)
    assert pull_data["draft"] is True
    assert pull_data["assignees"] == ["reviewer"]
    assert pull_data["merged_at"] is None
    assert indexed[("contributor", "maintainer")]


def test_pagination_and_commit_limit_are_bounded():
    seen_pages = []

    def handler(request):
        page = int(request.url.params["page"])
        seen_pages.append(page)
        if page == 1:
            return _json_response([{"n": value} for value in range(100)], request=request)
        return _json_response([{"n": 100}], request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    values = client.get_paginated("/repos/example/project/commits", {}, 150)
    assert len(values) == 101
    assert seen_pages == [1, 2]
    client.close()


def test_commit_cap_stops_pagination_at_100_records():
    seen_pages = []

    def handler(request):
        seen_pages.append(int(request.url.params["page"]))
        return _json_response([{"n": value} for value in range(100)], request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    values = client.get_paginated("/repos/example/project/commits", {}, MAX_COMMITS)
    assert len(values) == 100
    assert seen_pages == [1]
    client.close()


def test_tree_and_selected_file_limits_and_exclusions():
    entries = []
    for index in range(25):
        entries.append({"path": "src/file{}.py".format(index), "type": "blob", "size": 10, "sha": "c" * 40})
    entries.extend([
        {"path": "node_modules/package/index.js", "type": "blob", "size": 10, "sha": "d" * 40},
        {"path": "package-lock.json", "type": "blob", "size": 10, "sha": "e" * 40},
        {"path": "dist/app.min.js", "type": "blob", "size": 10, "sha": "f" * 40},
        {"path": ".env", "type": "blob", "size": 10, "sha": "1" * 40},
        {"path": "archive.zip", "type": "blob", "size": 10, "sha": "2" * 40},
        {"path": "src/large.py", "type": "blob", "size": MAX_FILE_BYTES + 1, "sha": "3" * 40},
    ])
    tree = entries + [
        {"path": "later/entry{}.py".format(index), "type": "blob", "size": 1, "sha": "4" * 40}
        for index in range(MAX_TREE_ENTRIES)
    ]

    def handler(request):
        path = request.url.path
        if path.endswith("/git/trees/" + "a" * 40):
            return _json_response({"tree": tree}, request=request)
        return _handler_for_repository(request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    evidence = GitHubIngestionService(client).collect("https://github.com/example/project")
    client.close()
    tree_record = next(item for item in evidence if item.evidence_type == "tree")
    tree_content = json.loads(tree_record.content)
    assert len(tree_content["entries"]) == MAX_TREE_ENTRIES
    assert tree_content["truncated"] is True
    files = [item for item in evidence if item.evidence_type == "source_file"]
    assert len(files) == MAX_SELECTED_FILES
    assert all(item.source_identifier.startswith("src/file") for item in files)
    assert all(len(item.content.encode("utf-8")) <= MAX_FILE_BYTES for item in files)


@pytest.mark.parametrize("url", [
    "http://github.com/a/b", "https://github.com/a", "https://github.com/a/b/tree/main",
    "https://github.com.evil.test/a/b", "https://user@github.com/a/b", "https://github.com/a/b?x=1",
    "https://github.com/example/.git",
])
def test_invalid_repository_urls_are_rejected(url):
    with pytest.raises(ValueError):
        parse_repository_url(url)


def test_accepts_canonical_repository_and_optional_git_suffix():
    assert parse_repository_url("https://github.com/example/repo.git") == ("example", "repo")


def test_github_404_is_safe():
    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(
        lambda request: _json_response({}, 404, request=request)
    )), sleep=lambda _delay: None)
    with pytest.raises(GitHubRepositoryNotFound) as error:
        client.get_json("/repos/example/missing")
    assert "not found" in error.value.safe_message.lower()
    client.close()


def test_github_rate_limit_is_safe_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return _json_response({"message": "API rate limit exceeded"}, 403, request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    with pytest.raises(GitHubRateLimited):
        client.get_json("/repos/example/project")
    assert len(calls) == 1
    client.close()


def test_network_failures_use_bounded_retries():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("secret internal detail", request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None, max_retries=2)
    with pytest.raises(GitHubNetworkUnavailable) as error:
        client.get_json("/repos/example/project")
    assert len(calls) == 3
    assert "secret internal detail" not in error.value.safe_message
    client.close()


def test_file_selector_excludes_secret_binary_generated_and_dependency_paths():
    from app.services.github_ingestion import GitHubIngestionService
    is_selected = GitHubIngestionService._is_selected_text
    assert not is_selected("node_modules/pkg/index.js")
    assert not is_selected("src/app.min.js")
    assert not is_selected("package-lock.json")
    assert not is_selected("config/credentials.yaml")
    assert not is_selected("release/archive.tar.gz")
    assert is_selected("src/app.py")


def test_missing_readme_is_optional_for_a_nonempty_repository():
    def handler(request):
        if request.url.path.endswith("/readme"):
            return httpx.Response(404, json={"message": "Not Found"}, request=request)
        return _handler_for_repository(request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    try:
        evidence = GitHubIngestionService(client).collect("https://github.com/example/project")
    finally:
        client.close()
    assert any(item.evidence_type == "repository" for item in evidence)
    assert any(item.evidence_type == "tree" for item in evidence)
    assert not any(item.evidence_type == "readme" for item in evidence)


def test_empty_repository_without_default_branch_collects_safe_metadata():
    def handler(request):
        path = request.url.path
        if path.endswith("/repos/example/empty"):
            return _json_response({"full_name": "example/empty", "description": "", "default_branch": None}, request=request)
        if path.endswith(("/issues", "/pulls", "/contributors")):
            return httpx.Response(204, request=request)
        raise AssertionError("Empty repository should not request a branch or tree: {}".format(request.url))

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    try:
        evidence = GitHubIngestionService(client).collect("https://github.com/example/empty")
    finally:
        client.close()
    by_type = {item.evidence_type: item for item in evidence}
    assert set(by_type) == {"repository", "tree"}
    assert json.loads(by_type["tree"].content) == {"available": False, "entries": [], "truncated": False}


def test_malformed_partial_repository_metadata_fails_safely():
    def handler(request):
        return _json_response({"full_name": "example/broken", "default_branch": 7}, request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    with pytest.raises(GitHubResponseError):
        GitHubIngestionService(client).collect("https://github.com/example/broken")
    client.close()


def test_github_response_body_is_bounded_before_json_parsing():
    payload = b"{" + b" " * MAX_GITHUB_RESPONSE_BYTES
    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=payload, request=request)
    )), sleep=lambda _delay: None, max_retries=0)
    with pytest.raises(GitHubResponseError):
        client.get_json("/repos/example/large")
    client.close()


def test_github_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://attacker.invalid/"}, request=request)

    client = GitHubClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _delay: None)
    with pytest.raises(GitHubResponseError):
        client.get_json("/repos/example/renamed")
    assert len(calls) == 1
    client.close()
