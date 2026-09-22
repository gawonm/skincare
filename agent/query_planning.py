"""복합 사용자 요청을 실행 단계별 질의로 정규화한다."""

import re
from enum import StrEnum
from typing import ClassVar

from agent.schemas import Intent, IntentQueryPlan, QueryPlanningRequest, RagRoute


class ExplicitCaseContext(StrEnum):
    """Case 유사도에 필요하고 원문에서 결정적으로 복원할 수 있는 고정 문맥."""

    MALE = "남성"
    FEMALE = "여성"
    SPRING = "봄"
    SUMMER = "여름"
    AUTUMN = "가을"
    WINTER = "겨울"
    TRANSITION = "환절기"
    OILY = "지성"
    DRY = "건성"
    COMBINATION = "복합성"
    NORMAL = "중성"
    SENSITIVE = "민감성"


class IntentQueryPlanner:
    """LLM의 질의 분리를 보완하되 사용자가 명시한 Case 문맥은 삭제하지 않는다."""

    _AGE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?<!\d)(?:[1-9]0대|\d{1,2}세)")
    _CONTEXT_ALIASES: ClassVar[dict[ExplicitCaseContext, tuple[str, ...]]] = {
        ExplicitCaseContext.MALE: ("남성", "남자"),
        ExplicitCaseContext.FEMALE: ("여성", "여자"),
        ExplicitCaseContext.SPRING: ("봄",),
        ExplicitCaseContext.SUMMER: ("여름",),
        ExplicitCaseContext.AUTUMN: ("가을",),
        ExplicitCaseContext.WINTER: ("겨울",),
        ExplicitCaseContext.TRANSITION: ("환절기",),
        ExplicitCaseContext.OILY: ("지성",),
        ExplicitCaseContext.DRY: ("건성",),
        ExplicitCaseContext.COMBINATION: ("복합성",),
        ExplicitCaseContext.NORMAL: ("중성",),
        ExplicitCaseContext.SENSITIVE: ("민감성",),
    }

    def build(self, request: QueryPlanningRequest) -> IntentQueryPlan:
        parsed = request.parsed_request
        draft = parsed.query_plan
        case_query = self._case_query(request)
        return IntentQueryPlan(
            case_query=case_query,
            evidence_query=self._effective_query(draft.evidence_query, parsed.query),
            product_query=self._effective_query(draft.product_query, parsed.query),
            routine_query=self._effective_query(draft.routine_query, parsed.query),
        )

    def _case_query(self, request: QueryPlanningRequest) -> str | None:
        parsed = request.parsed_request
        needs_case_query = (
            parsed.rag_route is RagRoute.CLAIM_THEN_EVIDENCE
            or Intent.PRODUCT_DISCOVERY in parsed.intents
        )
        if not needs_case_query:
            return None

        base_query = self._effective_query(parsed.query_plan.case_query, parsed.query)
        if base_query is None:
            return None
        explicit_context = self._explicit_context(request.original_message)
        concerns = list(dict.fromkeys(parsed.skin_concerns + request.profile_concerns))
        missing_terms = [
            term
            for term in [*explicit_context, *concerns]
            if term.casefold() not in base_query.casefold()
        ]
        return self._normalize(" ".join([*missing_terms, base_query]))

    def _explicit_context(self, message: str) -> list[str]:
        positioned: list[tuple[int, str]] = [
            (match.start(), match.group(0)) for match in self._AGE_PATTERN.finditer(message)
        ]
        lowered = message.casefold()
        for context, aliases in self._CONTEXT_ALIASES.items():
            positions = [lowered.find(alias.casefold()) for alias in aliases]
            found = [position for position in positions if position >= 0]
            if found:
                positioned.append((min(found), context.value))
        positioned.sort(key=lambda item: item[0])
        return list(dict.fromkeys(value for _, value in positioned))

    def _effective_query(self, preferred: str | None, fallback: str) -> str | None:
        value = preferred or fallback
        normalized = self._normalize(value)
        return normalized or None

    def _normalize(self, value: str) -> str:
        return " ".join(value.split())
