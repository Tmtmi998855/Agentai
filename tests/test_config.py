import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_config_validation_and_defaults():
    """PRD Test 9: 설정 누락/오류 시 명확한 오류."""
    # Default settings should be valid
    s = Settings()
    assert s.REASONING_PROVIDER in ["mock", "openai_compatible"]
    assert s.TIMEOUT_SECONDS >= 1

    # Invalid timeout (< 1) should raise ValidationError
    with pytest.raises(ValidationError):
        Settings(TIMEOUT_SECONDS=-5)

    # Invalid max_retries (< 0) should raise ValidationError
    with pytest.raises(ValidationError):
        Settings(MAX_RETRIES=-1)


def test_no_external_api_calls_required():
    """PRD Test 10: 실제 외부 API 없이 전체 테스트 통과."""
    from app.providers import get_reasoning_provider
    provider = get_reasoning_provider("mock")
    assert provider is not None
