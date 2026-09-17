"""Claim별 Evidence 상태와 추천 성분 등급 변환 규칙을 검증한다."""

from agent.claim_verification import (
    CLAIM_ONLY_LIMITATION,
    ClaimEvidenceVerifier,
    IngredientRecommendationSelector,
)
from agent.rag.claim_schemas import (
    ClaimResolvedTarget,
    ClaimVerificationBundle,
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationStatus,
    RecommendationBasis,
)
from agent.rag.pipeline import EvidencePipeline
from agent.rag.schemas import (
    EvidenceBackedStatement,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientVerificationResult,
    LookupStatus,
    PerTargetResult,
    RagQueryResult,
)


class ScriptedEvidencePipeline(EvidencePipeline):
    def __init__(self, bundle: EvidenceBundle) -> None:
        self._bundle = bundle
        self.requests: list[EvidenceSearchRequest] = []

    async def run(self, request: EvidenceSearchRequest) -> EvidenceBundle:
        self.requests.append(request.model_copy(deep=True))
        return self._bundle.model_copy(deep=True)


class ClaimVerificationFixture:
    INGREDIENT_ID = "ingredient:niacinamide"
    SECOND_INGREDIENT_ID = "ingredient:retinol"
    STATEMENT_ID = "claim:1"

    def target(self) -> ClaimResolvedTarget:
        return ClaimResolvedTarget(
            statement_id=self.STATEMENT_ID,
            ingredient_ids=[self.INGREDIENT_ID],
            query="나이아신아마이드: 피지 고민 사례에서 언급됨",
        )

    def request(self) -> ClaimVerificationRequest:
        return ClaimVerificationRequest(target=self.target())

    def combination_target(self) -> ClaimResolvedTarget:
        return ClaimResolvedTarget(
            statement_id="claim:combination",
            ingredient_ids=[self.INGREDIENT_ID, self.SECOND_INGREDIENT_ID],
            query="나이아신아마이드와 레티놀을 함께 사용하는 조합",
        )

    def combination_request(self) -> ClaimVerificationRequest:
        return ClaimVerificationRequest(target=self.combination_target())

    def record(
        self,
        evidence_id: str = "evidence:1",
        target_ids: list[str] | None = None,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=evidence_id,
            source_id="pubmed:1",
            source_title="검증 테스트 논문",
            document_version="v1",
            text="나이아신아마이드 관련 검증 문장입니다.",
            locator="abstract",
            target_ids=target_ids or [self.INGREDIENT_ID],
            review_status=EvidenceReviewStatus.VERIFIED,
            is_demo=False,
        )

    def supported_bundle(self, source: EvidenceRecord | None = None) -> EvidenceBundle:
        searched = self.record()
        cited = source or searched
        return EvidenceBundle(
            search=EvidenceSearchResult(
                status=LookupStatus.SUCCESS,
                records=[searched],
            ),
            generated=RagQueryResult(
                per_target=[
                    PerTargetResult(
                        target_id=self.INGREDIENT_ID,
                        result=IngredientVerificationResult(
                            claims=[
                                EvidenceBackedStatement(
                                    sentence="검증 가능한 효능 근거가 확인됐습니다.",
                                    sources=[cited],
                                )
                            ]
                        ),
                    )
                ]
            ),
        )

    def individual_evidence_for_combination_bundle(self) -> EvidenceBundle:
        first = self.record("evidence:niacinamide", [self.INGREDIENT_ID])
        second = self.record("evidence:retinol", [self.SECOND_INGREDIENT_ID])
        return EvidenceBundle(
            search=EvidenceSearchResult(
                status=LookupStatus.SUCCESS,
                records=[first, second],
            ),
            generated=RagQueryResult(
                per_target=[
                    PerTargetResult(
                        target_id=self.INGREDIENT_ID,
                        result=IngredientVerificationResult(
                            claims=[
                                EvidenceBackedStatement(
                                    sentence="나이아신아마이드 단독 근거입니다.",
                                    sources=[first],
                                )
                            ]
                        ),
                    ),
                    PerTargetResult(
                        target_id=self.SECOND_INGREDIENT_ID,
                        result=IngredientVerificationResult(
                            claims=[
                                EvidenceBackedStatement(
                                    sentence="레티놀 단독 근거입니다.",
                                    sources=[second],
                                )
                            ]
                        ),
                    ),
                ]
            ),
        )

    def combination_evidence_bundle(
        self,
        searched: EvidenceRecord,
        cited: EvidenceRecord | None = None,
    ) -> EvidenceBundle:
        return EvidenceBundle(
            search=EvidenceSearchResult(
                status=LookupStatus.SUCCESS,
                records=[searched],
            ),
            generated=RagQueryResult(
                combination=IngredientVerificationResult(
                    claims=[
                        EvidenceBackedStatement(
                            sentence="두 성분 조합을 직접 다룬 근거입니다.",
                            sources=[cited or searched],
                        )
                    ]
                )
            ),
        )


