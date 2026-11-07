"use strict";
// ghrank 화면. 외부 텍스트(README·설명·주의 문구)는 textContent 로만 넣는다 — HTML 문자열로 끼워 넣지 않는다.

const API_HEADERS = { "X-Ghrank": "1" };
const OPTION_IDS = ["opt-n", "opt-sort", "opt-active", "opt-min-stars", "opt-lang", "opt-lists", "opt-loose"];

const $ = (id) => document.getElementById(id);

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem("ghrank:" + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("ghrank:" + key, JSON.stringify(value));
    } catch {
      /* 저장 못 해도 동작에는 지장 없음 */
    }
  },
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function safeUrl(value, githubOnly = false) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    if (githubOnly && url.hostname !== "github.com") return null;
    return url.href;
  } catch {
    return null;
  }
}

function extLink(href, text) {
  return el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
}

// 문장 속 http(s) 주소만 링크로 바꾼다(나머지는 텍스트).
function linkify(text) {
  const parts = String(text).split(/(https?:\/\/[^\s)]+)/g);
  return parts.map((part) => {
    const href = /^https?:\/\//.test(part) ? safeUrl(part) : null;
    return href ? extLink(href, part) : document.createTextNode(part);
  });
}

const fmt = new Intl.NumberFormat("ko-KR");

async function api(path, params, options = {}) {
  const query = params ? "?" + new URLSearchParams(params).toString() : "";
  let res;
  try {
    res = await fetch("/api/" + path + query, { headers: API_HEADERS, cache: "no-store", ...options });
  } catch {
    throw new Error("ghrank 화면 프로그램에 연결할 수 없습니다. 바탕화면 아이콘(또는 ghrank web)으로 다시 실행하세요.");
  }
  const type = res.headers.get("Content-Type") || "";
  if (!res.ok) {
    let message = `오류가 났습니다 (${res.status})`;
    if (type.includes("json")) {
      try {
        const body = await res.json();
        if (body.error) message = body.error;
      } catch {
        /* 본문이 JSON 이 아니면 기본 문구 */
      }
    }
    throw new Error(message);
  }
  return type.includes("json") ? res.json() : res.text();
}

// ---------------------------------------------------------------------------
// 상태 표시
// ---------------------------------------------------------------------------
function setState(kind, message) {
  const box = $("state");
  box.className = "state" + (kind ? " " + kind : "");
  box.textContent = message || "";
}

let busy = false;
function setBusy(value) {
  busy = value;
  document.querySelectorAll("button.chip, #find-form button, #guide-form button, .export-btn").forEach((b) => {
    b.disabled = value;
  });
}

async function loadStatus() {
  const badge = $("token-status");
  try {
    const s = await api("status");
    $("version").textContent = "ghrank " + s.version;
    if (s.error) {
      badge.className = "badge bad";
      badge.textContent = "토큰 오류";
      badge.title = s.error;
    } else if (s.token) {
      badge.className = "badge ok";
      badge.textContent = `토큰 사용 중 · 검색 분당 ${s.limits.search}회`;
      badge.title = `일반 조회 시간당 ${fmt.format(s.limits.core)}회`;
    } else {
      badge.className = "badge warn";
      badge.textContent = `토큰 없음 · 검색 분당 ${s.limits.search}회`;
      badge.title = "환경 변수 GITHUB_TOKEN 을 설정하면 한도가 늘어납니다";
    }
  } catch (err) {
    badge.className = "badge bad";
    badge.textContent = "연결 끊김";
    badge.title = err.message;
  }
}

// ---------------------------------------------------------------------------
// 조건
// ---------------------------------------------------------------------------
function readOptions() {
  const params = { n: $("opt-n").value, sort: $("opt-sort").value };
  if ($("opt-active").value) params.active_days = $("opt-active").value;
  const minStars = $("opt-min-stars").value.trim();
  if (minStars) params.min_stars = minStars;
  const lang = $("opt-lang").value.trim();
  if (lang) params.lang = lang;
  if ($("opt-lists").checked) params.include_lists = "1";
  if ($("opt-loose").checked) params.loose = "1";
  return params;
}

