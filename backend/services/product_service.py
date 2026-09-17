"""`data/scripts/product_candidate_schemas.py`의 `ProductCandidateRow`를 받아 `product`
테이블에 저장한다."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.product_repository import (
    ProductRepository,
    ProductTaxonomyUpdate,
    ProductTitleUpdate,
    ProductUpsertInput,
)
from data.scripts.product_candidate_schemas import ProductCandidateRow
from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductServiceCategory,
    ProductTargetGroup,
    ProductTitleSource,
    ProductTypeNormalized,
)


class ProductService:
    """상품 카탈로그 행 하나를 저장까지 끝낸다. commit은 호출부가 한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._repository = ProductRepository(session)

    async def ingest(self, row: ProductCandidateRow) -> tuple[Product, bool]:
        input_ = ProductUpsertInput(
            source=row.source.value,
            source_product_id=row.source_product_id,
            search_query=row.search_query,
            target_group=ProductTargetGroup(row.target_group.value) if row.target_group else None,
            raw_title=row.raw_title,
            display_title=row.display_title,
            title_source=ProductTitleSource(row.title_source.value),
            brand=row.brand,
            maker=row.maker or None,
            category1=row.category1,
            category2=row.category2 or None,
            category3=row.category3 or None,
            product_type_normalized=ProductTypeNormalized(row.product_type_normalized.value)
            if row.product_type_normalized
            else None,
            service_category=ProductServiceCategory(row.service_category.value)
            if row.service_category
            else None,
            lowest_price=row.lowest_price,
            highest_price=row.highest_price,
            price_band=ProductPriceBand(row.price_band.value),
            volume_value=row.volume_value,
            volume_unit=row.volume_unit,
            image_url=row.image_url,
            local_image_path=row.local_image_path,
            shopping_url=row.shopping_url,
            mall_name=row.mall_name,
            product_type=row.product_type,
            observed_at=row.observed_at,
            match_status=ProductMatchStatus(row.match_status.value),
            review_reasons=[reason.value for reason in row.review_reasons],
        )
        return await self._repository.upsert(input_)

    async def update_taxonomy(self, row: ProductCandidateRow) -> Product:
        """이미 적재된 상품의 분류 두 필드만 갱신한다. 재크롤링 없이 분류기만 다시 돌릴 때 쓴다."""
        input_ = ProductTaxonomyUpdate(
            source=row.source.value,
            source_product_id=row.source_product_id,
            product_type_normalized=ProductTypeNormalized(row.product_type_normalized.value)
            if row.product_type_normalized
            else None,
            service_category=ProductServiceCategory(row.service_category.value)
            if row.service_category
            else None,
        )
        return await self._repository.update_taxonomy(input_)

    async def update_title(self, row: ProductCandidateRow) -> Product:
        """이미 적재된 상품의 상품명 두 필드만 갱신한다. localization 백필 전용."""
        input_ = ProductTitleUpdate(
            source=row.source.value,
            source_product_id=row.source_product_id,
            display_title=row.display_title,
            title_source=ProductTitleSource(row.title_source.value),
        )
        return await self._repository.update_title(input_)
