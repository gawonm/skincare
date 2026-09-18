"""MFDS Evidence 전용 BGE-M3 임베딩 어댑터.

`agent/rag/embedding/local_embedder.py`가 같은 모델(BAAI/bge-m3)을 이미 감싸고 있지만,
이번 작업 지시(Agent/Backend 연결 작업 금지, data 파트 범위만)에 따라 `data/` 코드가
`agent/`를 import하지 않는다 - import하면 data -> agent 의존을 새로 만들게 되어
CLAUDE.md 규칙 11(허용된 import 방향에 없음)과 이번 작업 지시 둘 다 위반한다. 대신 같은
`sentence-transformers` 라이브러리(이미 `pyproject.toml` 의존성)로 같은 설정
(`normalize_embeddings=True`, `trust_remote_code=False`)을 독립적으로 재구현한다 -
Evidence 임베딩은 애초에 `rag_chunk`/Claim과 저장 테이블·검색 경로가 분리된 별개
컨트랙트다(`EVIDENCE_STORAGE_ERD.md` 6절).

배치 크기 등은 `settings.agent.embedding`의 기존 local 설정값(batch_size=16 등)을 그대로
읽어 쓴다 - 새 전역 설정을 만들지 않는다(지시사항). `provider` 토글은 보지 않는다 -
Evidence는 provider와 무관하게 항상 BGE-M3(local)로 고정이기 때문이다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from pydantic import BaseModel, ConfigDict

from core.config import EmbeddingSettings, LocalEmbeddingModel

EVIDENCE_EMBEDDING_DIMENSION = 1024


class MfdsEvidenceEmbeddingResult(BaseModel):
    """텍스트 목록 하나에 대한 임베딩 결과."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    model: str
    vectors: list[list[float]]


class MfdsEvidenceEmbedder:
    """BAAI/bge-m3를 프로세스 안에서 실행하는 동기 모델을 비동기로 감싼다."""

    def __init__(self, settings: EmbeddingSettings) -> None:
        if settings.model is not LocalEmbeddingModel.BGE_M3:
            raise ValueError(
                f"Evidence 임베딩은 BAAI/bge-m3 고정인데 설정값이 {settings.model!r}입니다."
            )
        self._settings = settings
        self._model: SentenceTransformer | None = None
        # PyTorch 추론을 직렬화해 같은 모델 인스턴스가 동시에 여러 스레드에서 호출되지 않게 한다.
        self._inference_lock = asyncio.Lock()

    async def embed_texts(self, texts: Sequence[str]) -> MfdsEvidenceEmbeddingResult:
        if not texts:
            return MfdsEvidenceEmbeddingResult(model=self._settings.model.value, vectors=[])
        try:
            async with self._inference_lock:
                return await asyncio.to_thread(self._embed_blocking, texts)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"BGE-M3 임베딩 실행에 실패했습니다({self._settings.model.value}): {exc}"
            ) from exc

    def _embed_blocking(self, texts: Sequence[str]) -> MfdsEvidenceEmbeddingResult:
        model = self._load_model()
        raw_vectors = model.encode(
            list(texts),
            batch_size=self._settings.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vectors = cast(Sequence[Sequence[float]], raw_vectors)
        if len(vectors) != len(texts):
            raise ValueError("임베딩 결과 수가 요청한 텍스트 수와 다릅니다.")
        for vector in vectors:
            if len(vector) != EVIDENCE_EMBEDDING_DIMENSION:
                raise ValueError(
                    f"임베딩 차원이 {len(vector)}인데 evidence_chunk는 "
                    f"{EVIDENCE_EMBEDDING_DIMENSION}차원을 요구합니다."
                )
        return MfdsEvidenceEmbeddingResult(
            model=self._settings.model.value,
            vectors=[[float(value) for value in vector] for vector in vectors],
        )

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device = self._settings.device.value if self._settings.device is not None else None
            self._model = SentenceTransformer(
                self._settings.model.value,
                device=device,
                cache_folder=self._settings.cache_folder,
                trust_remote_code=False,
                local_files_only=self._settings.local_files_only,
            )
        return self._model
