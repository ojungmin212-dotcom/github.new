import pytest

from ghrank.categories import (
    MAX_SEARCH_TOPICS,
    CategoryError,
    load_categories,
    match_categories,
    parse_categories,
    resolve_category,
)
from ghrank.ranking import Filters, category_query

CATS = load_categories()


def keys(cats):
    return [c.key for c in cats]


def test_builtin_categories_are_valid():
    assert len(CATS) >= 12
    assert len(set(keys(CATS))) == len(CATS)
    for c in CATS:
        assert c.topics and c.keywords and c.aliases
        assert len(c.search_topics) <= MAX_SEARCH_TOPICS


def test_category_query_respects_github_operator_limit():
    # GitHub 검색: AND/OR/NOT 연산자 최대 5개
    for c in CATS:
        q = category_query(c, Filters(), today=__import__("datetime").date(2026, 11, 5))
        assert q.split().count("OR") <= 5, c.key


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("이미지", ["image"]),
        ("이미지 레포", ["image"]),
        ("영상 만들기", ["video"]),
        ("동영상을 편집하는 프로그램", ["video"]),
        ("음성 합성", ["audio"]),
        ("tts", ["audio"]),
        ("Text-To-Image", ["image"]),
        ("3d", ["3d"]),
        ("크롤링", ["automation"]),
    ],
)
def test_match_categories(query, expected):
    assert keys(match_categories(query, CATS)) == expected


def test_short_ascii_alias_needs_whole_word():
    # 'ui' 가 'build', 'guide' 안에서 잡히면 안 된다
    assert "frontend" not in keys(match_categories("build guide", CATS))
    assert "frontend" in keys(match_categories("react ui kit", CATS))


def test_no_match_returns_empty():
    assert match_categories("zzqqxx", CATS) == []


def test_resolve_category_by_key_alias_and_errors():
    assert resolve_category("video", CATS).key == "video"
    assert resolve_category("영상", CATS).key == "video"
    assert resolve_category(" IMAGE ", CATS).key == "image"
    with pytest.raises(CategoryError, match="분야가 없습니다"):
        resolve_category("없는분야", CATS)


def test_resolve_category_ambiguous():
    cats = parse_categories(
        """
[[category]]
key = "a"
name = "A"
topics = ["x"]
keywords = ["x"]
aliases = ["공통어a"]
[[category]]
key = "b"
name = "B"
topics = ["y"]
keywords = ["y"]
aliases = ["공통어b"]
"""
    )
    with pytest.raises(CategoryError, match="여러 분야"):
        resolve_category("공통어a 공통어b", cats)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("not = [valid", "TOML"),
        ("x = 1", "category"),
        ('[[category]]\nkey = "Bad Key"\nname = "n"\ntopics=["a"]\nkeywords=["a"]', "key"),
        ('[[category]]\nkey = "a"\nname = ""\ntopics=["a"]\nkeywords=["a"]', "name"),
        ('[[category]]\nkey = "a"\nname = "n"\ntopics=[]\nkeywords=["a"]', "topics"),
        ('[[category]]\nkey="a"\nname="n"\ntopics=["a"]\nkeywords=["a"]\n[[category]]\nkey="a"\nname="m"\ntopics=["b"]\nkeywords=["b"]',
         "중복"),
    ],
)
def test_parse_categories_errors(toml, message):
    with pytest.raises(CategoryError, match=message):
        parse_categories(toml)


def test_aliases_default_to_key(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[[category]]\nkey = "k"\nname = "n"\ntopics=["t"]\nkeywords=["w"]\n', encoding="utf-8")
    (cat,) = load_categories(path)
    assert cat.aliases == ("k",)


def test_load_missing_file():
    with pytest.raises(CategoryError, match="읽을 수 없습니다"):
        load_categories("/nonexistent/categories.toml")
