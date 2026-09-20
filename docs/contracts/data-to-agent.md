# data → agent: RAG 근거 데이터 전달

data 파트가 수집·정제한 성분 근거(MFDS 고시, Knowledgedata, NIA Q&A)를 agent 파트의 RAG
파이프라인(`agent/rag/loaders/`)이 읽어 쓰는 지점을 정리한다. 초안은 값을 넘기는 data 파트가
쓴다(CLAUDE.md 규칙 16). **agent/, agent/rag/의 구현 자체는 data 파트가 만들지 않는다** —
이 문서는 어디까지나 경계에서 주고받는 타입·경로만 다룬다.

## 0. 먼저 정리해야 할 충돌

`data/manual_review/nia_labeling_schemas.py`와 `agent/rag/nia_labeling_schemas.py`가 **내용이
완전히 동일한 채로 두 곳에 존재**한다(diff 결과 줄바꿈 문자만 다름, 로직 차이 없음).
`docs/agent/README.md`는 이 파일을 agent 파트가 이번 세션에 만든 것으로 기록하고 있다.

- 이 문서는 이 파일의 소유권을 정하지 않는다. `RAG-담당자-인수인계.md`가 지적한 "데이터 파트가
  agent 산출물을 임의로 만들었을 수 있다"는 문제와 정확히 같은 사례이므로, **에이전트
  담당자가 확인 후 하나만 남기고 나머지를 삭제**해야 한다(규칙 15). data 파트가 임의로 어느
  쪽을 지우지 않는다.

## 1. 현재 이미 동작 중인 경계 (참고용 — 이 문서가 새로 만드는 계약 아님)

`agent/rag/loaders/`의 `EvidenceLoader`, `KnowledgeFactLoader`는 data 파트가
적재한 DB 테이블(`models/evidence.py`의 `Evidence`, `models/ingredient_knowledge.py`의
`IngredientKnowledgeFact`)을 세션으로 직접 조회해 `RagDocument`로 변환한다. CSV나 함수 호출이
아니라 **DB 테이블 자체가 현재의 data → agent 인터페이스**다. 이 방식은 이미 구현·검증
(`docs/data/rag_pipeline_handoff.md` 4.1절, 65,196청크 적재 확인)까지 끝난 상태라 이 문서에서
다시 정하지 않는다.

| 테이블 | 채우는 스크립트 | 소유 |
| --- | --- | --- |
| `evidence` | `data/scripts/import_mfds_restricted_ingredients.py` | data (모델 정의: `models/evidence.py`) |
| `ingredient_knowledge_fact` | `data/scripts/import_knowledgedata.py` | data (모델 정의: `models/ingredient_knowledge.py`) |
| NIA Q&A (AI Hub 배포 원본 Q-CoT-A, ZIP/JSONL, DB 테이블 아님) | `data/scripts/nia_original_loader.py`의 `NiaOriginalLoader` → `data/scripts/nia_case_document_builder.py`의 `NiaCaseDocumentBuilder` | 원본 읽기(`NiaOriginalRecord`)와 검색용 사례 Document(`NiaCaseDocument`) 생성까지 **data 소유**(팀 합의: Data/DB 먼저 구현, 이후 Backend/Agent가 맞춤). 아래 "NIA 사례 Document 계약" 참고. 기존 `NiaQaLoader`는 이 방향의 기준이 아니다 |

### NIA 사례 Document 계약 (v1)

`NiaOriginalRecord` 1건 → `NiaCaseDocument` 1건. 사례를 question/answer/CoT 단계별 조각으로
쪼개지 않는다(검색 결과 단위가 "유사 사례 Top-3" 이므로).

연령 범위: 팀 corpus는 `meta.age` 10~39세다. `NiaOriginalLoader`는 전체 원본을 읽고, 그 다음 단계인
`NiaOriginalAgeFilter`(`data/scripts/nia_original_age_filter.py`)가 `10 <= age <= 39`만 통과시킨 뒤
`NiaCaseDocumentBuilder`로 넘긴다. 필터는 loader 안에 넣지 않는다.

