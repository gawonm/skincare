"""복합 사용자 요청을 실행 단계별 질의로 정규화한다."""

import re
from enum import StrEnum
from typing import ClassVar

from agent.rag_route_policy import SkinConcernCue
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


class EvidenceQueryAxis(StrEnum):
    """Case Claim을 검증할 때 사용자 지시 대신 유지할 Evidence 검색 축."""

    EFFICACY = "효능"
    PRECAUTION = "주의사항"


class CaseQueryInstructionCue(StrEnum):
    """Case 유사도와 무관한 상품 선택·루틴 실행 지시의 고정 신호."""

    PRODUCT = "제품"
    PRODUCT_SYNONYM = "상품"
    RECOMMEND = "추천"
    ROUTINE = "루틴"
    WHAT_TO_USE = "뭘 써"
    WHAT_USE = "뭐 써"
    WHAT_SHOULD_I_USE = "무엇을 써"
    WHAT_TO_APPLY = "뭘 발라"
    WHAT_APPLY = "뭐 발라"
    WHAT_SHOULD_I_APPLY = "무엇을 발라"


class IntentQueryPlanner:
    """LLM의 질의 분리를 보완하되 사용자가 명시한 Case 문맥은 삭제하지 않는다."""

    _AGE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<!\d)(?:[1-9]0대|\d{1,2}(?:세|살))"
    )
    _CASE_QUERY_PURPOSE: ClassVar[str] = "피부 관련 성분 및 주의사항"
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
            evidence_query=self._evidence_query(request),
            product_query=self._effective_query(draft.product_query, parsed.query),
            routine_query=self._effective_query(draft.routine_query, parsed.query),
        )

    def _evidence_query(self, request: QueryPlanningRequest) -> str | None:
        parsed = request.parsed_request
        preferred = self._normalize(parsed.query_plan.evidence_query or "")
        if parsed.rag_route is not RagRoute.CLAIM_THEN_EVIDENCE:
            return preferred or self._effective_query(None, parsed.query)

        concerns = self._evidence_concerns(request)
        if not concerns and preferred:
            return preferred
        subject = " ".join(concerns) if concerns else "피부 고민"
        # 나이·성별·계절·상품·루틴 지시는 Case 검색에만 필요하다. Evidence 검색은
        # 성분 ID hard filter와 효능·주의 축에 집중해야 관련 청크가 지시문에 밀리지 않는다.
        return self._normalize(
            f"{subject} 관련 {EvidenceQueryAxis.EFFICACY.value} 및 "
            f"{EvidenceQueryAxis.PRECAUTION.value}"
        )

    def _evidence_concerns(self, request: QueryPlanningRequest) -> list[str]:
        normalized_message = request.original_message.casefold()
        positioned = [
            (normalized_message.find(concern.value.casefold()), concern.value)
            for concern in SkinConcernCue
            if concern.value.casefold() in normalized_message
        ]
        explicit = [value for _, value in sorted(positioned)]
        if explicit:
            # LLM이 "피지가 많고 여드름"처럼 복합 문구를 추가해도 원문의 고정 고민어만
            # 사용해야 같은 고민이 Evidence 임베딩 질의에 중복 삽입되지 않는다.
            return explicit
        parsed = request.parsed_request
        return list(dict.fromkeys(parsed.skin_concerns + request.profile_concerns))

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
        concerns = self._evidence_concerns(request)
        if self._has_case_instruction(base_query):
            # LLM이 상품 선택 문구를 Case 질의에 남겨도 임베딩·리랭크의 의미를 흐리지 않도록
            # 원문에서 결정적으로 확인한 사용자 문맥과 고민만으로 Case 질의를 다시 만든다.
            return self._rebuild_case_query(explicit_context, concerns)
        missing_terms = [
            term
            for term in [*explicit_context, *concerns]
            if term.casefold() not in base_query.casefold()
        ]
        return self._normalize(" ".join([*missing_terms, base_query]))

    def _has_case_instruction(self, query: str) -> bool:
        normalized = query.casefold()
        return any(cue.value.casefold() in normalized for cue in CaseQueryInstructionCue)

    def _rebuild_case_query(
        self,
        explicit_context: list[str],
        concerns: list[str],
    ) -> str:
        terms: list[str] = []
        for term in [*explicit_context, *concerns]:
            normalized_term = term.casefold()
            if any(
                normalized_term in existing.casefold()
                or existing.casefold() in normalized_term
                for existing in terms
            ):
                continue
            terms.append(term)
        return self._normalize(" ".join([*terms, self._CASE_QUERY_PURPOSE]))

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
