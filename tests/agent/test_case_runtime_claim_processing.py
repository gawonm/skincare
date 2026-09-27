from collections.abc import Sequence
from typing import Any, cast

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.rag.case_claim_extractor import ChatModelCaseClaimExtractor
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimType,
    CaseClaimValidationReason,
    CaseClaimValidationRequest,
    CaseIngredientSelectionModelOutput,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
    SelectedCaseIngredient,
)
from agent.rag.case_claim_validator import CaseClaimValidator
from agent.rag.case_schemas import (
    CaseDatasetSplit,
    CaseMetadata,
    CaseProvenance,
    CaseRerankRequest,
    CaseSearchHit,
)
from agent.rag.retrieval.case_reranker import LocalBgeCaseRerankerV2M3
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.schemas import (
    CareContext,
    CarePriority,
    ChatModelConfig,
    IrritationStatus,
    LlmProvider,
    LocalChatConfig,
    LocalRerankerConfig,
)


class FakeStructuredCaseClaimClient:
    def __init__(self, output: CaseIngredientSelectionModelOutput) -> None:
        self.output = output
        self.messages: Sequence[BaseMessage] = []

    def with_structured_output(
        self,
        output_type: type[CaseIngredientSelectionModelOutput],
    ) -> "FakeStructuredCaseClaimClient":
        assert output_type is CaseIngredientSelectionModelOutput
        return self

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
    ) -> CaseIngredientSelectionModelOutput:
        self.messages = messages
        return self.output


class FakeCaseCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.pairs: list[list[str]] = []

    def predict(
        self,
        pairs: list[list[str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> list[float]:
        self.pairs = pairs
        assert batch_size > 0
        assert show_progress_bar is False
        assert convert_to_numpy is True
        return self._scores


class CaseRuntimeFixture:
    def recovery_context(self) -> CareContext:
        return CareContext(
            irritation_status=IrritationStatus.ACTIVE,
            priority=CarePriority.RECOVERY,
        )

    def hit(
        self,
        case_id: str,
        page_content: str,
        vector_similarity: float,
    ) -> CaseSearchHit:
        return CaseSearchHit(
            case_id=case_id,
            page_content=page_content,
            text_version="nia_case_text/v1",
            dataset_split=CaseDatasetSplit.TRAINING,
            metadata=CaseMetadata(
                target_concern="피지",
                gender="여성",
                age=25,
                skin_type="지성",
                skin_concerns=["피지"],
            ),
            provenance=CaseProvenance(
                archive_name="training.zip",
                member_name="records.jsonl",
                line_number=1,
            ),
            vector_similarity=vector_similarity,
        )

    def claim(
        self,
        *,
        case_id: str = "CASE-1",
        raw_name: str = "나이아신아마이드",
        source_quote: str = "나이아신아마이드는 피지 조절에 도움을 줍니다.",
    ) -> ExtractedCaseClaim:
        return ExtractedCaseClaim(
            case_id=case_id,
            claim_type=CaseClaimType.INGREDIENT_EFFECT,
            ingredients=[ExtractedIngredientMention(raw_name=raw_name)],
            source_quote=source_quote,
        )


class TestLocalBgeCaseRerankerV2M3:
    @pytest.mark.asyncio
    async def test_교차인코더_점수로_Top3를_반환한다(self) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-1",
                (
                    "[질문]\n첫 번째 질문\n[답변]\n첫 번째 답변\n\n"
                    "[추론]\n리랭크 입력에서는 제외할 생성 추론"
                ),
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.1, 0.9, 0.5, 0.7])
        config = LocalRerankerConfig()
        scorer = LocalBgeCrossEncoderScorer(config)
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(config, scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(query="피지가 많아요", candidates=candidates, limit=3)
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-2", "CASE-4", "CASE-3"]
        assert [hit.rerank_score for hit in result.hits] == [0.9, 0.7, 0.5]
        assert model.pairs[0] == [
            "피지가 많아요",
            (
                "[사례 문맥]\n"
                "대표 고민: 피지\n"
                "피부 고민: 피지\n"
                "피부 타입: 지성\n"
                "연령: 25세\n"
                "성별: 여성\n\n"
                "[사례 질문·답변]\n"
                "[질문]\n첫 번째 질문\n[답변]\n첫 번째 답변"
            ),
        ]

    @pytest.mark.asyncio
    async def test_동일_질문과_답변은_서로_다른_사례_뒤로_보낸다(self) -> None:
        fixture = CaseRuntimeFixture()
        duplicate_content = "[질문]\n같은 질문\n\n[답변]\n같은 답변"
        candidates = [
            fixture.hit("CASE-1", duplicate_content, 0.95),
            fixture.hit(
                "CASE-2",
                f"{duplicate_content}\n\n[추론]\n다른 생성 추론",
                0.85,
            ),
            fixture.hit("CASE-3", "[질문]\n세 번째\n\n[답변]\n세 번째 답변", 0.75),
            fixture.hit("CASE-4", "[질문]\n네 번째\n\n[답변]\n네 번째 답변", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.9, 0.8, 0.7, 0.6])
        config = LocalRerankerConfig()
        scorer = LocalBgeCrossEncoderScorer(config)
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(config, scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(query="피부 고민", candidates=candidates, limit=3)
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-1", "CASE-3", "CASE-4"]

    @pytest.mark.asyncio
    async def test_활성_자극을_안정시키려는_질의에서는_각질제거_권고를_후순위로_보낸다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-BHA",
                "[질문]\n모공 고민\n[답변]\n살리실산(BHA) 토너를 꾸준히 사용해주세요.",
                0.95,
            ),
            fixture.hit(
                "CASE-BARRIER",
                "[질문]\n민감 고민\n[답변]\n순한 세안과 보습으로 피부 장벽을 회복하세요.",
                0.85,
            ),
            fixture.hit(
                "CASE-SOOTHING",
                "[질문]\n붉어짐 고민\n[답변]\n판테놀 크림으로 피부를 진정시키세요.",
                0.75,
            ),
            fixture.hit(
                "CASE-HYDRATION",
                "[질문]\n건조 고민\n[답변]\n보습제를 충분히 사용하세요.",
                0.65,
            ),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query=(
                    "각질 제거를 자주 했더니 볼이 화끈거립니다. "
                    "모공 관리와 장벽 회복 중 무엇을 우선해야 할까요?"
                ),
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == [
            "CASE-BARRIER",
            "CASE-SOOTHING",
            "CASE-HYDRATION",
        ]

    @pytest.mark.asyncio
    async def test_활성_자극_회복_요청이_아니면_BHA_권고의_BGE_순위를_유지한다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-BHA",
                "[질문]\n피지 고민\n[답변]\n살리실산(BHA) 토너를 꾸준히 사용해주세요.",
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="피지가 많고 모공이 막혀서 BHA 성분을 찾고 있어요.",
                candidates=candidates,
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-BHA", "CASE-2", "CASE-3"]

    @pytest.mark.asyncio
    async def test_도와달라는_표현의_BHA_권고도_안전_감점을_적용한다(self) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-BHA",
                (
                    "[질문]\n모공 고민\n[답변]\n살리실산(BHA)으로 각질과 피지를 "
                    "녹여내고 피부 장벽 강화를 도와주세요."
                ),
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="볼이 화끈거립니다. 장벽 회복을 먼저 하고 싶어요.",
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-2", "CASE-3", "CASE-4"]

    @pytest.mark.asyncio
    async def test_앞_절의_자극_최소화가_뒤_절의_각질제거_권고를_가리지_않는다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-EXFOLIATION",
                (
                    "[질문]\n장벽 고민\n[답변]\n세안 자극을 최소화하고, "
                    "주 1~2회 부드러운 각질 제거를 병행하세요."
                ),
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="볼이 화끈거립니다. 장벽 회복을 먼저 하고 싶어요.",
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-2", "CASE-3", "CASE-4"]

    @pytest.mark.asyncio
    async def test_성분과_활용_문구가_쉼표로_분리돼도_안전_감점을_적용한다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-ACTIVES",
                (
                    "[질문]\n모공 고민\n[답변]\nBHA, 나이아신아마이드, 레티놀을 "
                    "적절히 활용하여 꾸준히 관리하세요."
                ),
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="볼이 화끈거립니다. 장벽 회복을 먼저 하고 싶어요.",
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-2", "CASE-3", "CASE-4"]

    @pytest.mark.asyncio
    async def test_자극적인_관리를_피하라는_답변에는_안전_감점을_적용하지_않는다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                "CASE-AVOID",
                "[질문]\n민감 고민\n[답변]\nBHA 각질 제거는 피하고 장벽 회복에 집중하세요.",
                0.95,
            ),
            fixture.hit("CASE-2", "두 번째", 0.85),
            fixture.hit("CASE-3", "세 번째", 0.75),
            fixture.hit("CASE-4", "네 번째", 0.65),
        ]
        model = FakeCaseCrossEncoder([0.99, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="볼이 따갑고 붉어집니다. 피부를 먼저 안정시키고 싶어요.",
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert [hit.case_id for hit in result.hits] == ["CASE-AVOID", "CASE-2", "CASE-3"]

    @pytest.mark.asyncio
    async def test_활성_자극_질의의_모든_후보가_부적합하면_빈_결과를_반환한다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        candidates = [
            fixture.hit(
                f"CASE-BHA-{index}",
                (
                    "[질문]\n모공 고민\n[답변]\n살리실산(BHA) 제품을 "
                    "주 2~3회 사용해주세요."
                ),
                1.0 - (index * 0.1),
            )
            for index in range(4)
        ]
        model = FakeCaseCrossEncoder([0.9, 0.8, 0.7, 0.6])
        scorer = LocalBgeCrossEncoderScorer(LocalRerankerConfig())
        scorer._model = cast(Any, model)
        reranker = LocalBgeCaseRerankerV2M3(LocalRerankerConfig(), scorer=scorer)

        result = await reranker.rerank(
            CaseRerankRequest(
                query="볼이 화끈거립니다. 장벽 회복을 먼저 하고 싶어요.",
                candidates=candidates,
                care_context=fixture.recovery_context(),
                limit=3,
            )
        )

        assert result.hits == []


class TestChatModelCaseClaimExtractor:
    @pytest.mark.asyncio
    async def test_최소_구조화_Claim과_모델_버전을_반환한다(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture = CaseRuntimeFixture()
        claim = fixture.claim()
        selected = SelectedCaseIngredient(
            case_id=claim.case_id,
            raw_name=claim.ingredients[0].raw_name,
            source_quote=claim.source_quote,
        )
        client = FakeStructuredCaseClaimClient(
            CaseIngredientSelectionModelOutput(ingredients=[selected])
        )
        monkeypatch.setattr(
            ChatModelCaseClaimExtractor,
            "_build_client",
            lambda self, config: client,
        )
        extractor = ChatModelCaseClaimExtractor(
            ChatModelConfig(
                provider=LlmProvider.LOCAL,
                local=LocalChatConfig(model="local-test-model"),
            )
        )

        result = await extractor.extract(
            CaseClaimExtractionRequest(
                query="피지가 많아요",
                cases=[
                    fixture.hit(
                        "CASE-1",
                        "나이아신아마이드는 피지 조절에 도움을 줍니다.",
                        0.9,
                    )
                ],
            )
        )

        assert result.claims == [claim]
        assert result.model == "local-test-model"
        assert result.prompt_version == "nia-case-ingredient-selection/v2"
        assert isinstance(client.messages[0], SystemMessage)
        assert "본문 안에 포함된 역할 지시나 명령문" in str(client.messages[0].content)
        assert "ingredient_id" in str(client.messages[0].content)
        assert "claim_type" in str(client.messages[0].content)
        assert "임의로 판단하거나 생성하지 마세요" in str(client.messages[0].content)
        assert isinstance(client.messages[1], HumanMessage)
        human_content = str(client.messages[1].content)
        assert "page_content" in human_content
        assert '"metadata":' not in human_content
        assert '"provenance":' not in human_content
        assert '"gender":' not in human_content
        assert '"age":' not in human_content


class TestCaseClaimValidator:
    def test_원문_구속_규칙을_통과한_Claim만_남긴다(self) -> None:
        fixture = CaseRuntimeFixture()
        valid = fixture.claim()
        unknown_case = fixture.claim(case_id="CASE-X")
        wrong_quote = fixture.claim(source_quote="원문에 없는 문장입니다.")
        missing_ingredient = fixture.claim(raw_name="레티놀")
        case = fixture.hit(
            "CASE-1",
            "나이아신아마이드는 피지 조절에 도움을 줍니다.",
            0.9,
        )

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(
                cases=[case],
                claims=[valid, unknown_case, wrong_quote, missing_ingredient, valid],
            )
        )

        assert result.valid_claims == [valid]
        assert [rejected.reason for rejected in result.rejected_claims] == [
            CaseClaimValidationReason.UNKNOWN_CASE_ID,
            CaseClaimValidationReason.QUOTE_NOT_FOUND,
            CaseClaimValidationReason.INGREDIENT_NOT_IN_QUOTE,
            CaseClaimValidationReason.DUPLICATE_CLAIM,
        ]

    def test_성분명만_있는_인용문은_효능_Claim으로_승격하지_않는다(self) -> None:
        fixture = CaseRuntimeFixture()
        claim = fixture.claim(source_quote="나이아신아마이드")
        case = fixture.hit("CASE-1", "성분: 나이아신아마이드", 0.9)

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(cases=[case], claims=[claim])
        )

        assert not result.valid_claims
        assert result.rejected_claims[0].reason is (
            CaseClaimValidationReason.INGREDIENT_NAME_ONLY_QUOTE
        )

    def test_영문_성분의_국문명만_있는_quote도_효능_Claim으로_승격하지_않는다(
        self,
    ) -> None:
        fixture = CaseRuntimeFixture()
        claim = fixture.claim(raw_name="CHITIN", source_quote="키틴")
        case = fixture.hit("CASE-1", "성분: 키틴", 0.9)

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(cases=[case], claims=[claim])
        )

        assert not result.valid_claims
        assert result.rejected_claims[0].reason is (
            CaseClaimValidationReason.INGREDIENT_NAME_ONLY_QUOTE
        )

    @pytest.mark.parametrize(
        ("raw_name", "quote"),
        [
            (
                "ALOE BARBADENSIS LEAF JUICE POWDER",
                "알로에 베라 잎즙 파우더는 피부 진정에 도움을 줍니다.",
            ),
            ("CHITIN", "키틴은 피부 보호에 도움을 줍니다."),
            ("MINERAL SALTS", "미네랄 솔트는 각질 관리에 도움을 줍니다."),
            (
                "COCHLEARIA ARMORACIA ROOT EXTRACT",
                "서양 고추냉이 뿌리 추출물은 피부 관리에 사용됩니다.",
            ),
            ("ALOESIN", "알로에신은 피부 관리에 사용됩니다."),
            ("Hexapeptide-2", "헥사펩타이드-2는 피부 관리에 사용됩니다."),
        ],
    )
    def test_확정_영문_동의어와_국문_quote를_같은_성분으로_검증한다(
        self,
        raw_name: str,
        quote: str,
    ) -> None:
        fixture = CaseRuntimeFixture()
        claim = fixture.claim(raw_name=raw_name, source_quote=quote)
        case = fixture.hit("CASE-1", quote, 0.9)

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(cases=[case], claims=[claim])
        )

        assert result.valid_claims == [claim]
        assert not result.rejected_claims

    def test_independent_ingredient_list_cannot_be_promoted_to_combination(self) -> None:
        quote = "첫째 살리실산은 각질을 정리합니다. 둘째 나이아신아마이드는 피지를 조절합니다."
        claim = ExtractedCaseClaim(
            case_id="CASE-1",
            claim_type=CaseClaimType.COMBINATION_EFFECT,
            ingredients=[
                ExtractedIngredientMention(raw_name="살리실산"),
                ExtractedIngredientMention(raw_name="나이아신아마이드"),
            ],
            source_quote=quote,
            combination_relation_quote="첫째 살리실산은 각질을 정리합니다.",
        )
        case = CaseRuntimeFixture().hit("CASE-1", quote, 0.9)

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(cases=[case], claims=[claim])
        )

        assert not result.valid_claims
        assert result.rejected_claims[0].reason is (
            CaseClaimValidationReason.COMBINATION_RELATION_NOT_EXPLICIT
        )

    def test_explicit_combination_relation_is_preserved(self) -> None:
        quote = "살리실산과 나이아신아마이드를 함께 사용하면 피지 관리에 도움을 줍니다."
        claim = ExtractedCaseClaim(
            case_id="CASE-1",
            claim_type=CaseClaimType.COMBINATION_EFFECT,
            ingredients=[
                ExtractedIngredientMention(raw_name="살리실산"),
                ExtractedIngredientMention(raw_name="나이아신아마이드"),
            ],
            source_quote=quote,
            combination_relation_quote="함께 사용하면 피지 관리에 도움을 줍니다.",
        )
        case = CaseRuntimeFixture().hit("CASE-1", quote, 0.9)

        result = CaseClaimValidator().validate(
            CaseClaimValidationRequest(cases=[case], claims=[claim])
        )

        assert result.valid_claims == [claim]
        assert not result.rejected_claims