- `page_content` = 질문 + 답변 + CoT 전체. 형식은 `[질문]` / `[답변]` / `[추론]` 라벨과
  `{step}. {title}` 줄바꿈뿐이며, 원문은 요약·재작성·strip 하지 않는다. `initial_skin_condition`,
  `external` 은 넣지 않는다.
- `embedding_text` = `page_content` (v1). `text_version` 으로 형식 버전을 기록한다.
- `metadata` = 검색 filter 후보(`target_concern`, `gender`, `age`, `skin_type`, `skin_concerns`),
  출처(`case_id`, `source_survey_id`, `image_filename`, `evidence_sources`), 문맥
  (`initial_skin_condition`, `external`). 저장소와 무관한 논리 구조이며 list/객체를 펴는 일(JSON 문자열,
  boolean 키 등)은 벡터 저장소 어댑터가 한다.

Backend/Agent가 이어받을 지점: `NiaCaseDocument` 를 agent 쪽 입력으로 넘기는 방식(agent 는 data 를
import 하지 않으므로 backend mapper 경유)과 저장소별 metadata 변환은 **미정**이며, 임베딩·검색·
성분 추출 단계에서 별도 계약으로 정한다.

## 2. 아직 정해지지 않은 것 (인수인계 문서 6절 인계 요구 중 미해결분)

아래는 data 파트가 갖고 있지만 아직 agent와 연결이 합의되지 않은 항목이다. 임의로 형식을
정하지 않고 여기 적어 둔다(규칙 3, 16).

- **성분 매칭 확정/미해결 상태**: `data/manual_review/knowledgedata_ingredient_match_queue.csv`,
  `mfds_ingredient_match_queue.csv`에 있는 미해결 매칭이 RAG 검색·근거 검증에 어떻게 반영돼야
  하는지 — 지금은 agent 쪽이 이 큐를 전혀 참조하지 않는다.
- **NIA 의미 라벨링(`NiaLabelingDocument`) ↔ `RagChunk` 연결**: `docs/agent/README.md` "다음에
  필요한 것" 절이 이미 미정으로 남긴 것과 동일 항목. 0절의 파일 중복이 정리된 뒤에나 논의 가능.
- **제품 전성분(`product_ingredient`)과 RAG 근거의 연결 여부**: 현재 RAG는 성분 자체의 근거만
  다루고, 특정 제품의 전성분 목록과 엮는 기능은 없음. 필요 여부 자체가 미정.

## 3. 실패했을 때

해당 없음 — DB 조회 기반이라 별도의 실패 계약이 없다. 미해결 매칭 항목을 향후 연결하게 되면
그때 실패 처리(전체 중단 vs 건너뛰기)를 이 문서에 추가한다.

## 4. 절차

1. 에이전트 담당자가 0절의 중복 파일부터 정리.
2. 2절 항목 중 실제로 필요한 것부터 에이전트 담당자와 논의해 이 문서에 시그니처·타입을 추가.
3. 합의 전까지 data 파트는 `agent/`에 파일을 추가하지 않는다.

## 5. NIA Case 검색 확장 계약 초안 — 2026-09-20 01:48 KST

> 상태: **핵심 정책 사용자 확인 완료, P1 Data exporter 구현 완료**

NIA 원본을 Agent가 직접 import하지 않는다. Data는 기존
`NiaOriginalLoader → NiaOriginalAgeFilter → NiaCaseDocumentBuilder`를 조립해 저장소와 무관한
JSONL을 만들고, Backend가 이를 검증·임베딩·저장한 뒤 Agent 소유 검색 DTO로 반환한다.

### 5.1 Data 산출 타입

타입 소유 위치는 `data/scripts/nia_case_rag/export_schemas.py`다.

