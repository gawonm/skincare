"""성분 미식별 시의 검색 범위를 결정한다. 조회·생성·그래프 상태 변경은 하지 않는다."""

from agent.rag.schemas import EvidenceSearchRequest
from agent.schemas import AgentState, Intent, UnresolvedItem, UnresolvedKind


class EvidenceQueryPolicy:
    def requires_clarification(self, state: AgentState) -> bool:
        if not state.resolved_entities.unresolved_names or self.allows_fallback(state):
            return False
        parsed = state.parsed_request
        # 근거 질의의 조회 장애는 사용자 입력 문제가 아니다. 혼합 작업의 엄격한 게이트는 유지한다.
        return not (
            parsed is not None
            and set(parsed.intents) == {Intent.EVIDENCE_QA}
            and self.has_lookup_failure(state)
        )

    def has_lookup_failure(self, state: AgentState) -> bool:
        return any(item.kind is UnresolvedKind.TOOL_FAILURE for item in state.unresolved)

    def allows_fallback(self, state: AgentState) -> bool:
        parsed = state.parsed_request
        return bool(
            parsed is not None
            and set(parsed.intents) == {Intent.EVIDENCE_QA}
            and parsed.ingredient_mentions
            and state.resolved_entities.unresolved_names
            and not self.has_lookup_failure(state)
        )

    def search_request(
        self, state: AgentState, request: EvidenceSearchRequest
    ) -> EvidenceSearchRequest:
        if not self.allows_fallback(state):
            return request.model_copy(deep=True)
        # 식별된 일부 ID로 제한하면 나머지 성분의 문헌은 후보에 들어올 수 없다.
        # 원문·조건은 유지하고 필터만 해제하며 병용 대상이 모두 확인된 것처럼 전달하지 않는다.
        return request.model_copy(
            deep=True, update={"target_ids": [], "combination_target_ids": []}
        )

    def limitation(self, state: AgentState) -> UnresolvedItem:
        names = ", ".join(dict.fromkeys(state.resolved_entities.unresolved_names))
        return UnresolvedItem(
            kind=UnresolvedKind.MISSING_INFORMATION,
            detail=(
                f"성분 식별 미확정: {names}. 질문 원문으로 문헌을 검색합니다. "
                "검색된 자료가 해당 성분·유도체와 동일하거나 모든 질문 대상을 다룬다고 "
                "확정할 수 없으며, 제품 추천·루틴·병용 안전성 판단에 사용하지 않습니다."
            ),
        )
