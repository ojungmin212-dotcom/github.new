"""GitHub REST API 클라이언트 (표준 라이브러리만 사용).

- 토큰: 환경변수 GITHUB_TOKEN 또는 GH_TOKEN (없어도 동작하지만 한도가 낮다)
- 한도: 검색 API 는 분당 10회(토큰 없음)/30회(토큰), 그 외 API 는 시간당 60회/5,000회
- 한도에 걸리면 초기화까지 max_wait 초 이하일 때만 기다렸다가 다시 시도하고, 더 길면 오류로 알린다.
- 성공 응답(200)만 디스크에 캐시한다. 토큰은 캐시 키·로그에 넣지 않는다.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ghrank import __version__

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = f"ghrank/{__version__} (+https://github.com)"
MAX_README_BYTES = 512 * 1024


@dataclass
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str], float], Response]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> Response:
    """실제 HTTP 호출. HTTP 오류도 예외 대신 Response 로 돌려준다(상태 코드로 판단하기 위해)."""
    req = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https 고정 URL만 사용)
            body = resp.read(MAX_README_BYTES * 4)
            return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body)
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        hdrs = {k.lower(): v for k, v in exc.headers.items()} if exc.headers is not None else {}
        return Response(exc.code, hdrs, body)


class GitHubError(RuntimeError):
    pass


class RateLimitError(GitHubError):
    pass


class NotFoundError(GitHubError):
    pass


def _api_message(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return body[:200].decode("utf-8", "replace")
    if isinstance(data, dict):
        msg = str(data.get("message", ""))
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            details = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
            msg = f"{msg} ({details})"
        return msg
    return str(data)[:200]


class FileCache:
    """URL → 응답 본문 캐시. 파일 수정 시각으로 만료를 판단한다."""

    def __init__(self, directory: Path, ttl_seconds: float, now: Callable[[], float] = time.time) -> None:
        self.directory = directory
        self.ttl = ttl_seconds
        self._now = now

    @staticmethod
    def default_dir() -> Path:
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        return base / "ghrank"

    def _path(self, key: str) -> Path:
        return self.directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".bin")

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            if self._now() - path.stat().st_mtime > self.ttl:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def set(self, key: str, body: bytes) -> None:
        path = self._path(key)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, path)
        except OSError:
            pass  # 캐시는 최적화일 뿐 - 실패해도 조회는 계속한다


@dataclass
class GitHubClient:
    token: str | None = None
    cache: FileCache | None = None
    transport: Transport = urllib_transport
    timeout: float = 20.0
    max_wait: float = 90.0
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    log: Callable[[str], None] = field(default=lambda msg: print(msg, file=sys.stderr))
    calls: int = 0  # 실제 네트워크 호출 수(캐시 적중 제외) - 테스트·진단용

    @classmethod
    def from_env(cls, cache: FileCache | None = None, **kwargs) -> GitHubClient:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
        return cls(token=token.strip() if token else None, cache=cache, **kwargs)

    # ---- 저수준 ---------------------------------------------------------------
    def _headers(self, accept: str, api: bool) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if api:
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _wait_seconds(self, resp: Response) -> float | None:
        """한도 초과 응답이면 기다릴 초, 아니면 None."""
        h = resp.headers
        retry_after = h.get("retry-after")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                return max(1.0, parsed.timestamp() - self.now())
        if h.get("x-ratelimit-remaining") == "0":
            reset = h.get("x-ratelimit-reset")
            if reset and reset.isdigit():
                return max(1.0, int(reset) - self.now() + 1)
            return 60.0
        return None

    def get(self, url: str, accept: str = "application/vnd.github+json", api: bool = True, use_cache: bool = True) -> bytes:
        cache_key = f"{accept} {url}"
        cache = self.cache if use_cache else None
        if cache is not None:
            hit = cache.get(cache_key)
            if hit is not None:
                return hit
        for attempt in range(3):
            try:
                self.calls += 1
                resp = self.transport(url, self._headers(accept, api), self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise GitHubError(f"네트워크 오류: {exc} - 인터넷·프록시 설정을 확인하세요") from exc
            if resp.status == 200:
                if cache is not None:
                    cache.set(cache_key, resp.body)
                return resp.body
            if resp.status == 404:
                raise NotFoundError(f"찾을 수 없음: {url}")
            if resp.status == 401:
                raise GitHubError("GitHub 토큰이 거부되었습니다(401). GITHUB_TOKEN 값·만료일을 확인하세요")
            if resp.status in (403, 429):
                wait = self._wait_seconds(resp)
                if wait is None:
                    raise GitHubError(f"접근 거부({resp.status}): {_api_message(resp.body)}")
                if wait > self.max_wait or attempt == 2:
                    hint = "" if self.token else " 토큰(GITHUB_TOKEN)을 설정하면 한도가 늘어납니다."
                    raise RateLimitError(f"GitHub 호출 한도 초과 - 약 {int(wait)}초 뒤 다시 시도하세요.{hint}")
                self.log(f"[대기] GitHub 호출 한도 도달 - {int(wait)}초 기다린 뒤 다시 시도합니다")
                self.sleep(wait)
                continue
            if resp.status == 422:
                raise GitHubError(f"검색어를 GitHub 가 거부했습니다(422): {_api_message(resp.body)}")
            raise GitHubError(f"GitHub 응답 오류({resp.status}): {_api_message(resp.body)}")
        raise GitHubError("재시도 횟수를 넘었습니다")  # pragma: no cover - 루프 안에서 항상 반환/예외

    def get_json(self, url: str, use_cache: bool = True) -> dict:
        data = json.loads(self.get(url, use_cache=use_cache).decode("utf-8"))
        if not isinstance(data, dict):
            raise GitHubError("예상하지 못한 응답 형식")
        return data

    # ---- 고수준 ---------------------------------------------------------------
    def rate_limit(self) -> dict[str, int]:
        """현재 호출 한도(캐시 안 함, 이 호출 자체는 한도를 쓰지 않음). {'search': 30, 'core': 5000} 형태."""
        res = self.get_json(f"{API}/rate_limit", use_cache=False).get("resources") or {}
        return {k: int((res.get(k) or {}).get("limit") or 0) for k in ("search", "core")}

    def search_repositories(self, query: str, sort: str = "stars", per_page: int = 100, page: int = 1) -> dict:
        params = {"q": query, "sort": sort, "order": "desc", "per_page": str(per_page), "page": str(page)}
        return self.get_json(f"{API}/search/repositories?{urllib.parse.urlencode(params)}")

    def get_repository(self, full_name: str) -> dict:
        """저장소 메타데이터. 검색 API(repo: 한정자)로 가져와 목록 결과와 같은 필드를 쓴다."""
        owner_repo = full_name.strip().strip("/")
        if owner_repo.count("/") != 1:
            raise GitHubError(f"'owner/repo' 형식이어야 합니다: {full_name}")
        data = self.search_repositories(f"repo:{owner_repo}", per_page=1)
        items = data.get("items") or []
        if not items:
            raise NotFoundError(f"저장소를 찾을 수 없습니다(비공개이거나 이름이 틀림): {owner_repo}")
        return items[0]

    def get_readme(self, full_name: str) -> str | None:
        """README 원문. raw.githubusercontent.com 의 README.md 를 먼저 시도(API 한도 절약)하고,
        없으면 API(/readme, 파일명 자동 판별)로 받는다. 끝내 없으면 None."""
        quoted = urllib.parse.quote(full_name.strip("/"), safe="/")
        try:
            body = self.get(f"{RAW}/{quoted}/HEAD/README.md", accept="text/plain", api=False)
        except NotFoundError:
            try:
                body = self.get(f"{API}/repos/{quoted}/readme", accept="application/vnd.github.raw+json")
            except NotFoundError:
                return None
        return body[:MAX_README_BYTES].decode("utf-8", "replace")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
