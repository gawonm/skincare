"""구조화 해석이 비어 있을 때만 보수적인 자극 상태 fallback을 적용한다."""

import re
from enum import StrEnum
from typing import ClassVar

from agent.rag.schemas import (
    CareContext,
    CarePriority,
    IrritationStatus,
    RagModel,
    SkinReaction,
)


class ActiveIrritationCue(StrEnum):
    BURNING = "화끈"
    STINGING = "따갑"
    SORE = "쓰라"
    REDDENING = "붉어"
    IRRITATED = "자극받"
    BARRIER_DAMAGE = "장벽 손상"


class RecoveryPriorityCue(StrEnum):
    CALM = "안정시키"
    SOOTHE = "진정"
    BARRIER_RECOVERY = "장벽 회복"
    RECOVERY_FIRST = "회복 중 무엇을 우선"
    BEFORE_MORE_ACTIVES = "성분을 늘리기 전에"
    STABILIZE_FIRST = "먼저 안정"
    UNTIL_SETTLED = "가라앉을 때까지"
    WHEN_SETTLED = "가라앉을 때"
    UNTIL_RECOVERED = "회복될 때까지"
    UNTIL_IRRITATION_STOPS = "자극이 없어질 때까지"


class CareContextResolutionRequest(RagModel):
    query: str
    interpreted: CareContext


class CareContextResolver:
    """LLM의 구조화 결과를 우선하고 미확정 필드만 제한적으로 보완한다."""

    _NEGATED_IRRITATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:화끈|따갑|쓰라|붉어|자극받).{0,8}(?:않|없|아니)"
    )
    _RESOLVED_IRRITATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:이제|지금은|현재는).{0,10}(?:괜찮|가라앉|회복|없)"
    )
    _SYMPTOM_BY_CUE: ClassVar[dict[ActiveIrritationCue, SkinReaction]] = {
        ActiveIrritationCue.BURNING: SkinReaction.BURNING,
        ActiveIrritationCue.STINGING: SkinReaction.STINGING,
        ActiveIrritationCue.SORE: SkinReaction.STINGING,
        ActiveIrritationCue.REDDENING: SkinReaction.REDNESS,
        ActiveIrritationCue.IRRITATED: SkinReaction.BARRIER_DAMAGE,
        ActiveIrritationCue.BARRIER_DAMAGE: SkinReaction.BARRIER_DAMAGE,
    }

    def resolve(self, request: CareContextResolutionRequest) -> CareContext:
        fallback = self._fallback(request.query)
        interpreted = request.interpreted
        irritation_status = (
            interpreted.irritation_status
            if interpreted.irritation_status is not IrritationStatus.UNKNOWN
            else fallback.irritation_status
        )
        priority = (
            interpreted.priority
            if interpreted.priority is not CarePriority.UNKNOWN
            else fallback.priority
        )
        return CareContext(
            irritation_status=irritation_status,
            priority=priority,
            symptoms=list(dict.fromkeys([*interpreted.symptoms, *fallback.symptoms])),
            source_quotes=(
                list(interpreted.source_quotes)
                if interpreted.source_quotes
                else fallback.source_quotes
            ),
        )

    def _fallback(self, query: str) -> CareContext:
        normalized = query.casefold()
        active_cues = [cue for cue in ActiveIrritationCue if cue.value in normalized]
        explicitly_inactive = bool(
            self._NEGATED_IRRITATION_PATTERN.search(normalized)
            or self._RESOLVED_IRRITATION_PATTERN.search(normalized)
        )
        status = IrritationStatus.UNKNOWN
        if active_cues:
            status = (
                IrritationStatus.INACTIVE
                if explicitly_inactive
                else IrritationStatus.ACTIVE
            )
        priority = (
            CarePriority.RECOVERY
            if any(cue.value in normalized for cue in RecoveryPriorityCue)
            else CarePriority.UNKNOWN
        )
        symptoms = list(
            dict.fromkeys(self._SYMPTOM_BY_CUE[cue] for cue in active_cues)
        )
        return CareContext(
            irritation_status=status,
            priority=priority,
            symptoms=symptoms,
            source_quotes=[query] if active_cues or priority is CarePriority.RECOVERY else [],
        )
