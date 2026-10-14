"""브리핑 JSON → 모바일용 리포트 HTML (웹 뷰어 /report/{id} 시제품).

사용:
    python -m scripts.render_report_html output/briefing_xxx.json report.html [--standalone]

외부 기사 문장이 그대로 들어가므로 모든 텍스트는 html.escape로 이스케이프하고,
링크는 http(s) 주소만 허용한다.
"""

import argparse
import json
from html import escape
from pathlib import Path

from app.domain.strategic_questions import QUESTION_LABELS
from app.domain.sales_templates import load_sales_template_catalog

SIGNAL_LABELS = {"NONE": "근거 없음", "WEAK": "약함", "MODERATE": "보통", "STRONG": "강함", "VERY_STRONG": "매우 강함"}
SIGNAL_STEPS = ["NONE", "WEAK", "MODERATE", "STRONG", "VERY_STRONG"]
TIER_LABELS = {"A": "공식·공공", "B": "주요 언론", "C": "기타"}

STYLE = """
<style>
/* 레이아웃: 폰 한 손 스크롤용 단일 컬럼. 질문 3선을 맨 위에, 근거는 아래로 */
:root {
  --bg: #f3f6f8; --surface: #ffffff; --ink: #14232b; --muted: #5a6b74; --line: #d9e2e7;
  --accent: #0f6b7a; --accent-soft: #e2f1f3; --warn: #8a5a00; --warn-soft: #fbf0d9; --ok: #2f6b3a;
  --font-body: "IBM Plex Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f171b; --surface: #16222a; --ink: #e4ecef; --muted: #96a8b1; --line: #26363f;
  --accent: #5cc3d1; --accent-soft: #15333a; --warn: #f0c065; --warn-soft: #3a2e14; --ok: #8fd19e; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f171b; --surface: #16222a; --ink: #e4ecef; --muted: #96a8b1; --line: #26363f;
  --accent: #5cc3d1; --accent-soft: #15333a; --warn: #f0c065; --warn-soft: #3a2e14; --ok: #8fd19e; color-scheme: dark; }
body { background: var(--bg); color: var(--ink); font-family: var(--font-body); font-size: 15px; line-height: 1.6; }
.wrap { max-width: 640px; margin: 0 auto; padding-inline: 16px; padding-block: 0 48px; display: grid; gap: 20px; }
header.top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 2; background: var(--bg);
  border-bottom: 1px solid var(--line); padding-inline: 16px; }
header.top .in { max-width: 640px; margin: 0 auto; padding-block: 12px 10px; display: grid; gap: 8px; }
.eyebrow { font-size: 12px; letter-spacing: .06em; color: var(--muted); }
h1 { font-size: 22px; line-height: 1.3; margin: 0; text-wrap: balance; }
nav.jump { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; }
nav.jump a { flex: none; font-size: 13px; color: var(--accent); text-decoration: none; padding: 4px 10px;
  border: 1px solid var(--line); border-radius: 999px; background: var(--surface); }
nav.jump a:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
section { display: grid; gap: 10px; scroll-margin-top: 110px; }
h2 { font-size: 13px; letter-spacing: .08em; color: var(--muted); margin: 8px 0 0; font-weight: 600; }
.notice { background: var(--warn-soft); color: var(--warn); border-radius: 10px; padding: 10px 12px; font-size: 13px; }
.q { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px; display: grid; gap: 8px; }
.q.primary { border-color: var(--accent); }
.q-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.q-no { font-family: var(--font-mono); font-weight: 600; color: var(--accent); }
.q-type { font-size: 13px; font-weight: 600; }
.chip { font-family: var(--font-mono); font-size: 11.5px; padding: 1px 7px; border-radius: 6px;
  background: var(--accent-soft); color: var(--accent); text-decoration: none; }
.chip.warn { background: var(--warn-soft); color: var(--warn); font-family: var(--font-body); }
.q-text { font-size: 17px; line-height: 1.55; margin: 0; font-weight: 500; }
.q-intent { font-size: 13px; color: var(--muted); margin: 0; }
.q-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
button.copy { font: inherit; font-size: 13px; color: var(--accent); background: none; border: 1px solid var(--line);
  border-radius: 8px; padding: 4px 10px; cursor: pointer; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px; display: grid; gap: 8px; min-width: 0; }
.summary p { margin: 0; }
.meter { display: grid; grid-template-columns: repeat(5, 1fr); gap: 3px; }
.meter i { height: 6px; border-radius: 3px; background: var(--line); }
.meter i.on { background: var(--accent); }
.chain { margin: 0; padding-left: 18px; font-size: 13.5px; color: var(--muted); display: grid; gap: 4px; }
.src { display: grid; gap: 6px; padding-block: 12px; border-top: 1px solid var(--line); min-width: 0; }
.src:first-of-type { border-top: 0; }
.src-meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 12.5px; color: var(--muted); }
.src p { margin: 0; overflow-wrap: anywhere; }
.src a.out { font-size: 13px; color: var(--accent); overflow-wrap: anywhere; }
details { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
summary { cursor: pointer; font-weight: 600; font-size: 14px; }
pre.msg { white-space: pre-wrap; font-family: var(--font-body); font-size: 14px; margin: 10px 0 0; overflow-wrap: anywhere; }
.muted { color: var(--muted); font-size: 13px; }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
"""

