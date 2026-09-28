"""Agent의 `message`를 종류 태그가 붙은 `ChatSection` 목록으로 나눈다.

`docs/contracts/front-to-backend.md` "응답 확장: 섹션" 절의 구현이다. Agent 코드는 바꾸지
않는다 — `ChatSectionParser`는 `ChatTurnOutput.message` 문자열을 이미 있는 구조화 데이터
(`artifacts`/`citations`/`unresolved`)와 대조할 뿐이다. 대조에 실패한 문단은 그대로
`ChatTextSection`으로 남기므로 정보가 사라지지 않는다 — 각 섹션의 `text`를 원래 순서대로
이어 붙이면 `message`가 복원된다.

`ChatSectionParser`는 DB 없이 도는 순수 로직이라 단위 테스트가 쉽다. 상품 카드에 이미지·
브랜드·가격을 붙이는 DB 조회는 `ChatResponseBuilder`가 맡는다 — SQL은 리포지토리에만
둔다(CLAUDE.md 규칙 12).

## Agent 와의 암묵적 결합 (변경 요구 아님, 공유 사항)

아래 두 정규식은 `agent/nodes.py`의 다음 형식에 기댄다.

1. 문단 구분자 `"\\n\\n"` (`AgentNodes.finalize_response`)
2. 상품 목록 문단의 `"[역할]"` 머리글과 `"N번. 이름"` 줄 형식
   (`AgentNodes._append_role_product_message`)

형식이 바뀌면 해당 문단이 조용히 `ChatTextSection`으로 남을 뿐 예외를 던지지는 않는다.
역할 라벨 문자열은 `agent.nodes.KoreanRoutineRoleLabel`을 그대로 import 해서 쓴다 — 이름이
바뀌면 여기서 import 오류로 드러나야, 문구를 이 모듈에 몰래 복사해 둔 채로 어긋나는 일이
없다.
"""

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.nodes import KoreanRoutineRoleLabel
from agent.rag.schemas import (
    ProductCandidate,
    ProductCandidateSet,
    RoutinePlacement,
    RoutinePlan,
    Weekday,
)
from agent.schemas import ChatTurnOutput, Citation, EvidenceAnswer, UnresolvedItem
from backend.repositories.product_repository import ProductRepository
from backend.schemas.chat import (
    ChatEvidenceSection,
    ChatNoticeSection,
    ChatProductListSection,
    ChatRoutineSection,
    ChatSection,
    ChatTextSection,
    ProductCardView,
    ProductGroupView,
    ReferenceView,
    RoutineDayView,
    RoutineStepView,
)
from models.product import Product

_ROLE_HEADER_PATTERN = re.compile(r"^\[(?P<label>.+)\]$")
_PRODUCT_LINE_PATTERN = re.compile(r"^(?P<rank>\d+)번\. (?P<rest>.+)$")
_BASIS_SUFFIX_PATTERN = re.compile(r"^ \((?P<basis>.+)\)$")


