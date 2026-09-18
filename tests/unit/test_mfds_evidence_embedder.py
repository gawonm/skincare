"""`MfdsEvidenceEmbedder` 단위 테스트. `SentenceTransformer`를 mock으로 대체해 모델
다운로드 없이 wrapper의 계약(차원 검증, 배치 설정 전달, 에러 래핑)만 검증한다.

실제 BGE-M3 가중치로 진짜 임베딩이 나오는지는 별도 수동 smoke가 담당한다
(`MFDS_EVIDENCE_EMBEDDING_RESULT` 보고서의 Smoke 절 참고) - 매 테스트 실행마다
~2GB 모델을 내려받게 만들지 않는다.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from core.config import EmbeddingSettings
from core.config import LocalEmbeddingModel as _LocalEmbeddingModel
from data.scripts.mfds_evidence_embedder import (
    EVIDENCE_EMBEDDING_DIMENSION,
    MfdsEvidenceEmbedder,
)


def _settings(**overrides) -> EmbeddingSettings:
    overrides.setdefault("batch_size", 4)
    return EmbeddingSettings(model=_LocalEmbeddingModel.BGE_M3, **overrides)


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_empty_input_short_circuits_without_loading_model(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings())
        result = await embedder.embed_texts([])
        assert result.vectors == []

    @pytest.mark.asyncio
    async def test_calls_encode_with_normalize_and_configured_batch_size(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings(batch_size=7))
        fake_model = MagicMock()
        fake_model.encode.return_value = np.zeros((2, EVIDENCE_EMBEDDING_DIMENSION))
        embedder._model = fake_model  # 모델 로딩 자체는 별도 관심사라 주입으로 건너뛴다.

        await embedder.embed_texts(["a", "b"])

        fake_model.encode.assert_called_once()
        _, kwargs = fake_model.encode.call_args
        assert kwargs["batch_size"] == 7
        assert kwargs["normalize_embeddings"] is True
        assert kwargs["convert_to_numpy"] is True

    @pytest.mark.asyncio
    async def test_result_has_evidence_chunk_dimension(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings())
        fake_model = MagicMock()
        fake_model.encode.return_value = np.zeros((3, EVIDENCE_EMBEDDING_DIMENSION))
        embedder._model = fake_model

        result = await embedder.embed_texts(["a", "b", "c"])

        assert len(result.vectors) == 3
        assert all(len(vector) == EVIDENCE_EMBEDDING_DIMENSION for vector in result.vectors)
        assert result.model == "BAAI/bge-m3"

    @pytest.mark.asyncio
    async def test_wrong_dimension_raises_clear_error(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings())
        fake_model = MagicMock()
        fake_model.encode.return_value = np.zeros((1, 768))  # evidence_chunk 계약 위반 차원
        embedder._model = fake_model

        with pytest.raises(RuntimeError, match="1024"):
            await embedder.embed_texts(["a"])

    @pytest.mark.asyncio
    async def test_mismatched_vector_count_raises_clear_error(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings())
        fake_model = MagicMock()
        fake_model.encode.return_value = np.zeros((1, EVIDENCE_EMBEDDING_DIMENSION))
        embedder._model = fake_model

        with pytest.raises(RuntimeError, match="다릅니다"):
            await embedder.embed_texts(["a", "b"])

    @pytest.mark.asyncio
    async def test_model_runtime_error_is_wrapped_not_swallowed(self) -> None:
        embedder = MfdsEvidenceEmbedder(_settings())
        fake_model = MagicMock()
        fake_model.encode.side_effect = RuntimeError("CUDA out of memory")
        embedder._model = fake_model

        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            await embedder.embed_texts(["a"])


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
