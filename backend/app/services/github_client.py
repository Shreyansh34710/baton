"""Small, unauthenticated GitHub REST client with bounded pagination/retries."""

import time
import json
from typing import Any, Callable, Dict, List, Optional

import httpx

MAX_GITHUB_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_GITHUB_ERROR_BYTES = 64 * 1024


class GitHubIngestionError(RuntimeError):
    code = "github_api_error"
    safe_message = "GitHub could not provide the repository data. Please retry later."


class GitHubRepositoryNotFound(GitHubIngestionError):
    code = "repository_not_found"
    safe_message = "The repository was not found or is not publicly accessible."


class GitHubRateLimited(GitHubIngestionError):
    code = "github_rate_limited"
    safe_message = "GitHub's public API rate limit was reached. Please retry later."


class GitHubNetworkUnavailable(GitHubIngestionError):
    code = "github_unavailable"
    safe_message = "GitHub could not be reached after several attempts. Please retry later."


class GitHubResponseError(GitHubIngestionError):
    code = "github_response_error"
    safe_message = "GitHub returned an unusable response. Please retry later."


class GitHubClient:
    API_ROOT = "https://api.github.com"
    PAGE_SIZE = 100
    MAX_PAGES = 5

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
    ) -> None:
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=10.0,
            follow_redirects=False,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "BATON-public-repository-ingestion",
            },
        )
        self.sleep = sleep
        self.max_retries = max(0, max_retries)

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not path.startswith("/repos/") or path.startswith("//"):
            raise GitHubResponseError("Invalid internal GitHub API path")
        url = self.API_ROOT + path
        for attempt in range(self.max_retries + 1):
            try:
                with self.http_client.stream("GET", url, params=params, follow_redirects=False) as response:
                    if response.status_code == 429:
                        raise GitHubRateLimited()
                    if response.status_code == 204:
                        return []
                    if response.status_code == 404:
                        raise GitHubRepositoryNotFound()
                    if response.status_code >= 500:
                        if attempt < self.max_retries:
                            self.sleep(min(0.25 * (2 ** attempt), 1.0))
                            continue
                        raise GitHubResponseError()
                    if response.status_code < 200 or response.status_code >= 300:
                        error_body = self._read_limited(response, MAX_GITHUB_ERROR_BYTES)
                        if self._is_rate_limited(response, error_body):
                            raise GitHubRateLimited()
                        raise GitHubResponseError()
                    body = self._read_limited(response, MAX_GITHUB_RESPONSE_BYTES)
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    self.sleep(min(0.25 * (2 ** attempt), 1.0))
                    continue
                raise GitHubNetworkUnavailable() from exc

            try:
                return json.loads(body)
            except ValueError as exc:
                raise GitHubResponseError() from exc
        raise GitHubNetworkUnavailable()

    @staticmethod
    def _is_rate_limited(response: httpx.Response, body: bytes = b"") -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if response.headers.get("X-RateLimit-Remaining") == "0" or response.headers.get("Retry-After"):
            return True
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            return False
        message = parsed.get("message", "") if isinstance(parsed, dict) else ""
        return "rate limit" in str(message).lower()

    @staticmethod
    def _read_limited(response: httpx.Response, limit: int) -> bytes:
        chunks = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > limit:
                raise GitHubResponseError()
            chunks.append(chunk)
        return b"".join(chunks)

    def get_paginated(
        self,
        path: str,
        params: Optional[Dict[str, Any]],
        limit: int,
        include: Optional[Callable[[Any], bool]] = None,
    ) -> List[Any]:
        """Build page URLs locally; never follow arbitrary GitHub Link URLs."""
        results: List[Any] = []
        page_params = dict(params or {})
        for page in range(1, self.MAX_PAGES + 1):
            page_params.update({"per_page": self.PAGE_SIZE, "page": page})
            values = self.get_json(path, params=page_params)
            if not isinstance(values, list):
                raise GitHubResponseError()
            for value in values:
                if include is None or include(value):
                    results.append(value)
                    if len(results) >= limit:
                        return results[:limit]
            if len(values) < self.PAGE_SIZE:
                break
        return results[:limit]
