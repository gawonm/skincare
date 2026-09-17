"""LLM이 반환한 Intent를 실행 의존성 순서로 정렬한다."""

from agent.schemas import Intent, ParsedRequest, RagRoute


class TaskPlanBuilder:
    """고민 기반 추천에서 Claim 검증이 상품 검색보다 먼저 실행되게 한다."""

    def build(self, request: ParsedRequest) -> list[Intent]:
        intents = list(dict.fromkeys(request.intents))
        if request.rag_route is not RagRoute.CLAIM_THEN_EVIDENCE:
            return intents

        # Claim에서 찾은 성분 ID가 뒤의 상품 필터에 들어가야 하므로 RAG를 항상 먼저 실행한다.
        without_evidence = [intent for intent in intents if intent is not Intent.EVIDENCE_QA]
        return [Intent.EVIDENCE_QA, *without_evidence]