function describeOptions() {
  const parts = [`${$("opt-n").value}개`, $("opt-sort").selectedOptions[0].textContent];
  if ($("opt-active").value) parts.push($("opt-active").selectedOptions[0].textContent);
  if ($("opt-min-stars").value.trim()) parts.push(`스타 ${fmt.format(Number($("opt-min-stars").value))}+`);
  if ($("opt-lang").value.trim()) parts.push($("opt-lang").value.trim());
  if ($("opt-lists").checked) parts.push("링크 모음 포함");
  if ($("opt-loose").checked) parts.push("관련성 필터 끔");
  $("options-summary").textContent = "· " + parts.join(" · ");
}

function saveOptions() {
  const saved = {};
  for (const id of OPTION_IDS) {
    const input = $(id);
    saved[id] = input.type === "checkbox" ? input.checked : input.value;
  }
  store.set("options", saved);
  describeOptions();
}

function restoreOptions() {
  const saved = store.get("options", {});
  for (const id of OPTION_IDS) {
    if (!(id in saved)) continue;
    const input = $(id);
    if (input.type === "checkbox") input.checked = Boolean(saved[id]);
    else input.value = saved[id];
  }
  for (const id of OPTION_IDS) $(id).addEventListener("change", saveOptions);
  describeOptions();
}

// ---------------------------------------------------------------------------
// 탭
// ---------------------------------------------------------------------------
const TABS = ["top", "find", "guide"];

function selectTab(name, focus = false) {
  for (const tab of TABS) {
    const on = tab === name;
    $("tab-" + tab).setAttribute("aria-selected", String(on));
    $("tab-" + tab).tabIndex = on ? 0 : -1;
    $("panel-" + tab).hidden = !on;
  }
  $("options").hidden = name === "guide";
  store.set("tab", name);
  if (focus) $("tab-" + name).focus();
}

function setupTabs() {
  TABS.forEach((name, index) => {
    const tab = $("tab-" + name);
    tab.addEventListener("click", () => selectTab(name));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      const step = event.key === "ArrowRight" ? 1 : -1;
      selectTab(TABS[(index + step + TABS.length) % TABS.length], true);
    });
  });
  selectTab(store.get("tab", "top"));
}

// ---------------------------------------------------------------------------
// 결과 그리기
// ---------------------------------------------------------------------------
function codeBlock(block) {
  const copyBtn = el("button", { type: "button", class: "btn small", text: "복사" });
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(block.code);
      copyBtn.textContent = "복사됨";
    } catch {
      copyBtn.textContent = "복사 실패";
    }
    setTimeout(() => (copyBtn.textContent = "복사"), 1500);
  });
  const label = [block.lang, block.source ? `README '${block.source}' 절` : ""].filter(Boolean).join(" · ");
  return el(
    "div",
    { class: "code" },
    el("div", { class: "code-head" }, el("span", { text: label || "코드" }), copyBtn),
    el("pre", {}, el("code", { text: block.code })),
    block.truncated ? el("div", { class: "truncated", text: "… 길어서 일부만 보여 줍니다. 전체는 README 원문을 확인하세요." }) : null,
  );
}

function renderGuide(container, data, shownCaveats = []) {
  const g = data.guide;
  container.replaceChildren();
  for (const [title, blocks] of [["설치", g.install], ["사용", g.usage]]) {
    if (!blocks.length) continue;
    container.append(el("h3", { text: title }), ...blocks.map(codeBlock));
  }
  const extra = (data.caveats || []).filter((c) => !shownCaveats.includes(c));
  if (extra.length) {
    container.append(el("h3", { text: "추가 주의" }), el("ul", { class: "caveats" }, extra.map((c) => el("li", { text: c }))));
  }
  if (g.notes.length) {
    container.append(el("h3", { text: "참고" }), el("ul", { class: "list" }, g.notes.map((n) => el("li", {}, linkify(n)))));
  }
  if (!container.childElementCount) container.append(el("p", { class: "muted", text: "README 에서 정리할 내용을 찾지 못했습니다." }));
}

