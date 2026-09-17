"""NIA Claim(검증 안 된 사용자 경험 기반 성분↔효능 언급) 원본 레코드 단위 provenance.

`docs/data/CLAIM_STORAGE_ERD.md` 2절 설계를 그대로 옮긴다. `Evidence(MFDS/CIR/PubMed)`와
분리된 Claim 전용 저장소다 - `ClaimHit != EvidenceRecord`
(`docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md` 8절).

`source_record_id`만으로 UNIQUE를 걸지 않는다 - 같은 NIA 레코드가 서로 다른 annotation run
(pilot/validation/production)에서 반복 라벨링되는 것이 정상 동작이고, 각 결과는 provenance·
regression 비교를 위해 전부 보존한다(2026-09-17 결정, `CLAUDE_SESSION_BOARD.md` 참고). 그래서
`UNIQUE(source_record_id, annotation_version)`로 여러 annotation_version이 공존할 수 있게
한다. 어느 annotation_version을 실제 retrieval에 쓸지는 이 테이블이 정하지 않는다 - 운영
설정/조회 호출에서 annotation_version을 명시적으로 골라 필터링한다(`is_active` 같은 상태
컬럼을 여기 두지 않는다).
"""

from enum import StrEnum

from sqlalchemy import Boolean, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


def _sql_enum(enum_cls: type, *, length: int) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
    )


class ClaimDatasetSplit(StrEnum):
    """`data.scripts.nia_labeling_schemas.NiaDatasetSplit`과 값만 맞춰 별도 선언한다 -
    `models/`는 `data/scripts/`를 import하지 않는다(import 방향 규칙, `models/evidence_chunk.py`
    등과 동일 관례). 값이 어긋나면 저장/조회 시점에 바로 드러난다."""

    TRAINING = "training"
    VALIDATION = "validation"


class ClaimDocument(EntityBase):
    """NIA 원본 레코드 한 건(= 하나의 annotation run에서 나온 `NiaLabelingDocument` 한 개).

    `data/scripts/nia_claim_document.py`의 FROZEN Pydantic `ClaimDocument`와 이름이 같지만
    다른 것이다 - 그쪽은 statement 단위(이 프로젝트의 `claim_chunk`에 대응), 이 ORM 클래스는
    레코드 단위다. 두 statement_type/dataset_split 등 Enum 값(`.value`)만 맞추고 별도
    선언한다(`models/product_ingredient.py`와 동일 관례 - `models/`가 `data/scripts/`의
    Pydantic 모델을 직접 import하지 않는다, import 방향 규칙).
    """

    __tablename__ = "claim_document"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id", "annotation_version", name="uq_claim_document_record_annotation"
        ),
        table_options(
            comment="NIA Claim 원본 레코드 단위 provenance. Evidence와 분리된 Claim 전용"
        ),
    )

    source_record_id: Mapped[str] = mapped_column(
        Text, nullable=False, comment="NiaLabelingDocument.source.record_id"
    )
    annotation_version: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="라벨링 실행 식별자(pilot/validation/production 구분). source_record_id와 묶어야 유일",
    )
    schema_version: Mapped[str] = mapped_column(
        Text, nullable=False, comment="ClaimDocument(Pydantic) schema_version"
    )
    dataset_split: Mapped[ClaimDatasetSplit] = mapped_column(
        _sql_enum(ClaimDatasetSplit, length=20), nullable=False, comment="training/validation"
    )
    skin_concerns_raw: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        comment="NiaLabelingDocument.case_context.skin_concerns_raw",
    )
    production_ready: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="사람 최종 검수 완료 여부(NiaLabelingDocument.production_ready). runtime 필수 필터로 강제하지 않는다",
    )
