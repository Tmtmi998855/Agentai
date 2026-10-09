"""docs/ui-review/samples/ 샘플 계약 및 무결성 재검증 테스트."""

import json
from pathlib import Path

import pytest
from app.domain.models import BriefingObject, ErrorResponse
from scripts.generate_ui_review_samples import generate_samples


SAMPLES_DIR = Path("docs/ui-review/samples")


def test_ui_review_samples_exist():
    """모든 UI 검토용 샘플 파일이 존재해야 한다."""
    expected_files = [
        "success.json",
        "insufficient_evidence.json",
        "entity_ambiguous.json",
        "provider_auth_error.json",
        "provider_timeout.json",
        "invalid_citation.json",
    ]
    for filename in expected_files:
        sample_path = SAMPLES_DIR / filename
        assert sample_path.exists(), f"Missing sample file: {sample_path}"


def test_success_sample_contract_and_citation_integrity():
    """success.json 샘플이 Pydantic BriefingObject를 만족하고 인용 무결성을 통과하는지 검증한다."""
    sample_path = SAMPLES_DIR / "success.json"
    content = sample_path.read_text(encoding="utf-8")
    briefing = BriefingObject.model_validate_json(content)

    assert briefing.status == "SUCCESS"
    assert briefing.company.entity_confidence == "HIGH"
    assert len(briefing.demand_hypotheses) > 0
    assert len(briefing.sources) > 0

    # 인용 무결성 검증 (정상 출처만 인용되었는지 확인)
    invalid_citations = briefing.validate_citations()
    assert invalid_citations == [], f"Unexpected invalid citations in success.json: {invalid_citations}"

    # 보안/감사 필드 격리 검증: 내부 원문 및 검증 기록이 고객용 JSON에 노출되지 않아야 함
    data = json.loads(content)
    assert "verified_raw_content" not in content
    assert "verification_record" not in content


def test_insufficient_evidence_sample_contract():
    """insufficient_evidence.json 샘플 계약을 검증한다."""
    sample_path = SAMPLES_DIR / "insufficient_evidence.json"
    content = sample_path.read_text(encoding="utf-8")
    briefing = BriefingObject.model_validate_json(content)

    assert briefing.status == "INSUFFICIENT_EVIDENCE"
    assert len(briefing.demand_hypotheses) == 0
    assert len(briefing.sources) == 0
    assert len(briefing.warnings) > 0


def test_entity_ambiguous_sample_contract():
    """entity_ambiguous.json 샘플 계약을 검증한다."""
    sample_path = SAMPLES_DIR / "entity_ambiguous.json"
    content = sample_path.read_text(encoding="utf-8")
    briefing = BriefingObject.model_validate_json(content)

    assert briefing.status == "ENTITY_AMBIGUOUS"
    assert briefing.company.entity_confidence == "LOW"
    assert briefing.company.resolved_name is None
    assert len(briefing.company.candidate_entities) > 0
    assert len(briefing.demand_hypotheses) == 0
    assert len(briefing.sources) == 0


def test_provider_auth_error_sample_contract():
    """provider_auth_error.json 샘플 계약(HTTP 502)을 검증한다."""
    sample_path = SAMPLES_DIR / "provider_auth_error.json"
    content = sample_path.read_text(encoding="utf-8")
    err_res = ErrorResponse.model_validate_json(content)

    assert err_res.error_code == "PROVIDER_AUTH_ERROR"
    assert "일시적으로 이용할 수 없습니다" in err_res.message
    # detail 내부에 내부 원인이나 시크릿이 포함되어선 안 됨
    assert err_res.detail == {}


def test_provider_timeout_sample_contract():
    """provider_timeout.json 샘플 계약(HTTP 504)을 검증한다."""
    sample_path = SAMPLES_DIR / "provider_timeout.json"
    content = sample_path.read_text(encoding="utf-8")
    err_res = ErrorResponse.model_validate_json(content)

    assert err_res.error_code == "PROVIDER_TIMEOUT"
    assert "응답 시간이 초과되었습니다" in err_res.message
    assert err_res.detail == {}


