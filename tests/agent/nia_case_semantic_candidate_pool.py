"""전체 NIA Case 코퍼스에서 calibration 관련도 판정 후보 풀을 만든다.

운영 검색 성능을 평가하기 전에 현재 dense 결과 밖의 관련 Case도 발견해야 하므로,
현재 BGE-M3 깊은 검색과 질문 어휘·추천 성분·메타데이터 후보를 합친다.
"""

import argparse
import asyncio
import hashlib
import re
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from agent.rag.case_schemas import CaseSearchRequest
from agent.rag.embedding.factory import TextEmbedderFactory
from agent.rag.ports import CaseRetriever, TextEmbedder
from agent.rag.schemas import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    EmbeddingRequest,
    LookupStatus,
    RagModel,
)
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)
from tests.agent.nia_case_semantic_golden_schemas import (
    NiaCaseSemanticCalibrationLoader,
    NiaCaseSemanticQueryReference,
    NiaCaseSemanticReferenceSet,
)


class CandidatePoolSource(StrEnum):
    DENSE_TOP_100 = "dense_top_100"
    QUERY_LEXICAL_TOP_50 = "query_lexical_top_50"
    CLINICAL_LEXICAL_TOP_50 = "clinical_lexical_top_50"
    METADATA_LEXICAL_TOP_30 = "metadata_lexical_top_30"
    METADATA_EXHAUSTIVE = "metadata_exhaustive"
    DENSE_HARD_NEGATIVE = "dense_hard_negative"
    EXACT_QUESTION_DUPLICATE = "exact_question_duplicate"


class NiaCorpusSource(RagModel):
    model_config = ConfigDict(extra="ignore")

    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class NiaCorpusMetadata(RagModel):
    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(min_length=1)
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)


class NiaCorpusDocumentPayload(RagModel):
    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(min_length=1)
    page_content: str = Field(min_length=1)
    text_version: str = Field(min_length=1)
    metadata: NiaCorpusMetadata

    @model_validator(mode="after")
    def validate_case_id(self) -> Self:
        if self.case_id != self.metadata.case_id:
            raise ValueError("NIA Case 본문과 metadata의 case_id가 다릅니다.")
        return self


class NiaCorpusEnvelope(RagModel):
    model_config = ConfigDict(extra="ignore")

    dataset_split: str = Field(min_length=1)
    source: NiaCorpusSource
    document: NiaCorpusDocumentPayload


class NiaSemanticCorpusCase(RagModel):
    case_id: str = Field(min_length=1)
    dataset_split: str = Field(min_length=1)
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    normalized_question: str = Field(min_length=1)


class NiaSemanticCorpus(RagModel):
    cases: list[NiaSemanticCorpusCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("NIA Case 코퍼스에 중복 case_id가 있습니다.")
        return self


class CandidatePoolAccumulator(RagModel):
    case: NiaSemanticCorpusCase
    sources: list[CandidatePoolSource] = Field(default_factory=list)
    dense_rank: int | None = Field(default=None, ge=1)
    dense_similarity: FiniteFloat | None = None
    query_lexical_score: int = Field(default=0, ge=0)
    clinical_lexical_score: int = Field(default=0, ge=0)

    def add_source(self, source: CandidatePoolSource) -> None:
        if source not in self.sources:
            self.sources.append(source)


class InternalCandidatePoolEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    case_id: str = Field(min_length=1)
    dataset_split: str = Field(min_length=1)
    target_concern: str = Field(min_length=1)
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    skin_concerns: list[str] = Field(default_factory=list)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sources: list[CandidatePoolSource] = Field(min_length=1)
    dense_rank: int | None = Field(default=None, ge=1)
    dense_similarity: FiniteFloat | None = None
    query_lexical_score: int = Field(ge=0)
    clinical_lexical_score: int = Field(ge=0)


class BlindCandidatePoolEntry(RagModel):
    review_key: str = Field(pattern=r"^[0-9a-f]{16}$")
    gender: str = Field(min_length=1)
    age: int = Field(ge=10, le=39)
    skin_type: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class InternalCandidatePoolItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    candidate_count: int = Field(ge=1)
    candidates: list[InternalCandidatePoolEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_count(self) -> Self:
        if self.candidate_count != len(self.candidates):
            raise ValueError("내부 후보 수와 candidates 길이가 다릅니다.")
        return self


class BlindCandidatePoolItem(RagModel):
    evaluation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    candidate_count: int = Field(ge=1)
    candidates: list[BlindCandidatePoolEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_count(self) -> Self:
        if self.candidate_count != len(self.candidates):
            raise ValueError("블라인드 후보 수와 candidates 길이가 다릅니다.")
        return self


class CandidatePoolBuildResult(RagModel):
    internal_items: list[InternalCandidatePoolItem] = Field(min_length=1)
    blind_items: list[BlindCandidatePoolItem] = Field(min_length=1)


class CandidatePoolArguments(RagModel):
    calibration_path: Path
    corpus_path: Path
    internal_output_path: Path
    blind_output_path: Path


class CandidatePoolArgumentParser:
    DEFAULT_CALIBRATION_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_v1.jsonl"
    )
    DEFAULT_CORPUS_PATH: ClassVar[Path] = Path(
        "data/processed/nia_case_documents_10s_30s.jsonl"
    )
    DEFAULT_INTERNAL_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_pool_v1.jsonl"
    )
    DEFAULT_BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_eval_data/nia_case_semantic_calibration_blind_v1.jsonl"
    )

    def parse(self) -> CandidatePoolArguments:
        parser = argparse.ArgumentParser(
            description="전체 NIA Case에서 calibration 관련도 판정 후보 풀을 만듭니다."
        )
        parser.add_argument(
            "--calibration",
            type=Path,
            default=self.DEFAULT_CALIBRATION_PATH,
        )
        parser.add_argument("--corpus", type=Path, default=self.DEFAULT_CORPUS_PATH)
        parser.add_argument(
            "--internal-output",
            type=Path,
            default=self.DEFAULT_INTERNAL_OUTPUT_PATH,
        )
        parser.add_argument(
            "--blind-output",
            type=Path,
            default=self.DEFAULT_BLIND_OUTPUT_PATH,
        )
        parsed = parser.parse_args()
        return CandidatePoolArguments(
            calibration_path=parsed.calibration,
            corpus_path=parsed.corpus,
            internal_output_path=parsed.internal_output,
            blind_output_path=parsed.blind_output,
        )


