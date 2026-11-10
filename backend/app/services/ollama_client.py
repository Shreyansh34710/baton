"""Local-only Ollama HTTP client with bounded errors and JSON output."""

import ipaddress
import json
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

from app.core.config import settings

MAX_OLLAMA_RESPONSE_BYTES = 2 * 1024 * 1024


class OllamaError(RuntimeError):
    code = "ollama_generation_failed"
    safe_message = "Local AI enrichment could not be completed. Deterministic results are still available."

    def __init__(
        self, message: Optional[str] = None, diagnostic_category: Optional[str] = None
    ) -> None:
        super().__init__(self.safe_message if message is None else message)
        self.diagnostic_category = diagnostic_category


class OllamaUnavailable(OllamaError):
    code = "ollama_unavailable"
    safe_message = "The local Ollama service is unavailable. Deterministic results are still available."


class OllamaModelNotFound(OllamaError):
    code = "ollama_model_not_found"
    safe_message = "The configured Ollama model is not available locally. Pull the model and retry enrichment."


class OllamaRequestTimeout(OllamaError):
    code = "ollama_timeout"
    safe_message = "Local AI enrichment timed out. Deterministic results are still available."


class OllamaInvalidResponse(OllamaError):
    code = "ollama_invalid_response"
    safe_message = "Ollama returned an invalid structured response. Deterministic results are still available."

    def __init__(self, diagnostic_category: str = "invalid_json") -> None:
        super().__init__(diagnostic_category=diagnostic_category)


class OllamaConfigurationError(OllamaError):
    code = "ollama_configuration_error"
    safe_message = "Ollama must be configured with a local loopback URL and a valid model name."


class OllamaClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.ollama_timeout_seconds
        self.last_response_text: Optional[str] = None
        self.last_response_diagnostics: Dict[str, Any] = {}
        self._validate_config()
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def _validate_config(self) -> None:
        try:
            parsed = urlsplit(self.base_url)
            host = parsed.hostname
            parsed.port  # Force malformed or out-of-range ports to fail during configuration.
            if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError
            if parsed.scheme.lower() not in {"http", "https"} or parsed.path not in {"", "/"}:
                raise ValueError
            local_host = host.lower() == "localhost"
            if not local_host:
                local_host = ipaddress.ip_address(host).is_loopback
            if not local_host:
                raise ValueError
            if not isinstance(self.model, str) or not self.model.strip() or self.model != self.model.strip() or len(self.model) > 128:
                raise ValueError
            if not isinstance(self.timeout_seconds, (int, float)) or not 1 <= self.timeout_seconds <= 600:
                raise ValueError
        except (ValueError, TypeError):
            raise OllamaConfigurationError()

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def generate_json(
        self,
        system: str,
        prompt: str,
        response_schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.last_response_text = None
        self.last_response_diagnostics = {}
        try:
            response = self.http_client.post(
                self.base_url + "/api/generate",
                json={
                    "model": self.model,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "format": response_schema,
                    "options": {"temperature": 0, "seed": 17, "num_predict": 2048},
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise OllamaRequestTimeout() from exc
        except httpx.RequestError as exc:
            raise OllamaUnavailable() from exc

        if response.status_code == 404:
            raise OllamaModelNotFound()
        if response.status_code == 400:
            try:
                error_text = str(response.json().get("error", "")).lower()
            except (ValueError, AttributeError):
                error_text = ""
            if "model" in error_text and "not found" in error_text:
                raise OllamaModelNotFound()
            raise OllamaError()
        if response.status_code >= 500:
            raise OllamaUnavailable()
        if response.status_code < 200 or response.status_code >= 300:
            raise OllamaError()
        if len(response.content) > MAX_OLLAMA_RESPONSE_BYTES:
            raise OllamaInvalidResponse("invalid_output_structure")
        try:
            outer = response.json()
        except ValueError as exc:
            raise OllamaInvalidResponse() from exc
        if not isinstance(outer, dict) or not isinstance(outer.get("response"), str):
            if isinstance(outer, dict) and outer.get("error"):
                raise OllamaError()
            raise OllamaInvalidResponse("invalid_output_structure")
        raw_text = outer["response"]
        self.last_response_text = raw_text
        self.last_response_diagnostics = {
            "raw_response_bytes": len(raw_text.encode("utf-8", "replace")),
            "done_reason_length": outer.get("done_reason") == "length",
            "thinking_prefix_present": "</think>" in raw_text,
        }
        if outer.get("done_reason") == "length":
            raise OllamaInvalidResponse("truncated_response")
        parsed = _parse_response_json(raw_text)
        if not isinstance(parsed, dict):
            raise OllamaInvalidResponse("invalid_output_structure")
        return parsed


def _parse_response_json(raw_text: str) -> Any:
    """Parse plain JSON or JSON following Qwen-style thinking text/fences."""
    candidates = [raw_text.strip()]
    if "</think>" in raw_text:
        candidates.insert(0, raw_text.rsplit("</think>", 1)[1].strip())
    for candidate in candidates:
        if candidate.startswith("```json"):
            candidate = candidate[7:]
        elif candidate.startswith("```"):
            candidate = candidate[3:]
        if candidate.endswith("```"):
            candidate = candidate[:-3].strip()
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            pass

    # Thinking text can contain braces. Scan balanced objects and accept only a
    # complete object that independently parses as JSON.
    for start, char in enumerate(raw_text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(raw_text)):
            current = raw_text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw_text[start:end + 1])
                    except (ValueError, TypeError):
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
    raise OllamaInvalidResponse("invalid_json")
