"""올리브영 파서(`data/scripts/product_ingredient_text_parser.py` +
`data/scripts/product_ingredient_option_linker.py`)가 만든 `ProductIngredientParseResult`를 받아
표준 성분(`IngredientMaster`)과 매칭하고 `product_ingredient_snapshot`/`product_ingredient`에
저장한다.

`data/scripts/`에 두지 않고 여기 두는 이유는 `rag_ingestion_service.py`와 같다 - 저장에
`backend/repositories`가 필요하고, `backend/services/`가 이미 `scripts`를 부르는 계층이라
(`RagIngestionService`가 `data.scripts.mfds_importer` 등을 이미 그렇게 쓴다) 여기서 조립한다.

원문이 그대로면(해시 동일) 재실행해도 새 스냅샷을 만들지 않는다. 원문은 그대로인데 파서
버전만 올라간 경우(로직 개선) 기존 스냅샷의 `parser_version`만 갱신하고 토큰을
`sync_tokens`로 다시 맞춘다 - 원문이 실제로 바뀐 경우만 새 스냅샷 행(이력)이 늘어난다.
"""

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.ingredient_master_repository import IngredientMasterRepository
from backend.repositories.product_ingredient_repository import (
    ProductIngredientRepository,
    ProductIngredientTokenInsert,
    ProductIngredientTokenSyncResult,
)
from data.scripts.ingredient_name_matcher import IngredientNameMatcher
from data.scripts.ingredient_name_normalizer import IngredientNameNormalizer
from data.scripts.product_ingredient_match_acceptance_policy import (
    ProductIngredientMatchAcceptancePolicy,
)
from data.scripts.product_ingredient_parse_schemas import (
    IngredientSectionLinkStatus,
    IngredientSectionParse,
    IngredientTokenParseStatus,
    ParsedIngredientToken,
    ProductIngredientParseResult,
)
from models.product_ingredient import (
    IngredientMatchAcceptance,
    ProductIngredientSectionLinkStatus,
    ProductIngredientSnapshot,
    ProductIngredientTokenParseStatus,
)


class ProductIngredientIngestionResult:
    """`ProductIngredientService.ingest` 실행 결과. 무엇이 실제로 바뀌었는지 검증할 때 쓴다."""

    def __init__(
        self,
        snapshot: ProductIngredientSnapshot,
        is_new_snapshot: bool,
        token_sync: ProductIngredientTokenSyncResult,
    ) -> None:
        self.snapshot = snapshot
        self.is_new_snapshot = is_new_snapshot
        self.token_sync = token_sync


# 파싱 단계의 두 Enum(`IngredientSectionLinkStatus`/`IngredientTokenParseStatus`)과 저장
# 단계의 두 Enum(`ProductIngredientSectionLinkStatus`/`ProductIngredientTokenParseStatus`)은
# 값(`.value`)만 같고 별개 타입이다 - `models/`가 `data/scripts/`를 import하지 않는다는 규칙
# 때문에 값으로만 변환한다. 값이 어긋나면 아래 매핑에서 KeyError로 바로 드러난다.
_SECTION_LINK_STATUS_MAP = {
    IngredientSectionLinkStatus.NO_OPTION_SECTIONS: ProductIngredientSectionLinkStatus.NO_OPTION_SECTIONS,
    IngredientSectionLinkStatus.LINKED: ProductIngredientSectionLinkStatus.LINKED,
    IngredientSectionLinkStatus.AMBIGUOUS: ProductIngredientSectionLinkStatus.AMBIGUOUS,
}
_TOKEN_PARSE_STATUS_MAP = {
    IngredientTokenParseStatus.PARSED: ProductIngredientTokenParseStatus.PARSED,
    IngredientTokenParseStatus.NEEDS_REVIEW: ProductIngredientTokenParseStatus.NEEDS_REVIEW,
}