class NiaPageContentParser:
    _QUESTION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\[질문\]\s*(.*?)(?=\n\s*\[답변\])",
        re.DOTALL,
    )
    _ANSWER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\[답변\]\s*(.*?)(?=\n\s*\[추론\]|\Z)",
        re.DOTALL,
    )

    def question(self, page_content: str) -> str:
        match = self._QUESTION_PATTERN.search(page_content)
        if match is None or not match.group(1).strip():
            raise ValueError("NIA Case page_content에서 질문을 찾지 못했습니다.")
        return match.group(1).strip()

    def answer(self, page_content: str) -> str:
        match = self._ANSWER_PATTERN.search(page_content)
        if match is None or not match.group(1).strip():
            raise ValueError("NIA Case page_content에서 답변을 찾지 못했습니다.")
        return match.group(1).strip()


class NiaSemanticCorpusLoader:
    EXPECTED_CASE_COUNT: ClassVar[int] = 3_581

    def __init__(self, parser: NiaPageContentParser | None = None) -> None:
        self._parser = parser or NiaPageContentParser()

    def load(self, path: Path) -> NiaSemanticCorpus:
        cases: list[NiaSemanticCorpusCase] = []
        try:
            with path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        envelope = NiaCorpusEnvelope.model_validate_json(line)
                        payload = envelope.document
                        metadata = payload.metadata
                        question = self._parser.question(payload.page_content)
                        answer = self._parser.answer(payload.page_content)
                        cases.append(
                            NiaSemanticCorpusCase(
                                case_id=payload.case_id,
                                dataset_split=envelope.dataset_split,
                                target_concern=metadata.target_concern,
                                gender=metadata.gender,
                                age=metadata.age,
                                skin_type=metadata.skin_type,
                                skin_concerns=metadata.skin_concerns,
                                question=question,
                                answer=answer,
                                normalized_question=self._normalize(question),
                            )
                        )
                    except (ValueError, TypeError) as error:
                        raise RuntimeError(
                            "NIA Case 코퍼스를 읽는 중 잘못된 레코드를 발견했습니다: "
                            f"path={path}, line={line_number}, detail={error}"
                        ) from error
        except OSError as error:
            raise RuntimeError(f"NIA Case 코퍼스를 읽지 못했습니다: {path}") from error
        if len(cases) != self.EXPECTED_CASE_COUNT:
            raise RuntimeError(
                "NIA Case 코퍼스 수가 평가 기준과 다릅니다: "
                f"expected={self.EXPECTED_CASE_COUNT}, actual={len(cases)}"
            )
        return NiaSemanticCorpus(cases=cases)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()


