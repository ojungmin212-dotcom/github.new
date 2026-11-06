from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from ghrank.github import GitHubClient, Response

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def api_repo(full_name: str, stars: int = 100, **over) -> dict:
    """GitHub 검색 API items[] 한 건과 같은 모양."""
    base = {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "",
        "stargazers_count": stars,
        "forks_count": 1,
        "language": "Python",
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "topics": [],
        "pushed_at": "2026-11-01T00:00:00Z",
        "created_at": "2020-01-01T00:00:00Z",
        "archived": False,
        "fork": False,
        "size": 1000,
        "open_issues_count": 3,
        "homepage": None,
        "default_branch": "main",
    }
    base.update(over)
    return base


class FakeTransport:
    """URL 부분 문자열 → 응답 목록(차례대로 소비). 호출 기록을 남긴다."""

    def __init__(self, routes: dict[str, list[Response]] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def add(self, needle: str, *responses: Response) -> None:
        self.routes.setdefault(needle, []).extend(responses)

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> Response:
        self.requests.append((url, dict(headers)))
        for needle, queue in self.routes.items():
            if needle in url and queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return Response(404, {}, b'{"message": "Not Found"}')


def ok_json(payload: object) -> Response:
    return Response(200, {}, json.dumps(payload).encode("utf-8"))


def search_page(items: list[dict], total: int | None = None) -> Response:
    return ok_json({"total_count": len(items) if total is None else total, "incomplete_results": False, "items": items})


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> GitHubClient:
    slept: list[float] = []
    c = GitHubClient(token=None, cache=None, transport=transport, sleep=slept.append, now=lambda: 1_000_000.0,
                     log=lambda _m: None)
    c.slept = slept  # type: ignore[attr-defined]
    return c
