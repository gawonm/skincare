"""NIA Case 의미 검색 calibration 기준표의 구조와 독립성을 검증한다."""

from pathlib import Path
from typing import ClassVar

from agent.rag.retrieval.case_candidate_selector import NiaCaseConcernCategory
from tests.agent.nia_case_semantic_calibration_sampler import (
    CalibrationSampleManifestItem,
    CalibrationSampleStratum,
    NiaCaseCalibrationReviewSampler,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    BlindCandidatePoolEntry,
    CandidatePoolArtifactLoader,
    KoreanLexicalCandidateRanker,
    NiaSemanticCorpusCase,
    NiaSemanticCorpusLoader,
)
from tests.agent.nia_case_semantic_evaluation_anchor_sampler import (
    EvaluationAnchorManifestItem,
    EvaluationAnchorStratum,
    NiaCaseSemanticEvaluationAnchorSampler,
)
from tests.agent.nia_case_semantic_evaluation_schemas import (
    NiaCaseSemanticEvaluationQueryLoader,
    NiaCaseSemanticEvaluationReferenceBuilder,
    SemanticEvaluationCohort,
)
from tests.agent.nia_case_semantic_final_golden import (
    NiaCaseSemanticGoldenArtifact,
    SemanticGoldenJudgmentPolicy,
)
from tests.agent.nia_case_semantic_golden_schemas import (
    FinalRelevanceGrade,
    JudgmentReasonCode,
    NiaCaseSemanticCalibrationLoader,
    NiaCaseSemanticJudgment,
    NiaCaseSemanticJudgmentBatch,
    RecommendationConflictCode,
    RecommendationUtilityScore,
    SemanticGoldenPhase,
    SituationFitScore,
)
from tests.agent.nia_case_semantic_metrics import (
    NiaCaseSemanticMetricScorer,
    RankedSemanticCase,
    SemanticRetrievalStage,
    SemanticStageRanking,
)


class TestNiaCaseSemanticCalibrationSet:
    CALIBRATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_v1.jsonl"
    )
    EXPECTED_ITEM_COUNT: ClassVar[int] = 10

    def test_loads_ten_unique_calibration_references(self) -> None:
        calibration = NiaCaseSemanticCalibrationLoader().load(self.CALIBRATION_PATH)

        assert len(calibration.items) == self.EXPECTED_ITEM_COUNT
        assert all(item.phase is SemanticGoldenPhase.CALIBRATION for item in calibration.items)
        assert len({item.evaluation_id for item in calibration.items}) == len(calibration.items)
        assert len({item.query for item in calibration.items}) == len(calibration.items)

    def test_covers_all_nia_case_concern_categories(self) -> None:
        calibration = NiaCaseSemanticCalibrationLoader().load(self.CALIBRATION_PATH)

        covered = {
            concern
            for item in calibration.items
            for concern in [*item.primary_concerns, *item.secondary_concerns]
        }

        assert covered == set(NiaCaseConcernCategory)

    def test_freezes_reference_before_case_judgments(self) -> None:
        calibration = NiaCaseSemanticCalibrationLoader().load(self.CALIBRATION_PATH)

        for item in calibration.items:
            dumped = item.model_dump(mode="json")
            assert "relevant_case_ids" not in dumped
            assert "judgments" not in dumped
            assert all(
                source.url.host == "www.aad.org" for source in item.reference_sources
            )