```python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from data.scripts.nia_case_document_schemas import NiaCaseDocument


class NiaCaseDatasetSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"


class NiaCaseSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_name: str = Field(min_length=1)
    member_name: str | None = Field(default=None, min_length=1)
    line_number: int = Field(ge=1)


class NiaCaseExportRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_split: NiaCaseDatasetSplit
    source: NiaCaseSource
    document: NiaCaseDocument


class NiaCaseArchiveManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_name: str = Field(min_length=1)
    dataset_split: NiaCaseDatasetSplit
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)


class NiaCaseExportManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text_version: str = Field(min_length=1)
    input_archive_count: int = Field(ge=0)
    input_record_count: int = Field(ge=0)
    output_record_count: int = Field(ge=0)
    training_record_count: int = Field(ge=0)
    validation_record_count: int = Field(ge=0)
    duplicate_case_id_count: int = Field(ge=0)
    failed_record_count: int = Field(ge=0)
    archives: list[NiaCaseArchiveManifestEntry]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

`dataset_split`은 원본 archive 경로의 `Training`/`Validation` 구분에서 결정한다. 저장 경로가
달라져도 결과가 바뀌지 않도록 전체 절대 경로는 산출물에 넣지 않고 파일명, ZIP member, 물리적
줄 번호만 보존한다.

### 5.2 생성 규칙

- AI Hub 원본 한 줄은 `NiaOriginalRecord` 한 건이고, 연령 필터를 통과하면
  `NiaCaseExportRecord` 한 건이 된다.
- 연령 범위는 만 10~39세를 양끝 포함으로 적용한다.
- `document`는 기존 `NiaCaseDocumentBuilder` 결과를 수정 없이 사용한다.
- `case_id` 중복, 파싱 실패, 알 수 없는 split은 조용히 건너뛰지 않고 전체 생성을 실패시킨다.
- 출력 순서는 Loader가 제공한 archive/member/line 순서를 유지한다.
- JSONL과 manifest는 같은 실행에서 생성하며 manifest의 SHA-256은 최종 JSONL 바이트 기준이다.
- NIA `metadata.evidence_sources`는 provenance일 뿐 MFDS/CIR/PubMed Evidence나 Citation이 아니다.

### 5.3 실제 원본 검증 기준선

2026-09-20에 AI Hub 원본 15개 ZIP을 기존 코드로 읽은 기준선은 전체 9,000건, Training 8,000건,
Validation 1,000건, 10~39세 3,581건, 중복 `case_id` 0건, 빈 검색 본문 0건이다. Exporter 완료
조건은 이 값과 일치하는 것이다.

### 5.4 Agent가 받는 논리 정보

Agent는 위 Data 타입을 import하지 않는다. Backend가 다음 정보만 Agent 소유 `CaseSearchHit`로
변환한다.

- `case_id`, `dataset_split`, `page_content`, `text_version`
- `target_concern`, `gender`, `age`, `skin_type`, `skin_concerns`
- 검색 점수와 원본 archive/member/line provenance
- 원문 metadata 중 `evidence_sources`는 표시용 Citation에서 제외

Case와 Claim의 결정적 연결 키는
`NiaCaseDocument.case_id == claim_document.source_record_id`다. Claim의
`annotation_version`은 이 연결 키에 섞지 않고 기존 운영 설정에서 별도로 선택한다.

### 5.5 실패 계약

- 입력 파일을 열 수 없음: 입력 경로를 포함한 `RuntimeError`
- JSON/스키마 오류: 기존 `NiaOriginalParseError`를 그대로 전파
- 알 수 없는 split 또는 중복 `case_id`: 원인과 ID를 포함한 전용 export 오류
- 출력 파일 쓰기 실패: 부분 파일을 정상 산출물로 간주하지 않고 실패

개별 오류를 숨기거나 실패 레코드만 제외한 채 manifest를 성공으로 만들지 않는다.
