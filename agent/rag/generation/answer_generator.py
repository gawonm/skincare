"""현재 EvidenceRecord 계약을 유지하면서 새 RAG의 문장별 인용·보류 판정을 적용한다."""

from agent.rag.generation.condition_preservation_checker import ConditionPreservationChecker
from agent.rag.ports import ClaimGenerator
from agent.rag.retrieval.question_intent_classifier import QuestionIntentClassifier
from agent.rag.schemas import (
    AnsweredClaim,
    ClaimGenerationRequest,
    EvidenceRecord,
    EvidenceReviewStatus,
    EvidenceScope,
    EvidenceSearchRequest,
    EvidenceSearchResult,
    IngredientVerificationResult,
    PerTargetResult,
    QuestionIntent,
    RagConfidenceTier,
    RagQueryResult,
    RetrievedChunk,
    UnverifiableReason,
)


class AnswerGenerator:
    _VERIFIABLE_TIERS = frozenset(
        (
            RagConfidenceTier.OFFICIAL_REGULATORY,
            RagConfidenceTier.STRUCTURED_KNOWLEDGE,
        )
    )
    _INDIVIDUAL_QUERY = "이 대상의 개별 효능과 주의사항을 근거에 따라 설명하세요."

    def __init__(self, client: ClaimGenerator) -> None:
        self._client = client
        self._classifier = QuestionIntentClassifier()
        self._checker = ConditionPreservationChecker()

    async def generate(
        self, request: EvidenceSearchRequest, search: EvidenceSearchResult
    ) -> RagQueryResult:
        intents = self._classifier.classify(request)
        is_combination = QuestionIntent.COMBINATION in intents
        if not request.target_ids:
            if is_combination:
                return RagQueryResult(
                    combination=self._missing(UnverifiableReason.MISSING_COMBINATION_EVIDENCE)
                )
            return RagQueryResult(free_text=await self._answer(request, search.chunks, intents))
        results: list[PerTargetResult] = []
        for target_id in sorted(set(request.target_ids)):
            chunks = [
                hit
                for hit in search.chunks
                if target_id in hit.chunk.evidence.target_ids
                and hit.chunk.evidence.scope is not EvidenceScope.PAIR
            ]
            individual_request = request.model_copy(
                deep=True,
                update={
                    "query": self._INDIVIDUAL_QUERY if is_combination else request.query,
                    "target_ids": [target_id],
                    "combination_target_ids": [],
                },
            )
            individual_intents = (
                [QuestionIntent.EFFICACY, QuestionIntent.PRECAUTION] if is_combination else intents
            )
            results.append(
                PerTargetResult(
                    target_id=target_id,
                    result=await self._answer(individual_request, chunks, individual_intents),
                )
            )
        combination = None
        if is_combination:
            pair_ids = set(request.combination_target_ids)
            chunks = [
                hit
                for hit in search.chunks
                if len(pair_ids) >= 2
                and hit.chunk.evidence.scope is EvidenceScope.PAIR
                and set(hit.chunk.evidence.target_ids) == pair_ids
            ]
            combination = (
                await self._answer(request, chunks, intents)
                if chunks
                else self._missing(UnverifiableReason.MISSING_COMBINATION_EVIDENCE)
            )
        return RagQueryResult(per_target=results, combination=combination)

    async def _answer(
        self,
        request: EvidenceSearchRequest,
        chunks: list[RetrievedChunk],
        intents: list[QuestionIntent],
    ) -> IngredientVerificationResult:
        if not chunks:
            return self._missing(UnverifiableReason.NO_EVIDENCE_FOUND)
        verified = [
            hit
            for hit in chunks
            if hit.chunk.confidence_tier in self._VERIFIABLE_TIERS
            and hit.chunk.evidence.review_status is EvidenceReviewStatus.VERIFIED
            and not hit.chunk.evidence.is_demo
        ]
        if not verified:
            return self._missing(UnverifiableReason.UNREVIEWED_EVIDENCE)
        axes = set(intents) - {QuestionIntent.COMBINATION}
        relevant = [hit for hit in verified if not axes or axes.intersection(hit.chunk.intents)]
        # 복합 질문에서 지원하지 않는 축을 다른 축 근거로 덮어쓰지 않는다.
        supported = {intent for hit in relevant for intent in hit.chunk.intents}
        if not relevant or not axes.issubset(supported):
            return self._missing(UnverifiableReason.NOT_RELEVANT_TO_QUESTION)
        records: dict[str, EvidenceRecord] = {}
        for hit in relevant:
            evidence = hit.chunk.evidence
            previous = records.get(evidence.evidence_id)
            if previous is not None and previous != evidence:
                raise ValueError("동일 evidence_id에 서로 다른 원문이나 출처가 연결되었습니다.")
            records[evidence.evidence_id] = evidence
        generated = await self._client.generate(
            ClaimGenerationRequest(
                question=request.query,
                records=list(records.values()),
                known_conditions=request.known_conditions,
                is_combination=QuestionIntent.COMBINATION in intents,
            )
        )
        claims: list[AnsweredClaim] = []
        for claim in generated.claims:
            ids = list(dict.fromkeys(claim.evidence_ids))
            if not ids or any(evidence_id not in records for evidence_id in ids):
                continue
            sources = [records[evidence_id] for evidence_id in ids]
            if not all(self._checker.is_preserved(claim, source) for source in sources):
                continue
            claims.append(AnsweredClaim(sentence=claim.sentence, sources=sources))
        return (
            IngredientVerificationResult(claims=claims)
            if claims
            else self._missing(UnverifiableReason.CITATION_VALIDATION_FAILED)
        )

    def _missing(self, reason: UnverifiableReason) -> IngredientVerificationResult:
        return IngredientVerificationResult(unverifiable_reason=reason)
