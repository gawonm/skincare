"""NIA AI Hub "스킨케어 성분-효능 추천 데이터"(dataset 71886) Q-CoT-A jsonl을 `RagDocument`로 바꾼다.

원본은 `Training|Validation/02.라벨링데이터/*.zip` 안에 `{survey_id}/{survey_id}.jsonl`
형태로, 파일 하나에 레코드 하나가 들어 있다. 이 데이터는 실제 IRB 승인 피험자의 설문·이미지를
바탕으로 AI가 생성하고 전문가 패널이 검증한 Q&A/CoT다 - 사람이 직접 타이핑한 실사용자
채팅 로그가 아니다. `docs/data.md`가 이 성격을 그대로 기록해야 한다.

레코드 하나를 통째로 임베딩하지 않고 의미단위(질문/답변/CoT 각 단계)별로 쪼갠다 -
무관한 추론 텍스트가 한 벡터에 섞이면 검색 정밀도가 떨어지기 때문이다.
"""

import json
import zipfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.rag.schemas import RagDocument, RagDocumentField, RagDocumentMetadata
from models.rag_chunk import RagChunkField, RagConfidenceTier, RagSourceTable

_JSONL_SUFFIX = ".jsonl"


class _NiaChainOfThoughtStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: int
    title: str
    content: str


class _NiaInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    target_concern: str
    question: str
    answer: str
    evidence_sources: tuple[str, ...] = Field(default=())


class NiaQaRecord(BaseModel):
    """NIA jsonl 레코드 한 건의 파싱 결과."""

    model_config = ConfigDict(frozen=True)

    info: _NiaInfo
    chain_of_thought: tuple[_NiaChainOfThoughtStep, ...]


class NiaQaLoader:
    """NIA Q-CoT-A jsonl(zip 압축 상태)을 소스 무관 공통 문서 형태로 변환한다."""

    def load(self, zip_paths: list[Path]) -> list[RagDocument]:
        documents: list[RagDocument] = []
        for zip_path in zip_paths:
            documents.extend(self._load_zip(zip_path))
        return documents

    def _load_zip(self, zip_path: Path) -> list[RagDocument]:
        documents: list[RagDocument] = []
        with zipfile.ZipFile(zip_path) as archive:
            for entry in archive.infolist():
                if not entry.filename.endswith(_JSONL_SUFFIX):
                    continue
                with archive.open(entry) as jsonl_file:
                    for line in jsonl_file:
                        if not line.strip():
                            continue
                        record = NiaQaRecord.model_validate(json.loads(line))
                        documents.append(self._to_document(record))
        return documents

    def _to_document(self, record: NiaQaRecord) -> RagDocument:
        fields = [
            RagDocumentField(chunk_field=RagChunkField.NIA_QUESTION, content=record.info.question),
            RagDocumentField(chunk_field=RagChunkField.NIA_ANSWER, content=record.info.answer),
        ]
        fields.extend(
            RagDocumentField(
                chunk_field=RagChunkField.NIA_COT_STEP,
                chunk_index=step.step,
                content=step.content,
            )
            for step in record.chain_of_thought
        )

        return RagDocument(
            source_table=RagSourceTable.NIA_QA,
            # NIA Q&A는 상황(페르소나+피부고민) 상담 사례라 한 성분에 매이지 않는다.
            ingredient_id=None,
            nia_record_id=record.info.id,
            fields=tuple(fields),
            metadata=RagDocumentMetadata(
                confidence_tier=RagConfidenceTier.AI_GENERATED_REVIEWED,
                source_title=f"NIA 스킨케어 상담 사례 - {record.info.target_concern} ({record.info.id})",
                source_url=None,
                citation_refs=record.info.evidence_sources,
                cites_cir=False,
            ),
        )