function repoCard(repo, rank, { openGuide = null } = {}) {
  const [owner, name] = repo.full_name.split("/");
  const href = safeUrl(repo.url, true);
  const title = href
    ? el("a", { class: "repo-name", href, target: "_blank", rel: "noopener noreferrer" }, owner + "/", el("strong", { text: name }))
    : el("span", { class: "repo-name" }, owner + "/", el("strong", { text: name }));
  const meta = [
    repo.language || "언어 미표기",
    repo.license || "라이선스 없음",
    repo.pushed_at ? "마지막 푸시 " + repo.pushed_at.slice(0, 10) : null,
    repo.score
      ? `추천점수 ${repo.score.score} (인기 ${repo.score.popularity} · 증가세 ${repo.score.momentum} · 최근성 ${repo.score.freshness})`
      : null,
  ].filter(Boolean);
  const caveats = repo.caveats || [];
  const guideBox = el("div", { class: "guide", hidden: true });
  const guideBtn = el("button", { type: "button", class: "btn small", "aria-expanded": "false", text: "설치·사용법 보기" });

  async function toggleGuide() {
    const open = guideBtn.getAttribute("aria-expanded") === "true";
    if (open) {
      guideBox.hidden = true;
      guideBtn.setAttribute("aria-expanded", "false");
      guideBtn.textContent = "설치·사용법 보기";
      return;
    }
    if (!guideBox.dataset.loaded) {
      guideBtn.disabled = true;
      guideBtn.textContent = "README 읽는 중…";
      try {
        renderGuide(guideBox, await api("guide", { repo: repo.full_name }), caveats);
        guideBox.dataset.loaded = "1";
      } catch (err) {
        guideBox.replaceChildren(el("div", { class: "error-line", text: err.message }));
      } finally {
        guideBtn.disabled = false;
      }
    }
    guideBox.hidden = false;
    guideBtn.setAttribute("aria-expanded", "true");
    guideBtn.textContent = "접기";
  }
  guideBtn.addEventListener("click", toggleGuide);

  const card = el(
    "li",
    { class: "card" },
    el("div", { class: "rank", text: rank }),
    el(
      "div",
      { class: "card-main" },
      el("div", { class: "title-row" }, title, el("span", { class: "stars", title: "GitHub 스타", text: "★ " + fmt.format(repo.stars) })),
      repo.description ? el("p", { class: "desc", text: repo.description }) : null,
      el("div", { class: "meta" }, meta.map((m) => el("span", { text: m }))),
      caveats.length ? el("ul", { class: "caveats" }, caveats.map((c) => el("li", { text: c }))) : null,
      el("div", { class: "actions" }, guideBtn, href ? extLink(href, "GitHub 에서 열기") : null),
      guideBox,
    ),
  );
  if (openGuide) {
    renderGuide(guideBox, openGuide, caveats);
    guideBox.dataset.loaded = "1";
    guideBox.hidden = false;
    guideBtn.setAttribute("aria-expanded", "true");
    guideBtn.textContent = "접기";
  }
  return card;
}

function summaryText(r) {
  const dropped = [];
  if (r.dropped_lists) dropped.push(`목록형 ${r.dropped_lists}개`);
  if (r.dropped_irrelevant) dropped.push(`관련성 낮음 ${r.dropped_irrelevant}개`);
  const when = new Date(r.fetched_at).toLocaleString("ko-KR");
  return `GitHub 검색 결과 ${fmt.format(r.total_count)}개 중 상위 ${r.scanned}개 검토` +
    (dropped.length ? ` · 제외: ${dropped.join(", ")}` : "") + ` · ${when} 조회`;
}

function downloadName(params) {
  const label = (params.category || params.q || "report").replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 40);
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `ghrank-${label}-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}.md`;
}

async function exportReport(params, button) {
  if (busy) return;
  setBusy(true);
  button.textContent = "보고서 만드는 중…";
  setState("loading", "저장소마다 README 를 읽어 설치·사용법을 정리하고 있습니다. 개수에 따라 수십 초 걸릴 수 있습니다.");
  try {
    const text = await api("report", params);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const a = el("a", { href: url, download: downloadName(params) });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    setState("", "");
  } catch (err) {
    setState("error", err.message);
  } finally {
    button.textContent = "보고서 저장(.md)";
    setBusy(false);
  }
}

