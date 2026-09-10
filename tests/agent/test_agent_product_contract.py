"""데이터 제공자의 새 분류와 불완전한 상품이 실제 그래프 경계를 통과하는지 검사한다."""

from typing import ClassVar

import pytest
from pydantic import ValidationError

from agent.adapters import FakeLlmClient
from agent.factory import DevelopmentAgentApplication, DevelopmentAgentFactory
from agent.ports import ProductRepository
from agent.rag.schemas import (
    LookupStatus,
    ProductCandidateSet,
    ProductCategory,
    ProductGetRequest,
    ProductGetResult,
    ProductRecord,
    ProductSearchRequest,
    ProductSearchResult,
    ProductSkinFeel,
    ProductTaxonomy,
    ProductTexture,
)
from agent.schemas import ChatStatus, ParsedRequest, RegisterRoomRequest, UnderstandingRequest
from tests.agent.test_agent_chat import AgentTestFactory


class ProviderCatalog:
    MASK: ClassVar[ProductCategory] = ProductCategory(code="shop:sheet-mask", name="시트 마스크")
    SHEET: ClassVar[ProductTexture] = ProductTexture(code="shop:sheet", name="시트형")
    LIGHT: ClassVar[ProductSkinFeel] = ProductSkinFeel(code="shop:light", name="산뜻")
    RICH: ClassVar[ProductSkinFeel] = ProductSkinFeel(code="shop:rich", name="리치")

    def taxonomy(self) -> ProductTaxonomy:
        return ProductTaxonomy(
            version="catalog-v1",
            categories=[self.MASK],
            textures=[self.SHEET],
            skin_feels=[self.LIGHT, self.RICH],
        )

    def product(self, skin_feel: ProductSkinFeel | None = None) -> ProductRecord:
        return ProductRecord(
            product_id="shop:product-1",
            name="조회된 시트 마스크",
            category=self.MASK,
            texture=self.SHEET,
            skin_feel=skin_feel,
            source_id="catalog:source",
            checked_at="2026-09-10",
            is_demo=False,
        )

    def register(self, app: DevelopmentAgentApplication) -> None:
        app.history.register_room(
            RegisterRoomRequest(actor_id="user-a", chat_room_id="room-a", thread_id="thread-a")
        )


class ProviderProducts(ProductRepository):
    """조건을 누락하는 외부 어댑터도 agent가 그대로 추천하지 않는지 확인한다."""

    def __init__(
        self, products: list[ProductRecord], status: LookupStatus = LookupStatus.SUCCESS
    ) -> None:
        self.products = products
        self.status = status
        self.requests: list[ProductSearchRequest] = []

    async def search(self, request: ProductSearchRequest) -> ProductSearchResult:
        self.requests.append(request.model_copy(deep=True))
        return ProductSearchResult(status=self.status, products=self.products)

    async def get(self, request: ProductGetRequest) -> ProductGetResult:
        for product in self.products:
            if product.product_id == request.product_id and (
                request.version is None or request.version == product.version
            ):
                return ProductGetResult(status=LookupStatus.SUCCESS, product=product)
        return ProductGetResult(status=LookupStatus.NO_RESULTS)


class UnknownCodeLlm(FakeLlmClient):
    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        parsed = await super().understand(request)
        parsed.category = ProductCategory(code="hallucinated", name="시트 마스크")
        return parsed


class UnsupportedConditionLlm(FakeLlmClient):
    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        parsed = await super().understand(request)
        parsed.unsupported_product_conditions = ["현재 카탈로그에 확인된 사용감 데이터가 없음"]
        return parsed


class RenamedCodeLlm(FakeLlmClient):
    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        parsed = await super().understand(request)
        parsed.category = ProviderCatalog.MASK.model_copy(update={"name": "모델이 바꾼 이름"})
        return parsed


