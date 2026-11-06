"""분야(카테고리) 정의 읽기와 사용자 입력 → 분야 해석."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

# GitHub 검색은 AND/OR/NOT 연산자를 5개까지만 허용한다 → OR 로 묶을 수 있는 토픽은 6개.
MAX_SEARCH_TOPICS = 6

_COMPACT_DROP = re.compile(r"[\s\-_·.,/]+")
_ASCII_TOKEN = re.compile(r"[a-z0-9+#]+(?:-[a-z0-9+#]+)*")
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


class CategoryError(ValueError):
    """분야 정의 파일이 잘못되었거나, 입력을 분야로 해석할 수 없을 때."""


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    topics: tuple[str, ...]
    keywords: tuple[str, ...]
    aliases: tuple[str, ...]

    @property
    def search_topics(self) -> tuple[str, ...]:
        return self.topics[:MAX_SEARCH_TOPICS]


def compact(text: str) -> str:
    """소문자화하고 공백·하이픈·밑줄·가운뎃점을 지운다. '영상 만들기' → '영상만들기'."""
    return _COMPACT_DROP.sub("", text.lower())


def has_non_ascii(text: str) -> bool:
    return bool(_NON_ASCII.search(text))


def _as_str_tuple(value: object, field: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise CategoryError(f"분야 '{key}': {field} 는 비어 있지 않은 문자열 목록이어야 합니다")
    return tuple(v.strip() for v in value)


def parse_categories(text: str) -> list[Category]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CategoryError(f"분야 파일 TOML 문법 오류: {exc}") from exc
    raw = data.get("category")
    if not isinstance(raw, list) or not raw:
        raise CategoryError("분야 파일에 [[category]] 항목이 없습니다")
    out: list[Category] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise CategoryError("[[category]] 항목 형식이 잘못되었습니다")
        key = item.get("key")
        name = item.get("name")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", key):
            raise CategoryError(f"분야 key 는 영문 소문자·숫자·하이픈이어야 합니다: {key!r}")
        if key in seen:
            raise CategoryError(f"분야 key 중복: {key}")
        if not isinstance(name, str) or not name.strip():
            raise CategoryError(f"분야 '{key}': name 이 필요합니다")
        seen.add(key)
        out.append(
            Category(
                key=key,
                name=name.strip(),
                topics=_as_str_tuple(item.get("topics"), "topics", key),
                keywords=_as_str_tuple(item.get("keywords"), "keywords", key),
                aliases=_as_str_tuple(item.get("aliases", []) or [key], "aliases", key),
            )
        )
    return out


def load_categories(path: str | Path | None = None) -> list[Category]:
    if path is None:
        text = resources.files("ghrank").joinpath("categories.toml").read_text(encoding="utf-8")
    else:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise CategoryError(f"분야 파일을 읽을 수 없습니다: {path} ({exc})") from exc
    return parse_categories(text)


def _alias_hits(query: str, cat: Category) -> bool:
    q_compact = compact(query)
    tokens = set(_ASCII_TOKEN.findall(query.lower()))
    tokens |= {t.replace("-", "") for t in tokens}
    for alias in (cat.key, *cat.aliases):
        a = compact(alias)
        if not a:
            continue
        if has_non_ascii(a):
            # 한글 별칭은 조사가 붙어도 잡히도록 부분 일치("영상을" ⊃ "영상")
            if a in q_compact:
                return True
        elif a in tokens or a == q_compact or (len(a) >= 6 and a in q_compact):
            # 짧은 영문 별칭(ui, 3d …)은 단어 단위로만 일치시켜 'build' 속 'ui' 같은 오탐을 막는다
            return True
    return False


def match_categories(query: str, categories: list[Category]) -> list[Category]:
    """입력에 해당하는 분야들(정의 순서 유지). 없으면 빈 목록."""
    return [c for c in categories if _alias_hits(query, c)]


def resolve_category(name: str, categories: list[Category]) -> Category:
    """`top` 명령의 인자 하나를 분야 하나로 해석한다. 모호하거나 없으면 CategoryError."""
    by_key = {c.key: c for c in categories}
    key = name.strip().lower()
    if key in by_key:
        return by_key[key]
    exact = [c for c in categories if any(compact(a) == compact(name) for a in c.aliases)]
    if len(exact) == 1:
        return exact[0]
    hits = exact or match_categories(name, categories)
    if len(hits) == 1:
        return hits[0]
    keys = ", ".join(c.key for c in categories)
    if not hits:
        raise CategoryError(f"'{name}' 에 해당하는 분야가 없습니다. 가능한 분야: {keys}  (자유 검색은 ghrank find)")
    cands = ", ".join(f"{c.key}({c.name})" for c in hits)
    raise CategoryError(f"'{name}' 이(가) 여러 분야에 해당합니다: {cands}. key 로 지정해 주세요.")