function renderResults(data, params) {
  const root = $("results");
  root.replaceChildren();
  for (const note of data.notes) root.append(el("div", { class: "note" }, linkify(note)));
  for (const error of data.errors) root.append(el("div", { class: "error-line", text: error }));
  for (const r of data.rankings) {
    const exportBtn = el("button", { type: "button", class: "btn small export-btn", text: "보고서 저장(.md)" });
    const exportParams = r.category ? { ...params, mode: "top", category: r.category } : params;
    exportBtn.addEventListener("click", () => exportReport(exportParams, exportBtn));
    const section = el(
      "section",
      { class: "ranking" },
      el("div", { class: "ranking-head" },
        el("div", {}, el("h2", { text: r.title }), el("p", { class: "summary", text: summaryText(r) })),
        r.repos.length ? exportBtn : null),
    );
    if (!r.repos.length) {
      section.append(el("p", { class: "muted", text: "결과가 없습니다. 조건(최근 활동·최소 스타·주 언어)을 줄이거나 '관련성 필터 끄기'를 켜 보세요." }));
    } else {
      section.append(el("ol", { class: "cards" }, r.repos.map((repo) => repoCard(repo, repo.rank))));
    }
    root.append(section);
  }
}

// ---------------------------------------------------------------------------
// 동작
// ---------------------------------------------------------------------------
async function runSearch(params, label) {
  if (busy) return;
  setBusy(true);
  setState("loading", `${label} 조회 중… (GitHub 호출 한도에 걸리면 최대 1분 정도 기다릴 수 있습니다)`);
  try {
    const data = await api("search", params);
    setState("", "");
    renderResults(data, params);
  } catch (err) {
    setState("error", err.message);
  } finally {
    setBusy(false);
    loadStatus();
  }
}

async function loadCategories() {
  const box = $("cats");
  try {
    const cats = await api("categories");
    box.replaceChildren(
      ...cats.map((c) => {
        const chip = el("button", { type: "button", class: "chip", "aria-pressed": "false", title: "별칭: " + c.aliases.join(", "), text: c.name });
        chip.addEventListener("click", () => {
          box.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", String(b === chip)));
          runSearch({ ...readOptions(), mode: "top", category: c.key }, c.name);
        });
        return chip;
      }),
    );
  } catch (err) {
    setState("error", err.message);
  }
}

function setupForms() {
  $("find-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const q = $("q").value.trim();
    if (!q) return;
    const params = { ...readOptions(), mode: "find", q };
    if ($("raw").checked) params.raw = "1";
    runSearch(params, `'${q}'`);
  });

  $("guide-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const repo = $("repo").value.trim();
    if (!repo || busy) return;
    setBusy(true);
    setState("loading", "README 를 읽고 있습니다…");
    try {
      const data = await api("guide", { repo });
      setState("", "");
      $("results").replaceChildren(el("ol", { class: "cards" }, repoCard(data, "·", { openGuide: data })));
    } catch (err) {
      setState("error", err.message);
    } finally {
      setBusy(false);
    }
  });

  $("quit").addEventListener("click", async () => {
    if (!window.confirm("ghrank 화면을 종료할까요? 다시 쓰려면 바탕화면 아이콘을 실행하세요.")) return;
    try {
      await api("shutdown", null, { method: "POST" });
    } catch {
      /* 이미 꺼져 있어도 같은 안내 */
    }
    clearInterval(pingTimer);
    document.querySelector("main").replaceChildren(
      el("div", { class: "state" }, "ghrank 화면을 종료했습니다. 이 탭은 닫아도 됩니다."),
    );
    $("token-status").className = "badge";
    $("token-status").textContent = "종료됨";
  });
}

// 화면이 열려 있는 동안 서버에 신호를 보내 '쓰지 않을 때 자동 종료'가 작동하지 않게 한다.
let pingTimer = null;
function keepAlive() {
  pingTimer = setInterval(() => {
    api("ping").catch(() => {
      $("token-status").className = "badge bad";
      $("token-status").textContent = "연결 끊김";
    });
  }, 60_000);
}

document.addEventListener("DOMContentLoaded", () => {
  restoreOptions();
  setupTabs();
  setupForms();
  loadStatus();
  loadCategories();
  keepAlive();
});
