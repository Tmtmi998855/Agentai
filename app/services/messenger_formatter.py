"""메신저(텔레그램 등) 현장 브리핑 텍스트 포맷터.

엘리베이터·차 안에서 30초 안에 읽을 분량만 담고, 상세는 웹 리포트 링크로 넘긴다.
마크다운 파싱 오류를 피하려고 텔레그램 parse_mode 없이 보내는 평문을 만든다.
"""

from app.domain.models import BriefingObject
from app.domain.strategic_questions import QUESTION_LABELS

TELEGRAM_MAX_CHARS = 4096
MAX_SUMMARY_LINES = 3
MOCK_NOTICE_PREFIX = "MOCK_VIRTUAL"


def format_messenger_briefing(briefing: BriefingObject, report_url: str | None = None) -> str:
    company = briefing.company.resolved_name or briefing.company.name
    lines: list[str] = [f"📌 {company} 미팅 브리핑", ""]

    if briefing.status == "ENTITY_AMBIGUOUS":
        lines.append("기업을 하나로 특정하지 못했어요. 아래 중 정확한 이름으로 다시 보내주세요.")
        lines += [f"• {c}" for c in briefing.company.candidate_entities] or ["• (후보 없음)"]
        return _finish(lines, report_url=None)

    summary = [l.strip() for l in briefing.company_snapshot.summary.splitlines() if l.strip()]
    lines.append("[현황 요약]")
    lines += [f"• {l}" for l in summary[:MAX_SUMMARY_LINES]]

    questions = briefing.strategic_questions.questions if briefing.strategic_questions else []
    lines += ["", "[미팅 질문 3선]"]
    if questions:
        for i, q in enumerate(questions, start=1):
            marker = "" if q.grounded or q.type == "SOLUTION_BRIDGE" else " (근거 부족·일반 질문)"
            lines.append(f"Q{i}. [{QUESTION_LABELS[q.type]}]{marker}")
            lines.append(f"   {q.question}")
    else:
        lines += [f"Q{i}. {q}" for i, q in enumerate(briefing.meeting_questions[:3], start=1)]

    notices = [w for w in briefing.warnings if w.startswith(MOCK_NOTICE_PREFIX)]
    if briefing.status == "INSUFFICIENT_EVIDENCE":
        notices.insert(0, "확인된 공개 근거가 부족해 일반 질문 위주로 구성했어요.")
    if notices:
        lines += ["", *[f"⚠ {n}" for n in notices]]

    return _finish(lines, report_url)


def _finish(lines: list[str], report_url: str | None) -> str:
    # 길이 초과 시 본문만 자르고 리포트 링크는 항상 보존한다.
    suffix = f"\n\n🔗 출처·상세 리포트: {report_url}" if report_url else ""
    body = "\n".join(lines)
    limit = TELEGRAM_MAX_CHARS - len(suffix)
    if len(body) > limit:
        body = body[: limit - 1] + "…"
    return body + suffix
