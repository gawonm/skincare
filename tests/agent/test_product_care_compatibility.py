from agent.rag.care_context import CareContextResolutionRequest, CareContextResolver
from agent.rag.retrieval.product_care_compatibility import ProductCareCompatibilityPolicy
from agent.rag.schemas import (
    CareContext,
    CarePriority,
    IrritationStatus,
    ProductRecord,
)


class TestProductCareCompatibilityPolicy:
    def test_회복_요청의_각질제거_상품은_제외한다(self) -> None:
        product = ProductRecord(
            product_id="exfoliating-cleanser",
            name="AHA BHA 클렌징 폼",
            source_id="fixture",
            checked_at="2026-09-27",
        )

        assessment = ProductCareCompatibilityPolicy().assess(
            CareContext(
                irritation_status=IrritationStatus.ACTIVE,
                priority=CarePriority.RECOVERY,
            ),
            product,
        )

        assert assessment.is_incompatible()

    def test_일반_피부_질문과_명시되지_않은_상품은_유지한다(self) -> None:
        product = ProductRecord(
            product_id="basic-cleanser",
            name="저자극 클렌저",
            source_id="fixture",
            checked_at="2026-09-27",
        )

        assessment = ProductCareCompatibilityPolicy().assess(
            CareContext(
                irritation_status=IrritationStatus.INACTIVE,
                priority=CarePriority.STANDARD,
            ),
            product,
        )

        assert not assessment.is_incompatible()

    def test_성분명_일부에_포함된_산_표기는_각질제거로_간주하지_않는다(self) -> None:
        product = ProductRecord(
            product_id="alpha-arbutin-serum",
            name="알파알부틴 세럼",
            source_id="fixture",
            checked_at="2026-09-27",
        )

        assessment = ProductCareCompatibilityPolicy().assess(
            CareContext(
                irritation_status=IrritationStatus.ACTIVE,
                priority=CarePriority.RECOVERY,
            ),
            product,
        )

        assert not assessment.is_incompatible()


class TestCareContextResolver:
    def test_미확정_구조화_결과만_표현_fallback으로_보완한다(self) -> None:
        context = CareContextResolver().resolve(
            CareContextResolutionRequest(
                query="볼이 붉고 화끈거립니다. 피부가 가라앉을 때까지 기다릴까요?",
                interpreted=CareContext(),
            )
        )

        assert context.requires_recovery_first()

    def test_명시적으로_부정한_자극은_활성으로_판정하지_않는다(self) -> None:
        context = CareContextResolver().resolve(
            CareContextResolutionRequest(
                query="지금은 화끈거리지 않아요. 일반 보습 루틴을 알려주세요.",
                interpreted=CareContext(),
            )
        )

        assert context.irritation_status is IrritationStatus.INACTIVE
        assert not context.requires_recovery_first()

    def test_여드름이_가라앉는다는_표현만으로_자극을_추정하지_않는다(self) -> None:
        context = CareContextResolver().resolve(
            CareContextResolutionRequest(
                query="여드름이 가라앉을 때까지 어떤 제품을 쓰면 좋을까요?",
                interpreted=CareContext(),
            )
        )

        assert context.irritation_status is IrritationStatus.UNKNOWN
        assert not context.requires_recovery_first()

    def test_LLM이_해석한_상태를_fallback보다_우선한다(self) -> None:
        context = CareContextResolver().resolve(
            CareContextResolutionRequest(
                query="화끈거림이 있다는 가정에서 설명해 주세요.",
                interpreted=CareContext(
                    irritation_status=IrritationStatus.INACTIVE,
                    priority=CarePriority.STANDARD,
                ),
            )
        )

        assert context.irritation_status is IrritationStatus.INACTIVE
        assert context.priority is CarePriority.STANDARD
