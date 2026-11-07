"""0.2 기능: 추천 순 · 순위 변동 비교 · Windows 토큰 · 정확도 회귀 기준."""

import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import NOW, FakeTransport, api_repo, search_page

from ghrank import github
from ghrank.cli import load_previous, main
from ghrank.github import GitHubClient
from ghrank.ranking import Filters, Ranking, Repo, apply_comparison, rank, recommend_score
from ghrank.render import change_label, md_ranking, ranking_dict, text_ranking


def repo(name="o/r", **over) -> Repo:
    return Repo.from_api(api_repo(name, **over))


def client(t: FakeTransport) -> GitHubClient:
    return GitHubClient(transport=t, sleep=lambda s: None, now=lambda: 1_000_000.0, log=lambda m: None)


# ---------------------------------------------------------------------------
# 추천 점수
# ---------------------------------------------------------------------------
def test_recommend_score_components():
    s = recommend_score(repo(stars=999_999, created_at="2025-11-07T00:00:00Z", pushed_at="2026-11-07T00:00:00Z"),
                        datetime(2026, 11, 7, tzinfo=UTC))
    assert s["popularity"] == pytest.approx(1.0, abs=1e-3)
    assert s["freshness"] == 1.0
    assert 0 < s["momentum"] <= 1 and 0 < s["score"] <= 100


def test_recommend_score_prefers_active_growing_over_old_stale():
    now = datetime(2026, 11, 7, tzinfo=UTC)
    old = repo("o/old", stars=60_000, created_at="2012-01-01T00:00:00Z", pushed_at="2023-01-01T00:00:00Z")
    new = repo("o/new", stars=30_000, created_at="2025-06-01T00:00:00Z", pushed_at="2026-11-06T00:00:00Z")
    assert recommend_score(new, now)["score"] > recommend_score(old, now)["score"]


def test_recommend_score_clamps_brand_new_repo_age():
    now = datetime(2026, 11, 7, tzinfo=UTC)
    week_old = repo(stars=50_000, created_at="2026-10-31T00:00:00Z")
    half_year = repo(stars=50_000, created_at="2026-05-09T00:00:00Z")
    # 반년 미만은 반년으로 계산 → 일주일 된 레포가 증가세 만점을 받지 않는다
    assert recommend_score(week_old, now)["momentum"] == pytest.approx(recommend_score(half_year, now)["momentum"], abs=0.01)


def test_recommend_score_missing_dates():
    s = recommend_score(repo(pushed_at=None, created_at=None), NOW)
    assert s["freshness"] < 0.001


def test_rank_by_score_reorders_and_uses_star_search(client_t=None):
    t = FakeTransport()
    items = [
        api_repo("a/old", 9000, description="image tool", created_at="2010-01-01T00:00:00Z", pushed_at="2020-01-01T00:00:00Z"),
        api_repo("a/new", 5000, description="image tool", created_at="2026-01-01T00:00:00Z", pushed_at="2026-11-01T00:00:00Z"),
    ]
    t.add("search/repositories", search_page(items))
    r = rank(client(t), "q", 1, Filters(sort="score"), "t", now=NOW)
    assert [x.full_name for x in r.repos] == ["a/new"]
    assert "sort=stars" in t.requests[0][0] and r.sort == "score"
    assert any("추천 순" in n for n in r.notes)


# ---------------------------------------------------------------------------
# 순위 변동
# ---------------------------------------------------------------------------
def ranking_of(*names: str) -> Ranking:
    return Ranking(title="t", query="q", fetched_at=NOW, repos=[repo(n) for n in names], total_count=3, scanned=3)


def test_apply_comparison_marks_new_up_down_same_and_dropped():
    r = ranking_of("a/up", "a/same", "a/new", "a/down")
    apply_comparison(r, {"a/same": 2, "a/up": 3, "a/down": 1, "a/gone": 4, "a/gone2": 5})
    assert r.changes is not None
    assert change_label(r.changes["a/up"]) == "▲2"
    assert change_label(r.changes["a/same"]) == "="
    assert change_label(r.changes["a/new"]) == "NEW"
    assert change_label(r.changes["a/down"]) == "▼3"
    assert r.dropped_out == ["a/gone", "a/gone2"]
    assert change_label(None) == ""


def test_renderers_show_changes_and_scores():
    r = ranking_of("a/x", "a/y")
    r.sort = "score"
    apply_comparison(r, {"a/y": 1})
    text = text_ranking(r, now=NOW)
    assert "a/x [NEW] [추천 " in text and "a/y [▼1]" in text
    md = md_ranking(r, now=NOW)
    assert "| # | 변동 | 저장소 | ★ | 추천점수 |" in md and "| 1 | NEW | [a/x]" in md
    d = ranking_dict(r, now=NOW)
    assert d["sort"] == "score" and d["repos"][0]["change"]["new"] is True and "score" in d["repos"][0]
    plain = ranking_of("a/x")
    assert "변동" not in md_ranking(plain, now=NOW) and "change" not in ranking_dict(plain, now=NOW)["repos"][0]


