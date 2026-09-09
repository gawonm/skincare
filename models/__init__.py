"""SQLAlchemy 테이블 정의.

`backend`와 `agent`가 모두 테이블을 읽으므로 어느 한쪽에 넣지 않고 루트에 둔다.

새 모델 파일을 추가하면 `config.yaml`의 `database.model_modules`에도 모듈 경로를
등록해야 Alembic autogenerate 에 잡힌다.

의존: `core` 만 import 한다.
"""

from models.evidence import Evidence, EvidenceRegulateType, EvidenceSourceType, EvidenceTopic
from models.ingredient import IngredientMaster
from models.ingredient_knowledge import IngredientKnowledgeFact, RegulatoryConfidence
from models.product_ingredient import (
    IngredientMatchAcceptance,
    ProductIngredient,
    ProductIngredientSectionLinkStatus,
    ProductIngredientSnapshot,
    ProductIngredientTokenParseStatus,
)
from models.rag_chunk import (
    EMBEDDING_DIMENSION,
    RagChunk,
    RagChunkField,
    RagConfidenceTier,
    RagSourceTable,
)

__all__ = [
    "EMBEDDING_DIMENSION",
    "Evidence",
    "EvidenceRegulateType",
    "EvidenceSourceType",
    "EvidenceTopic",
    "IngredientKnowledgeFact",
    "IngredientMaster",
    "IngredientMatchAcceptance",
    "ProductIngredient",
    "ProductIngredientSectionLinkStatus",
    "ProductIngredientSnapshot",
    "ProductIngredientTokenParseStatus",
    "RagChunk",
    "RagChunkField",
    "RagConfidenceTier",
    "RagSourceTable",
    "RegulatoryConfidence",
]