class TestClaimEvidenceVerifier:
    async def test_verified_generated_statement_becomes_supported(self) -> None:
        fixture = ClaimVerificationFixture()
        pipeline = ScriptedEvidencePipeline(fixture.supported_bundle())

        result = await ClaimEvidenceVerifier(pipeline).verify(fixture.request())

        assert result.status is ClaimVerificationStatus.SUPPORTED
        assert result.evidence_ids == ["evidence:1"]
        assert result.summary == "검증 가능한 효능 근거가 확인됐습니다."
        assert pipeline.requests[0].query == fixture.target().query
        assert pipeline.requests[0].target_ids == [fixture.INGREDIENT_ID]

    async def test_no_results_remains_claim_only_eligible(self) -> None:
        fixture = ClaimVerificationFixture()
        pipeline = ScriptedEvidencePipeline(
            EvidenceBundle(search=EvidenceSearchResult(status=LookupStatus.NO_RESULTS))
        )

        result = await ClaimEvidenceVerifier(pipeline).verify(fixture.request())

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_ids
        assert result.reasons

    async def test_unknown_generated_source_is_not_promoted(self) -> None:
        fixture = ClaimVerificationFixture()
        unknown = fixture.record("evidence:unknown")
        pipeline = ScriptedEvidencePipeline(fixture.supported_bundle(source=unknown))

        result = await ClaimEvidenceVerifier(pipeline).verify(fixture.request())

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_records

    async def test_source_for_different_ingredient_is_not_promoted(self) -> None:
        fixture = ClaimVerificationFixture()
        wrong_target = fixture.record()
        wrong_target.target_ids = ["ingredient:other"]
        bundle = fixture.supported_bundle(source=wrong_target)
        bundle.search.records = [wrong_target]
        pipeline = ScriptedEvidencePipeline(bundle)

        result = await ClaimEvidenceVerifier(pipeline).verify(fixture.request())

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_records

    async def test_combination_evidence_covering_all_targets_becomes_supported(self) -> None:
        fixture = ClaimVerificationFixture()
        record = fixture.record(
            "evidence:combination",
            [fixture.INGREDIENT_ID, fixture.SECOND_INGREDIENT_ID],
        )
        pipeline = ScriptedEvidencePipeline(
            fixture.combination_evidence_bundle(searched=record)
        )

        result = await ClaimEvidenceVerifier(pipeline).verify(
            fixture.combination_request()
        )

        assert result.status is ClaimVerificationStatus.SUPPORTED
        assert result.evidence_ids == ["evidence:combination"]
        assert pipeline.requests[0].combination_target_ids == [
            fixture.INGREDIENT_ID,
            fixture.SECOND_INGREDIENT_ID,
        ]

    async def test_individual_evidence_does_not_support_combination_claim(self) -> None:
        fixture = ClaimVerificationFixture()
        pipeline = ScriptedEvidencePipeline(
            fixture.individual_evidence_for_combination_bundle()
        )

        result = await ClaimEvidenceVerifier(pipeline).verify(
            fixture.combination_request()
        )

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_records

    async def test_unknown_combination_source_is_not_promoted(self) -> None:
        fixture = ClaimVerificationFixture()
        searched = fixture.record(
            "evidence:combination",
            [fixture.INGREDIENT_ID, fixture.SECOND_INGREDIENT_ID],
        )
        unknown = fixture.record(
            "evidence:unknown",
            [fixture.INGREDIENT_ID, fixture.SECOND_INGREDIENT_ID],
        )
        pipeline = ScriptedEvidencePipeline(
            fixture.combination_evidence_bundle(searched=searched, cited=unknown)
        )

        result = await ClaimEvidenceVerifier(pipeline).verify(
            fixture.combination_request()
        )

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_records

    async def test_partial_target_combination_source_is_not_promoted(self) -> None:
        fixture = ClaimVerificationFixture()
        partial = fixture.record("evidence:partial", [fixture.INGREDIENT_ID])
        pipeline = ScriptedEvidencePipeline(
            fixture.combination_evidence_bundle(searched=partial)
        )

        result = await ClaimEvidenceVerifier(pipeline).verify(
            fixture.combination_request()
        )

        assert result.status is ClaimVerificationStatus.INSUFFICIENT
        assert not result.evidence_records


class TestIngredientRecommendationSelector:
    def test_supported_first_and_insufficient_is_kept_as_claim_only(self) -> None:
        bundle = ClaimVerificationBundle(
            results=[
                ClaimVerificationResult(
                    statement_id="claim:only",
                    ingredient_ids=["ingredient:claim-only"],
                    status=ClaimVerificationStatus.INSUFFICIENT,
                    reasons=["no_evidence_found"],
                ),
                ClaimVerificationResult(
                    statement_id="claim:supported",
                    ingredient_ids=["ingredient:supported"],
                    status=ClaimVerificationStatus.SUPPORTED,
                    evidence_ids=["evidence:1"],
                    evidence_records=[ClaimVerificationFixture().record()],
                    summary="검증됨",
                ),
            ]
        )

        result = IngredientRecommendationSelector().select(bundle)

        assert [candidate.ingredient_id for candidate in result.candidates] == [
            "ingredient:supported",
            "ingredient:claim-only",
        ]
        assert result.candidates[0].basis is RecommendationBasis.EVIDENCE_SUPPORTED
        assert result.candidates[1].basis is RecommendationBasis.CLAIM_ONLY
        assert result.candidates[1].limitation == CLAIM_ONLY_LIMITATION

    def test_error_or_contradiction_blocks_same_ingredient(self) -> None:
        bundle = ClaimVerificationBundle(
            results=[
                ClaimVerificationResult(
                    statement_id="claim:insufficient",
                    ingredient_ids=["ingredient:held"],
                    status=ClaimVerificationStatus.INSUFFICIENT,
                ),
                ClaimVerificationResult(
                    statement_id="claim:error",
                    ingredient_ids=["ingredient:held"],
                    status=ClaimVerificationStatus.ERROR,
                    reasons=["검색 장애"],
                ),
                ClaimVerificationResult(
                    statement_id="claim:contradicted",
                    ingredient_ids=["ingredient:excluded"],
                    status=ClaimVerificationStatus.CONTRADICTED,
                    reasons=["명시적 상반 근거"],
                ),
            ]
        )

        result = IngredientRecommendationSelector().select(bundle)

        assert result.candidates == []
