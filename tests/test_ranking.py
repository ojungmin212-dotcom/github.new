from datetime import date

import pytest
from conftest import api_repo, search_page

from ghrank.categories import load_categories
from ghrank.ranking import PER_PAGE, Filters, Repo, category_query, free_query, is_list_repo, is_relevant, rank

CATS = {c.key: c for c in load_categories()}
TODAY = date(2026, 11, 5)


def repo(name="o/r", **over) -> Repo:
    return Repo.from_api(api_repo(name, **over))


def test_category_query_qualifiers():
    q = category_query(CATS["image"], Filters(language="Python", min_stars=500, active_days=30), TODAY)
    assert q.startswith("text-to-image OR stable-diffusion")
    assert "in:topics" in q and "archived:false" in q
    assert "language:Python" in q and "stars:>=500" in q and "pushed:>=2026-10-06" in q


def test_category_query_include_archived_and_spaced_language():
    q = category_query(CATS["data"], Filters(include_archived=True, language="Jupyter Notebook"), TODAY)
    assert "archived:" not in q
    assert 'language:"Jupyter Notebook"' in q


def test_free_query_default_and_user_qualifiers():
    assert free_query("  pdf   ocr ", Filters(), TODAY) == "pdf ocr in:name,description,topics archived:false"
    q = free_query("ocr language:rust in:readme archived:true", Filters(language="python"), TODAY)
    assert "in:name" not in q  # 사용자가 in: 을 지정하면 기본값을 붙이지 않음
    assert "language:python" not in q and "archived:false" not in q
    with pytest.raises(ValueError):
        free_query("   ", Filters(), TODAY)


@pytest.mark.parametrize(
    ("name", "desc", "topics", "expected"),
    [
        ("o/awesome-stable-diffusion", "", [], True),
        ("o/Diffusion-Models-Papers-Survey-Taxonomy", "", [], True),
        ("o/tool", "A curated list of TTS resources", [], True),
        ("o/tool", "", ["awesome-list"], True),
        ("o/funNLP", "中英文敏感词…文本生成资源大列表", [], True),
        ("o/free-programming-books-zh_CN", "免费的计算机编程类中文书籍", [], True),
        ("o/todo-list", "A simple todo list app", [], False),
        ("o/paper-qa", "QA over scientific papers", [], False),
        ("o/ComfyUI", "diffusion model GUI", ["stable-diffusion"], False),
    ],
)
def test_is_list_repo(name, desc, topics, expected):
    assert is_list_repo(repo(name, description=desc, topics=topics)) is expected


def test_is_relevant_keyword_and_topic_ratio():
    image = CATS["image"]
    assert is_relevant(repo("o/x", description="Stable Diffusion web UI"), image)
    assert is_relevant(repo("o/x", description="AI 图像生成工具"), image)
    # 키워드가 없어도 저장소 토픽의 25% 이상이 분야 토픽이면 관련
    assert is_relevant(repo("o/x", description="Bring portraits to life!", topics=["stable-diffusion", "face", "gan", "art"]),
                       image)
    # 토픽을 20개 붙인 범용 저장소에 분야 토픽 1개 → 관련 아님
    many = ["stable-diffusion"] + [f"t{i}" for i in range(19)]
    assert not is_relevant(repo("o/x", description="LLM fine-tuning", topics=many), image)
    assert not is_relevant(repo("o/x", description="nothing here", topics=[]), image)


def test_short_keyword_word_boundary():
    fe = CATS["frontend"]
    assert is_relevant(repo("o/x", description="Beautiful UI components"), fe)
    assert not is_relevant(repo("o/x", description="build system for guides"), fe)


def test_rank_filters_lists_and_irrelevant(client, transport):
    items = [
        api_repo("a/awesome-image", 900, description="curated list"),
        api_repo("a/generic", 800, description="LLM tool", topics=["image-generation"] + [f"t{i}" for i in range(9)]),
        api_repo("a/sd-ui", 700, description="Stable Diffusion UI"),
        api_repo("a/upscaler", 600, description="image upscaler"),
    ]
    transport.add("search/repositories", search_page(items, total=4))
    r = rank(client, "q", top=12, filters=Filters(), title="t", category=CATS["image"])
    assert [x.full_name for x in r.repos] == ["a/sd-ui", "a/upscaler"]
    assert (r.scanned, r.dropped_lists, r.dropped_irrelevant, r.total_count) == (4, 1, 1, 4)


def test_rank_loose_and_include_lists_keep_everything(client, transport):
    items = [api_repo("a/awesome-x", 9, description="curated list"), api_repo("a/generic", 8, description="LLM")]
    transport.add("search/repositories", search_page(items))
    r = rank(client, "q", 12, Filters(loose=True, include_lists=True), "t", category=CATS["image"])
    assert len(r.repos) == 2


def test_rank_stops_at_top_and_paginates_when_filtered(client, transport):
    page1 = [api_repo(f"a/awesome-{i}", 1000 - i) for i in range(PER_PAGE)]  # 전부 목록형 → 다음 쪽 필요
    page2 = [api_repo(f"b/tool-{i}", 100 - i, description="image tool") for i in range(5)]
    transport.add("&page=1", search_page(page1, total=105))
    transport.add("&page=2", search_page(page2, total=105))
    r = rank(client, "q", top=3, filters=Filters(), title="t", category=CATS["image"])
    assert [x.full_name for x in r.repos] == ["b/tool-0", "b/tool-1", "b/tool-2"]
    assert sum("search/repositories" in u for u, _ in transport.requests) == 2


def test_rank_dedupes_and_stops_on_short_page(client, transport):
    items = [api_repo("a/x", 5, description="image"), api_repo("a/x", 5, description="image")]
    transport.add("search/repositories", search_page(items, total=2))
    r = rank(client, "q", 12, Filters(), "t", category=CATS["image"])
    assert len(r.repos) == 1 and r.scanned == 1
    assert len(transport.requests) == 1


def test_rank_incomplete_results_note_and_bad_sort(client, transport):
    from conftest import ok_json

    transport.add("search/repositories", ok_json({"total_count": 0, "incomplete_results": True, "items": []}))
    r = rank(client, "q", 12, Filters(), "t")
    assert r.notes and "incomplete" in r.notes[0]
    with pytest.raises(ValueError):
        rank(client, "q", 12, Filters(sort="best"), "t")


def test_repo_from_api_handles_nulls():
    r = Repo.from_api(api_repo("o/r", description=None, license=None, topics=None, pushed_at=None, homepage=""))
    assert r.description == "" and r.license_spdx is None and r.topics == () and r.pushed_at is None
    assert r.homepage is None
    assert r.to_dict()["license"] is None