class KoreanLexicalCandidateRanker:
    _TOKEN_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[0-9A-Za-z가-힣]+")
    _STOP_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "관리",
            "방법",
            "성분",
            "피부",
            "싶어요",
            "싶습니다",
            "어떤",
            "있어요",
            "입니다",
            "하면서",
            "위해",
            "같이",
        }
    )

    def query_score(self, query: str, case: NiaSemanticCorpusCase) -> int:
        tokens = set(self._tokens(query))
        question_tokens = set(self._tokens(case.question))
        return sum(
            2
            for token in tokens
            if any(self._tokens_match(token, question_token) for question_token in question_tokens)
        )

    def clinical_score(
        self,
        reference: NiaCaseSemanticQueryReference,
        case: NiaSemanticCorpusCase,
    ) -> int:
        normalized_answer = self._normalize(case.answer)
        matched_groups = 0
        matched_examples = 0
        for group in reference.acceptable_ingredient_groups:
            group_matches = [
                example
                for example in group.examples
                if self._normalize(example) in normalized_answer
            ]
            if group_matches:
                matched_groups += 1
                matched_examples += len(group_matches)
        return matched_groups * 3 + matched_examples

    def _tokens(self, text: str) -> list[str]:
        return [
            token
            for token in (match.group(0).casefold() for match in self._TOKEN_PATTERN.finditer(text))
            if len(token) >= 2 and token not in self._STOP_WORDS
        ]

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()

    def _tokens_match(self, left: str, right: str) -> bool:
        if left in right or right in left:
            return True
        common_prefix_length = 0
        for left_character, right_character in zip(left, right, strict=False):
            if left_character != right_character:
                break
            common_prefix_length += 1
        # 한국어 조사·활용형이 달라도 의미 어간 두 글자가 같으면 후보 발견 단계에서는 보존한다.
        return common_prefix_length >= 2


