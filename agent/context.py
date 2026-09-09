"""대화 원문과 그래프 상태에서 이번 LLM 호출용 문맥을 구성한다."""

from agent.schemas import AgentState, ConversationSummary, LlmContext, MessageRole

SUMMARY_ITEM_SEPARATOR = " | "
SUMMARY_ROLE_SEPARATOR = ": "
SUMMARY_MAX_CONTENT_LENGTH = 120


class ConversationSummarizer:
    """개발 환경에서 범위 메타데이터를 보존하는 결정적 요약기."""

    def summarize(self, state: AgentState) -> ConversationSummary | None:
        limits = state.context_limits
        if len(state.messages) < limits.summary_trigger:
            return state.summary

        covered_count = len(state.messages) - limits.recent_message_limit
        if covered_count <= 0:
            return state.summary

        covered_messages = state.messages[:covered_count]
        last_sequence = covered_messages[-1].sequence
        if state.summary and state.summary.covered_through_sequence >= last_sequence:
            return state.summary

        parts: list[str] = []
        for message in covered_messages:
            role = "사용자" if message.role is MessageRole.USER else "어시스턴트"
            content = message.content[:SUMMARY_MAX_CONTENT_LENGTH]
            parts.append(f"{role}{SUMMARY_ROLE_SEPARATOR}{content}")

        previous_version = state.summary.version if state.summary else 0
        return ConversationSummary(
            content=SUMMARY_ITEM_SEPARATOR.join(parts),
            version=previous_version + 1,
            covered_through_sequence=last_sequence,
        )


class ContextBuilder:
    """요약과 최근 원문의 범위가 겹치지 않도록 LLM 문맥을 만든다."""

    def __init__(self, summarizer: ConversationSummarizer) -> None:
        self._summarizer = summarizer

    def build(self, state: AgentState) -> LlmContext:
        summary = self._summarizer.summarize(state)
        covered_sequence = summary.covered_through_sequence if summary else 0
        uncovered = [message for message in state.messages if message.sequence > covered_sequence]
        recent_messages = uncovered[-state.context_limits.recent_message_limit :]
        return LlmContext(
            summary=summary,
            recent_messages=recent_messages,
            pending_question=state.pending_question,
            candidate_set=state.candidate_set,
            routine=state.routine,
        )
