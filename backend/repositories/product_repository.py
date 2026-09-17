"""`product` 조회·저장. commit은 하지 않는다."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductServiceCategory,
    ProductTargetGroup,
    ProductTitleSource,
    ProductTypeNormalized,
)


class ProductUpsertInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    source_product_id: str
    search_query: str
    target_group: ProductTargetGroup | None
    raw_title: str
    display_title: str
    title_source: ProductTitleSource
    brand: str
    maker: str | None
    category1: str
    category2: str | None
    category3: str | None
    product_type_normalized: ProductTypeNormalized | None
    service_category: ProductServiceCategory | None
    lowest_price: int
    highest_price: int
    price_band: ProductPriceBand
    volume_value: float | None
    volume_unit: str | None
    image_url: str
    local_image_path: str
    shopping_url: str
    mall_name: str
    product_type: str
    observed_at: datetime
    match_status: ProductMatchStatus
    review_reasons: list[str]


class ProductTaxonomyUpdate(BaseModel):
    """`ProductRepository.update_taxonomy`의 입력. 분류 두 필드만 갱신 대상이다."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_product_id: str
    product_type_normalized: ProductTypeNormalized | None
    service_category: ProductServiceCategory | None


class ProductTitleUpdate(BaseModel):
    """`ProductRepository.update_title`의 입력. 상품명 두 필드만 갱신 대상이다.

    가격·이미지·URL·카테고리 등 나머지 필드는 이 모델에 없다 — 백필이 title 매핑만
    가지고 있을 때, 다른 필드를 실수로 덮어쓸 방법 자체를 없앤다.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    source_product_id: str
    display_title: str
    title_source: ProductTitleSource


class ProductRepository:
    """`Product` 조회·저장 전용. commit은 하지 않는다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, source: str, source_product_id: str) -> Product | None:
        statement = select(Product).where(
            Product.source == source, Product.source_product_id == source_product_id
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def upsert(self, input_: ProductUpsertInput) -> tuple[Product, bool]:
        existing = await self.find(input_.source, input_.source_product_id)
        if existing is not None:
            self._apply(existing, input_)
            return existing, False

        product = self._to_row(input_)
        self._session.add(product)
        return product, True

    async def update_taxonomy(self, input_: ProductTaxonomyUpdate) -> Product:
        """분류 두 필드만 갱신한다. 전체 재적재와 달리 상품명·가격 등은 건드리지 않는다."""
        existing = await self.find(input_.source, input_.source_product_id)
        if existing is None:
            raise LookupError(
                f"분류 백필 대상 상품을 찾지 못함: source={input_.source}, "
                f"source_product_id={input_.source_product_id}"
            )

        # 값이 같으면 대입해도 SQLAlchemy가 dirty로 표시하지 않아 UPDATE가 안 나가지만,
        # 재실행 시 "정말 안 바뀌었다"는 걸 명시적으로 드러내기 위해 비교부터 한다.
        if (
            existing.product_type_normalized == input_.product_type_normalized
            and existing.service_category == input_.service_category
        ):
            return existing

        existing.product_type_normalized = input_.product_type_normalized
        existing.service_category = input_.service_category
        return existing

    async def update_title(self, input_: ProductTitleUpdate) -> Product:
        """상품명(`display_title`, `title_source`) 두 필드만 갱신한다.

        `_apply`(전체 재적재)와 달리 가격·이미지·URL·카테고리·raw_title 등은 절대
        건드리지 않는다 — localization 백필은 raw_title 기준 매핑만 갖고 있고 나머지
        필드의 최신값을 모르므로, 건드릴 수 있는 필드 자체를 이 두 개로 좁힌다.
        """
        existing = await self.find(input_.source, input_.source_product_id)
        if existing is None:
            raise LookupError(
                f"title 백필 대상 상품을 찾지 못함: source={input_.source}, "
                f"source_product_id={input_.source_product_id}"
            )

        # update_taxonomy와 같은 이유로 비교부터 한다: 값이 같으면 SQLAlchemy가 dirty로
        # 표시하지 않아 UPDATE가 안 나가므로, 재실행 시 "정말 안 바뀌었다"를 명시적으로 본다.
        if existing.display_title == input_.display_title and existing.title_source == input_.title_source:
            return existing

        existing.display_title = input_.display_title
        existing.title_source = input_.title_source
        return existing

    def _apply(self, row: Product, input_: ProductUpsertInput) -> None:
        row.search_query = input_.search_query
        row.target_group = input_.target_group
        row.raw_title = input_.raw_title
        row.display_title = input_.display_title
        row.title_source = input_.title_source
        row.brand = input_.brand
        row.maker = input_.maker
        row.category1 = input_.category1
        row.category2 = input_.category2
        row.category3 = input_.category3
        row.product_type_normalized = input_.product_type_normalized
        row.service_category = input_.service_category
        row.lowest_price = input_.lowest_price
        row.highest_price = input_.highest_price
        row.price_band = input_.price_band
        row.volume_value = input_.volume_value
        row.volume_unit = input_.volume_unit
        row.image_url = input_.image_url
        row.local_image_path = input_.local_image_path
        row.shopping_url = input_.shopping_url
        row.mall_name = input_.mall_name
        row.product_type = input_.product_type
        row.observed_at = input_.observed_at
        row.match_status = input_.match_status
        row.review_reasons = input_.review_reasons

    def _to_row(self, input_: ProductUpsertInput) -> Product:
        return Product(
            source=input_.source,
            source_product_id=input_.source_product_id,
            search_query=input_.search_query,
            target_group=input_.target_group,
            raw_title=input_.raw_title,
            display_title=input_.display_title,
            title_source=input_.title_source,
            brand=input_.brand,
            maker=input_.maker,
            category1=input_.category1,
            category2=input_.category2,
            category3=input_.category3,
            product_type_normalized=input_.product_type_normalized,
            service_category=input_.service_category,
            lowest_price=input_.lowest_price,
            highest_price=input_.highest_price,
            price_band=input_.price_band,
            volume_value=input_.volume_value,
            volume_unit=input_.volume_unit,
            image_url=input_.image_url,
            local_image_path=input_.local_image_path,
            shopping_url=input_.shopping_url,
            mall_name=input_.mall_name,
            product_type=input_.product_type,
            observed_at=input_.observed_at,
            match_status=input_.match_status,
            review_reasons=input_.review_reasons,
        )
