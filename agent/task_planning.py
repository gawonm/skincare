"""LLM이 반환한 Intent를 실행 의존성 순서로 정렬한다."""

from enum import IntEnum
from typing import ClassVar

from agent.schemas import Intent, ParsedRequest, RagRoute


class IntentExecutionStage(IntEnum):
    EVIDENCE = 10
    PRODUCT = 20
    ROUTINE = 30
    SAVE = 40
    UNORDERED = 100


class TaskPlanBuilder:
    """LLM 반환 순서와 무관하게 산출물 의존성이 있는 Intent를 먼저 실행한다."""

    _STAGES: ClassVar[dict[Intent, IntentExecutionStage]] = {
        Intent.EVIDENCE_QA: IntentExecutionStage.EVIDENCE,
        Intent.PRODUCT_DISCOVERY: IntentExecutionStage.PRODUCT,
        Intent.ROUTINE_PLANNING: IntentExecutionStage.ROUTINE,
        Intent.ROUTINE_SAVE: IntentExecutionStage.SAVE,
    }

    def build(self, request: ParsedRequest) -> list[Intent]:
        intents = list(dict.fromkeys(request.intents))
        if (
            request.rag_route is RagRoute.CLAIM_THEN_EVIDENCE
            and Intent.EVIDENCE_QA not in intents
        ):
            # Claim에서 찾은 성분 ID가 뒤의 상품 필터에 들어가야 하므로 RAG를 항상 먼저 실행한다.
            intents.append(Intent.EVIDENCE_QA)
        indexed = list(enumerate(intents))
        return [
            intent
            for _, intent in sorted(
                indexed,
                key=lambda item: (
                    self._STAGES.get(item[1], IntentExecutionStage.UNORDERED),
                    item[0],
                ),
            )
        ]