SCRIPT = """
<script>
document.querySelectorAll("button.copy").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var text = btn.getAttribute("data-text");
    function done() { btn.textContent = "복사됨"; setTimeout(function () { btn.textContent = "질문 복사"; }, 1500); }
    function fallback() {
      var el = btn.closest(".q").querySelector(".q-text");
      var r = document.createRange(); r.selectNodeContents(el);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      btn.textContent = "선택됨 · 길게 눌러 복사";
    }
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
  });
});
</script>
"""


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _safe_url(url: str | None) -> str | None:
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def _value_prop_label(vp_id: str | None) -> str | None:
    if not vp_id:
        return None
    for category in load_sales_template_catalog().categories:
        vp = category.find_value_prop(vp_id)
        if vp:
            return vp.label
    return None


def _evidence_chips(ids: list[str]) -> str:
    return "".join(f'<a class="chip" href="#src-{_e(i)}">{_e(i)}</a>' for i in ids)


def render(briefing: dict, messenger_text: str | None = None) -> str:
    company = briefing["company"]
    name = company.get("resolved_name") or company["name"]
    sources = briefing.get("sources", [])
    questions = (briefing.get("strategic_questions") or {}).get("questions", [])

    parts = [f"<title>{_e(company['name'])} 브리핑</title>", STYLE]
    parts.append(
        '<header class="top"><div class="in">'
        f'<div class="eyebrow">아데어 · 미팅 브리핑 · {_e((briefing.get("created_at") or "")[:10])}</div>'
        f"<h1>{_e(name)}</h1>"
        '<nav class="jump" aria-label="섹션 이동">'
        '<a href="#questions">질문 3선</a><a href="#summary">현황</a>'
        '<a href="#hypotheses">수요 가설</a><a href="#sources">출처</a></nav>'
        "</div></header>"
    )
    parts.append('<main class="wrap">')

    notices = [w for w in briefing.get("warnings", []) if w]
    if notices:
        parts.append("".join(f'<div class="notice">{_e(n)}</div>' for n in notices))

    # 질문 3선
    parts.append('<section id="questions"><h2>미팅 질문 3선</h2>')
    if questions:
        for i, q in enumerate(questions, start=1):
            badges = _evidence_chips(q.get("evidence_ids", []))
            if q["type"] != "SOLUTION_BRIDGE" and not q.get("grounded", True):
                badges += '<span class="chip warn">근거 부족 · 열린 질문</span>'
            vp = _value_prop_label(q.get("value_prop_id"))
            if vp:
                badges += f'<span class="chip">소구점: {_e(vp)}</span>'
            parts.append(
                f'<article class="q{" primary" if i == 1 else ""}">'
                f'<div class="q-head"><span class="q-no">Q{i}</span>'
                f'<span class="q-type">{_e(QUESTION_LABELS.get(q["type"], q["type"]))}</span>{badges}</div>'
                f'<p class="q-text">{_e(q["question"])}</p>'
                f'<div class="q-foot"><p class="q-intent">의도: {_e(q.get("intent"))}</p>'
                f'<button class="copy" type="button" data-text="{_e(q["question"])}">질문 복사</button></div>'
                "</article>"
            )
    else:
        for i, q in enumerate(briefing.get("meeting_questions", [])[:3], start=1):
            parts.append(f'<article class="q"><div class="q-head"><span class="q-no">Q{i}</span></div>'
                         f'<p class="q-text">{_e(q)}</p></article>')
    parts.append("</section>")

    # 현황 요약 + 아이스브레이킹
    snap = briefing.get("company_snapshot", {})
    lines = [l for l in (snap.get("summary") or "").splitlines() if l.strip()]
    parts.append('<section id="summary"><h2>현황 요약</h2><div class="card summary">')
    parts.append("".join(f"<p>{_e(l)}</p>" for l in lines))
    if snap.get("evidence_ids"):
        parts.append(f'<div class="src-meta">근거 {_evidence_chips(snap["evidence_ids"])}</div>')
    parts.append("</div>")
    for st in briefing.get("small_talk", []):
        parts.append(
            f'<div class="card"><div class="src-meta">아이스브레이킹 · {_e(st.get("topic"))} '
            f'{_evidence_chips(st.get("evidence_ids", []))}</div><p style="margin:0">{_e(st.get("talking_point"))}</p></div>'
        )
    parts.append("</section>")

    # 수요 가설
    parts.append('<section id="hypotheses"><h2>수요 가설 (미팅에서 확인할 추정)</h2>')
    hyps = briefing.get("demand_hypotheses", [])
    if not hyps:
        parts.append('<div class="card muted">확인된 근거가 부족해 가설을 만들지 않았습니다.</div>')
    for h in hyps:
        level = h.get("signal_level", "NONE")
        on = SIGNAL_STEPS.index(level) if level in SIGNAL_STEPS else 0
        meter = "".join(f'<i class="{"on" if n <= on and on > 0 else ""}"></i>' for n in range(1, 6))
        parts.append(
            f'<div class="card"><strong>{_e(h["title"])}</strong>'
            f'<div class="src-meta">신호 강도 {_e(SIGNAL_LABELS.get(level, level))} · 근거 {_evidence_chips(h.get("supporting_evidence", []))}</div>'
            f'<div class="meter" aria-label="신호 강도 {_e(SIGNAL_LABELS.get(level, level))}">{meter}</div>'
            f'<p style="margin:0">{_e(h.get("reason"))}</p>'
            f'<ol class="chain">{"".join(f"<li>{_e(c)}</li>" for c in h.get("reasoning_chain", []))}</ol></div>'
        )
    parts.append("</section>")

    # 출처 (기업 / 산업)
    parts.append('<section id="sources"><h2>확인된 출처 (원문 대조 완료)</h2>')
    for scope, label in (("COMPANY", "기업"), ("INDUSTRY", "산업"), (None, "기타")):
        group = [s for s in sources if s.get("scope") == scope]
        if not group:
            continue
        parts.append(f'<div class="card"><strong>{label} · {len(group)}건</strong>')
        for s in group:
            url = _safe_url(s.get("url"))
            link = f'<a class="out" href="{_e(url)}" target="_blank" rel="noopener noreferrer">원문 보기 · {_e(s.get("publisher"))}</a>' if url else ""
            parts.append(
                f'<div class="src" id="src-{_e(s["evidence_id"])}">'
                f'<div class="src-meta"><span class="chip">{_e(s["evidence_id"])}</span>'
                f'<span>출처 등급 {_e(s.get("source_tier"))} ({_e(TIER_LABELS.get(s.get("source_tier"), ""))})</span>'
                f'<span>{_e(s.get("published_at") or "날짜 미상")}</span></div>'
                f"<p>{_e(s.get('claim'))}</p>{link}</div>"
            )
        parts.append("</div>")
    if not sources:
        parts.append('<div class="card muted">원문으로 확인된 출처가 없습니다.</div>')
    parts.append("</section>")

    if messenger_text:
        parts.append(f'<details><summary>텔레그램 답장 미리보기</summary><pre class="msg">{_e(messenger_text)}</pre></details>')

    parts.append('<p class="muted">이 리포트의 사실은 원문 페이지에 글자 그대로 있는 문장만 사용했습니다. '
                 "수요 가설과 질문은 미팅에서 확인할 추정입니다.</p>")
    parts.append("</main>")
    parts.append(SCRIPT)
    return "\n".join(parts)


def main() -> None:
    from app.domain.models import BriefingObject
    from app.services.messenger_formatter import format_messenger_briefing

    parser = argparse.ArgumentParser(description="브리핑 JSON을 모바일 리포트 HTML로 변환")
    parser.add_argument("briefing_json")
    parser.add_argument("output_html")
    parser.add_argument("--standalone", action="store_true", help="브라우저에서 바로 열 수 있게 문서 머리말 포함")
    args = parser.parse_args()

    data = json.loads(Path(args.briefing_json).read_text(encoding="utf-8"))
    messenger = format_messenger_briefing(BriefingObject.model_validate(data))
    body = render(data, messenger)
    if args.standalone:
        body = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">'
                f"</head><body>{body}</body></html>")
    else:
        body = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">\n'
                + body)
    Path(args.output_html).write_text(body, encoding="utf-8")
    print(f"저장: {args.output_html}")


if __name__ == "__main__":
    main()
