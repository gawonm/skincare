# data → backend: 상품 카탈로그 저장

data 파트(`data/scripts/ingest_product_catalog.py`)가 상품 카탈로그 CSV 한 행을 파싱한 뒤,
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

`ProductCandidateRow` — data 파트가 이미 정의해 둔 모델. `data/scripts/product_candidate_schemas.py`
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
| `ProductCandidateRow` | `data/scripts/product_candidate_schemas.py` | data |
| `Product` (ORM 모델) | `models/product.py` | data |
| `ProductService`, `ProductRepository` | `backend/services/`, `backend/repositories/` | backend |

## 실패했을 때

현재 명시적으로 잡는 예외 없음. `ingredient_id` FK 위반이나 NOT NULL 위반 등은 SQLAlchemy
예외가 그대로 올라간다. 이 계약을 부르는 `data/scripts/ingest_product_catalog.py`는 개별 행 실패를
잡지 않고 전체 배치가 실패하게 둔다 — 필요하면 이 부분을 backend와 협의해 바꾼다(미정).

## 아직 안 정한 것

- **commit 시점**: 기존 `ProductIngredientService` 관례를 따르면 `ProductService`는 flush만
  하고 `commit`은 호출부(`data/scripts/`)가 한다. backend 파트가 다르게 정하고 싶으면 여기에 먼저
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
"""`data/scripts/product_candidate_schemas.py`의 `ProductCandidateRow`를 받아 `product`
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
from data.scripts.product_candidate_schemas import ProductCandidateRow


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

이 두 파일로 `uv run python -m data.scripts.ingest_product_catalog` 실행 → 1,838개 상품 적재,
재실행 시 중복 없이 갱신만 발생하는 것까지 확인했다.


## 상품 분류 확장안 — 2026-09-11, 사용자 확인 완료·backend 합의 전

이 절은 위의 기존 계약과 참고 구현에 대한 변경 제안이다. 위 참고 구현의 기존 검증 기록은
새 분류 필드의 검증 기록이 아니다. 현재 로컬에는 `product_service.py`와
`product_repository.py`가 없고, `product_ingredient_service.py`와
`product_ingredient_repository.py`는 전성분 테이블만 담당한다.

### 타입과 입력 변경

`data/scripts/product_candidate_schemas.py`에 아래 타입을 정의하고 기존
`ProductCandidateRow`에 두 선택 필드를 추가한다. 기존 필드는 그대로 유지한다.

```python
from enum import StrEnum

class ProductTypeNormalized(StrEnum):
    SERUM = "serum"
    ESSENCE = "essence"
    AMPOULE = "ampoule"
    CREAM = "cream"
    LOTION = "lotion"
    EMULSION = "emulsion"
    TONER = "toner"
    TONER_PAD = "toner_pad"
    CLEANSER = "cleanser"
    CLEANSING_FOAM = "cleansing_foam"
    CLEANSING_GEL = "cleansing_gel"
    CLEANSING_OIL = "cleansing_oil"
    CLEANSING_BALM = "cleansing_balm"
    CLEANSING_WATER = "cleansing_water"
    SHEET_MASK = "sheet_mask"
    WASH_OFF_MASK = "wash_off_mask"
    SLEEPING_MASK = "sleeping_mask"
    PATCH = "patch"
    SUNSCREEN = "sunscreen"
    MIST = "mist"
    FACIAL_OIL = "facial_oil"
    BALM = "balm"
    SPOT_TREATMENT = "spot_treatment"
    BOOSTER = "booster"
    PEELING = "peeling"
    ALL_IN_ONE = "all_in_one"

class ServiceCategory(StrEnum):
    ESSENCE_SERUM = "에센스·세럼"
    AMPOULE = "앰플"
    CREAM_LOTION = "크림·로션"
    TONER_PAD = "토너·패드"
    CLEANSER = "클렌저"
    MASK_PATCH = "마스크·패치"
    SUNCARE = "선케어"
    OTHER = "기타"

# 기존 ProductCandidateRow 클래스에 추가할 필드
# product_type_normalized: ProductTypeNormalized | None = None
# service_category: ServiceCategory | None = None
```

ORM용 Enum은 기존 가격대 Enum의 관례대로 `models/product.py`에서 별도로 정의하고
값의 일치를 검증한다. 공용 `core`나 RAG 파일로 타입을 이동하지 않는다.
CSV에 새 컬럼이 없어도 None으로 읽으며, 빈 셀도 None으로 변환한다.

### 분류 및 저장 계약

- `ingest_product_catalog.py`에서 두 CSV를 합치고 기존 우선순위대로 중복을 제거한 후,
  새 `ProductTaxonomyNormalizer`가 원본 상품명·표시명·원본 카테고리를 바탕으로 분류한다.
- `ProductCandidateRow`는 frozen이므로 새 필드가 반영된 검증된 새 행을 만들어 전달한다.
  서비스 호출 형태 `ProductService.ingest(row)`와 기존 반환 형태는 유지한다.
- 분류 매핑은 `docs/erd/app.md`의 상품 분류 확장 표를 따른다.
  예: `cleansing_balm → 클렌저`, `mist → 기타`, 판별 불가 `None → None`.
- 분류 미리보기는 DB 서비스 import나 DB 연결 없이 실행 가능하게 한다.
  고유 상품 수·유형별 건수·그룹별 건수·미분류 상품과 사유를 보고한다.
- backend 담당자는 `ProductUpsertInput`, 서비스의 Enum 변환,
  리포지토리의 신규 생성과 기존 행 갱신에 두 필드를 모두 반영한다.
- None은 기존 값 유지 지시가 아니라 이번 분류에서 미확정이라는 뜻이다.
  전체 적재는 최신 분류 결과로 두 필드를 함께 갱신한다. 수동 확정값 보존 정책은 이번 범위에 없다.
- 기존 DB 행을 채우는 작업은 전체 카탈로그 재적재와 구분한다. backend 담당자가
  아래 갱신 메서드를 제공하면 기존 상품의 분류 두 필드만 갱신한다.
  상품명·가격·관측 시각·매칭 상태·전성분을 다시 적재하지 않는다.

```python
# backend 소유: backend/repositories/product_repository.py
# ProductUpsertInput 등과 동일하게 models.product의 ORM용 Enum을 사용한다.
class ProductTaxonomyUpdate(BaseModel):
    source: str
    source_product_id: str
    product_type_normalized: ProductTypeNormalized | None
    service_category: ServiceCategory | None

# ProductRepository 메서드 제안
async def update_taxonomy(self, input_: ProductTaxonomyUpdate) -> Product:
    ...

# backend 소유: backend/services/product_service.py
# 호출부는 이미 분류된 ProductCandidateRow를 넘긴다.
async def update_taxonomy(self, row: ProductCandidateRow) -> Product:
    ...
```

기존 상품을 찾지 못하면 `LookupError`로 실패하고 새 상품을 생성하지 않는다.
잘못된 Enum 입력은 검증 오류로 실패한다. 서비스는 리포지토리에 변환된 입력을 넘기고,
리포지토리는 commit하지 않는다. 기존 로더처럼 호출부에서 전체 성공 후 commit하는 것을 제안한다.
분류 전용 갱신을 재실행해 값이 같으면 UPDATE하지 않도록 한다.

### 담당 범위와 확인할 항목

- data: ERD·분류 스키마·분류기·CSV 호환성·적재 호출부·컬럼 추가 마이그레이션·검증.
- backend: 빠진 상품 서비스/리포지토리 구현, 신규·갱신 매핑, 분류 전용 갱신 메서드.
- 전성분 저장 파일과 RAG 파일은 변경하지 않는다.
- 사용자 확인: 제품 세부 유형과 서비스 카테고리를 분리하는 방향 확인 완료.
- backend 합의: 새 필드와 분류 전용 갱신 인터페이스, 트랜잭션 및 실패 정책.
- front 후속 전달: 화면 카테고리는 `에센스·세럼 / 앰플 / 크림·로션 / 토너·패드 /
  클렌저 / 마스크·패치 / 선케어`로 변경한다. `기타`의 화면 노출 방식은 프론트 기획 시
  결정하며, 상품 조회 API 형태가 정해지면 별도 backend→front 계약에 반영한다.
- 합의 후 검증: 기존 CSV 호환성, 애매한 상품명, 구체적 표현 우선순위, 모든 유형의 그룹 매핑,
  두 필드의 신규·갱신 저장, 재실행 무변경, 분류 전용 갱신 시 다른 상품 정보 보존.
