"""NIA Case 코퍼스 내부 검색 관련성 판정 스키마.

외부 임상 지침의 완성도가 아니라 사용자 질의와 실제 NIA Case 문서 사이의
검색 관련성을 판정한다. 기존 임상 기준 혼합 v1과 수치가 섞이지 않도록 별도 타입으로 둔다.
"""

from enum import IntEnum, StrEnum
from typing import Self

from pydantic import Field, model_validator

from agent.rag.schemas import RagModel


class CorpusConcernFitScore(IntEnum):
    NONE = 0
    ADJACENT = 1
    DIRECT = 2


class CorpusContextFitScore(IntEnum):
    NONE = 0
    PARTIAL = 1
    STRONG = 2


class CorpusRequestFitScore(IntEnum):
    NONE = 0
    PARTIAL = 1
    DIRECT = 2


class CorpusRelevanceGrade(IntEnum):
    NOT_RELEVANT = 0
    ADJACENT = 1
    RELEVANT = 2
    HIGHLY_RELEVANT = 3


class CorpusDirectionConflictCode(StrEnum):
    EXPLICIT_REQUEST_CONFLICT = "explicit_request_conflict"
    DOMINANT_GOAL_CONFLICT = "dominant_goal_conflict"


class CorpusRelevanceReasonCode(StrEnum):
    PRIMARY_CONCERN_MATCH = "primary_concern_match"
    ADJACENT_CONCERN_MATCH = "adjacent_concern_match"
    SYMPTOM_STATE_MATCH = "symptom_state_match"
    REQUEST_DIRECTION_MATCH = "request_direction_match"
    SKIN_CONTEXT_MATCH = "skin_context_match"
    SEASON_OR_SITE_MATCH = "season_or_site_match"
    DEMOGRAPHIC_SUPPORT = "demographic_support"
    PARTIAL_CONTEXT_ONLY = "partial_context_only"
    INCIDENTAL_KEYWORD_ONLY = "incidental_keyword_only"
    EXPLICIT_DIRECTION_CONFLICT = "explicit_direction_conflict"
    UNRELATED_PRIMARY_GOAL = "unrelated_primary_goal"


class CorpusRelevanceJudgmentPolicy(StrEnum):
    NIA_CORPUS_RELATIVE_POOLED_V1 = "nia_corpus_relative_pooled_v1"


class NiaCaseCorpusRelevanceJudgment(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    concern_fit: CorpusConcernFitScore
    context_fit: CorpusContextFitScore
    request_fit: CorpusRequestFitScore
    direction_conflicts: list[CorpusDirectionConflictCode] = Field(default_factory=list)
    reason_codes: list[CorpusRelevanceReasonCode] = Field(min_length=1)
    relevance_grade: CorpusRelevanceGrade
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relevance_grade(self) -> Self:
        expected = self.expected_relevance_grade()
        if self.relevance_grade is not expected:
            raise ValueError(
                "코퍼스 관련성 세부 점수와 최종 등급이 일치하지 않습니다: "
                f"review_key={self.review_key}, expected={expected.value}, "
                f"actual={self.relevance_grade.value}"
            )
        if len(self.direction_conflicts) != len(set(self.direction_conflicts)):
            raise ValueError("요청 방향 충돌 코드가 중복되었습니다.")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("코퍼스 관련성 판정 이유 코드가 중복되었습니다.")
        return self

    def expected_relevance_grade(self) -> CorpusRelevanceGrade:
        # 외부 임상 기준이 아니라 문서가 질의의 핵심 목표와 직접 충돌할 때만 0점으로 강등한다.
        if self.direction_conflicts or self.concern_fit is CorpusConcernFitScore.NONE:
            return CorpusRelevanceGrade.NOT_RELEVANT
        if (
            self.concern_fit is CorpusConcernFitScore.DIRECT
            and self.request_fit is CorpusRequestFitScore.DIRECT
            and self.context_fit is not CorpusContextFitScore.NONE
        ):
            return CorpusRelevanceGrade.HIGHLY_RELEVANT
        if (
            self.concern_fit is CorpusConcernFitScore.DIRECT
            and self.request_fit is not CorpusRequestFitScore.NONE
        ) or (
            self.concern_fit is CorpusConcernFitScore.ADJACENT
            and self.request_fit is CorpusRequestFitScore.DIRECT
            and self.context_fit is CorpusContextFitScore.STRONG
        ):
            return CorpusRelevanceGrade.RELEVANT
        return CorpusRelevanceGrade.ADJACENT


class NiaCaseCorpusRelevanceJudgmentBatch(RagModel):
    evaluation_id: str = Field(pattern=r"^evaluation_[a-z0-9_]+$")
    policy: CorpusRelevanceJudgmentPolicy
    judgments: list[NiaCaseCorpusRelevanceJudgment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_review_keys(self) -> Self:
        review_keys = [judgment.review_key for judgment in self.judgments]
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("코퍼스 관련성 판정 batch에 중복 review_key가 있습니다.")
        return self
