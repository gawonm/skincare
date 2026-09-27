"""`ChatSectionParser` 단위 테스트. DB 없이 순수하게 문단 분류만 검증한다.

`docs/contracts/front-to-backend.md` "응답 확장: 섹션" 절의 분류 규칙(노티스 → 근거 →
상품 목록 → 루틴 → 텍스트 순서, 실패 시 텍스트로 안전하게 떨어짐)을 그대로 시험한다.
"""

from types import SimpleNamespace

import pytest

from agent.rag.schemas import (
    ConstraintSource,
    DayPeriod,
    ProductCandidate,
    ProductCandidateSet,
    ProductRecord,
    RoutineConstraint,
    RoutinePlacement,
    RoutinePlan,
    Weekday,
)
from agent.schemas import (
    Artifact,
    ChatStatus,
    ChatTurnOutput,
    Citation,
    EvidenceAnswer,
    UnresolvedItem,
    UnresolvedKind,
)
from backend.schemas.chat import (
    ChatEvidenceSection,
    ChatNoticeSection,
    ChatProductListSection,
    ChatRoutineSection,
    ChatTextSection,
)
from backend.services.chat_response_builder import ChatSectionParser


def _output(
    message: str,
    *,
    artifacts: list[Artifact] | None = None,
    citations: list[Citation] | None = None,
    unresolved: list[UnresolvedItem] | None = None,
) -> ChatTurnOutput:
    return ChatTurnOutput(
        chat_room_id="room-1",
        request_id="req-1",
        assistant_message_id="assistant-1",
        status=ChatStatus.COMPLETED,
        message=message,
        artifacts=artifacts or [],
        citations=citations or [],
        unresolved=unresolved or [],
    )


