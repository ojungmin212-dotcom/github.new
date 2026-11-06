import os
import urllib.error

import pytest
from conftest import FakeTransport, api_repo, ok_json, search_page

from ghrank.github import (
    FileCache,
    GitHubClient,
    GitHubError,
    NotFoundError,
    RateLimitError,
    Response,
    parse_time,
)


def make(transport, **kw) -> GitHubClient:
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("now", lambda: 1_000_000.0)
    kw.setdefault("log", lambda m: None)
    return GitHubClient(transport=transport, **kw)


def test_search_builds_url_and_headers():
    t = FakeTransport()
    t.add("search/repositories", search_page([api_repo("a/b")]))
    c = make(t, token="secret-token")
    data = c.search_repositories("topic:x archived:false", sort="forks", per_page=50, page=2)
    assert data["items"][0]["full_name"] == "a/b"
    url, headers = t.requests[0]
    assert "q=topic%3Ax+archived%3Afalse" in url and "sort=forks" in url and "per_page=50" in url and "page=2" in url
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["User-Agent"].startswith("ghrank/")


def test_token_not_sent_to_raw_host():
    t = FakeTransport()
    t.add("raw.githubusercontent.com", Response(200, {}, b"# readme"))
    c = make(t, token="secret-token")
    assert c.get_readme("o/r") == "# readme"
    url, headers = t.requests[0]
    assert url == "https://raw.githubusercontent.com/o/r/HEAD/README.md"
    assert "Authorization" not in headers


def test_readme_falls_back_to_api_then_none():
    t = FakeTransport()
    t.add("/repos/o/r/readme", Response(200, {}, "README.rst 내용".encode()))
    c = make(t)
    assert c.get_readme("o/r") == "README.rst 내용"
    assert make(FakeTransport()).get_readme("o/none") is None


def test_rate_limit_waits_then_succeeds():
    t = FakeTransport()
    t.add("search", Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1000030"}, b"{}"),
          search_page([]))
    slept: list[float] = []
    c = make(t, sleep=slept.append)
    assert c.search_repositories("q")["items"] == []
    assert slept == [31.0]


def test_retry_after_header():
    t = FakeTransport()
    t.add("search", Response(429, {"retry-after": "7"}, b"{}"), search_page([]))
    slept: list[float] = []
    make(t, sleep=slept.append).search_repositories("q")
    assert slept == [7.0]


def test_rate_limit_too_long_raises_with_token_hint():
    t = FakeTransport()
    t.add("search", Response(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1003600"}, b"{}"))
    with pytest.raises(RateLimitError, match="GITHUB_TOKEN"):
        make(t, max_wait=60).search_repositories("q")
    with pytest.raises(RateLimitError) as exc:
        make(t, max_wait=60, token="x").search_repositories("q")
    assert "GITHUB_TOKEN" not in str(exc.value)


def test_rate_limit_gives_up_after_three_attempts():
    t = FakeTransport()
    t.add("search", Response(429, {"retry-after": "1"}, b"{}"))
    slept: list[float] = []
    with pytest.raises(RateLimitError):
        make(t, sleep=slept.append).search_repositories("q")
    assert len(slept) == 2 and len(t.requests) == 3


@pytest.mark.parametrize(
    ("status", "body", "exc", "needle"),
    [
        (401, b"{}", GitHubError, "401"),
        (403, b'{"message": "Forbidden"}', GitHubError, "Forbidden"),
        (422, b'{"message": "Validation Failed", "errors": [{"message": "bad q"}]}', GitHubError, "bad q"),
        (500, b"oops", GitHubError, "500"),
        (404, b"{}", NotFoundError, "찾을 수 없음"),
    ],
)
def test_http_errors(status, body, exc, needle):
    t = FakeTransport()
    t.add("search", Response(status, {}, body))
    with pytest.raises(exc, match=needle):
        make(t).search_repositories("q")


def test_network_error_is_wrapped():
    def boom(url, headers, timeout):
        raise urllib.error.URLError("no route")

    with pytest.raises(GitHubError, match="네트워크"):
        make(boom).search_repositories("q")


def test_get_repository_uses_repo_qualifier_and_validates():
    t = FakeTransport()
    t.add("search", search_page([api_repo("Comfy-Org/ComfyUI")]))
    c = make(t)
    assert c.get_repository("Comfy-Org/ComfyUI")["full_name"] == "Comfy-Org/ComfyUI"
    assert "q=repo%3AComfy-Org%2FComfyUI" in t.requests[0][0]
    with pytest.raises(GitHubError, match="owner/repo"):
        c.get_repository("justname")
    empty = FakeTransport()
    empty.add("search", search_page([]))
    with pytest.raises(NotFoundError):
        make(empty).get_repository("o/missing")


def test_get_json_rejects_non_object():
    t = FakeTransport()
    t.add("search", ok_json([1, 2]))
    with pytest.raises(GitHubError, match="형식"):
        make(t).search_repositories("q")


def test_cache_hit_skips_network_and_expires(tmp_path):
    clock = [1000.0]
    cache = FileCache(tmp_path, ttl_seconds=60, now=lambda: clock[0])
    t = FakeTransport()
    t.add("search", search_page([api_repo("a/b")]))
    c = make(t, cache=cache)
    c.search_repositories("q")
    c.search_repositories("q")
    assert len(t.requests) == 1
    # 파일 수정 시각 기준 만료
    for f in tmp_path.iterdir():
        os.utime(f, (clock[0], clock[0]))
    clock[0] += 61
    c.search_repositories("q")
    assert len(t.requests) == 2


def test_cache_does_not_store_errors(tmp_path):
    t = FakeTransport()
    t.add("search", Response(500, {}, b"x"))
    c = make(t, cache=FileCache(tmp_path, 60))
    with pytest.raises(GitHubError):
        c.search_repositories("q")
    assert list(tmp_path.iterdir()) == []


def test_cache_write_failure_is_ignored(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cache = FileCache(blocker / "sub", 60)  # 파일 아래에 디렉터리를 만들 수 없음
    cache.set("k", b"v")
    assert cache.get("k") is None


def test_from_env_reads_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", " tok \n")
    assert GitHubClient.from_env().token == "tok"
    monkeypatch.delenv("GH_TOKEN")
    assert GitHubClient.from_env().token is None


def test_default_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert FileCache.default_dir() == tmp_path / "ghrank"
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "L"))
    assert FileCache.default_dir() == tmp_path / "L" / "ghrank"


def test_parse_time():
    assert parse_time("2026-11-05T01:02:03Z").isoformat() == "2026-11-05T01:02:03+00:00"
    assert parse_time(None) is None and parse_time("garbage") is None
