"""리포트 HTML 렌더러: 외부 문장 이스케이프와 링크 제한."""

from app.domain.models import BriefingObject, BriefingSource, CompanyEntity, CompanySnapshot
from scripts.render_report_html import render


def test_render_escapes_external_text_and_blocks_unsafe_links():
    briefing = BriefingObject(
        company=CompanyEntity(name="<b>회사</b>", entity_confidence="HIGH"),
        company_snapshot=CompanySnapshot(summary="a\nb\nc"),
        meeting_questions=["q1", "q2", "q3"],
        sources=[
            BriefingSource(evidence_id="E01", claim="<script>alert(1)</script>", publisher="x",
                           url="javascript:alert(1)", source_tier="A", scope="COMPANY"),
        ],
    ).model_dump(mode="json")
    html = render(briefing)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "javascript:alert" not in html
    assert "&lt;b&gt;회사&lt;/b&gt;" in html
