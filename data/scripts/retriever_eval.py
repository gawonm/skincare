"""production Evidence retriever(HybridEvidenceRetriever)를 canonical v5 read-only
평가 DB에 대해 실제로 호출해 채점하는 진입점.

Agent/Backend 코드는 읽기/호출만 한다 - 이 스크립트는 그 코드를 한 줄도 고치지
않는다. DB는 읽기 전용 연결만 쓴다(INSERT/UPDATE/DELETE 없음).

사용법:
    uv run python -m data.scripts.retriever_eval --dsn postgresql+asyncpg://app:app@localhost:5432/evidence_retriever_eval
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from sqlalchemy import text

from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.retrieval.cross_encoder import LocalBgeCrossEncoderScorer
from agent.rag.retrieval.hybrid_retriever import HybridEvidenceRetriever
from agent.rag.retrieval.ingredient_alias_mapper import CommonIngredientAliasMapper
from agent.rag.retrieval.local_reranker import LocalBgeRerankerV2M3
from agent.rag.schemas import (
    EmbeddingProvider,
    EvidenceSearchRequest,
    IngredientResolveRequest,
    LocalEmbeddingConfig,
    LocalEmbeddingModel,
    LocalRerankerConfig,
    LocalRerankerModel,
    LookupStatus,
    RagRetrievalPolicy,
    RetrievedChunk,
    TextEmbeddingConfig,
)
from backend.services.two_layer_rag_adapters import TwoLayerEvidenceSearchBackend
from core.database import Database, DatabaseConfig
from data.scripts.retriever_eval_schemas import (
    EvalCase,
    EvalCaseResult,
    FailureClassification,
    RetrievedChunkSummary,
    TargetMode,
    Verdict,
)

_DEFAULT_RESULTS_CSV = Path("data/outputs/evidence_coverage/retriever_eval_results.csv")
_DEFAULT_REPORT_MD = Path("docs/data/RETRIEVER_EVAL_REPORT.md")

# 프로젝트 config.yaml에 agent.retrieval 블록이 없어 production 기본값이 존재하지
# 않는다(core/config.py의 RagRetrievalSettings.free_text_min_vector_similarity는
# None이 기본값이고, 실제 실행 시 명시하지 않으면 RuntimeError가 난다 - 다른 dev
# 진입점(tests/agent/interactive_two_layer_rag_cli.py)도 마찬가지). 평가 목적으로
# 0.3(BGE-M3 코사인 유사도 완만한 컷오프)을 직접 골랐다 - "이게 production 값"이
# 아니라 이 평가에서 쓴 값임을 보고서에 명시한다.
_FREE_TEXT_MIN_VECTOR_SIMILARITY = 0.3

_CASES: list[EvalCase] = [
    EvalCase(
        case_id="niacinamide_efficacy",
        query="나이아신아마이드 피지 조절과 미백 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Niacinamide",
        expected_source_types=["paper", "cir"],
        expected_claim_topics=["efficacy"],
    ),
    EvalCase(
        case_id="niacinamide_barrier_sebum",
        query="나이아신아마이드가 피부 장벽 회복과 피지 분비 억제에 어떤 효과가 있나요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Niacinamide",
        expected_source_types=["paper"],
        expected_claim_topics=["efficacy"],
    ),
    EvalCase(
        case_id="retinol_efficacy",
        query="레티놀 주름 개선 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Retinol",
        expected_source_types=["paper", "cir"],
        expected_claim_topics=["efficacy"],
    ),
    EvalCase(
        case_id="retinol_precaution",
        query="레티놀 자극이나 부작용 위험이 있나요 주의사항 알려주세요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Retinol",
        expected_source_types=["cir", "paper"],
        expected_claim_topics=["precaution"],
    ),
    EvalCase(
        case_id="salicylic_acid_efficacy",
        query="살리실산 여드름 각질 개선 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Salicylic Acid",
        expected_source_types=["paper", "cir"],
        expected_claim_topics=["efficacy"],
    ),
    EvalCase(
        case_id="salicylic_acid_precaution",
        query="살리실산 자극이나 부작용이 있나요 주의사항 알려주세요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Salicylic Acid",
        expected_source_types=["cir", "paper"],
        expected_claim_topics=["precaution"],
    ),
    EvalCase(
        case_id="ascorbic_acid",
        query="아스코빅애씨드(비타민C) 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Ascorbic Acid",
        expected_source_types=["cir", "paper"],
        expected_claim_topics=["efficacy"],
        forbidden_ingredient_names=["Sodium Ascorbyl Phosphate"],
        notes="같은 CIR document를 공유하는 Sodium Ascorbyl Phosphate와 chunk 단위로 분리되는지 확인",
    ),
    EvalCase(
        case_id="sodium_ascorbyl_phosphate",
        query="소듐아스코빌포스페이트 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Sodium Ascorbyl Phosphate",
        expected_source_types=["cir"],
        expected_claim_topics=["efficacy", "precaution"],
        forbidden_ingredient_names=["Ascorbic Acid"],
        notes="같은 CIR document를 공유하는 Ascorbic Acid와 chunk 단위로 분리되는지 확인",
    ),
    EvalCase(
        case_id="capryloyl_salicylic_acid",
        query="카프릴로일살리실릭애씨드 안전성 정보가 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Capryloyl Salicylic Acid",
        expected_source_types=["cir"],
        expected_claim_topics=["precaution"],
        forbidden_ingredient_names=["Salicylic Acid"],
        notes="이름이 비슷한 Salicylic Acid 자체 보고서와 혼동되지 않는지 확인",
    ),
    EvalCase(
        case_id="tranexamic_acid",
        query="트라넥사믹애씨드 미백 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Tranexamic Acid",
        expected_source_types=["paper"],
        expected_claim_topics=["efficacy"],
    ),
    EvalCase(
        case_id="adenosine_safety",
        query="아데노신 안전성 자료가 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Adenosine",
        expected_source_types=["cir"],
        expected_claim_topics=["precaution"],
    ),
    EvalCase(
        case_id="hyaluronic_acid_family",
        query="하이알루로닉애씨드 보습 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Hyaluronic Acid",
        expected_source_types=["cir", "paper"],
        expected_claim_topics=["efficacy"],
        forbidden_ingredient_names=["Sodium Hyaluronate", "Hydrolyzed Hyaluronic Acid"],
        notes="같은 CIR Hyaluronates 문서를 공유하는 유도체 성분과 섞이지 않는지 확인",
    ),
    EvalCase(
        case_id="centella_madecassoside",
        query="마데카소사이드 피부 진정 효능이 궁금해요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Madecassoside",
        expected_source_types=["paper"],
        expected_claim_topics=["efficacy"],
        forbidden_ingredient_names=["Panthenol"],
        notes="PMID 30945430의 Panthenol link 제거(Decision 3) 이후에도 Madecassoside 검색이 정상인지 회귀 확인",
    ),
    EvalCase(
        case_id="bare_bha_ambiguity",
        query="BHA 성분이 궁금해요",
        target_mode=TargetMode.AMBIGUOUS_FAMILY,
        expected_ingredient_name="BHA",
        notes="CommonIngredientAliasMapper가 단일 성분으로 확정하지 않고 모호 상태로 유지하는지 확인",
    ),
    EvalCase(
        case_id="zero_evidence_ingredient",
        query="소듐씨12-14알케스-3설페이트 효능이 궁금해요",
        target_mode=TargetMode.ZERO_EVIDENCE,
        expected_ingredient_name="Sodium C12-14 Alketh-3 Sulfate",
        notes="evidence_chunk_ingredient가 0건인 성분 - 결과가 비어있어야 정상",
    ),
    EvalCase(
        case_id="mfds_regulatory_query",
        query="살리실산 배합 한도가 어떻게 되나요 사용제한 알려주세요",
        target_mode=TargetMode.SINGLE,
        expected_ingredient_name="Salicylic Acid",
        expected_source_types=["mfds_restricted_ingredient"],
        expected_claim_topics=["concentration_regulation"],
    ),
]


class RetrieverEvalRunner:
    """케이스 목록을 production retriever로 실행하고 채점한다."""

    def __init__(self, database: Database, retriever: HybridEvidenceRetriever) -> None:
        self._database = database
        self._retriever = retriever
        self._alias_mapper = CommonIngredientAliasMapper()

    _AGENT_TO_DB_SOURCE_TYPE: ClassVar[dict[str, str]] = {
        "paper": "pubmed_abstract",
        "cir": "cir",
        "mfds_restricted_ingredient": "mfds",
    }

    async def _evidence_exists(
        self,
        ingredient_id: str | None,
        *,
        source_types: list[str] | None = None,
        claim_topics: list[str] | None = None,
    ) -> bool:
        """DB에 실제로 해당 조건의 evidence가 있는지(랭킹 문제 vs 수집 공백 구분용)."""
        if ingredient_id is None:
            return False
        clauses = ["eci.ingredient_id = CAST(:ingredient_id AS uuid)"]
        params: dict[str, object] = {"ingredient_id": ingredient_id}
        if source_types:
            db_types = [self._AGENT_TO_DB_SOURCE_TYPE.get(t, t) for t in source_types]
            clauses.append("ec.source_type = ANY(CAST(:source_types AS text[]))")
            params["source_types"] = db_types
        if claim_topics:
            clauses.append("ed.claim_topics && CAST(:claim_topics AS text[])")
            params["claim_topics"] = claim_topics
        query = (
            "SELECT 1 FROM evidence_chunk_ingredient eci "
            "JOIN evidence_chunk ec ON ec.id = eci.evidence_chunk_id "
            "JOIN evidence_document ed ON ed.id = ec.document_id "
            f"WHERE {' AND '.join(clauses)} LIMIT 1"
        )
        async with self._database.session_factory() as session:
            row = (await session.execute(text(query), params)).first()
        return row is not None

    async def resolve_ingredient_id(self, name: str) -> UUID | None:
        async with self._database.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id FROM ingredient_master "
                        "WHERE standard_name_en = :name OR standard_name_ko = :name"
                    ),
                    {"name": name},
                )
            ).first()
        return row[0] if row else None

    async def run_case(self, case: EvalCase) -> EvalCaseResult:
        target_ids: list[str] = []
        expected_ingredient_id: str | None = None

        if case.target_mode is TargetMode.AMBIGUOUS_FAMILY:
            request = IngredientResolveRequest(name=case.expected_ingredient_name or case.query)
            is_ambiguous = self._alias_mapper.is_ambiguous_family(request)
            if not is_ambiguous:
                return self._make_result(
                    case,
                    expected_ingredient_id=None,
                    target_ids_used=[],
                    lookup_status="n/a",
                    retrieved=[],
                    verdict=Verdict.FAIL,
                    failure=FailureClassification.AGENT_RETRIEVAL,
                    reason=(
                        "CommonIngredientAliasMapper가 'BHA'를 모호 성분군으로 판정하지 않음"
                        "(production 별칭 사전이 바뀌었을 가능성)"
                    ),
                )
            candidates = self._alias_mapper.family_candidates(request)
            reason = f"정상: 'BHA'가 모호 성분군으로 판정됨(candidates={candidates}), 단일 target_id로 자동 확정하지 않음"
            return self._make_result(
                case,
                expected_ingredient_id=None,
                target_ids_used=[],
                lookup_status="ambiguous_family",
                retrieved=[],
                verdict=Verdict.PASS,
                failure=FailureClassification.NONE,
                reason=reason,
            )

        if case.expected_ingredient_name is not None:
            pk = await self.resolve_ingredient_id(case.expected_ingredient_name)
            if pk is None:
                return self._make_result(
                    case,
                    expected_ingredient_id=None,
                    target_ids_used=[],
                    lookup_status="n/a",
                    retrieved=[],
                    verdict=Verdict.FAIL,
                    failure=FailureClassification.DATA,
                    reason=f"ingredient_master에서 '{case.expected_ingredient_name}'을 찾을 수 없음",
                )
            expected_ingredient_id = str(pk)
            target_ids = [expected_ingredient_id]

        result = await self._retriever.search(
            EvidenceSearchRequest(query=case.query, target_ids=target_ids, limit=5)
        )

        if result.status in (LookupStatus.ERROR, LookupStatus.UNSUPPORTED):
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=result.status.value,
                retrieved=[],
                verdict=Verdict.FAIL,
                failure=FailureClassification.UNKNOWN,
                reason=f"retriever가 {result.status.value} 상태를 반환함: {result.error_message}",
            )

        retrieved = [self._to_summary(rank, hit) for rank, hit in enumerate(result.chunks, start=1)]

        if case.target_mode is TargetMode.ZERO_EVIDENCE:
            false_positive = len(retrieved) > 0
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=result.status.value,
                retrieved=retrieved,
                verdict=Verdict.FAIL if false_positive else Verdict.PASS,
                failure=FailureClassification.BACKEND_REPOSITORY
                if false_positive
                else FailureClassification.NONE,
                reason=(
                    f"zero-evidence 성분인데 {len(retrieved)}건이 반환됨(false positive)"
                    if false_positive
                    else "정상: zero-evidence 성분에 결과 없음"
                ),
                zero_evidence_false_positive=false_positive,
            )

        return await self._score_single_target(
            case, expected_ingredient_id, target_ids, result.status.value, retrieved
        )

    async def _score_single_target(
        self,
        case: EvalCase,
        expected_ingredient_id: str | None,
        target_ids: list[str],
        lookup_status: str,
        retrieved: list[RetrievedChunkSummary],
    ) -> EvalCaseResult:
        top5 = retrieved[:5]

        def has_expected(rows: list[RetrievedChunkSummary]) -> bool:
            return any(expected_ingredient_id in row.target_ids for row in rows)

        hit_at_5 = has_expected(top5)
        expected_source_hit = (
            any(row.source_type in case.expected_source_types for row in top5)
            if case.expected_source_types
            else True
        )
        claim_topic_hit = (
            any(topic in row.claim_topics for row in top5 for topic in case.expected_claim_topics)
            if case.expected_claim_topics
            else True
        )
        forbidden_hit_count = sum(
            1
            for row in top5
            if any(
                name in row.source_title or name in row.chunk_id
                for name in case.forbidden_ingredient_names
            )
            and expected_ingredient_id not in row.target_ids
        )

        if not retrieved:
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=lookup_status,
                retrieved=retrieved,
                verdict=Verdict.FAIL,
                failure=FailureClassification.DATA,
                reason="검색 결과가 비어 있음(예상 성분에 대한 evidence가 DB에 없거나 검색 임계값에 걸림)",
            )
        if not hit_at_5:
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=lookup_status,
                retrieved=retrieved,
                verdict=Verdict.FAIL,
                failure=FailureClassification.AGENT_RETRIEVAL,
                reason="target_ids로 조회했는데도 top-5에 예상 성분이 없음(리트리버 필터링/정렬 문제로 추정)",
            )
        if forbidden_hit_count > 0:
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=lookup_status,
                retrieved=retrieved,
                verdict=Verdict.FAIL,
                failure=FailureClassification.DATA,
                reason=f"금지 성분과 혼동되는 chunk가 {forbidden_hit_count}건 포함됨(문서/링크 분리 문제로 추정)",
                forbidden_ingredient_hit_count=forbidden_hit_count,
            )
        if not expected_source_hit:
            exists_in_db = await self._evidence_exists(
                expected_ingredient_id, source_types=case.expected_source_types
            )
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=lookup_status,
                retrieved=retrieved,
                verdict=Verdict.FAIL,
                failure=(
                    FailureClassification.AGENT_RETRIEVAL
                    if exists_in_db
                    else FailureClassification.DATA
                ),
                reason=(
                    f"기대한 source_type({case.expected_source_types})의 evidence가 DB에 있는데도 "
                    "top-5 밖으로 밀림(랭킹/후보 다양성 문제로 추정)"
                    if exists_in_db
                    else f"기대한 source_type({case.expected_source_types})의 evidence 자체가 이 성분에 없음(수집 공백)"
                ),
            )
        if not claim_topic_hit:
            exists_in_db = await self._evidence_exists(
                expected_ingredient_id, claim_topics=case.expected_claim_topics
            )
            return self._make_result(
                case,
                expected_ingredient_id=expected_ingredient_id,
                target_ids_used=target_ids,
                lookup_status=lookup_status,
                retrieved=retrieved,
                verdict=Verdict.FAIL,
                failure=(
                    FailureClassification.AGENT_RETRIEVAL
                    if exists_in_db
                    else FailureClassification.DATA
                ),
                reason=(
                    f"기대한 claim_topic({case.expected_claim_topics}) evidence가 DB에 있는데도 "
                    "top-5 밖으로 밀림(랭킹/후보 다양성 문제로 추정)"
                    if exists_in_db
                    else f"기대한 claim_topic({case.expected_claim_topics})이 태깅된 evidence 자체가 이 성분에 없음(수집·태깅 공백)"
                ),
            )
        return self._make_result(
            case,
            expected_ingredient_id=expected_ingredient_id,
            target_ids_used=target_ids,
            lookup_status=lookup_status,
            retrieved=retrieved,
            verdict=Verdict.PASS,
            failure=FailureClassification.NONE,
            reason="정상: 예상 성분/출처/claim_topic이 top-5 안에서 확인됨",
        )

    def _citation_ok(self, row: RetrievedChunkSummary) -> bool:
        if row.source_type == "paper":
            return bool(row.pmid) and bool(row.url)
        if row.source_type == "cir":
            return bool(row.url)
        return True  # mfds는 legacy 데이터 특성상 url 없음이 정상(EVIDENCE_STORAGE_ERD 참고)

    def _to_summary(self, rank: int, hit: RetrievedChunk) -> RetrievedChunkSummary:
        evidence = hit.chunk.evidence
        source_reference = evidence.source_reference or ""
        pmid = next(
            (
                part.split(":", 1)[1]
                for part in source_reference.split("; ")
                if part.startswith("PMID:")
            ),
            None,
        )
        doi = next(
            (
                part.split(":", 1)[1]
                for part in source_reference.split("; ")
                if part.startswith("DOI:")
            ),
            None,
        )
        return RetrievedChunkSummary(
            rank=rank,
            chunk_id=hit.chunk.chunk_id,
            source_type=evidence.source_type.value,
            source_title=evidence.source_title,
            pmid=pmid,
            doi=doi,
            url=evidence.url,
            locator=evidence.locator,
            claim_topics=[t.strip() for t in (evidence.topic or "").split(",") if t.strip()],
            target_ids=evidence.target_ids,
            vector_similarity=hit.vector_similarity,
            bm25_relevance=hit.bm25_relevance,
            reranker_score=hit.reranker_score,
        )

    def _make_result(
        self,
        case: EvalCase,
        *,
        expected_ingredient_id: str | None,
        target_ids_used: list[str],
        lookup_status: str,
        retrieved: list[RetrievedChunkSummary],
        verdict: Verdict,
        failure: FailureClassification,
        reason: str,
        forbidden_ingredient_hit_count: int = 0,
        zero_evidence_false_positive: bool = False,
    ) -> EvalCaseResult:
        top5 = retrieved[:5]
        top3 = retrieved[:3]

        def has_expected(rows: list[RetrievedChunkSummary]) -> bool:
            return expected_ingredient_id is not None and any(
                expected_ingredient_id in row.target_ids for row in rows
            )

        return EvalCaseResult(
            case_id=case.case_id,
            query=case.query,
            expected_ingredient_name=case.expected_ingredient_name,
            expected_ingredient_id=expected_ingredient_id,
            target_ids_used=target_ids_used,
            lookup_status=lookup_status,
            retrieved=retrieved,
            ingredient_hit_at_3=has_expected(top3),
            ingredient_hit_at_5=has_expected(top5),
            ingredient_precision_at_5=(
                sum(1 for row in top5 if expected_ingredient_id in row.target_ids) / len(top5)
                if top5 and expected_ingredient_id is not None
                else 0.0
            ),
            expected_source_hit_at_5=(
                any(row.source_type in case.expected_source_types for row in top5)
                if case.expected_source_types
                else True
            ),
            claim_topic_hit_at_5=(
                any(
                    topic in row.claim_topics
                    for row in top5
                    for topic in case.expected_claim_topics
                )
                if case.expected_claim_topics
                else True
            ),
            forbidden_ingredient_hit_count=forbidden_ingredient_hit_count,
            citation_metadata_complete=all(self._citation_ok(row) for row in top5)
            if top5
            else True,
            zero_evidence_false_positive=zero_evidence_false_positive,
            verdict=verdict,
            failure_classification=failure,
            reason=reason,
        )


def _build_retriever(database: Database) -> HybridEvidenceRetriever:
    embedder = TextEmbedderFactory().create(
        TextEmbeddingConfig(
            provider=EmbeddingProvider.LOCAL,
            local=LocalEmbeddingConfig(model=LocalEmbeddingModel.BGE_M3),
        )
    )
    reranker_config = LocalRerankerConfig(model=LocalRerankerModel.BGE_RERANKER_V2_M3)
    scorer = LocalBgeCrossEncoderScorer(reranker_config)
    policy = RagRetrievalPolicy(
        free_text_min_vector_similarity=_FREE_TEXT_MIN_VECTOR_SIMILARITY,
        rrf_k=60,
        rerank_candidate_limit=30,
    )
    return HybridEvidenceRetriever(
        backend=TwoLayerEvidenceSearchBackend(database.session_factory),
        embedder=embedder,
        policy=policy,
        reranker=LocalBgeRerankerV2M3(reranker_config, scorer=scorer),
    )


def _write_csv(results: list[EvalCaseResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "query",
        "expected_ingredient_name",
        "expected_ingredient_id",
        "rank",
        "chunk_id",
        "source_type",
        "source_title",
        "pmid",
        "doi",
        "url",
        "locator",
        "claim_topics",
        "target_ids",
        "verdict",
        "failure_classification",
        "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            rows = result.retrieved or [None]
            for row in rows:
                writer.writerow(
                    {
                        "case_id": result.case_id,
                        "query": result.query,
                        "expected_ingredient_name": result.expected_ingredient_name or "",
                        "expected_ingredient_id": result.expected_ingredient_id or "",
                        "rank": row.rank if row else "",
                        "chunk_id": row.chunk_id if row else "",
                        "source_type": row.source_type if row else "",
                        "source_title": row.source_title if row else "",
                        "pmid": row.pmid if row else "",
                        "doi": row.doi if row else "",
                        "url": row.url if row else "",
                        "locator": row.locator if row else "",
                        "claim_topics": ";".join(row.claim_topics) if row else "",
                        "target_ids": ";".join(row.target_ids) if row else "",
                        "verdict": result.verdict.value,
                        "failure_classification": result.failure_classification.value,
                        "reason": result.reason,
                    }
                )


async def _run(dsn: str) -> list[EvalCaseResult]:
    database = Database(DatabaseConfig(url=dsn))
    try:
        retriever = _build_retriever(database)
        runner = RetrieverEvalRunner(database, retriever)
        return [await runner.run_case(case) for case in _CASES]
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="asyncpg DSN(postgresql+asyncpg://...)")
    parser.add_argument("--results-csv", type=Path, default=_DEFAULT_RESULTS_CSV)
    args = parser.parse_args()

    results = asyncio.run(_run(args.dsn))
    _write_csv(results, args.results_csv)
    print(
        json.dumps(
            [r.model_dump(mode="json") for r in results],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
