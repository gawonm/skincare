"""LangGraph 노드가 공유하는 실행 제한·오류·식별자 정책."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agent.schemas import (
    AgentState,
    ChatStatus,
    ChatTurnInput,
    ErrorCode,
    ExecutionEvent,
    ExecutionEventKind,
    GraphNode,
    ParsedRequest,
    UnresolvedItem,
    UnresolvedKind,
)


class AgentRuntime:
    """기능별 노드가 실행 제한과 실패 의미를 서로 다르게 구현하지 않게 한다."""

    def execution_limit_reached(self, state: AgentState, node: GraphNode) -> bool:
        elapsed = (datetime.now(UTC) - state.started_at).total_seconds()
        if state.tool_call_count >= state.execution_limits.max_tool_calls:
            self._mark_limit(state, node, "최대 도구 호출 수에 도달했습니다.")
            return True
        if elapsed >= state.execution_limits.timeout_seconds:
            self._mark_limit(state, node, "요청 실행 시간 제한에 도달했습니다.")
            return True
        return False

    def reserve_tool_call(self, state: AgentState, node: GraphNode) -> bool:
        if self.execution_limit_reached(state, node):
            return False
        state.tool_call_count += 1
        state.events.append(
            ExecutionEvent(
                node=node,
                kind=ExecutionEventKind.TOOL_CALLED,
                detail=f"도구 호출 {state.tool_call_count}회",
            )
        )
        return True

    def add_tool_failure(self, state: AgentState, detail: str | None) -> None:
        message = detail or "도구가 원인을 제공하지 않고 실패했습니다."
        state.status = ChatStatus.PARTIAL
        state.error_code = ErrorCode.TOOL_FAILED
        state.retryable = True
        state.unresolved.append(
            UnresolvedItem(
                kind=UnresolvedKind.TOOL_FAILURE,
                detail=message,
                retryable=True,
            )
        )

    def record_node(self, state: AgentState, node: GraphNode, detail: str) -> None:
        state.events.append(
            ExecutionEvent(node=node, kind=ExecutionEventKind.NODE_COMPLETED, detail=detail)
        )

    def stable_id(self, state: AgentState, namespace: str) -> str:
        turn = self.require_turn(state)
        return str(uuid5(NAMESPACE_URL, f"{namespace}:{state.chat_room_id}:{turn.request_id}"))

    def require_turn(self, state: AgentState) -> ChatTurnInput:
        if state.turn_input is None:
            raise RuntimeError("그래프 상태에 현재 사용자 입력이 없습니다.")
        return state.turn_input

    def require_parsed(self, state: AgentState) -> ParsedRequest:
        if state.parsed_request is None:
            raise RuntimeError("요청 해석 결과 없이 다음 노드를 실행할 수 없습니다.")
        return state.parsed_request

    def _mark_limit(self, state: AgentState, node: GraphNode, detail: str) -> None:
        if state.error_code is ErrorCode.EXECUTION_LIMIT_REACHED:
            return
        state.status = ChatStatus.PARTIAL
        state.error_code = ErrorCode.EXECUTION_LIMIT_REACHED
        state.retryable = True
        state.response_parts.append(detail)
        state.unresolved.append(
            UnresolvedItem(
                kind=UnresolvedKind.CONFLICT,
                detail=detail,
                retryable=True,
            )
        )
        state.events.append(
            ExecutionEvent(
                node=node,
                kind=ExecutionEventKind.LIMIT_REACHED,
                detail=detail,
            )
        )
