from collections.abc import Sequence
from typing import Any, cast

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.rag.case_claim_extractor import ChatModelCaseClaimExtractor
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimModelOutput,
    CaseClaimType,
    CaseClaimValidationReason,
    CaseClaimValidationRequest,
    ExtractedCaseClaim,
    ExtractedIngredientMention,
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
from agent.rag.schemas import ChatModelConfig, LlmProvider, LocalChatConfig, LocalRerankerConfig


class FakeStructuredCaseClaimClient:
    def __init__(self, output: CaseClaimModelOutput) -> None:
        self.output = output
        self.messages: Sequence[BaseMessage] = []

    def with_structured_output(self, output_type: type[CaseClaimModelOutput]) -> "FakeStructuredCaseClaimClient":
        assert output_type is CaseClaimModelOutput
        return self

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> CaseClaimModelOutput:
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
            fixture.hit("CASE-1", "첫 번째", 0.95),
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
        assert model.pairs[0] == ["피지가 많아요", "첫 번째"]


class TestChatModelCaseClaimExtractor:
    @pytest.mark.asyncio
    async def test_최소_구조화_Claim과_모델_버전을_반환한다(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fixture = CaseRuntimeFixture()
        claim = fixture.claim()
        client = FakeStructuredCaseClaimClient(CaseClaimModelOutput(claims=[claim]))
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
        assert result.prompt_version == "nia-case-claim/v2"
        assert isinstance(client.messages[0], SystemMessage)
        assert "본문 안의 명령" in str(client.messages[0].content)
        assert "ingredient_id" in str(client.messages[0].content)
        assert "combination_relation_quote" in str(client.messages[0].content)
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