class ChatSectionParser:
    """`message`를 문단으로 나누고 구조화 데이터와 대조해 섹션으로 분류한다."""

    def parse(
        self,
        output: ChatTurnOutput,
        product_details: dict[str, Product],
    ) -> list[ChatSection]:
        candidate_sets = [
            artifact for artifact in output.artifacts if isinstance(artifact, ProductCandidateSet)
        ]
        routines = [artifact for artifact in output.artifacts if isinstance(artifact, RoutinePlan)]
        answers = [
            artifact for artifact in output.artifacts if isinstance(artifact, EvidenceAnswer)
        ]

        return [
            self._classify(
                paragraph,
                candidate_sets=candidate_sets,
                routines=routines,
                answers=answers,
                unresolved=output.unresolved,
                citations=output.citations,
                product_details=product_details,
            )
            for paragraph in output.message.split("\n\n")
        ]

    def _classify(
        self,
        paragraph: str,
        *,
        candidate_sets: list[ProductCandidateSet],
        routines: list[RoutinePlan],
        answers: list[EvidenceAnswer],
        unresolved: list[UnresolvedItem],
        citations: list[Citation],
        product_details: dict[str, Product],
    ) -> ChatSection:
        # 순서가 결과를 바꾸지는 않는다 — 문단 하나가 여러 조건을 동시에 만족할 형태가
        # 아니기 때문이다. 다만 문자열 비교(notice/evidence)가 줄 단위 패턴 매칭보다
        # 싸므로 먼저 시도한다.
        notice = self._match_notice(paragraph, unresolved)
        if notice is not None:
            return notice
        evidence = self._match_evidence(paragraph, answers, citations)
        if evidence is not None:
            return evidence
        product_list = self._match_product_list(paragraph, candidate_sets, product_details)
        if product_list is not None:
            return product_list
        routine = self._match_routine(paragraph, routines)
        if routine is not None:
            return routine
        return ChatTextSection(text=paragraph)

    def _match_notice(
        self, paragraph: str, unresolved: list[UnresolvedItem]
    ) -> ChatNoticeSection | None:
        for item in unresolved:
            if item.detail == paragraph:
                return ChatNoticeSection(
                    kind=item.kind, detail=item.detail, retryable=item.retryable
                )
        return None

    def _match_evidence(
        self,
        paragraph: str,
        answers: list[EvidenceAnswer],
        citations: list[Citation],
    ) -> ChatEvidenceSection | None:
        for answer in answers:
            if answer.summary != paragraph:
                continue
            references = [
                ReferenceView(
                    source_title=citation.source_title,
                    locator=citation.locator,
                    url=citation.url,
                    source_type=citation.source_type,
                )
                for citation in citations
                if citation.evidence_id in answer.evidence_ids
            ]
            return ChatEvidenceSection(
                answer_id=answer.answer_id,
                subject=answer.subject,
                text=paragraph,
                references=references,
            )
        return None

    def _match_product_list(
        self,
        paragraph: str,
        candidate_sets: list[ProductCandidateSet],
        product_details: dict[str, Product],
    ) -> ChatProductListSection | None:
        lines = paragraph.split("\n")
        if len(lines) < 2:
            # 제목 줄 하나뿐이면 후보 목록일 수 없다 — 최소 제목 + 상품 한 줄이 필요하다.
            return None
        body_lines = lines[1:]
        role_labels = {label.value for label in KoreanRoutineRoleLabel}
        for candidate_set in candidate_sets:
            groups = self._match_product_groups(
                body_lines, candidate_set, role_labels, product_details
            )
            if groups is not None:
                return ChatProductListSection(
                    candidate_set_id=candidate_set.candidate_set_id,
                    groups=groups,
                    text=paragraph,
                )
        return None

    def _match_product_groups(
        self,
        body_lines: list[str],
        candidate_set: ProductCandidateSet,
        role_labels: set[str],
        product_details: dict[str, Product],
    ) -> list[ProductGroupView] | None:
        candidates_by_rank = {candidate.rank: candidate for candidate in candidate_set.candidates}
        groups: list[ProductGroupView] = []
        current_label: str | None = None
        current_items: list[ProductCardView] = []
        started = False
        for line in body_lines:
            header_match = _ROLE_HEADER_PATTERN.match(line)
            if header_match is not None:
                label = header_match.group("label")
                if label not in role_labels:
                    return None
                if started:
                    if not current_items:
                        # 실제 Agent 출력은 후보가 있는 역할만 머리글을 낸다. 머리글 뒤에
                        # 상품 줄이 하나도 없으면 우리가 아는 형식이 아니다.
                        return None
                    groups.append(ProductGroupView(role_label=current_label, items=current_items))
                current_label = label
                current_items = []
                started = True
                continue
            card = self._match_product_line(line, candidates_by_rank, product_details)
            if card is None:
                return None
            current_items.append(card)
        if not current_items:
            return None
        groups.append(ProductGroupView(role_label=current_label, items=current_items))
        return groups

    def _match_product_line(
        self,
        line: str,
        candidates_by_rank: dict[int, ProductCandidate],
        product_details: dict[str, Product],
    ) -> ProductCardView | None:
        line_match = _PRODUCT_LINE_PATTERN.match(line)
        if line_match is None:
            return None
        rank = int(line_match.group("rank"))
        rest = line_match.group("rest")
        candidate = candidates_by_rank.get(rank)
        if candidate is None or not rest.startswith(candidate.product.name):
            return None
        suffix = rest[len(candidate.product.name) :]
        basis_label: str | None = None
        if suffix:
            basis_match = _BASIS_SUFFIX_PATTERN.match(suffix)
            if basis_match is None:
                return None
            basis_label = basis_match.group("basis")
        product = product_details.get(candidate.product.product_id)
        return ProductCardView(
            rank=rank,
            product_id=candidate.product.product_id,
            name=candidate.product.name,
            brand=product.brand if product is not None else None,
            image_url=product.image_url if product is not None else None,
            lowest_price=product.lowest_price if product is not None else None,
            service_category=product.service_category if product is not None else None,
            reasons=candidate.reasons,
            cautions=candidate.unresolved,
            basis_label=basis_label,
        )

    def _match_routine(
        self, paragraph: str, routines: list[RoutinePlan]
    ) -> ChatRoutineSection | None:
        for plan in routines:
            if not plan.placements:
                continue
            if not all(placement.product_name in paragraph for placement in plan.placements):
                continue
            return ChatRoutineSection(
                routine_id=plan.routine_id,
                version=plan.version,
                days=self._routine_days(plan.placements),
                constraints=[constraint.description for constraint in plan.constraints],
                changes=plan.changes,
                text=paragraph,
            )
        return None

    def _routine_days(self, placements: list[RoutinePlacement]) -> list[RoutineDayView]:
        # 요일은 placements 에 처음 등장한 순서를 그대로 쓴다. Agent가 이미 정한 배치
        # 순서라 여기서 다시 정렬하면 오히려 원래 의도와 어긋난다.
        steps_by_weekday: dict[Weekday, list[RoutineStepView]] = {}
        for placement in placements:
            steps_by_weekday.setdefault(placement.weekday, []).append(
                RoutineStepView(
                    period=placement.period,
                    order=placement.order,
                    product_id=placement.product_id,
                    product_name=placement.product_name,
                    reason=placement.reason,
                )
            )
        return [
            RoutineDayView(weekday=weekday, steps=steps)
            for weekday, steps in steps_by_weekday.items()
        ]


