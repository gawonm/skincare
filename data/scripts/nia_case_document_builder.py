"""`NiaOriginalRecord` 한 건을 검색용 `NiaCaseDocument` 한 건으로 만든다.

원문은 요약·재작성·strip 하지 않는다(LLM 도 쓰지 않는다). 하는 일은 섹션 라벨과 줄바꿈을 붙이는
표현 작업뿐이다. 사례 하나를 question/answer/CoT 단계별 조각으로 쪼개지 않는 이유는, 검색 결과의
단위가 "유사 사례 Top-3" 이라 사례 전체가 한 문서여야 하기 때문이다.

embedding, 벡터 저장소 적재, 검색, 성분 추출은 이 모듈의 책임이 아니다.
"""

from data.scripts.nia_case_document_schemas import NiaCaseDocument, NiaCaseMetadata
from data.scripts.nia_original_schemas import NiaOriginalRecord

TEXT_VERSION = "nia_case_text/v1"

_QUESTION_LABEL = "[질문]"
_ANSWER_LABEL = "[답변]"
_REASONING_LABEL = "[추론]"
_SECTION_SEPARATOR = "\n\n"


class NiaCaseDocumentBuilder:
    def build(self, record: NiaOriginalRecord) -> NiaCaseDocument:
        page_content = self._build_page_content(record)
        return NiaCaseDocument(
            case_id=record.info.id,
            page_content=page_content,
            embedding_text=page_content,
            text_version=TEXT_VERSION,
            metadata=self._build_metadata(record),
        )

    def _build_page_content(self, record: NiaOriginalRecord) -> str:
        sections = [
            f"{_QUESTION_LABEL}\n{record.info.question}",
            f"{_ANSWER_LABEL}\n{record.info.answer}",
        ]
        # CoT 가 비어 있는 원본도 문서는 만들어야 하므로 빈 [추론] 라벨은 붙이지 않는다
        if record.chain_of_thought:
            # 번호는 원본 step 값을 쓴다. 순서는 원본 배열 순서 그대로다
            steps = _SECTION_SEPARATOR.join(
                f"{step.step}. {step.title}\n{step.content}" for step in record.chain_of_thought
            )
            sections.append(f"{_REASONING_LABEL}\n{steps}")
        return _SECTION_SEPARATOR.join(sections)

    def _build_metadata(self, record: NiaOriginalRecord) -> NiaCaseMetadata:
        return NiaCaseMetadata(
            case_id=record.info.id,
            source_survey_id=record.info.source_survey_id,
            image_filename=record.meta.image_filename,
            evidence_sources=list(record.info.evidence_sources),
            target_concern=record.info.target_concern,
            gender=record.meta.gender,
            age=record.meta.age,
            skin_type=record.meta.skin_type,
            skin_concerns=list(record.meta.skin_concerns),
            initial_skin_condition=record.meta.initial_skin_condition,
            external=list(record.external),
        )
