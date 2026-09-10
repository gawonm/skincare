# data → backend: 상품 카탈로그 저장

data 파트(`scripts/ingest_product_catalog.py`)가 상품 카탈로그 CSV 한 행을 파싱한 뒤,
DB에 저장하는 걸 backend 파트에 맡긴다. 저장 로직(`backend/repositories/`,
`backend/services/`)은 [CLAUDE.md](../../CLAUDE.md) 규칙 15의 경로표상 backend 파트 소유라
data 파트가 직접 만들지 않는다.

## 부르는 대상

```python
ProductService.ingest(row: ProductCandidateRow) -> tuple[Product, bool]
```

`backend/services/product_service.py`에 둔다 (`backend/repositories/product_repository.py`의
`ProductRepository`를 내부에서 쓴다).

## 입력

`ProductCandidateRow` — data 파트가 이미 정의해 둔 모델. `scripts/product_candidate_schemas.py`
소유(캐주얼 변경 없음, 값이 바뀌면 이 문서를 먼저 고친다).

```python
class ProductCandidateRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    source: DataSource
    target_group: TargetGroup | None = None
    search_query: str
    source_product_id: str
    raw_title: str
    display_title: str
    title_source: TitleSource
    brand: str
    maker: str
    category1: str
    category2: str
    category3: str
    lowest_price: int
    highest_price: int
    price_band: PriceBand
    volume_value: float | None = None
    volume_unit: str | None = None
    image_url: str
    local_image_path: str
    raw_ingredients_text: str | None = None
    shopping_url: str
    mall_name: str
    product_type: str
    observed_at: datetime
    match_status: MatchStatus
    review_reasons: tuple[ReviewReason, ...] = ()
```

## 출력

`tuple[Product, bool]` — `Product`는 `models/product.py`(data 파트 소유, 이미 작성·마이그레이션
완료). 두 번째 값은 신규 생성 여부(`True`=새 행 생성, `False`=기존 행 갱신).

`Product`는 `(source, source_product_id)` UK로 **최신 상태 한 행만 유지**한다 — 이력 저장소가
아니다. 같은 상품을 다시 `ingest`하면 기존 행을 덮어쓴다. (판단 근거는
[docs/erd/app.md](../erd/app.md) 참고.)

## 누가 이 타입을 소유하나

| 타입 | 위치 | 소유 |
| --- | --- | --- |
| `ProductCandidateRow` | `scripts/product_candidate_schemas.py` | data |
| `Product` (ORM 모델) | `models/product.py` | data |
| `ProductService`, `ProductRepository` | `backend/services/`, `backend/repositories/` | backend |

## 실패했을 때

현재 명시적으로 잡는 예외 없음. `ingredient_id` FK 위반이나 NOT NULL 위반 등은 SQLAlchemy
예외가 그대로 올라간다. 이 계약을 부르는 `scripts/ingest_product_catalog.py`는 개별 행 실패를
잡지 않고 전체 배치가 실패하게 둔다 — 필요하면 이 부분을 backend와 협의해 바꾼다(미정).

## 아직 안 정한 것

- **commit 시점**: 기존 `ProductIngredientService` 관례를 따르면 `ProductService`는 flush만
  하고 `commit`은 호출부(`scripts/`)가 한다. backend 파트가 다르게 정하고 싶으면 여기에 먼저
  적고 협의한다.
- 개별 행 실패 시 계속 진행할지(skip) 전체 중단할지.

## 참고 구현 (data 세션이 먼저 짜본 버전)

아래는 이 계약대로 동작을 한 번 구현·검증(1,838개 상품 적재, 재실행 idempotent 확인)까지
끝낸 코드다. backend 파트가 그대로 가져가 써도 되고, 다르게 설계해도 된다 — 참고용이다.

<details>
<summary><code>backend/repositories/product_repository.py</code></summary>

```python
"""`product` 조회·저장. commit은 하지 않는다."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductTargetGroup,
    ProductTitleSource,
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


class ProductRepository:
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
```

</details>

<details>
<summary><code>backend/services/product_service.py</code></summary>

```python
"""`scripts/product_candidate_schemas.py`의 `ProductCandidateRow`를 받아 `product`
테이블에 저장한다."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.product_repository import ProductRepository, ProductUpsertInput
from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductTargetGroup,
    ProductTitleSource,
)
from scripts.product_candidate_schemas import ProductCandidateRow


class ProductService:
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
```

</details>

이 두 파일로 `uv run python -m scripts.ingest_product_catalog` 실행 → 1,838개 상품 적재,
재실행 시 중복 없이 갱신만 발생하는 것까지 확인했다.