class TestNiaCaseSemanticCandidatePool:
    CORPUS_PATH: ClassVar[Path] = Path(
        "data/processed/nia_case_documents_10s_30s.jsonl"
    )
    EXPECTED_CORPUS_COUNT: ClassVar[int] = 3_581
    INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_pool_v1.jsonl"
    )
    BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_blind_v1.jsonl"
    )
    EXPECTED_CALIBRATION_COUNT: ClassVar[int] = 10
    EXPECTED_DENSE_TOP_40_COUNT: ClassVar[int] = 400
    SAMPLE_MANIFEST_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_sample_manifest_v1.jsonl"
    )
    SAMPLE_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_sample_blind_v1.jsonl"
    )
    JUDGMENTS_PATHS: ClassVar[tuple[Path, ...]] = (
        Path("tests/agent/nia_case_semantic_calibration_judgments_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_calibration_judgments_pores_v1.jsonl"),
        Path(
            "tests/agent/nia_case_semantic_calibration_judgments_acne_sensitive_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_calibration_judgments_acne_comedonal_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_calibration_judgments_pigment_post_acne_v1.jsonl"
        ),
        Path("tests/agent/nia_case_semantic_calibration_judgments_redness_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_calibration_judgments_wrinkles_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_calibration_judgments_sagging_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_calibration_judgments_melasma_v1.jsonl"),
        Path(
            "tests/agent/nia_case_semantic_calibration_judgments_combo_dehydrated_v1.jsonl"
        ),
    )
    SUPPLEMENT_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_supplement_blind_v1.jsonl"
    )
    SUPPLEMENT_JUDGMENTS_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_calibration_supplement_judgments_v1.jsonl"
    )

    def test_loads_full_corpus_without_reasoning_text(self) -> None:
        corpus = NiaSemanticCorpusLoader().load(self.CORPUS_PATH)

        assert len(corpus.cases) == self.EXPECTED_CORPUS_COUNT
        assert all("[추론]" not in case.answer for case in corpus.cases)

    def test_lexical_ranker_separates_query_and_clinical_matches(self) -> None:
        calibration = NiaCaseSemanticCalibrationLoader().load(
            TestNiaCaseSemanticCalibrationSet.CALIBRATION_PATH
        )
        reference = next(
            item
            for item in calibration.items
            if item.evaluation_id == "calibration_dry_sensitive_winter_01"
        )
        relevant = NiaSemanticCorpusCase(
            case_id="case-relevant",
            dataset_split="training",
            target_concern=NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS.value,
            gender="여성",
            age=30,
            skin_type="건성",
            skin_concerns=[NiaCaseConcernCategory.HYPERKERATOSIS_DRYNESS.value],
            question="겨울철 볼 당김과 각질, 따가움이 고민입니다.",
            answer="세라마이드와 글리세린, 페트롤라툼을 활용한 보습이 필요합니다.",
            normalized_question="겨울철 볼 당김과 각질, 따가움이 고민입니다.",
        )
        unrelated = relevant.model_copy(
            update={
                "case_id": "case-unrelated",
                "question": "여름철 코 모공과 피지가 고민입니다.",
                "answer": "살리실산으로 막힌 모공을 관리합니다.",
                "normalized_question": "여름철 코 모공과 피지가 고민입니다.",
            }
        )
        ranker = KoreanLexicalCandidateRanker()

        assert ranker.query_score(reference.query, relevant) > ranker.query_score(
            reference.query, unrelated
        )
        assert ranker.clinical_score(reference, relevant) > ranker.clinical_score(
            reference, unrelated
        )

    def test_blind_candidate_schema_hides_rank_and_case_identity(self) -> None:
        field_names = set(BlindCandidatePoolEntry.model_fields)

        assert "case_id" not in field_names
        assert "target_concern" not in field_names
        assert "sources" not in field_names
        assert "dense_rank" not in field_names

    def test_generated_pool_preserves_top_40_and_blind_mapping(self) -> None:
        loader = CandidatePoolArtifactLoader()
        internal_items = loader.load_internal(self.INTERNAL_POOL_PATH)
        blind_items = loader.load_blind(self.BLIND_POOL_PATH)

        assert len(internal_items) == self.EXPECTED_CALIBRATION_COUNT
        assert len(blind_items) == self.EXPECTED_CALIBRATION_COUNT
        assert (
            sum(
                candidate.dense_rank is not None and candidate.dense_rank <= 40
                for item in internal_items
                for candidate in item.candidates
            )
            == self.EXPECTED_DENSE_TOP_40_COUNT
        )
        for internal, blind in zip(internal_items, blind_items, strict=True):
            assert internal.evaluation_id == blind.evaluation_id
            assert internal.candidate_count == blind.candidate_count
            assert {candidate.review_key for candidate in internal.candidates} == {
                candidate.review_key for candidate in blind.candidates
            }
            assert all(
                candidate.query_lexical_score > 0
                for candidate in internal.candidates
                if "query_lexical_top_50" in candidate.sources
            )
            assert all(
                candidate.clinical_lexical_score > 0
                for candidate in internal.candidates
                if "clinical_lexical_top_50" in candidate.sources
            )

    def test_calibration_review_sample_has_five_items_per_stratum(self) -> None:
        manifest_items = [
            CalibrationSampleManifestItem.model_validate_json(line)
            for line in self.SAMPLE_MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(self.SAMPLE_BLIND_PATH)

        assert len(manifest_items) == self.EXPECTED_CALIBRATION_COUNT
        assert len(blind_items) == self.EXPECTED_CALIBRATION_COUNT
        for manifest, blind in zip(manifest_items, blind_items, strict=True):
            assert len(manifest.entries) == (
                NiaCaseCalibrationReviewSampler.ITEMS_PER_STRATUM
                * len(CalibrationSampleStratum)
            )
            assert all(
                sum(entry.stratum is stratum for entry in manifest.entries)
                == NiaCaseCalibrationReviewSampler.ITEMS_PER_STRATUM
                for stratum in CalibrationSampleStratum
            )
            assert {entry.review_key for entry in manifest.entries} == {
                candidate.review_key for candidate in blind.candidates
            }

    def test_complete_judgments_match_all_blind_sample_keys(self) -> None:
        batches = [
            NiaCaseSemanticJudgmentBatch.model_validate_json(line)
            for path in self.JUDGMENTS_PATHS
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(self.SAMPLE_BLIND_PATH)

        assert len(batches) == self.EXPECTED_CALIBRATION_COUNT
        assert len({batch.evaluation_id for batch in batches}) == len(batches)
        assert sum(len(batch.judgments) for batch in batches) == 150
        for batch in batches:
            blind = next(
                item for item in blind_items if item.evaluation_id == batch.evaluation_id
            )
            assert {judgment.review_key for judgment in batch.judgments} == {
                candidate.review_key for candidate in blind.candidates
            }

    def test_duplicate_candidates_receive_same_scores(self) -> None:
        batches = [
            NiaCaseSemanticJudgmentBatch.model_validate_json(line)
            for path in self.JUDGMENTS_PATHS
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(self.SAMPLE_BLIND_PATH)
        judgments_by_key = {
            judgment.review_key: judgment
            for batch in batches
            for judgment in batch.judgments
        }
        candidates_by_content: dict[
            tuple[str, str, str], list[BlindCandidatePoolEntry]
        ] = {}
        for item in blind_items:
            for candidate in item.candidates:
                candidates_by_content.setdefault(
                    (item.evaluation_id, candidate.question, candidate.answer), []
                ).append(candidate)

        duplicate_groups = [
            candidates
            for candidates in candidates_by_content.values()
            if len(candidates) > 1
        ]

        assert duplicate_groups
        for candidates in duplicate_groups:
            scores = {
                (
                    judgments_by_key[candidate.review_key].situation_fit,
                    judgments_by_key[candidate.review_key].recommendation_utility,
                    judgments_by_key[candidate.review_key].relevance_grade,
                )
                for candidate in candidates
            }
            assert len(scores) == 1

    def test_supplement_judgments_match_blind_candidates(self) -> None:
        batches = [
            NiaCaseSemanticJudgmentBatch.model_validate_json(line)
            for line in self.SUPPLEMENT_JUDGMENTS_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(
            self.SUPPLEMENT_BLIND_PATH
        )

        assert len(batches) == 2
        assert sum(len(batch.judgments) for batch in batches) == 20
        for batch in batches:
            blind = next(
                item for item in blind_items if item.evaluation_id == batch.evaluation_id
            )
            assert {judgment.review_key for judgment in batch.judgments} == {
                candidate.review_key for candidate in blind.candidates
            }


class TestNiaCaseSemanticJudgment:
    def test_strong_fit_and_utility_is_highly_relevant(self) -> None:
        judgment = NiaCaseSemanticJudgment(
            review_key="0123456789abcdef",
            situation_fit=SituationFitScore.STRONG,
            recommendation_utility=RecommendationUtilityScore.STRONG,
            reason_codes=[JudgmentReasonCode.PRIMARY_CONCERN_MATCH],
            relevance_grade=FinalRelevanceGrade.HIGHLY_RELEVANT,
            note="주 고민과 필수 추천 기능이 모두 일치한다.",
        )

        assert judgment.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT

    def test_conflict_forces_not_relevant(self) -> None:
        judgment = NiaCaseSemanticJudgment(
            review_key="fedcba9876543210",
            situation_fit=SituationFitScore.STRONG,
            recommendation_utility=RecommendationUtilityScore.STRONG,
            conflict_codes=[RecommendationConflictCode.AGGRESSIVE_EXFOLIATION],
            reason_codes=[JudgmentReasonCode.DOMINANT_GOAL_CONFLICT],
            relevance_grade=FinalRelevanceGrade.NOT_RELEVANT,
            note="사용자 조건과 충돌하는 강한 각질 제거를 우선한다.",
        )

        assert judgment.relevance_grade is FinalRelevanceGrade.NOT_RELEVANT


class TestNiaCaseSemanticMetricScorer:
    def test_ceiling_hit_uses_best_grade_available_in_corpus(self) -> None:
        ranking = SemanticStageRanking(
            stage=SemanticRetrievalStage.RERANKER_TOP_3,
            items=[
                RankedSemanticCase(
                    review_key="0123456789abcdef",
                    rank=1,
                    relevance_grade=FinalRelevanceGrade.RELEVANT,
                ),
                RankedSemanticCase(
                    review_key="1111111111111111",
                    rank=2,
                    relevance_grade=FinalRelevanceGrade.SUPPORTIVE,
                ),
            ],
        )

        metric = NiaCaseSemanticMetricScorer().score_stage(
            ranking=ranking,
            all_judged_grades=[
                FinalRelevanceGrade.RELEVANT,
                FinalRelevanceGrade.SUPPORTIVE,
            ],
        )

        assert metric.corpus_ceiling_grade is FinalRelevanceGrade.RELEVANT
        assert metric.ceiling_hit is True
        assert metric.ndcg == 1.0

    def test_missing_available_grade_lowers_ceiling_hit_and_ndcg(self) -> None:
        ranking = SemanticStageRanking(
            stage=SemanticRetrievalStage.RERANKER_TOP_3,
            items=[
                RankedSemanticCase(
                    review_key="fedcba9876543210",
                    rank=1,
                    relevance_grade=FinalRelevanceGrade.SUPPORTIVE,
                )
            ],
        )

        metric = NiaCaseSemanticMetricScorer().score_stage(
            ranking=ranking,
            all_judged_grades=[
                FinalRelevanceGrade.HIGHLY_RELEVANT,
                FinalRelevanceGrade.SUPPORTIVE,
            ],
        )

        assert metric.corpus_ceiling_grade is FinalRelevanceGrade.HIGHLY_RELEVANT
        assert metric.ceiling_hit is False
        assert metric.ndcg is not None
        assert metric.ndcg < 1.0


class TestNiaCaseSemanticEvaluationQueries:
    EVALUATION_QUERY_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_queries_v1.jsonl"
    )
    EVALUATION_INTERNAL_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    EVALUATION_BLIND_POOL_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_blind_v1.jsonl"
    )
    EVALUATION_ANCHOR_MANIFEST_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_anchor_manifest_v1.jsonl"
    )
    EVALUATION_ANCHOR_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_anchor_blind_v1.jsonl"
    )
    FINAL_GOLDEN_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_golden_v1.jsonl"
    )
    EVALUATION_JUDGMENT_PATHS: ClassVar[tuple[Path, ...]] = (
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_01_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_02_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_03_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_04_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_05_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_06_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_07_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pores_08_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_01_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_02_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_03_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_04_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_05_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_06_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_07_v1.jsonl"
        ),
        Path(
            "tests/agent/nia_case_semantic_evaluation_anchor_judgments_pigment_08_v1.jsonl"
        ),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_02_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_03_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_04_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_05_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_06_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_07_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_acne_08_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_02_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_03_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_04_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_05_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_composite_06_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_dry_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_dry_02_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_dry_03_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_redness_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_redness_02_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_redness_03_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_wrinkles_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_wrinkles_02_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_sensitive_01_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_anchor_judgments_sagging_01_v1.jsonl"),
    )
    RERANK_JUDGMENT_PATHS: ClassVar[tuple[Path, ...]] = (
        Path("tests/agent/nia_case_semantic_evaluation_rerank_judgments_pores_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_rerank_judgments_pigment_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_rerank_judgments_acne_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_rerank_judgments_composite_v1.jsonl"),
        Path("tests/agent/nia_case_semantic_evaluation_rerank_judgments_rare_v1.jsonl"),
    )
    RERANK_UNJUDGED_BLIND_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_rerank_unjudged_blind_v1.jsonl"
    )

    def test_freezes_forty_queries_with_agreed_cohort_sizes(self) -> None:
        query_set = NiaCaseSemanticEvaluationQueryLoader().load(
            self.EVALUATION_QUERY_PATH
        )

        assert len(query_set.items) == 40
        assert (
            sum(item.cohort is SemanticEvaluationCohort.CORE for item in query_set.items)
            == 30
        )
        assert (
            sum(
                item.cohort is SemanticEvaluationCohort.RARE_STRESS
                for item in query_set.items
            )
            == 10
        )

    def test_uses_only_existing_calibration_reference_templates(self) -> None:
        query_set = NiaCaseSemanticEvaluationQueryLoader().load(
            self.EVALUATION_QUERY_PATH
        )
        calibration = NiaCaseSemanticCalibrationLoader().load(
            TestNiaCaseSemanticCalibrationSet.CALIBRATION_PATH
        )
        known_ids = {item.evaluation_id for item in calibration.items}

        assert all(
            set(item.calibration_template_ids) <= known_ids
            for item in query_set.items
        )

    def test_builds_forty_evaluation_reference_cards_without_search_results(self) -> None:
        query_set = NiaCaseSemanticEvaluationQueryLoader().load(
            self.EVALUATION_QUERY_PATH
        )
        calibration = NiaCaseSemanticCalibrationLoader().load(
            TestNiaCaseSemanticCalibrationSet.CALIBRATION_PATH
        )

        references = NiaCaseSemanticEvaluationReferenceBuilder().build(
            query_set=query_set,
            calibration_references=calibration.items,
        )

        assert len(references.items) == 40
        assert all(
            item.phase is SemanticGoldenPhase.EVALUATION for item in references.items
        )
        assert all(item.required_functions for item in references.items)
        assert all(item.reference_sources for item in references.items)

    def test_evaluation_candidate_pool_preserves_all_dense_top_40(self) -> None:
        loader = CandidatePoolArtifactLoader()
        internal_items = loader.load_internal(self.EVALUATION_INTERNAL_POOL_PATH)
        blind_items = loader.load_blind(self.EVALUATION_BLIND_POOL_PATH)

        assert len(internal_items) == 40
        assert len(blind_items) == 40
        assert (
            sum(
                candidate.dense_rank is not None and candidate.dense_rank <= 40
                for item in internal_items
                for candidate in item.candidates
            )
            == 1_600
        )
        for internal, blind in zip(internal_items, blind_items, strict=True):
            assert internal.evaluation_id == blind.evaluation_id
            assert internal.candidate_count == blind.candidate_count
            assert {candidate.review_key for candidate in internal.candidates} == {
                candidate.review_key for candidate in blind.candidates
            }

    def test_evaluation_anchor_sample_has_fifteen_unique_items_per_query(self) -> None:
        manifests = [
            EvaluationAnchorManifestItem.model_validate_json(line)
            for line in self.EVALUATION_ANCHOR_MANIFEST_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(
            self.EVALUATION_ANCHOR_BLIND_PATH
        )

        assert len(manifests) == 40
        assert len(blind_items) == 40
        for manifest, blind in zip(manifests, blind_items, strict=True):
            assert blind.candidate_count == 15
            assert (
                sum(
                    item.stratum is EvaluationAnchorStratum.DENSE_PROBE
                    for item in manifest.entries
                )
                == NiaCaseSemanticEvaluationAnchorSampler.DENSE_PROBE_COUNT
            )
            assert (
                sum(
                    item.stratum is EvaluationAnchorStratum.OFF_RANK_ANCHOR
                    for item in manifest.entries
                )
                == NiaCaseSemanticEvaluationAnchorSampler.OFF_RANK_ANCHOR_COUNT
            )
            assert len({(item.question, item.answer) for item in blind.candidates}) == 15

    def test_evaluation_judgment_batches_match_anchor_candidates(self) -> None:
        batches = [
            NiaCaseSemanticJudgmentBatch.model_validate_json(line)
            for path in self.EVALUATION_JUDGMENT_PATHS
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(
            self.EVALUATION_ANCHOR_BLIND_PATH
        )

        assert len(batches) == len(self.EVALUATION_JUDGMENT_PATHS)
        for batch in batches:
            blind = next(
                item for item in blind_items if item.evaluation_id == batch.evaluation_id
            )
            assert {item.review_key for item in batch.judgments} == {
                item.review_key for item in blind.candidates
            }

    def test_final_golden_contains_forty_queries_and_merged_qrels(self) -> None:
        golden = NiaCaseSemanticGoldenArtifact().load(self.FINAL_GOLDEN_PATH)

        assert len(golden.items) == 40
        assert sum(len(item.graded_qrels) for item in golden.items) == 681
        assert all(
            item.provenance.judgment_policy
            is SemanticGoldenJudgmentPolicy.POOLED_ANCHOR
            for item in golden.items
        )

    def test_final_golden_relevant_ids_are_derived_from_graded_qrels(self) -> None:
        golden = NiaCaseSemanticGoldenArtifact().load(self.FINAL_GOLDEN_PATH)

        for item in golden.items:
            assert item.relevant_case_ids == [
                qrel.case_id
                for qrel in item.graded_qrels
                if qrel.relevance_grade >= FinalRelevanceGrade.RELEVANT
            ]
            assert item.highly_relevant_case_ids == [
                qrel.case_id
                for qrel in item.graded_qrels
                if qrel.relevance_grade is FinalRelevanceGrade.HIGHLY_RELEVANT
            ]

    def test_reranker_supplement_judgments_cover_all_unjudged_top3(self) -> None:
        batches = [
            NiaCaseSemanticJudgmentBatch.model_validate_json(line)
            for path in self.RERANK_JUDGMENT_PATHS
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blind_items = CandidatePoolArtifactLoader().load_blind(
            self.RERANK_UNJUDGED_BLIND_PATH
        )
        judgments_by_id = {
            batch.evaluation_id: batch.judgments for batch in batches
        }

        assert sum(len(batch.judgments) for batch in batches) == 81
        assert set(judgments_by_id) == {
            item.evaluation_id for item in blind_items
        }
        for blind in blind_items:
            assert {
                item.review_key for item in judgments_by_id[blind.evaluation_id]
            } == {item.review_key for item in blind.candidates}
