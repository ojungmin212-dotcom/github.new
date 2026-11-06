"""검색어 조립, 관련성·목록형 저장소 필터, 순위 산출."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from ghrank.categories import Category, has_non_ascii
from ghrank.github import GitHubClient, parse_time

SORT_KEYS = ("stars", "forks", "updated")
PER_PAGE = 100
MAX_PAGES = 3  # 검색 API 호출을 분야당 최대 3회로 제한(관련 없는 저장소를 걸러 내고도 N개가 안 될 때만 더 가져옴)
# 관련성: 이름·설명에 분야 키워드가 없을 때, 저장소 토픽 중 분야 토픽 비율이 이 값 이상이면 관련으로 본다.
# (노출을 위해 토픽을 20개씩 붙인 범용 저장소가 섞이는 것을 막기 위함)
TOPIC_RATIO_MIN = 0.25


@dataclass(frozen=True)
class Repo:
    full_name: str
    html_url: str
    description: str
    stars: int
    forks: int
    language: str | None
    license_spdx: str | None
    license_name: str | None
    topics: tuple[str, ...]
    pushed_at: datetime | None
    created_at: datetime | None
    archived: bool
    fork: bool
    size_kb: int
    open_issues: int
    homepage: str | None
    default_branch: str | None

    @classmethod
    def from_api(cls, d: dict) -> Repo:
        lic = d.get("license") or {}
        return cls(
            full_name=str(d.get("full_name", "")),
            html_url=str(d.get("html_url", "")),
            description=str(d.get("description") or "").strip(),
            stars=int(d.get("stargazers_count") or 0),
            forks=int(d.get("forks_count") or 0),
            language=d.get("language"),
            license_spdx=lic.get("spdx_id") if isinstance(lic, dict) else None,
            license_name=lic.get("name") if isinstance(lic, dict) else None,
            topics=tuple(d.get("topics") or ()),
            pushed_at=parse_time(d.get("pushed_at")),
            created_at=parse_time(d.get("created_at")),
            archived=bool(d.get("archived")),
            fork=bool(d.get("fork")),
            size_kb=int(d.get("size") or 0),
            open_issues=int(d.get("open_issues_count") or 0),
            homepage=(d.get("homepage") or None),
            default_branch=d.get("default_branch"),
        )

    def to_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "url": self.html_url,
            "description": self.description,
            "stars": self.stars,
            "forks": self.forks,
            "language": self.language,
            "license": self.license_spdx,
            "topics": list(self.topics),
            "pushed_at": self.pushed_at.isoformat() if self.pushed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived": self.archived,
            "size_kb": self.size_kb,
            "open_issues_and_prs": self.open_issues,
            "homepage": self.homepage,
        }


@dataclass(frozen=True)
class Filters:
    language: str | None = None
    min_stars: int | None = None
    active_days: int | None = None
    include_archived: bool = False
    include_lists: bool = False
    loose: bool = False
    sort: str = "stars"

    def qualifiers(self, today: date) -> list[str]:
        q: list[str] = []
        if not self.include_archived:
            q.append("archived:false")
        if self.language:
            lang = self.language.strip()
            q.append(f'language:"{lang}"' if " " in lang else f"language:{lang}")
        if self.min_stars is not None:
            q.append(f"stars:>={self.min_stars}")
        if self.active_days is not None:
            q.append(f"pushed:>={(today - timedelta(days=self.active_days)).isoformat()}")
        return q


def category_query(cat: Category, filters: Filters, today: date) -> str:
    topics = " OR ".join(cat.search_topics)
    return " ".join([topics, "in:topics", *filters.qualifiers(today)])


_QUALIFIER = re.compile(r"^-?[a-z]+:", re.I)


def free_query(text: str, filters: Filters, today: date) -> str:
    text = " ".join(text.split())
    if not text:
        raise ValueError("검색어가 비어 있습니다")
    words = text.split()
    has_in = any(w.lower().startswith("in:") for w in words)
    parts = [text] if has_in else [text, "in:name,description,topics"]
    # 사용자가 직접 넣은 한정자(language: 등)와 겹치는 기본 한정자는 빼서 충돌을 막는다
    user_quals = {w.split(":", 1)[0].lower().lstrip("-") for w in words if _QUALIFIER.match(w)}
    parts += [q for q in filters.qualifiers(today) if q.split(":", 1)[0] not in user_quals]
    return " ".join(parts)


_LIST_DESC = re.compile(
    r"\b(curated|awesome)\b.*\b(list|collection|resources)\b|^a list of\b|"
    r"(资源|资料|工具).{0,6}(列表|大全|合集|汇总|整理)|精选列表|링크 모음|자료 모음",
    re.I,
)
_LIST_TOPICS = {"awesome", "awesome-list", "awesome-lists", "curated-list", "paper-list", "papers-list"}
_LIST_NAME = re.compile(r"^awesome|(^|-)(papers|survey|books)(-|$)")


def is_list_repo(repo: Repo) -> bool:
    """awesome-* 같은 링크 모음·논문 목록 저장소(설치형 프로그램이 아님)."""
    name = repo.full_name.split("/")[-1].lower().replace("_", "-")
    if _LIST_NAME.search(name):
        return True
    if _LIST_TOPICS & {t.lower() for t in repo.topics}:
        return True
    return bool(_LIST_DESC.search(repo.description))


def _keyword_hit(keyword: str, text: str) -> bool:
    kw = keyword.lower()
    if has_non_ascii(kw):
        return kw in text
    # 영문 키워드는 단어 앞부분 일치: 'ui' 는 'ui', 'uikit' 에는 맞지만 'build' 에는 안 맞는다
    return re.search(r"(?<![a-z0-9])" + re.escape(kw), text) is not None


def is_relevant(repo: Repo, cat: Category) -> bool:
    text = f"{repo.full_name.split('/')[-1]} {repo.description}".lower().replace("_", "-")
    if any(_keyword_hit(k, text) for k in cat.keywords):
        return True
    if not repo.topics:
        return False
    cat_topics = {t.lower() for t in cat.topics}
    overlap = sum(1 for t in repo.topics if t.lower() in cat_topics)
    return overlap > 0 and overlap / len(repo.topics) >= TOPIC_RATIO_MIN


@dataclass
class Ranking:
    title: str
    query: str
    fetched_at: datetime
    repos: list[Repo]
    total_count: int
    scanned: int
    dropped_lists: int = 0
    dropped_irrelevant: int = 0
    category: Category | None = None
    notes: list[str] = field(default_factory=list)


def rank(
    client: GitHubClient,
    query: str,
    top: int,
    filters: Filters,
    title: str,
    category: Category | None = None,
    now: datetime | None = None,
) -> Ranking:
    if filters.sort not in SORT_KEYS:
        raise ValueError(f"정렬 기준은 {', '.join(SORT_KEYS)} 중 하나여야 합니다")
    now = now or datetime.now(UTC)
    result = Ranking(title=title, query=query, fetched_at=now, repos=[], total_count=0, scanned=0, category=category)
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        data = client.search_repositories(query, sort=filters.sort, per_page=PER_PAGE, page=page)
        items = data.get("items") or []
        result.total_count = int(data.get("total_count") or 0)
        if data.get("incomplete_results"):
            result.notes.append("GitHub 가 시간 제한으로 일부 결과만 돌려주었습니다(incomplete_results)")
        for item in items:
            repo = Repo.from_api(item)
            if repo.full_name in seen:
                continue
            seen.add(repo.full_name)
            result.scanned += 1
            if not filters.include_lists and is_list_repo(repo):
                result.dropped_lists += 1
                continue
            if category is not None and not filters.loose and not is_relevant(repo, category):
                result.dropped_irrelevant += 1
                continue
            result.repos.append(repo)
            if len(result.repos) >= top:
                return result
        if len(items) < PER_PAGE or page * PER_PAGE >= min(result.total_count, 1000):
            break
    return result
