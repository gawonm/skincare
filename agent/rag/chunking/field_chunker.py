"""새 RAG의 필드 단위 청킹을 저장소 독립 DTO에 적용한다."""

from uuid import NAMESPACE_URL, uuid5

from agent.rag.schemas import RagChunkDraft, RagDocument


class FieldChunker:
    """근거 문서를 필드 단위로 분할하여 청크 초안을 생성하는 청커.

    글자 수 기준 기계적 분할은 효능과 주의사항의 문맥을 끊어버릴 위험이 있으므로,
    지식 데이터의 구조화된 필드(RagDocumentField)를 의미 단위의 청크로 보존한다.
    """

    def chunk(self, document: RagDocument) -> list[RagChunkDraft]:
        field_ids = [field.field_id for field in document.fields]
        # 동일 문서 내에 중복된 field_id가 있으면 아래의 청크 ID 충돌로 DB 적재 시 덮어쓰기가 발생하므로 검증한다
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("같은 문서의 field_id가 중복되어 청크를 구분할 수 없습니다.")

        return [
            RagChunkDraft(
                # 데이터 재적재 시에도 동일한 청크 ID를 생성해 중복 적재를 방지하고 멱등성을 보장하기 위해 uuid5를 사용한다
                chunk_id=str(
                    uuid5(NAMESPACE_URL, document.evidence.evidence_id + ":" + field.field_id)
                ),
                # Backend 저장 어댑터가 Agent DTO를 DB의 의미 필드와 안전하게 연결할 수 있어야 한다.
                field_id=field.field_id,
                content=field.content,
                # 조건을 별도 청크로 분리하면 효능 검색 시 제한 문구가 누락되므로, 모든 청크에 근거 메타데이터를 복제해 보존한다
                evidence=document.evidence.model_copy(deep=True),
                # 검색기(HybridRetriever)가 추가 DB 조회 없이 질문 의도와 신뢰도 수준으로 청크를 직접 필터링할 수 있게 한다
                intents=field.intents,
                confidence_tier=document.confidence_tier,
            )
            for field in document.fields
        ]
