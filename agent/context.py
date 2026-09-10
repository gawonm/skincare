"""원문 저장소와 분리해 이번 LLM 호출에 필요한 제한된 문맥을 만든다."""

from agent.schemas import AgentState, ConversationSummary, LlmContext, MessageRole

SUMMARY_ITEM_SEPARATOR = " | "
SUMMARY_MAX_CONTENT_LENGTH = 120


class ConversationSummarizer:
    """추가로 밀려난 메시지만 반영하는, 길이가 제한된 개발용 발췌 요약기."""

    def summarize(self, state: AgentState) -> ConversationSummary | None:
        limits = state.context_limits
        # trigger 전에도 윈도 밖의 원문이 조용히 사라지지 않도록 요약한다.
        window = min(limits.recent_message_limit, limits.summary_trigger - 1)
        covered = state.messages[:-window]
        previous_sequence = state.summary.covered_through_sequence if state.summary else 0
        new_messages = [message for message in covered if message.sequence > previous_sequence]
        if not new_messages:
            return state.summary

        parts = [state.summary.content] if state.summary else []
        for message in new_messages:
            role = "사용자" if message.role is MessageRole.USER else "어시스턴트"
            parts.append(f"{role}: {message.content[:SUMMARY_MAX_CONTENT_LENGTH]}")
        return ConversationSummary(
            content=SUMMARY_ITEM_SEPARATOR.join(parts)[-limits.summary_char_limit :],
            version=(state.summary.version if state.summary else 0) + 1,
            covered_through_sequence=new_messages[-1].sequence,
        )


class ContextBuilder:
    """프로필·작업 조건은 구조화해서 보존하고 원문 윈도만 요약·축소한다."""

    def __init__(self, summarizer: ConversationSummarizer) -> None:
        self._summarizer = summarizer

    def compact(self, state: AgentState) -> None:
        state.summary = self._summarizer.summarize(state)
        covered_sequence = state.summary.covered_through_sequence if state.summary else 0
        state.messages = [
            message for message in state.messages if message.sequence > covered_sequence
        ]

    def build(self, state: AgentState) -> LlmContext:
        self.compact(state)
        return LlmContext(
            summary=state.summary,
            recent_messages=[
                message.model_copy(
                    update={"content": message.content[: state.context_limits.message_char_limit]}
                )
                for message in state.messages
            ],
            pending_question=state.pending_question,
            candidate_set=state.candidate_set,
            routine=state.routine,
            profile=state.profile,
            task_context=state.task_context,
        )
