"""검색어 조립, 관련성·목록형 저장소 필터, 순위 산출."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from ghrank.categories import Category, has_non_ascii, match_categories
from ghrank.github import GitHubClient, parse_time

SORT_KEYS = ("stars", "forks", "updated", "score")
# "score"(추천 순)는 GitHub 정렬이 아니라, 스타 상위 후보(최대 100개)를 받아 아래 추천 점수로 다시 줄 세운다.
SCORE_POOL = 100
SCORE_WEIGHTS = {"popularity": 0.35, "momentum": 0.40, "freshness": 0.25}
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
    sort: str = "stars"
    # 이전 보고서와 비교했을 때만 채운다(None = 비교 안 함). full_name → {"prev_rank", "delta", "new"}
    changes: dict[str, dict] | None = None
    dropped_out: list[str] = field(default_factory=list)  # 이전 순위에는 있었는데 이번에 빠진 저장소


def apply_comparison(result: Ranking, previous: dict[str, int] | None) -> None:
    """이전 순위(full_name → 순위)와 비교해 신규 진입·상승·하락·이탈을 기록한다."""
    prev = previous or {}
    result.changes = {}
    for i, repo in enumerate(result.repos, 1):
        before = prev.get(repo.full_name)
        result.changes[repo.full_name] = {
            "prev_rank": before,
            "delta": None if before is None else before - i,
            "new": before is None,
        }
    now_names = {r.full_name for r in result.repos}
    result.dropped_out = [name for name, _ in sorted(prev.items(), key=lambda kv: kv[1]) if name not in now_names]


def recommend_score(repo: Repo, now: datetime) -> dict[str, float]:
    """추천 점수(0~100)와 구성 요소(각 0~1). 공식을 숨기지 않고 화면·보고서에 함께 보여 준다.

    - 인기 popularity  = log10(스타+1) / 6            (스타 100만 → 1)
    - 증가세 momentum  = log10(연평균 스타+1) / 5      (생성 이후 연 10만 스타 → 1, 오래된 레포 편향 완화)
    - 최근성 freshness = exp(-마지막 푸시 경과일 / 180) (오늘 1, 6개월 0.37, 1년 0.13)
    """
    popularity = min(1.0, math.log10(repo.stars + 1) / 6)
    created = repo.created_at or now
    age_years = max((now - created).days / 365.25, 0.5)  # 반년 미만 신생 레포의 과대평가 방지
    momentum = min(1.0, math.log10(repo.stars / age_years + 1) / 5)
    days = max(0, (now - repo.pushed_at).days) if repo.pushed_at else 3650
    freshness = math.exp(-days / 180)
    w = SCORE_WEIGHTS
    score = 100 * (w["popularity"] * popularity + w["momentum"] * momentum + w["freshness"] * freshness)
    return {
        "score": round(score, 1),
        "popularity": round(popularity, 3),
        "momentum": round(momentum, 3),
        "freshness": round(freshness, 3),
    }


_SEARCH_QUAL = re.compile(r"^(-?)([a-z_]+):(.+)$", re.I)


def query_terms(query: str) -> tuple[list[str], list[str]]:
    """자유 검색어 → (낱말, topic: 값). language:·stars: 같은 다른 한정자와 AND/OR/NOT, 제외(-) 조건은 뺀다."""
    words: list[str] = []
    topics: list[str] = []
    for token in query.split():
        m = _SEARCH_QUAL.match(token)
        if m:
            if not m.group(1) and m.group(2).lower() == "topic":
                topics.append(m.group(3).strip('"').lower())
            continue
        if token.upper() in ("AND", "OR", "NOT") or token.startswith("-"):
            continue
        word = token.strip('"').lower()
        if word:
            words.append(word)
    return words, topics


@dataclass(frozen=True)
class SearchFilter:
    """자유 검색 관련성 판정. basis 는 검색어+이어지는 분야의 키워드·토픽, terms 는 검색어 낱말."""

    basis: Category
    terms: tuple[str, ...]

    def matches(self, repo: Repo) -> bool:
        # 검색어 낱말이 2개 이상이고 저장소가 그 낱말을 모두 토픽으로 달았으면 관련(예: 'pdf ocr' → pdf·ocr 토픽).
        # 낱말 하나만 토픽으로 걸친 경우(토픽 19개 중 text-to-speech 하나)는 이 지름길을 쓰지 않는다.
        topics = {t.lower() for t in repo.topics}
        if len(self.terms) >= 2 and all(t in topics for t in self.terms):
            return True
        return is_relevant(repo, self.basis)


def search_relevance(query: str, categories: list[Category]) -> SearchFilter | None:
    """자유 검색의 관련성 기준. 검색어 자체 + 검색어와 이어지는 분야(토픽·별칭 일치)의 키워드·토픽을 합친다.
    예: 'topic:text-to-speech' → 음성 분야와 이어져, 설명에 voice·speech 등이 없고 토픽 수십 개 중
    하나로만 TTS 를 단 영상 제작 도구는 걸러진다. 낱말이 하나도 없으면(한정자만) None = 거르지 않음."""
    words, topics = query_terms(query)
    if not words and not topics:
        return None
    terms = set(words) | set(topics)
    related = [c for c in categories if terms & {t.lower() for t in c.topics}]
    related += [c for c in match_categories(query, categories) if c not in related]
    keywords = list(dict.fromkeys([*words, *topics, *(k for c in related for k in c.keywords)]))
    topic_set = list(dict.fromkeys([*topics, *words, *(t for c in related for t in c.topics)]))
    basis = Category(key="search", name="검색", topics=tuple(topic_set), keywords=tuple(keywords), aliases=())
    return SearchFilter(basis=basis, terms=tuple(dict.fromkeys([*words, *topics])))


def rank(
    client: GitHubClient,
    query: str,
    top: int,
    filters: Filters,
    title: str,
    category: Category | None = None,
    now: datetime | None = None,
    relevance: SearchFilter | None = None,
) -> Ranking:
    """relevance 를 주면 그 기준으로 관련성을 거르고(자유 검색), 없으면 category 기준(분야 순위)."""
    if filters.sort not in SORT_KEYS:
        raise ValueError(f"정렬 기준은 {', '.join(SORT_KEYS)} 중 하나여야 합니다")
    now = now or datetime.now(UTC)
    result = Ranking(title=title, query=query, fetched_at=now, repos=[], total_count=0, scanned=0, category=category,
                     sort=filters.sort)
    by_score = filters.sort == "score"
    want = max(top, SCORE_POOL) if by_score else top  # 추천 순은 후보를 넉넉히 모은 뒤 다시 줄 세운다
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        data = client.search_repositories(query, sort="stars" if by_score else filters.sort, per_page=PER_PAGE, page=page)
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
            if filters.loose:
                relevant = True
            elif relevance is not None:
                relevant = relevance.matches(repo)
            else:
                relevant = category is None or is_relevant(repo, category)
            if not relevant:
                result.dropped_irrelevant += 1
                continue
            result.repos.append(repo)
            if len(result.repos) >= want:
                break
        # 추천 순도 다음 쪽은 개수가 모자랄 때만 가져온다(검색 호출 수를 스타 순과 같게 유지)
        if len(result.repos) >= top or len(items) < PER_PAGE or page * PER_PAGE >= min(result.total_count, 1000):
            break
    if by_score:
        result.repos.sort(key=lambda r: recommend_score(r, now)["score"], reverse=True)
        result.notes.append(f"추천 순: 스타 상위 후보 {len(result.repos)}개를 인기·증가세·최근성 점수로 다시 정렬했습니다")
        result.repos = result.repos[:top]
    return result
