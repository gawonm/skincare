"""상품 조회 유스케이스: 홈 목록, 상세. 읽기 전용이라 commit이 없다."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.product_repository import ProductRepository
from backend.schemas.product import ProductCardResponse, ProductDetailResponse, ProductListResponse
from models.product import Product, ProductServiceCategory


class ProductQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = ProductRepository(session)

    async def list_popular(
        self, *, service_category: ProductServiceCategory | None, limit: int
    ) -> ProductListResponse:
        products = await self._repository.list_popular(
            service_category=service_category, limit=limit
        )
        return ProductListResponse(
            items=[self._to_card(product) for product in products],
            total=len(products),
        )

    async def get_detail(self, product_id: UUID) -> ProductDetailResponse | None:
        """상세 조회. 존재하면 조회수를 1 증가시키고 커밋한 뒤 새 값을 응답에 싣는다.

        홈 목록(`list_popular`)은 그냥 지나치는 것만으로는 증가시키지 않는다 — "본다"로
        셀 만한 행동은 상세를 여는 것뿐이라는 2026-09-23 확정에 따른다.
        """
        product = await self._repository.get_by_id(product_id)
        if product is None:
            return None
        view_count = await self._repository.increment_view_count(product_id)
        await self._session.commit()
        return self._to_detail(product, view_count)

    def _to_card(self, product: Product) -> ProductCardResponse:
        return ProductCardResponse(
            id=product.id,
            display_title=product.display_title,
            brand=product.brand,
            image_url=product.image_url,
            lowest_price=product.lowest_price,
            service_category=product.service_category,
            volume_value=product.volume_value,
            volume_unit=product.volume_unit,
            view_count=product.view_count,
        )

    def _to_detail(self, product: Product, view_count: int) -> ProductDetailResponse:
        return ProductDetailResponse(
            id=product.id,
            display_title=product.display_title,
            brand=product.brand,
            image_url=product.image_url,
            lowest_price=product.lowest_price,
            service_category=product.service_category,
            volume_value=product.volume_value,
            volume_unit=product.volume_unit,
            view_count=view_count,
            maker=product.maker,
            category1=product.category1,
            category2=product.category2,
            category3=product.category3,
            price_band=product.price_band,
            shopping_url=product.shopping_url,
            mall_name=product.mall_name,
        )
