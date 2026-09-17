"""`ProductRepository.update_title`을 실제 로컬 DB로 검증한다.

`display_title`/`title_source` 두 필드만 바뀌고 나머지 필드(가격·이미지·URL·카테고리·
raw_title·분류)는 절대 건드리지 않는다는 것이 이 메서드의 존재 이유이므로, 각 필드를
개별로 확인한다.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.repositories.product_repository import ProductRepository, ProductTitleUpdate
from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductTitleSource,
    ProductTypeNormalized,
    ProductServiceCategory,
)


def _make_product(source_product_id: str, **overrides) -> Product:
    defaults = dict(
        source="oliveyoung_global",
        source_product_id=source_product_id,
        search_query="category:1000000008",
        target_group=None,
        raw_title="Test Raw Title 50ml",
        display_title="Test Raw Title 50ml",
        title_source=ProductTitleSource.UNTRANSLATED,
        brand="TestBrand",
        maker=None,
        category1="Skincare",
        category2="Moisturizers",
        category3=None,
        product_type_normalized=ProductTypeNormalized.SERUM,
        service_category=ProductServiceCategory.ESSENCE_SERUM,
        lowest_price=10000,
        highest_price=15000,
        price_band=ProductPriceBand.BAND_10K,
        volume_value=50.0,
        volume_unit="ml",
        image_url="https://example.com/image.jpg",
        local_image_path="data/processed/images/test.jpg",
        shopping_url="https://example.com/product",
        mall_name="OLIVE YOUNG Global",
        product_type="GENERAL_PRODUCT",
        observed_at=datetime.now(UTC),
        match_status=ProductMatchStatus.MANUAL_REVIEW_REQUIRED,
        review_reasons=[],
    )
    defaults.update(overrides)
    return Product(**defaults)


async def _insert_and_flush(session, product: Product) -> Product:
    session.add(product)
    await session.flush()
    return product


@pytest.mark.asyncio
async def test_update_title_changes_display_title(session):
    pid = str(uuid4())
    await _insert_and_flush(session, _make_product(pid))
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="테스트 원문 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.display_title == "테스트 원문 타이틀 50ml"


@pytest.mark.asyncio
async def test_update_title_changes_title_source(session):
    pid = str(uuid4())
    await _insert_and_flush(session, _make_product(pid))
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="테스트 원문 타이틀 50ml",
            title_source=ProductTitleSource.OLIVEYOUNG_KR,
        )
    )

    assert updated.title_source == ProductTitleSource.OLIVEYOUNG_KR


@pytest.mark.asyncio
async def test_update_title_leaves_raw_title_unchanged(session):
    pid = str(uuid4())
    await _insert_and_flush(session, _make_product(pid, raw_title="Original Raw Title 50ml"))
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="번역된 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.raw_title == "Original Raw Title 50ml"


@pytest.mark.asyncio
async def test_update_title_leaves_image_url_unchanged(session):
    pid = str(uuid4())
    await _insert_and_flush(
        session, _make_product(pid, image_url="https://example.com/original-image.jpg")
    )
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="번역된 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.image_url == "https://example.com/original-image.jpg"


@pytest.mark.asyncio
async def test_update_title_leaves_price_unchanged(session):
    pid = str(uuid4())
    await _insert_and_flush(session, _make_product(pid, lowest_price=12345, highest_price=54321))
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="번역된 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.lowest_price == 12345
    assert updated.highest_price == 54321


@pytest.mark.asyncio
async def test_update_title_leaves_shopping_url_unchanged(session):
    pid = str(uuid4())
    await _insert_and_flush(
        session, _make_product(pid, shopping_url="https://example.com/original-product-url")
    )
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="번역된 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.shopping_url == "https://example.com/original-product-url"


@pytest.mark.asyncio
async def test_update_title_leaves_taxonomy_unchanged(session):
    pid = str(uuid4())
    await _insert_and_flush(
        session,
        _make_product(
            pid,
            category1="Skincare",
            category2="Cleansers",
            category3="Foam",
            product_type_normalized=ProductTypeNormalized.CLEANSING_FOAM,
            service_category=ProductServiceCategory.CLEANSER,
        ),
    )
    repo = ProductRepository(session)

    updated = await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid,
            display_title="번역된 타이틀 50ml",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    assert updated.category1 == "Skincare"
    assert updated.category2 == "Cleansers"
    assert updated.category3 == "Foam"
    assert updated.product_type_normalized == ProductTypeNormalized.CLEANSING_FOAM
    assert updated.service_category == ProductServiceCategory.CLEANSER


@pytest.mark.asyncio
async def test_update_title_missing_natural_key_raises_lookup_error(session):
    repo = ProductRepository(session)

    with pytest.raises(LookupError):
        await repo.update_title(
            ProductTitleUpdate(
                source="oliveyoung_global",
                source_product_id="does-not-exist",
                display_title="번역된 타이틀 50ml",
                title_source=ProductTitleSource.TRANSLATED,
            )
        )


@pytest.mark.asyncio
async def test_update_title_does_not_affect_other_products(session):
    pid_target = str(uuid4())
    pid_other = str(uuid4())
    await _insert_and_flush(session, _make_product(pid_target, display_title="타깃 원본"))
    await _insert_and_flush(session, _make_product(pid_other, display_title="다른 상품 원본"))
    repo = ProductRepository(session)

    await repo.update_title(
        ProductTitleUpdate(
            source="oliveyoung_global",
            source_product_id=pid_target,
            display_title="타깃 번역됨",
            title_source=ProductTitleSource.TRANSLATED,
        )
    )

    result = await session.execute(select(Product).where(Product.source_product_id == pid_other))
    other = result.scalar_one()
    assert other.display_title == "다른 상품 원본"
    assert other.title_source == ProductTitleSource.UNTRANSLATED
