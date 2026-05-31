import json
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_HEADERS = {
    "User-Agent": "AgentRG paper-acquisition/1.0",
    "Accept": "application/json, text/markdown;q=0.9, text/plain;q=0.8, */*;q=0.5",
}


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class NotFoundError(HttpError):
    pass


def request_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30, retries: int = 3) -> str:
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=merged_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                raise NotFoundError(exc.code, body) from exc
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise HttpError(exc.code, body) from exc
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("request failed")


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30, retries: int = 3) -> Any:
    return json.loads(request_text(url, headers=headers, timeout=timeout, retries=retries))


def jget(obj: Any, path: str, default: Any = None) -> Any:
    """Navigate a nested JSON object along a dot-separated key path.

    ``jget(data, 'result.hits.hit', [])`` is equivalent to
    ``(data.get('result') or {}).get('hits') or {}).get('hit', [])``
    but stops and returns ``default`` at the first non-dict step.
    """
    node: Any = obj
    for key in path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node if node is not None else default