def test_dropped_out_rendered():
    r = ranking_of("a/x")
    apply_comparison(r, {"a/x": 1, "a/gone": 2})
    assert "순위에서 빠짐: a/gone" in text_ranking(r, now=NOW)
    assert "`a/gone`" in md_ranking(r, now=NOW)


def test_cli_compare_end_to_end(tmp_path, capsys):
    t1 = FakeTransport()
    t1.add("search/repositories", search_page([api_repo("a/one", 9, description="image"), api_repo("a/two", 8, description="image")]))
    prev = tmp_path / "prev.json"
    assert main(["top", "-q", "image", "--format", "json", "-o", str(prev)], client=client(t1), now=NOW) == 0
    t2 = FakeTransport()
    t2.add("search/repositories", search_page([api_repo("a/two", 9, description="image"), api_repo("a/three", 8, description="image")]))
    code = main(["top", "-q", "image", "video", "--compare", str(prev), "--format", "md"], client=client(t2), now=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert "| 1 | ▲1 | [a/two]" in out and "| 2 | NEW | [a/three]" in out and "`a/one`" in out
    assert "이전 결과에 이 분야가 없어" in out  # video 는 이전 결과에 없음


def test_load_previous_errors(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        load_previous(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"x": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="형식이 아닙니다"):
        load_previous(wrong)
    with pytest.raises(ValueError):
        load_previous(tmp_path / "missing.json")


def test_cli_compare_bad_file_exit_code(tmp_path, capsys):
    t = FakeTransport()
    t.add("search/repositories", search_page([]))
    assert main(["top", "-q", "image", "--compare", str(tmp_path / "none.json")], client=client(t), now=NOW) == 1
    assert "비교할 이전 결과" in capsys.readouterr().err


def test_load_previous_skips_garbage_entries(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"rankings": [1, {"title": "x", "repos": "nope"},
                                          {"category": "image", "repos": [{"full_name": "a/b", "rank": 2}, "junk"]}]}),
                 encoding="utf-8")
    assert load_previous(p) == {"x": {}, "image": {"a/b": 2}}


# ---------------------------------------------------------------------------
# Windows 사용자 환경 변수에서 토큰 읽기
# ---------------------------------------------------------------------------
def fake_winreg(values: dict[str, str]):
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER = object()

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def open_key(root, path):
        assert path == "Environment"
        return Key()

    def query(key, name):
        if name not in values:
            raise OSError("not found")
        return values[name], 1

    mod.OpenKey = open_key
    mod.QueryValueEx = query
    return mod


def test_windows_user_env_reads_registry(monkeypatch):
    monkeypatch.setattr(github.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg({"GITHUB_TOKEN": "  ghp_x  "}))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert github.windows_user_env("GITHUB_TOKEN") == "ghp_x"
    assert github.windows_user_env("NOPE") is None
    assert GitHubClient.from_env().token == "ghp_x"


def test_windows_user_env_other_platforms(monkeypatch):
    monkeypatch.setattr(github.sys, "platform", "linux")
    assert github.windows_user_env("GITHUB_TOKEN") is None


def test_process_env_wins_over_registry(monkeypatch):
    monkeypatch.setattr(github.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg({"GITHUB_TOKEN": "from-registry"}))
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert GitHubClient.from_env().token == "from-env"


# ---------------------------------------------------------------------------
# 정확도 회귀 기준(F1): 정답 데이터로 잰 분야 분류 정확도가 떨어지면 실패
# ---------------------------------------------------------------------------
def _run_eval_module():
    evals = Path(__file__).resolve().parent.parent / "evals"
    sys.path.insert(0, str(evals))
    try:
        import run_eval  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(evals))
    return run_eval


def test_category_accuracy_does_not_regress():
    run_eval = _run_eval_module()
    summary = run_eval.category_summary(run_eval.eval_categories())
    assert summary["precision_at_12"] >= 0.79        # 2026-11-07 측정 79.3%
    assert summary["good_recall"] >= 0.83            # 좋은 저장소를 과하게 걸러 내지 않음
    assert summary["precision_at_12"] > summary["baseline_precision_at_12"] + 0.15  # 필터가 실제로 도움이 됨


def test_install_eval_metrics_with_fake_readmes():
    run_eval = _run_eval_module()
    results = [
        run_eval.InstallResult("a", "commands", "commands", 2, 2, []),
        run_eval.InstallResult("b", "commands", "none", 1, 0, ["pip install b"]),
        run_eval.InstallResult("c", "download", "commands", 0, 0, []),
    ]
    s = run_eval.install_summary(results)
    assert s["kind_accuracy"] == pytest.approx(1 / 3)
    assert s["command_repos_any_hit"] == 0.5 and s["command_recall"] == pytest.approx(2 / 3) and s["false_commands"] == 1.0
    assert run_eval.norm("$  pip   install x ") == "pip install x"
