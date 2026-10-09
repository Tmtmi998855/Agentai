"""V0 서버 Rule Engine 정책 상수."""

from dataclasses import dataclass
from typing import Final

from app.domain.models import SignalLevel


@dataclass(frozen=True, slots=True)
class RulePolicy:
    """LLM이 아닌 서버가 적용하는 수요 가설 점수 정책."""

    tier_weights: dict[str, int]
    contradiction_penalty: int
    weak_min_score: int
    moderate_min_score: int
    strong_min_score: int
    very_strong_min_score: int
    tier_c_max_level: SignalLevel


V0_POLICY: Final = RulePolicy(
    tier_weights={"A": 3, "B": 2, "C": 1},
    contradiction_penalty=2,
    weak_min_score=1,
    moderate_min_score=3,
    strong_min_score=5,
    very_strong_min_score=7,
    tier_c_max_level="MODERATE",
)
V0_RULE_POLICY: Final = V0_POLICY

SIGNAL_LEVEL_ORDER: Final[tuple[SignalLevel, ...]] = (
    "NONE",
    "WEAK",
    "MODERATE",
    "STRONG",
    "VERY_STRONG",
)