class TestDynamicProductContract:
    async def test_new_category_without_agent_enum_and_unknown_product_fields(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            product_repository=repo, product_taxonomy=catalog.taxonomy()
        ).create()
        catalog.register(app)
        result = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "시트 마스크 추천해줘")
        )
        candidates = next(
            item for item in result.artifacts if isinstance(item, ProductCandidateSet)
        )
        assert repo.requests[0].filters.category == catalog.MASK
        assert not candidates.is_demo
        assert "개발용" not in result.message
        assert candidates.candidates[0].product.version is None
        assert candidates.candidates[0].product.directions is None
        assert "제품 사용법 미상" in candidates.candidates[0].unresolved
        assert ProductCandidateSet.model_validate_json(candidates.model_dump_json()) == candidates

    async def test_skin_feel_change_keeps_category_and_texture_across_rebuild(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product(catalog.LIGHT), catalog.product(catalog.RICH)])
        app = DevelopmentAgentFactory(
            product_repository=repo, product_taxonomy=catalog.taxonomy()
        ).create()
        catalog.register(app)
        requests = AgentTestFactory()
        await app.service.handle_turn(
            requests.request("room-a", "1", "산뜻한 시트형 시트 마스크 추천해줘")
        )
        rebuilt = DevelopmentAgentFactory(
            history=app.history,
            product_repository=repo,
            product_taxonomy=catalog.taxonomy(),
        ).create()
        result = await rebuilt.service.handle_turn(
            requests.request("room-a", "2", "리치한 것으로 바꿔줘")
        )
        filters = repo.requests[-1].filters
        assert filters.category == catalog.MASK
        assert filters.texture == catalog.SHEET
        assert filters.skin_feel == catalog.RICH
        candidates = next(
            item for item in result.artifacts if isinstance(item, ProductCandidateSet)
        )
        assert len(candidates.candidates) == 1
        assert candidates.candidates[0].product.skin_feel == catalog.RICH

    async def test_missing_attribute_does_not_match_requested_condition(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            product_repository=repo, product_taxonomy=catalog.taxonomy()
        ).create()
        catalog.register(app)
        result = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "산뜻한 시트 마스크 추천해줘")
        )
        assert result.status is ChatStatus.PARTIAL
        assert not any(isinstance(item, ProductCandidateSet) for item in result.artifacts)

    async def test_invented_code_is_blocked_before_repository_search(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            llm=UnknownCodeLlm(),
            product_repository=repo,
            product_taxonomy=catalog.taxonomy(),
        ).create()
        catalog.register(app)
        result = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "시트 마스크 추천해줘")
        )
        assert result.status is ChatStatus.PARTIAL
        assert not repo.requests
        assert any("hallucinated" in item.detail for item in result.unresolved)

    async def test_unavailable_attribute_is_not_silently_removed(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            llm=UnsupportedConditionLlm(),
            product_repository=repo,
            product_taxonomy=ProductTaxonomy(version="no-attributes", categories=[catalog.MASK]),
        ).create()
        catalog.register(app)
        result = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "산뜻한 시트 마스크 추천해줘")
        )
        assert result.status is ChatStatus.PARTIAL
        assert not repo.requests
        assert any("사용감" in item.detail for item in result.unresolved)

    async def test_valid_code_uses_provider_name(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            llm=RenamedCodeLlm(),
            product_repository=repo,
            product_taxonomy=catalog.taxonomy(),
        ).create()
        catalog.register(app)
        await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "시트 마스크 추천해줘")
        )
        assert repo.requests[0].filters.category == catalog.MASK

    @pytest.mark.parametrize("message", ["다른 것으로 바꿔줘", "1번 대신 제품 추천해줘"])
    async def test_removed_code_in_restored_session_is_not_used(self, message: str) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()])
        app = DevelopmentAgentFactory(
            product_repository=repo, product_taxonomy=catalog.taxonomy()
        ).create()
        catalog.register(app)
        requests = AgentTestFactory()
        await app.service.handle_turn(requests.request("room-a", "1", "시트 마스크 추천해줘"))
        repo.requests.clear()
        rebuilt = DevelopmentAgentFactory(
            history=app.history,
            product_repository=repo,
            product_taxonomy=ProductTaxonomy(version="v2"),
        ).create()
        result = await rebuilt.service.handle_turn(requests.request("room-a", "2", message))
        assert result.status is ChatStatus.PARTIAL
        assert not repo.requests
        assert any(catalog.MASK.code in item.detail for item in result.unresolved)

    async def test_unsupported_backend_cannot_return_successful_candidates(self) -> None:
        catalog = ProviderCatalog()
        repo = ProviderProducts([catalog.product()], LookupStatus.UNSUPPORTED)
        app = DevelopmentAgentFactory(
            product_repository=repo, product_taxonomy=catalog.taxonomy()
        ).create()
        catalog.register(app)
        result = await app.service.handle_turn(
            AgentTestFactory().request("room-a", "1", "시트 마스크 추천해줘")
        )
        assert result.status is ChatStatus.PARTIAL
        assert not result.artifacts

    def test_duplicate_codes_and_unpaired_adapter_injection_fail_explicitly(self) -> None:
        catalog = ProviderCatalog()
        with pytest.raises(ValidationError, match="중복"):
            ProductTaxonomy(version="v1", categories=[catalog.MASK, catalog.MASK])
        with pytest.raises(ValueError, match="지원 분류 목록"):
            DevelopmentAgentFactory(product_repository=ProviderProducts([]))