def test_invalid_citation_sample_contract():
    """invalid_citation.json 샘플 계약(HTTP 422)을 검증한다."""
    sample_path = SAMPLES_DIR / "invalid_citation.json"
    content = sample_path.read_text(encoding="utf-8")
    err_res = ErrorResponse.model_validate_json(content)

    assert err_res.error_code == "INVALID_CITATION"
    assert "unconfirmed_citations" in err_res.detail
    assert "E99" in err_res.detail["unconfirmed_citations"]


@pytest.mark.asyncio
async def test_generate_samples_regeneration_with_tmp_path(tmp_path):
    """generate_samples(tmp_path)를 실행하여 6개 JSON 및 manifest가 실제 생성되고,
    BriefingObject/ErrorResponse roundtrip, 상태코드(200, 502, 504, 422), MOCK_VIRTUAL provenance,
    정상 인용 무결성, 내부 감사필드 미노출을 검증한다."""
    results = await generate_samples(tmp_path)

    expected_files = [
        "success.json",
        "insufficient_evidence.json",
        "entity_ambiguous.json",
        "provider_auth_error.json",
        "provider_timeout.json",
        "invalid_citation.json",
        "manifest.json",
    ]
    for filename in expected_files:
        filepath = tmp_path / filename
        assert filepath.exists(), f"Missing expected file in tmp_path: {filename}"
        assert filename in results

    # 1. BriefingObject roundtrip & Status 200 OK & Citation integrity & Security isolation
    success_content = (tmp_path / "success.json").read_text(encoding="utf-8")
    briefing_success = BriefingObject.model_validate_json(success_content)
    assert briefing_success.status == "SUCCESS"
    assert briefing_success.validate_citations() == []
    assert "verified_raw_content" not in success_content
    assert "verification_record" not in success_content

    insufficient_content = (tmp_path / "insufficient_evidence.json").read_text(encoding="utf-8")
    briefing_insufficient = BriefingObject.model_validate_json(insufficient_content)
    assert briefing_insufficient.status == "INSUFFICIENT_EVIDENCE"

    ambiguous_content = (tmp_path / "entity_ambiguous.json").read_text(encoding="utf-8")
    briefing_ambiguous = BriefingObject.model_validate_json(ambiguous_content)
    assert briefing_ambiguous.status == "ENTITY_AMBIGUOUS"

    # 2. ErrorResponse roundtrip & Status Codes (502, 504, 422)
    auth_content = (tmp_path / "provider_auth_error.json").read_text(encoding="utf-8")
    err_auth = ErrorResponse.model_validate_json(auth_content)
    assert err_auth.error_code == "PROVIDER_AUTH_ERROR"

    timeout_content = (tmp_path / "provider_timeout.json").read_text(encoding="utf-8")
    err_timeout = ErrorResponse.model_validate_json(timeout_content)
    assert err_timeout.error_code == "PROVIDER_TIMEOUT"

    citation_content = (tmp_path / "invalid_citation.json").read_text(encoding="utf-8")
    err_citation = ErrorResponse.model_validate_json(citation_content)
    assert err_citation.error_code == "INVALID_CITATION"

    # 3. Manifest status codes & MOCK_VIRTUAL provenance
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["samples_provenance"] == "MOCK_VIRTUAL"
    samples_meta = manifest["samples"]
    assert samples_meta["success.json"]["status_code"] == 200
    assert samples_meta["insufficient_evidence.json"]["status_code"] == 200
    assert samples_meta["entity_ambiguous.json"]["status_code"] == 200
    assert samples_meta["provider_auth_error.json"]["status_code"] == 502
    assert samples_meta["provider_timeout.json"]["status_code"] == 504
    assert samples_meta["invalid_citation.json"]["status_code"] == 422

