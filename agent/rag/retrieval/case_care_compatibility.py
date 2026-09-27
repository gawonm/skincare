"""현재 피부 상태와 Case 답변의 관리 강도가 어긋나는 후보를 식별한다."""

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import RagModel


class CaseCareMismatchReason(StrEnum):
    """확정 평가에서 반복 확인된 피부 상태-관리 부적합 유형."""

    ACTIVE_IRRITATION_EXFOLIATION_ADVICE = (
        "active_irritation_exfoliation_advice"
    )


class CaseCareCompatibilityAssessment(RagModel):
    """리랭커 후보의 피부 상태-관리 부적합 사유를 설명 가능하게 보존한다."""

    mismatch_reasons: list[CaseCareMismatchReason] = Field(default_factory=list)

    def is_incompatible(self) -> bool:
        return bool(self.mismatch_reasons)


class CaseCareCompatibilityPolicy:
    """활성 자극을 먼저 안정시키려는 요청에 공격적 관리를 권하는 답변을 식별한다."""

    _ANSWER_LABEL: ClassVar[str] = "[답변]"
    _REASONING_LABEL: ClassVar[str] = "[추론]"
    _SENTENCE_SPLIT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<=[.!?])\s+|[\r\n]+"
    )
    _CLAUSE_SPLIT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[,;]+")
    _ACTIVE_IRRITATION_CUES: ClassVar[tuple[str, ...]] = (
        "화끈",
        "따갑",
        "쓰라",
        "붉어",
        "붉은",
        "자극받",
        "장벽 손상",
    )
    _RECOVERY_PRIORITY_CUES: ClassVar[tuple[str, ...]] = (
        "안정시키",
        "진정",
        "장벽 회복",
        "회복 중 무엇을 우선",
        "성분을 늘리기 전에",
        "먼저 안정",
    )
    _HIGH_IRRITATION_CARE_CUES: ClassVar[tuple[str, ...]] = (
        "살리실산",
        "bha",
        "aha",
        "pha",
        "lha",
        "글리콜산",
        "락틱애씨드",
        "레티놀",
        "레티노이드",
        "스크럽",
        "필링",
        "각질 제거",
        "각질을 제거",
        "딥 클렌징",
        "이중 세안",
    )
    _RECOMMENDATION_CUES: ClassVar[tuple[str, ...]] = (
        "추천",
        "권장",
        "사용",
        "활용",
        "해주세요",
        "주세요",
        "도와주",
        "바르",
        "병행",
        "주기적",
        "꾸준",
        "관리",
        "집중",
        "중요",
    )
    _AVOIDANCE_CUES: ClassVar[tuple[str, ...]] = (
        "피하",
        "중단",
        "자제",
        "사용하지",
        "권하지",
        "삼가",
        "하지 말",
        "최소화",
    )

    def assess(
        self,
        query: str,
        page_content: str,
    ) -> CaseCareCompatibilityAssessment:
        if not self._requires_recovery_first(query):
            return CaseCareCompatibilityAssessment()
        if not self._recommends_high_irritation_care(page_content):
            return CaseCareCompatibilityAssessment()
        return CaseCareCompatibilityAssessment(
            mismatch_reasons=[
                CaseCareMismatchReason.ACTIVE_IRRITATION_EXFOLIATION_ADVICE
            ]
        )

    def _requires_recovery_first(self, query: str) -> bool:
        normalized = query.casefold()
        return self._contains_any(normalized, self._ACTIVE_IRRITATION_CUES) and self._contains_any(
            normalized,
            self._RECOVERY_PRIORITY_CUES,
        )

    def _recommends_high_irritation_care(self, page_content: str) -> bool:
        answer = self._answer_only(page_content).casefold()
        for sentence in self._SENTENCE_SPLIT_PATTERN.split(answer):
            if not sentence.strip():
                continue
            risky_clauses = [
                clause
                for clause in self._CLAUSE_SPLIT_PATTERN.split(sentence)
                if self._contains_any(clause, self._HIGH_IRRITATION_CARE_CUES)
            ]
            if not risky_clauses:
                continue
            if all(
                self._contains_any(clause, self._AVOIDANCE_CUES)
                for clause in risky_clauses
            ):
                continue
            if self._contains_any(sentence, self._RECOMMENDATION_CUES):
                return True
        return False

    def _answer_only(self, page_content: str) -> str:
        without_reasoning = page_content.split(
            self._REASONING_LABEL,
            maxsplit=1,
        )[0]
        if self._ANSWER_LABEL not in without_reasoning:
            return without_reasoning
        return without_reasoning.split(self._ANSWER_LABEL, maxsplit=1)[1]

    def _contains_any(self, text: str, cues: tuple[str, ...]) -> bool:
        return any(cue.casefold() in text for cue in cues)
