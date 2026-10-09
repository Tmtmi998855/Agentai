"""전략 미팅 질문 3선 (Q1 기업 이슈 인지 / Q2 산업 트렌드 공감 / Q3 솔루션 브리지)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBaseModel(BaseModel):
    # app.domain.models가 이 모듈을 import하므로 순환 import를 피하려고 동일 설정을 여기서 정의한다.
    model_config = ConfigDict(extra="forbid")


QuestionType = Literal["COMPANY_ISSUE", "INDUSTRY_TREND", "SOLUTION_BRIDGE"]
QUESTION_ORDER: tuple[QuestionType, ...] = ("COMPANY_ISSUE", "INDUSTRY_TREND", "SOLUTION_BRIDGE")
QUESTION_LABELS: dict[str, str] = {
    "COMPANY_ISSUE": "기업 이슈 인지",
    "INDUSTRY_TREND": "산업 트렌드 공감",
    "SOLUTION_BRIDGE": "솔루션 브리지",
}

EvidenceScope = Literal["COMPANY", "INDUSTRY"]


class StrategicQuestion(StrictBaseModel):
    type: QuestionType
    question: str = Field(..., min_length=5, max_length=300, description="미팅에서 그대로 읽을 수 있는 질문 문장")
    intent: str = Field(..., min_length=2, max_length=200, description="이 질문으로 확인하려는 것 (영업사원용 메모)")
    evidence_ids: list[str] = Field(default_factory=list, description="근거가 된 확정 evidence_id")
    value_prop_id: str | None = Field(default=None, description="Q3에서 연결한 소구점 ID")
    grounded: bool = Field(default=True, description="확정 근거로 뒷받침되는지 (서버가 계산)")

    @model_validator(mode="after")
    def validate_value_prop_binding(self) -> "StrategicQuestion":
        if self.type == "SOLUTION_BRIDGE" and not self.value_prop_id:
            raise ValueError("SOLUTION_BRIDGE question must reference a value_prop_id")
        if self.type != "SOLUTION_BRIDGE" and self.value_prop_id is not None:
            raise ValueError("Only SOLUTION_BRIDGE question may reference a value_prop_id")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Duplicate evidence_id in strategic question")
        return self


class StrategicQuestionSet(StrictBaseModel):
    """정확히 3개, Q1→Q2→Q3 순서로 유형이 고정된 질문 묶음."""
    questions: list[StrategicQuestion] = Field(..., min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_order(self) -> "StrategicQuestionSet":
        types = tuple(q.type for q in self.questions)
        if types != QUESTION_ORDER:
            raise ValueError(f"Strategic questions must be ordered {QUESTION_ORDER}, got {types}")
        return self

    def cited_evidence_ids(self) -> set[str]:
        return {eid for q in self.questions for eid in q.evidence_ids}