class TestChatSectionParser:
    @pytest.fixture
    def parser(self) -> ChatSectionParser:
        return ChatSectionParser()

    def test_plain_paragraph_without_structured_match_stays_as_text(
        self, parser: ChatSectionParser
    ) -> None:
        output = _output("피부 타입에 따라 순한 성분부터 시작하는 게 좋습니다.")

        sections = parser.parse(output, product_details={})

        assert sections == [ChatTextSection(text=output.message)]

    def test_product_list_paragraph_becomes_product_list_section_with_role_group(
        self, parser: ChatSectionParser
    ) -> None:
        product = ProductRecord(
            product_id="11111111-1111-1111-1111-111111111111",
            name="순한 수분크림",
            source_id="oliveyoung_global:p1",
            checked_at="2026-01-01T00:00:00",
            is_demo=False,
        )
        candidate = ProductCandidate(
            rank=1, product=product, reasons=["보습 효과"], unresolved=["제품 사용법 미상"]
        )
        candidate_set = ProductCandidateSet(
            candidate_set_id="cs-1", candidates=[candidate], is_demo=False
        )
        message = "역할별 제품 후보:\n[보습]\n1번. 순한 수분크림 (검수 근거)"
        output = _output(message, artifacts=[candidate_set])
        product_row = SimpleNamespace(
            brand="브랜드A",
            image_url="https://cdn.example/1.jpg",
            lowest_price=12000,
            service_category=None,
        )

        sections = parser.parse(output, product_details={product.product_id: product_row})

        assert len(sections) == 1
        section = sections[0]
        assert isinstance(section, ChatProductListSection)
        assert section.candidate_set_id == "cs-1"
        assert section.text == message
        assert len(section.groups) == 1
        group = section.groups[0]
        assert group.role_label == "보습"
        card = group.items[0]
        assert card.rank == 1
        assert card.product_id == product.product_id
        assert card.name == "순한 수분크림"
        assert card.basis_label == "검수 근거"
        assert card.brand == "브랜드A"
        assert card.image_url == "https://cdn.example/1.jpg"
        assert card.lowest_price == 12000
        assert card.reasons == ["보습 효과"]
        assert card.cautions == ["제품 사용법 미상"]

    def test_product_without_db_row_still_becomes_a_card_with_none_fields(
        self, parser: ChatSectionParser
    ) -> None:
        """개발용 fixture 상품처럼 product 테이블에 없는(또는 UUID가 아닌) 상품도 카드는 만들어진다."""
        product = ProductRecord(
            product_id="retinol-fixture-1",
            name="레티놀 세럼",
            source_id="fixture:1",
            checked_at="2026-01-01T00:00:00",
        )
        candidate = ProductCandidate(rank=1, product=product)
        candidate_set = ProductCandidateSet(candidate_set_id="cs-1", candidates=[candidate])
        message = "개발용 제품 후보:\n[케어]\n1번. 레티놀 세럼"
        output = _output(message, artifacts=[candidate_set])

        sections = parser.parse(output, product_details={})

        section = sections[0]
        assert isinstance(section, ChatProductListSection)
        card = section.groups[0].items[0]
        assert card.brand is None
        assert card.image_url is None
        assert card.lowest_price is None
        assert card.basis_label is None

    def test_unresolved_detail_paragraph_becomes_notice_section(
        self, parser: ChatSectionParser
    ) -> None:
        detail = "현재 연결된 근거로 충분히 확인하지 못한 후보 성분: 레티놀"
        unresolved = UnresolvedItem(kind=UnresolvedKind.NO_EVIDENCE, detail=detail, retryable=True)
        output = _output(detail, unresolved=[unresolved])

        sections = parser.parse(output, product_details={})

        assert sections == [
            ChatNoticeSection(kind=UnresolvedKind.NO_EVIDENCE, detail=detail, retryable=True)
        ]

    def test_evidence_answer_summary_paragraph_becomes_evidence_section_with_references(
        self, parser: ChatSectionParser
    ) -> None:
        summary = "대상 1: 나이아신아마이드는 미백에 도움이 됩니다."
        answer = EvidenceAnswer(
            answer_id="answer-1",
            subject="나이아신아마이드",
            summary=summary,
            evidence_ids=["ev-1"],
            is_demo=False,
        )
        matching_citation = Citation(
            evidence_id="ev-1",
            source_id="src-1",
            locator="p.1",
            source_title="CIR 보고서",
            url="https://example.com/ev1",
        )
        unrelated_citation = Citation(
            evidence_id="ev-2", source_id="src-2", locator="p.2", source_title="관련 없는 문서"
        )
        output = _output(
            summary, artifacts=[answer], citations=[matching_citation, unrelated_citation]
        )

        sections = parser.parse(output, product_details={})

        assert len(sections) == 1
        section = sections[0]
        assert isinstance(section, ChatEvidenceSection)
        assert section.answer_id == "answer-1"
        assert section.subject == "나이아신아마이드"
        assert len(section.references) == 1
        assert section.references[0].source_title == "CIR 보고서"
        assert section.references[0].url == "https://example.com/ev1"

    def test_routine_paragraph_becomes_routine_section(self, parser: ChatSectionParser) -> None:
        placement = RoutinePlacement(
            weekday=Weekday.MONDAY,
            period=DayPeriod.MORNING,
            product_id="11111111-1111-1111-1111-111111111111",
            product_name="순한 클렌저",
            order=1,
            reason="세안 단계",
        )
        constraint = RoutineConstraint(
            description="주 2회 이하로 사용", source=ConstraintSource.PRODUCT_DIRECTIONS
        )
        plan = RoutinePlan(
            routine_id="routine-1",
            version=1,
            placements=[placement],
            constraints=[constraint],
            changes=["첫 루틴 생성"],
            is_demo=False,
        )
        message = "루틴 초안:\n1일차:\n- 세안: 순한 클렌저"
        output = _output(message, artifacts=[plan])

        sections = parser.parse(output, product_details={})

        assert len(sections) == 1
        section = sections[0]
        assert isinstance(section, ChatRoutineSection)
        assert section.routine_id == "routine-1"
        assert section.version == 1
        assert section.constraints == ["주 2회 이하로 사용"]
        assert section.changes == ["첫 루틴 생성"]
        assert len(section.days) == 1
        assert section.days[0].weekday == Weekday.MONDAY
        assert section.days[0].steps[0].product_name == "순한 클렌저"

    def test_unknown_role_label_falls_back_to_text_without_losing_content(
        self, parser: ChatSectionParser
    ) -> None:
        """Agent의 역할 라벨 형식이 바뀌어도 예외 없이, 정보 손실 없이 text로 떨어진다."""
        candidate = ProductCandidate(
            rank=1,
            product=ProductRecord(
                product_id="p-1",
                name="어떤 제품",
                source_id="s:1",
                checked_at="2026-01-01T00:00:00",
            ),
        )
        candidate_set = ProductCandidateSet(candidate_set_id="cs-1", candidates=[candidate])
        message = "제품 후보:\n[알수없는역할]\n1번. 어떤 제품"
        output = _output(message, artifacts=[candidate_set])

        sections = parser.parse(output, product_details={})

        assert sections == [ChatTextSection(text=message)]

    def test_sections_recompose_original_message_in_paragraph_order(
        self, parser: ChatSectionParser
    ) -> None:
        """각 섹션의 원문을 순서대로 이어 붙이면 원래 message가 복원돼야 한다."""
        detail = "현재 연결된 근거로 충분히 확인하지 못한 후보 성분: 레티놀"
        unresolved = UnresolvedItem(kind=UnresolvedKind.MISSING_INFORMATION, detail=detail)
        text_paragraph = "요청하신 내용을 확인했습니다."
        message = f"{text_paragraph}\n\n{detail}"
        output = _output(message, unresolved=[unresolved])

        sections = parser.parse(output, product_details={})

        recomposed = "\n\n".join(
            section.detail if isinstance(section, ChatNoticeSection) else section.text
            for section in sections
        )
        assert recomposed == message
