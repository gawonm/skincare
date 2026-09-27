"""`ProductRepository.list_by_ids`를 실제 로컬 DB로 검증한다.

채팅 응답 카드 보강(`backend/services/chat_response_builder.py`)이 후보 상품 id 목록을
한 번에 조회할 때 쓰는 메서드다. 순서 보장은 계약에 없으므로 결과를 id로 다시 찾아 비교한다.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.repositories.product_repository import ProductRepository
from models.product import (
    Product,
    ProductMatchStatus,
    ProductPriceBand,
    ProductServiceCategory,
    ProductTitleSource,
    ProductTypeNormalized,
)


def _make_product(source_product_id: str, **overrides) -> Product:
    defaults = {
        "source": "oliveyoung_global",
        "source_product_id": source_product_id,
        "search_query": "category:1000000008",
        "target_group": None,
        "raw_title": "Test Raw Title 50ml",
        "display_title": "Test Raw Title 50ml",
        "title_source": ProductTitleSource.UNTRANSLATED,
        "brand": "TestBrand",
        "maker": None,
        "category1": "Skincare",
        "category2": "Moisturizers",
        "category3": None,
        "product_type_normalized": ProductTypeNormalized.SERUM,
        "service_category": ProductServiceCategory.ESSENCE_SERUM,
        "lowest_price": 10000,
        "highest_price": 15000,
        "price_band": ProductPriceBand.BAND_10K,
        "volume_value": 50.0,
        "volume_unit": "ml",
        "image_url": "https://example.com/image.jpg",
        "local_image_path": "data/processed/images/test.jpg",
        "shopping_url": "https://example.com/product",
        "mall_name": "OLIVE YOUNG Global",
        "product_type": "GENERAL_PRODUCT",
        "observed_at": datetime.now(UTC),
        "match_status": ProductMatchStatus.MANUAL_REVIEW_REQUIRED,
        "review_reasons": [],
    }
    defaults.update(overrides)
    return Product(**defaults)


async def _insert_and_flush(session, product: Product) -> Product:
    session.add(product)
    await session.flush()
    return product


@pytest.mark.asyncio
async def test_list_by_ids_returns_only_requested_products(session):
    target = await _insert_and_flush(
        session, _make_product(str(uuid4()), display_title="타깃 상품")
    )
    await _insert_and_flush(session, _make_product(str(uuid4()), display_title="다른 상품"))
    repo = ProductRepository(session)

    result = await repo.list_by_ids([target.id])

    assert [product.id for product in result] == [target.id]
    assert result[0].display_title == "타깃 상품"


@pytest.mark.asyncio
async def test_list_by_ids_returns_all_matching_products_regardless_of_order(session):
    first = await _insert_and_flush(session, _make_product(str(uuid4()), display_title="첫 상품"))
    second = await _insert_and_flush(
        session, _make_product(str(uuid4()), display_title="둘째 상품")
    )
    repo = ProductRepository(session)

    result = await repo.list_by_ids([second.id, first.id])

    assert {product.id for product in result} == {first.id, second.id}


@pytest.mark.asyncio
async def test_list_by_ids_with_empty_list_returns_empty_without_querying(session):
    repo = ProductRepository(session)

    result = await repo.list_by_ids([])

    assert result == []


@pytest.mark.asyncio
async def test_list_by_ids_skips_ids_that_do_not_exist(session):
    target = await _insert_and_flush(
        session, _make_product(str(uuid4()), display_title="존재하는 상품")
    )
    repo = ProductRepository(session)

    result = await repo.list_by_ids([target.id, uuid4()])

    assert [product.id for product in result] == [target.id]