class NiaCaseSemanticCandidatePoolBuilder:
    TEXT_VERSION: ClassVar[str] = "nia_case_text/v1"
    DENSE_LIMIT: ClassVar[int] = 100
    QUERY_LEXICAL_LIMIT: ClassVar[int] = 50
    CLINICAL_LEXICAL_LIMIT: ClassVar[int] = 50
    METADATA_LEXICAL_LIMIT: ClassVar[int] = 30
    METADATA_EXHAUSTIVE_LIMIT: ClassVar[int] = 100
    HARD_NEGATIVE_DENSE_LIMIT: ClassVar[int] = 40

    def __init__(
        self,
        embedder: TextEmbedder,
        retriever: CaseRetriever,
        lexical_ranker: KoreanLexicalCandidateRanker | None = None,
    ) -> None:
        self._embedder = embedder
        self._retriever = retriever
        self._lexical_ranker = lexical_ranker or KoreanLexicalCandidateRanker()

    async def build(
        self,
        calibration: NiaCaseSemanticReferenceSet,
        corpus: NiaSemanticCorpus,
    ) -> CandidatePoolBuildResult:
        embedding = await self._embedder.embed(
            EmbeddingRequest(texts=[item.query for item in calibration.items])
        )
        if len(embedding.vectors) != len(calibration.items):
            raise RuntimeError(
                "calibration 질의와 임베딩 수가 다릅니다: "
                f"queries={len(calibration.items)}, vectors={len(embedding.vectors)}"
            )
        if any(len(vector.values) != BGE_M3_EMBEDDING_DIMENSIONS for vector in embedding.vectors):
            raise RuntimeError("calibration 질의에 1,024차원이 아닌 임베딩이 있습니다.")

        cases_by_id = {case.case_id: case for case in corpus.cases}
        duplicate_groups = self._duplicate_groups(corpus)
        internal_items: list[InternalCandidatePoolItem] = []
        blind_items: list[BlindCandidatePoolItem] = []
        for reference, vector in zip(calibration.items, embedding.vectors, strict=True):
            search = await self._retriever.search(
                CaseSearchRequest(
                    query=reference.query,
                    query_embedding=vector,
                    text_version=self.TEXT_VERSION,
                    embedding_model=embedding.model,
                    candidate_limit=self.DENSE_LIMIT,
                )
            )
            if search.status is not LookupStatus.SUCCESS:
                raise RuntimeError(
                    "calibration dense 후보 검색에 실패했습니다: "
                    f"evaluation_id={reference.evaluation_id}, status={search.status.value}, "
                    f"detail={search.error_message or '없음'}"
                )
            accumulators: dict[str, CandidatePoolAccumulator] = {}
            for rank, hit in enumerate(search.hits, start=1):
                case = cases_by_id.get(hit.case_id)
                if case is None:
                    raise RuntimeError(f"DB 검색 Case가 코퍼스에 없습니다: {hit.case_id}")
                accumulator = self._accumulator(accumulators, case)
                accumulator.add_source(CandidatePoolSource.DENSE_TOP_100)
                accumulator.dense_rank = rank
                accumulator.dense_similarity = hit.vector_similarity

            query_ranked = sorted(
                corpus.cases,
                key=lambda case: (
                    -self._lexical_ranker.query_score(reference.query, case),
                    case.case_id,
                ),
            )
            for case in query_ranked[: self.QUERY_LEXICAL_LIMIT]:
                score = self._lexical_ranker.query_score(reference.query, case)
                if score == 0:
                    continue
                accumulator = self._accumulator(accumulators, case)
                accumulator.add_source(CandidatePoolSource.QUERY_LEXICAL_TOP_50)
                accumulator.query_lexical_score = score

            clinical_ranked = sorted(
                corpus.cases,
                key=lambda case: (
                    -self._lexical_ranker.clinical_score(reference, case),
                    case.case_id,
                ),
            )
            for case in clinical_ranked[: self.CLINICAL_LEXICAL_LIMIT]:
                score = self._lexical_ranker.clinical_score(reference, case)
                if score == 0:
                    continue
                accumulator = self._accumulator(accumulators, case)
                accumulator.add_source(CandidatePoolSource.CLINICAL_LEXICAL_TOP_50)
                accumulator.clinical_lexical_score = score

            concern_values = {
                concern.value
                for concern in [*reference.primary_concerns, *reference.secondary_concerns]
            }
            metadata_cases = [
                case
                for case in corpus.cases
                if case.target_concern in concern_values
                or bool(set(case.skin_concerns) & concern_values)
            ]
            if len(metadata_cases) <= self.METADATA_EXHAUSTIVE_LIMIT:
                for case in metadata_cases:
                    self._accumulator(accumulators, case).add_source(
                        CandidatePoolSource.METADATA_EXHAUSTIVE
                    )
            else:
                metadata_ranked = sorted(
                    metadata_cases,
                    key=lambda case: (
                        -self._lexical_ranker.query_score(reference.query, case),
                        -self._lexical_ranker.clinical_score(reference, case),
                        case.case_id,
                    ),
                )
                for case in metadata_ranked[: self.METADATA_LEXICAL_LIMIT]:
                    self._accumulator(accumulators, case).add_source(
                        CandidatePoolSource.METADATA_LEXICAL_TOP_30
                    )

            for hit in search.hits[: self.HARD_NEGATIVE_DENSE_LIMIT]:
                case = cases_by_id[hit.case_id]
                if case.target_concern not in concern_values:
                    self._accumulator(accumulators, case).add_source(
                        CandidatePoolSource.DENSE_HARD_NEGATIVE
                    )

            self._expand_exact_duplicates(accumulators, duplicate_groups)
            internal = self._internal_item(reference, accumulators)
            internal_items.append(internal)
            blind_items.append(self._blind_item(internal))
        return CandidatePoolBuildResult(
            internal_items=internal_items,
            blind_items=blind_items,
        )

    def _accumulator(
        self,
        accumulators: dict[str, CandidatePoolAccumulator],
        case: NiaSemanticCorpusCase,
    ) -> CandidatePoolAccumulator:
        if case.case_id not in accumulators:
            accumulators[case.case_id] = CandidatePoolAccumulator(case=case)
        return accumulators[case.case_id]

    def _duplicate_groups(
        self,
        corpus: NiaSemanticCorpus,
    ) -> dict[str, list[NiaSemanticCorpusCase]]:
        groups: dict[str, list[NiaSemanticCorpusCase]] = {}
        for case in corpus.cases:
            groups.setdefault(case.normalized_question, []).append(case)
        return {key: cases for key, cases in groups.items() if len(cases) > 1}

    def _expand_exact_duplicates(
        self,
        accumulators: dict[str, CandidatePoolAccumulator],
        duplicate_groups: dict[str, list[NiaSemanticCorpusCase]],
    ) -> None:
        selected_questions = {
            accumulator.case.normalized_question for accumulator in accumulators.values()
        }
        for normalized_question in selected_questions:
            for case in duplicate_groups.get(normalized_question, []):
                self._accumulator(accumulators, case).add_source(
                    CandidatePoolSource.EXACT_QUESTION_DUPLICATE
                )

    def _internal_item(
        self,
        reference: NiaCaseSemanticQueryReference,
        accumulators: dict[str, CandidatePoolAccumulator],
    ) -> InternalCandidatePoolItem:
        entries = [
            InternalCandidatePoolEntry(
                review_key=self._review_key(reference.evaluation_id, accumulator.case.case_id),
                case_id=accumulator.case.case_id,
                dataset_split=accumulator.case.dataset_split,
                target_concern=accumulator.case.target_concern,
                gender=accumulator.case.gender,
                age=accumulator.case.age,
                skin_type=accumulator.case.skin_type,
                skin_concerns=accumulator.case.skin_concerns,
                question=accumulator.case.question,
                answer=accumulator.case.answer,
                sources=sorted(accumulator.sources, key=lambda source: source.value),
                dense_rank=accumulator.dense_rank,
                dense_similarity=accumulator.dense_similarity,
                query_lexical_score=accumulator.query_lexical_score,
                clinical_lexical_score=accumulator.clinical_lexical_score,
            )
            for accumulator in accumulators.values()
        ]
        entries.sort(key=lambda entry: entry.review_key)
        return InternalCandidatePoolItem(
            evaluation_id=reference.evaluation_id,
            query=reference.query,
            candidate_count=len(entries),
            candidates=entries,
        )

    def _blind_item(self, internal: InternalCandidatePoolItem) -> BlindCandidatePoolItem:
        return BlindCandidatePoolItem(
            evaluation_id=internal.evaluation_id,
            query=internal.query,
            candidate_count=internal.candidate_count,
            candidates=[
                BlindCandidatePoolEntry(
                    review_key=candidate.review_key,
                    gender=candidate.gender,
                    age=candidate.age,
                    skin_type=candidate.skin_type,
                    question=candidate.question,
                    answer=candidate.answer,
                )
                for candidate in internal.candidates
            ],
        )

    def _review_key(self, evaluation_id: str, case_id: str) -> str:
        payload = f"{evaluation_id}\0{case_id}".encode()
        return hashlib.sha256(payload).hexdigest()[:16]


