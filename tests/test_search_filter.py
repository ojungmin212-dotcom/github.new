"""자유 검색 관련성 필터와 급성장 주의 (TTS 질문에서 영상 제작 도구가 섞이던 문제의 회귀 방지)."""

import json

import pytest
from conftest import NOW, FakeTransport, api_repo, search_page

from ghrank.categories import load_categories
from ghrank.cli import main
from ghrank.github import GitHubClient
from ghrank.guide import repo_caveats
from ghrank.ranking import Repo, query_terms, search_relevance

CATS = load_categories()

# 2026-11-08 실데이터에서 가져온 모양(설명·토픽)
OPENMONTAGE = dict(
    description="World's first open-source, agentic video production system. 12 production pipelines.",
    topics=["agent", "agentic-ai", "ai", "claude", "copilot", "cursor", "elevenlabs", "ffmpeg", "flux", "image-generation",
            "open-source", "openai", "python", "remotion", "stable-diffusion", "text-to-speech", "text-to-video",
            "video-generation", "video-production"],
)
VOICESTUDIO = dict(description="VoiceStudio is the open-source, fully-local ElevenLabs alternative — voice cloning, dubbing",
                   topics=["tts", "voice-cloning", "text-to-speech"])
PAPERLESS = dict(description="A community-supported supercharged document management system: scan, index and archive",
                 topics=["ai", "angular", "archiving", "django", "dms", "document-management", "document-management-system",
                         "llm", "machine-learning", "ocr", "optical-character-recognition", "pdf"])


def repo(name: str, **over) -> Repo:
    return Repo.from_api(api_repo(name, **over))


def test_query_terms_skip_qualifiers_and_operators():
    words, topics = query_terms('pdf OCR language:python -topic:java topic:"text-to-speech" OR -demo stars:>100')
    assert words == ["pdf", "ocr"] and topics == ["text-to-speech"]


def test_search_relevance_none_without_terms():
    assert search_relevance("language:rust stars:>1000", CATS) is None


def test_topic_query_links_to_category_keywords():
    f = search_relevance("topic:text-to-speech", CATS)
    assert f is not None and f.terms == ("text-to-speech",)
    assert "voice" in f.basis.keywords and "speech-recognition" in f.basis.topics  # 음성 분야와 연결


def test_tts_query_drops_video_tool_but_keeps_voice_tool():
    f = search_relevance("topic:text-to-speech", CATS)
    assert f is not None
    assert not f.matches(repo("OpenMontageInc/OpenMontage", **OPENMONTAGE))
    assert f.matches(repo("debpalash/VoiceStudio", **VOICESTUDIO))


def test_multi_term_query_keeps_repo_tagging_all_terms():
    f = search_relevance("pdf ocr", CATS)
    assert f is not None and f.matches(repo("paperless-ngx/paperless-ngx", **PAPERLESS))
    single = search_relevance("topic:pdf", CATS)
    assert single is not None and not single.matches(repo("x/y", description="archive tool", topics=["pdf"] + [f"t{i}" for i in range(9)]))


def test_plain_words_match_description():
    f = search_relevance("subtitle generator", CATS)
    assert f is not None and f.matches(repo("a/subs", description="Automatic subtitle generator", topics=[]))


def make_client(t: FakeTransport) -> GitHubClient:
    return GitHubClient(transport=t, sleep=lambda s: None, now=lambda: 1_000_000.0, log=lambda m: None)


def tts_transport() -> FakeTransport:
    t = FakeTransport()
    t.add("search/repositories", search_page([
        api_repo("OpenMontageInc/OpenMontage", 78_000, **OPENMONTAGE),
        api_repo("debpalash/VoiceStudio", 104_000, **VOICESTUDIO),
    ]))
    return t


def test_cli_find_filters_and_explains(capsys):
    assert main(["find", "-q", "topic:text-to-speech", "--raw", "--format", "json"], client=make_client(tts_transport()), now=NOW) == 0
    r = json.loads(capsys.readouterr().out)["rankings"][0]
    assert [x["full_name"] for x in r["repos"]] == ["debpalash/VoiceStudio"]
    assert r["dropped_irrelevant"] == 1 and any("--loose" in n for n in r["notes"])


def test_cli_find_loose_keeps_everything(capsys):
    main(["find", "-q", "topic:text-to-speech", "--raw", "--loose", "--format", "json"], client=make_client(tts_transport()), now=NOW)
    r = json.loads(capsys.readouterr().out)["rankings"][0]
    assert len(r["repos"]) == 2 and r["dropped_irrelevant"] == 0


def test_web_note_points_to_checkbox():
    from ghrank.web import App

    data = App(make_client(tts_transport()), CATS, now=lambda: NOW).search({"mode": "find", "q": "topic:text-to-speech", "raw": "1"})
    notes = data["rankings"][0]["notes"]
    assert any("관련성 필터 끄기" in n for n in notes) and not any("--loose" in n for n in notes)


def test_mcp_find_repos_loose():
    pytest.importorskip("mcp.server.mcpserver")
    import anyio
    from mcp.client.client import Client

    from ghrank.mcp_server import build_server

    server = build_server(make_client(tts_transport()), CATS)

    async def go(args):
        async with Client(server) as c:
            return await c.call_tool("find_repos", args)

    strict = anyio.run(go, {"query": "topic:text-to-speech", "raw": True})
    loose = anyio.run(go, {"query": "topic:text-to-speech", "raw": True, "loose": True})
    assert len(strict.structured_content["rankings"][0]["repos"]) == 1
    assert len(loose.structured_content["rankings"][0]["repos"]) == 2


# ---------------------------------------------------------------------------
# 급성장 주의
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("created", "stars", "expect_fast", "expect_new"),
    [
        ("2026-04-09T00:00:00Z", 104_843, True, False),   # 7개월에 10만 → 급성장
        ("2025-09-16T00:00:00Z", 41_747, False, False),   # 1년 넘음
        ("2026-05-01T00:00:00Z", 10_000, False, False),   # 1년 안이지만 연 환산 5만 미만
        ("2026-10-20T00:00:00Z", 50_000, False, True),    # 90일 미만은 기존 '신생' 주의만
    ],
)
def test_fast_growth_caveat(created, stars, expect_fast, expect_new):
    cav = " | ".join(repo_caveats(repo("o/r", stars=stars, created_at=created), NOW))
    assert ("급성장" in cav) is expect_fast
    assert ("일 된 저장소" in cav) is expect_new
