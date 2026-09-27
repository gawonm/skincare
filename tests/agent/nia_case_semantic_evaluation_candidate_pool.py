"""동결 평가 40질의의 dense·어휘·메타데이터 후보 풀을 생성한다."""

import asyncio
from pathlib import Path
from typing import ClassVar

from agent.rag.embedding.factory import TextEmbedderFactory
from backend.services.two_layer_rag_adapters import BackendNiaCaseRetriever
from core.database import Database
from tests.agent.interactive_two_layer_rag_cli import (
    ConfiguredDatabaseFactory,
    TwoLayerAgentModelConfigFactory,
    Utf8ConsoleConfigurator,
)
from tests.agent.nia_case_semantic_candidate_pool import (
    CandidatePoolJsonlWriter,
    NiaCaseSemanticCandidatePoolBuilder,
    NiaSemanticCorpusLoader,
)
from tests.agent.nia_case_semantic_golden_schemas import (
    NiaCaseSemanticReferenceLoader,
)


class NiaCaseSemanticEvaluationCandidatePoolCli:
    REFERENCE_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_references_v1.jsonl"
    )
    CORPUS_PATH: ClassVar[Path] = Path(
        "data/processed/nia_case_documents_10s_30s.jsonl"
    )
    INTERNAL_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_pool_v1.jsonl"
    )
    BLIND_OUTPUT_PATH: ClassVar[Path] = Path(
        "tests/agent/nia_case_semantic_evaluation_blind_v1.jsonl"
    )

    @classmethod
    async def main(cls) -> None:
        Utf8ConsoleConfigurator().configure()
        references = NiaCaseSemanticReferenceLoader().load(cls.REFERENCE_PATH)
        corpus = NiaSemanticCorpusLoader().load(cls.CORPUS_PATH)
        database: Database = ConfiguredDatabaseFactory().create()
        try:
            model_config = TwoLayerAgentModelConfigFactory()
            builder = NiaCaseSemanticCandidatePoolBuilder(
                embedder=TextEmbedderFactory().create(
                    model_config.create_embedding()
                ),
                retriever=BackendNiaCaseRetriever(database.session_factory),
            )
            result = await builder.build(references, corpus)
            writer = CandidatePoolJsonlWriter()
            writer.write(cls.INTERNAL_OUTPUT_PATH, list(result.internal_items))
            writer.write(cls.BLIND_OUTPUT_PATH, list(result.blind_items))
            print(
                "evaluation candidate pool: "
                f"queries={len(result.internal_items)}, "
                f"candidates={sum(item.candidate_count for item in result.internal_items)}"
            )
        finally:
            await database.dispose()


if __name__ == "__main__":
    asyncio.run(NiaCaseSemanticEvaluationCandidatePoolCli.main())