class ProductIngredientService:
    """파싱 결과 하나를 매칭·저장까지 끝낸다. commit은 호출부가 한다."""

    def __init__(self, session: AsyncSession, matcher: IngredientNameMatcher) -> None:
        self._repository = ProductIngredientRepository(session)
        self._policy = ProductIngredientMatchAcceptancePolicy(matcher)

    @classmethod
    async def create(cls, session: AsyncSession) -> "ProductIngredientService":
        """`IngredientMaster` 후보를 조회해 매칭기를 만들어준다."""
        candidates = await IngredientMasterRepository(session).list_all_as_candidates()
        matcher = IngredientNameMatcher(candidates, IngredientNameNormalizer())
        return cls(session, matcher)

    async def ingest(
        self, source: str, parse_result: ProductIngredientParseResult, parser_version: str
    ) -> ProductIngredientIngestionResult:
        raw_text_hash = self._hash(parse_result.raw_ingredients_text)
        existing = await self._repository.find_snapshot(
            source, parse_result.source_product_id, raw_text_hash
        )

        if existing is not None:
            # 원문(해시)이 같다 - 새 스냅샷을 만들지 않는다. 파서 버전만 다르면(로직이
            # 바뀌어 재파싱했지만 원문 자체는 그대로) 버전 표시만 갱신한다.
            existing.parser_version = parser_version
            snapshot = existing
            is_new_snapshot = False
        else:
            snapshot = await self._repository.create_snapshot(
                source=source,
                source_product_id=parse_result.source_product_id,
                raw_ingredients_text=parse_result.raw_ingredients_text,
                raw_text_hash=raw_text_hash,
                parser_version=parser_version,
            )
            is_new_snapshot = True

        inserts = self._build_token_inserts(parse_result)
        token_sync = await self._repository.sync_tokens(snapshot.id, inserts)

        return ProductIngredientIngestionResult(
            snapshot=snapshot, is_new_snapshot=is_new_snapshot, token_sync=token_sync
        )

    def _build_token_inserts(
        self, parse_result: ProductIngredientParseResult
    ) -> list[ProductIngredientTokenInsert]:
        inserts: list[ProductIngredientTokenInsert] = []
        for section_sequence, section in enumerate(parse_result.sections):
            section_link_status = _SECTION_LINK_STATUS_MAP[section.link_status]
            for token in section.tokens:
                inserts.append(
                    self._build_token_insert(section_sequence, section_link_status, section, token)
                )
        return inserts

    def _build_token_insert(
        self,
        section_sequence: int,
        section_link_status: ProductIngredientSectionLinkStatus,
        section: IngredientSectionParse,
        token: ParsedIngredientToken,
    ) -> ProductIngredientTokenInsert:
        token_parse_status = _TOKEN_PARSE_STATUS_MAP[token.parse_status]

        if token_parse_status is ProductIngredientTokenParseStatus.NEEDS_REVIEW:
            # 구분자 누락 의심 토큰은 내용 자체가 불확실하다 - 매칭을 시도하지 않고
            # 그대로 검토로 넘긴다(임의로 잘라서 매칭하지 않는다는 계약).
            return ProductIngredientTokenInsert(
                section_sequence=section_sequence,
                section_label=section.section_label,
                section_link_status=section_link_status,
                linked_option_gds_cd=section.linked_option_gds_cd,
                token_order=token.order,
                raw_token=token.raw_token,
                matching_name=token.matching_name,
                concentration_text=token.concentration_text,
                token_parse_status=token_parse_status,
                token_review_reason=token.review_reason,
                ingredient_id=None,
                match_method=None,
                match_acceptance=IngredientMatchAcceptance.NEEDS_REVIEW,
                match_review_reason=token.review_reason,
            )

        match_result = self._policy.match(token.matching_name)
        if match_result.matched_ingredient_id is not None:
            match_acceptance = IngredientMatchAcceptance.CONFIRMED
            match_review_reason = None
        elif match_result.review_candidate_ids:
            match_acceptance = IngredientMatchAcceptance.NEEDS_REVIEW
            match_review_reason = (
                f"매칭 방법={match_result.method.value}, "
                f"검토 후보={[str(cid) for cid in match_result.review_candidate_ids]}"
            )
        else:
            match_acceptance = IngredientMatchAcceptance.UNMATCHED
            match_review_reason = "표준 성분과 매칭되는 후보를 찾지 못함"

        return ProductIngredientTokenInsert(
            section_sequence=section_sequence,
            section_label=section.section_label,
            section_link_status=section_link_status,
            linked_option_gds_cd=section.linked_option_gds_cd,
            token_order=token.order,
            raw_token=token.raw_token,
            matching_name=token.matching_name,
            concentration_text=token.concentration_text,
            token_parse_status=token_parse_status,
            token_review_reason=None,
            ingredient_id=match_result.matched_ingredient_id,
            match_method=match_result.method.value,
            match_acceptance=match_acceptance,
            match_review_reason=match_review_reason,
        )

    def _hash(self, raw_text: str) -> str:
        return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