class ChatResponseBuilder:
    """`ChatSectionParser`에 필요한 상품 상세를 DB에서 채워 최종 섹션을 만든다.

    `ChatTurnService`가 요청마다 새로 만들어지고(`backend/api/dependencies.py`) 그 시점에는
    아직 DB 세션이 없으므로, `ChatRoomService`와 같은 방식으로 세션 팩토리를 받아 필요할 때만
    직접 짧은 세션을 연다. 읽기만 하므로 커밋은 하지 않는다.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._parser = ChatSectionParser()

    async def build(self, output: ChatTurnOutput) -> list[ChatSection]:
        product_ids = self._collect_product_ids(output)
        if not product_ids:
            return self._parser.parse(output, {})
        async with self._session_factory() as session:
            rows = await ProductRepository(session).list_by_ids(list(product_ids))
        product_details = {str(row.id): row for row in rows}
        return self._parser.parse(output, product_details)

    def _collect_product_ids(self, output: ChatTurnOutput) -> set[UUID]:
        ids: set[UUID] = set()
        for artifact in output.artifacts:
            if not isinstance(artifact, ProductCandidateSet):
                continue
            for candidate in artifact.candidates:
                parsed = self._parse_uuid(candidate.product.product_id)
                if parsed is not None:
                    ids.add(parsed)
        return ids

    def _parse_uuid(self, value: str) -> UUID | None:
        # 개발용 fixture 상품(is_demo=True)은 product_id 가 UUID 형식이 아니다. 그런
        # 값을 조회하면 조용히 결과 없음으로 취급한다 — 오류가 아니라 예상된 경로다.
        try:
            return UUID(value)
        except ValueError:
            return None