class CandidatePoolJsonlWriter:
    def write(self, path: Path, items: list[RagModel]) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="\n") as destination:
                for item in items:
                    destination.write(item.model_dump_json())
                    destination.write("\n")
        except OSError as error:
            raise RuntimeError(f"NIA Case 후보 풀을 쓰지 못했습니다: {path}") from error


class CandidatePoolArtifactLoader:
    def load_internal(self, path: Path) -> list[InternalCandidatePoolItem]:
        items: list[InternalCandidatePoolItem] = []
        try:
            with path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        items.append(InternalCandidatePoolItem.model_validate_json(line))
                    except ValueError as error:
                        raise RuntimeError(
                            "내부 후보 풀 형식이 잘못되었습니다: "
                            f"path={path}, line={line_number}, detail={error}"
                        ) from error
        except OSError as error:
            raise RuntimeError(f"내부 후보 풀을 읽지 못했습니다: {path}") from error
        return items

    def load_blind(self, path: Path) -> list[BlindCandidatePoolItem]:
        items: list[BlindCandidatePoolItem] = []
        try:
            with path.open("r", encoding="utf-8") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        items.append(BlindCandidatePoolItem.model_validate_json(line))
                    except ValueError as error:
                        raise RuntimeError(
                            "블라인드 후보 풀 형식이 잘못되었습니다: "
                            f"path={path}, line={line_number}, detail={error}"
                        ) from error
        except OSError as error:
            raise RuntimeError(f"블라인드 후보 풀을 읽지 못했습니다: {path}") from error
        return items


class NiaCaseSemanticCandidatePoolCli:
    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        arguments = CandidatePoolArgumentParser().parse()
        calibration = NiaCaseSemanticCalibrationLoader().load(arguments.calibration_path)
        corpus = NiaSemanticCorpusLoader().load(arguments.corpus_path)
        database: Database = ConfiguredDatabaseFactory().create()
        try:
            config = TwoLayerAgentModelConfigFactory()
            builder = NiaCaseSemanticCandidatePoolBuilder(
                embedder=TextEmbedderFactory().create(config.create_embedding()),
                retriever=BackendNiaCaseRetriever(database.session_factory),
            )
            result = await builder.build(calibration, corpus)
            writer = CandidatePoolJsonlWriter()
            writer.write(arguments.internal_output_path, list(result.internal_items))
            writer.write(arguments.blind_output_path, list(result.blind_items))
            for internal in result.internal_items:
                print(
                    f"{internal.evaluation_id}: candidates={internal.candidate_count}, "
                    f"dense_top40={sum(candidate.dense_rank is not None and candidate.dense_rank <= 40 for candidate in internal.candidates)}"
                )
        finally:
            await database.dispose()


if __name__ == "__main__":
    asyncio.run(NiaCaseSemanticCandidatePoolCli.main())
