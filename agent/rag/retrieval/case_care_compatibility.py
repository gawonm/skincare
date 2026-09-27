"""현재 피부 상태와 Case 답변의 관리 강도가 어긋나는 후보를 식별한다."""

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from agent.rag.schemas import CareContext, RagModel


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
    _WEEKLY_FREQUENCY_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"주\s*\d+\s*(?:[-~∼]\s*\d+\s*)?회"
    )
    _EXFOLIATION_ACTION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"각질(?:을|를)?[^.!?,;\r\n]{0,12}제거"
    )
    _REPEATED_EXFOLIATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:주기적|규칙적|정기적)(?:인|으로)?\s*(?:저자극\s*)?각질\s*관리"
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
        "시행",
        "실시",
        "통해",
        "제거하",
        "제거해",
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
    _DEFERRED_CUES: ClassVar[tuple[str, ...]] = (
        "회복 후",
        "회복된 후",
        "회복한 뒤",
        "진정된 후",
        "진정된 뒤",
        "가라앉은 후",
        "가라앉은 뒤",
    )

    def assess(
        self,
        care_context: CareContext,
        page_content: str,
    ) -> CaseCareCompatibilityAssessment:
        if not care_context.requires_recovery_first():
            return CaseCareCompatibilityAssessment()
        if not self._recommends_high_irritation_care(page_content):
            return CaseCareCompatibilityAssessment()
        return CaseCareCompatibilityAssessment(
            mismatch_reasons=[
                CaseCareMismatchReason.ACTIVE_IRRITATION_EXFOLIATION_ADVICE
            ]
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
                or self._EXFOLIATION_ACTION_PATTERN.search(clause)
                or self._REPEATED_EXFOLIATION_PATTERN.search(clause)
            ]
            if not risky_clauses:
                continue
            # 권고 동사가 뒤 절에 이어질 수 있으므로 문장 전체를 본다.
            # 위험 행위 자체를 피하거나 회복 뒤로 미룬 절은 현재 권고로 세지 않는다.
            if all(
                self._contains_any(clause, self._AVOIDANCE_CUES)
                or self._contains_any(clause, self._DEFERRED_CUES)
                for clause in risky_clauses
            ):
                continue
            if (
                self._contains_any(sentence, self._RECOMMENDATION_CUES)
                or self._WEEKLY_FREQUENCY_PATTERN.search(sentence)
            ):
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
