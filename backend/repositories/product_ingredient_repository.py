"""`product_ingredient_snapshot`/`product_ingredient` 저장·조회. commit은 하지 않는다.

`ProductIngredientInsert`를 이 파일에 따로 두는 이유는 `rag_chunk_repository.py`와 같다 -
`backend/repositories/`는 `models`만 import한다는 규칙이 있어 `scripts.product_ingredient_parse_schemas`를
직접 받을 수 없다. 호출하는 쪽(`backend/services/`)이 그 결과를 이 DTO로 변환해 넘긴다.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product_ingredient import (
    IngredientMatchAcceptance,
    ProductIngredient,
    ProductIngredientSectionLinkStatus,
    ProductIngredientSnapshot,
    ProductIngredientTokenParseStatus,
)


class ProductIngredientTokenInsert(BaseModel):
    """`ProductIngredientRepository.sync_tokens`의 입력 한 건(토큰 하나)."""

    model_config = ConfigDict(frozen=True)

    section_sequence: int
    section_label: str | None
    section_link_status: ProductIngredientSectionLinkStatus
    linked_option_gds_cd: str | None
    token_order: int
    raw_token: str
    matching_name: str
    concentration_text: str | None
    token_parse_status: ProductIngredientTokenParseStatus
    token_review_reason: str | None
    ingredient_id: UUID | None
    match_method: str | None
    match_acceptance: IngredientMatchAcceptance
    match_review_reason: str | None

    def position_key(self) -> tuple[int, int]:
        return (self.section_sequence, self.token_order)


class ProductIngredientTokenSyncResult(BaseModel):
    """`sync_tokens` 실행 결과. 무엇이 실제로 바뀌었는지 검증할 때 쓴다."""

    model_config = ConfigDict(frozen=True)

    inserted: int
    updated: int
    unchanged: int
    deleted: int


class ProductIngredientRepository:
    """`ProductIngredientSnapshot`/`ProductIngredient` 조회·저장 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_snapshot(
        self, source: str, source_product_id: str, raw_text_hash: str
    ) -> ProductIngredientSnapshot | None:
        """같은 원문(해시 동일)의 스냅샷이 이미 있으면 재사용한다 - 없으면 재파싱해도 새 스냅샷을 안 만든다."""
        statement = select(ProductIngredientSnapshot).where(
            ProductIngredientSnapshot.source == source,
            ProductIngredientSnapshot.source_product_id == source_product_id,
            ProductIngredientSnapshot.raw_text_hash == raw_text_hash,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create_snapshot(
        self,
        source: str,
        source_product_id: str,
        raw_ingredients_text: str,
        raw_text_hash: str,
        parser_version: str,
    ) -> ProductIngredientSnapshot:
        snapshot = ProductIngredientSnapshot(
            source=source,
            source_product_id=source_product_id,
            raw_ingredients_text=raw_ingredients_text,
            raw_text_hash=raw_text_hash,
            parser_version=parser_version,
        )
        self._session.add(snapshot)
        await self._session.flush()  # 이후 토큰 insert가 참조할 snapshot.id를 확정해야 한다.
        return snapshot

    async def sync_tokens(
        self, snapshot_id: UUID, inserts: list[ProductIngredientTokenInsert]
    ) -> ProductIngredientTokenSyncResult:
        """이 스냅샷의 토큰을 `inserts`와 일치하도록 맞춘다(같은 파서 버전 재실행 = 무변경).

        스냅샷이 새로 만들어진 직후(토큰이 하나도 없는 상태)에도, 파서 버전이 올라가
        같은 원문을 다시 토큰화했을 때도(기존 토큰과 위치가 겹칠 수 있음) 모두 이 메서드
        하나로 처리한다 - 위치(`section_sequence`, `token_order`)가 같으면 갱신, 새 위치는
        삽입, 더 이상 없는 위치는 삭제.
        """
        existing = await self._existing_by_position(snapshot_id)
        new_by_key = {insert.position_key(): insert for insert in inserts}

        to_delete: list[UUID] = []
        to_update: list[tuple[ProductIngredient, ProductIngredientTokenInsert]] = []
        unchanged = 0

        for key, row in existing.items():
            new_insert = new_by_key.get(key)
            if new_insert is None:
                to_delete.append(row.id)
            elif self._is_unchanged(row, new_insert):
                unchanged += 1
            else:
                to_update.append((row, new_insert))

        to_insert = [insert for key, insert in new_by_key.items() if key not in existing]

        if to_delete:
            await self._session.execute(
                delete(ProductIngredient).where(ProductIngredient.id.in_(to_delete))
            )
        for row, new_insert in to_update:
            self._apply(row, new_insert)
        if to_insert:
            self._session.add_all(self._to_rows(snapshot_id, to_insert))

        return ProductIngredientTokenSyncResult(
            inserted=len(to_insert),
            updated=len(to_update),
            unchanged=unchanged,
            deleted=len(to_delete),
        )

    async def _existing_by_position(
        self, snapshot_id: UUID
    ) -> dict[tuple[int, int], ProductIngredient]:
        statement = select(ProductIngredient).where(ProductIngredient.snapshot_id == snapshot_id)
        result = await self._session.execute(statement)
        return {(row.section_sequence, row.token_order): row for row in result.scalars().all()}

    def _is_unchanged(self, row: ProductIngredient, insert: ProductIngredientTokenInsert) -> bool:
        return (
            row.section_label == insert.section_label
            and row.section_link_status == insert.section_link_status
            and row.linked_option_gds_cd == insert.linked_option_gds_cd
            and row.raw_token == insert.raw_token
            and row.matching_name == insert.matching_name
            and row.concentration_text == insert.concentration_text
            and row.token_parse_status == insert.token_parse_status
            and row.token_review_reason == insert.token_review_reason
            and row.ingredient_id == insert.ingredient_id
            and row.match_method == insert.match_method
            and row.match_acceptance == insert.match_acceptance
            and row.match_review_reason == insert.match_review_reason
        )

    def _apply(self, row: ProductIngredient, insert: ProductIngredientTokenInsert) -> None:
        row.section_label = insert.section_label
        row.section_link_status = insert.section_link_status
        row.linked_option_gds_cd = insert.linked_option_gds_cd
        row.raw_token = insert.raw_token
        row.matching_name = insert.matching_name
        row.concentration_text = insert.concentration_text
        row.token_parse_status = insert.token_parse_status
        row.token_review_reason = insert.token_review_reason
        row.ingredient_id = insert.ingredient_id
        row.match_method = insert.match_method
        row.match_acceptance = insert.match_acceptance
        row.match_review_reason = insert.match_review_reason

    def _to_rows(
        self, snapshot_id: UUID, inserts: list[ProductIngredientTokenInsert]
    ) -> list[ProductIngredient]:
        return [
            ProductIngredient(
                snapshot_id=snapshot_id,
                section_sequence=insert.section_sequence,
                section_label=insert.section_label,
                section_link_status=insert.section_link_status,
                linked_option_gds_cd=insert.linked_option_gds_cd,
                token_order=insert.token_order,
                raw_token=insert.raw_token,
                matching_name=insert.matching_name,
                concentration_text=insert.concentration_text,
                token_parse_status=insert.token_parse_status,
                token_review_reason=insert.token_review_reason,
                ingredient_id=insert.ingredient_id,
                match_method=insert.match_method,
                match_acceptance=insert.match_acceptance,
                match_review_reason=insert.match_review_reason,
            )
            for insert in inserts
        ]
