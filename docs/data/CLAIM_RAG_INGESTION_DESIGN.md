# Claim RAG Ingestion Design

> 범위: 설계/조사만. embedding 호출, `rag_chunk` 재구축, migration, `claim_chunk` 구현
> 전부 하지 않았다. 목표는 "NIA annotation/claim_ingestion 결과를 실제 Claim RAG로
> 만드는 ingestion contract"를 확정하는 것.

---

## 1. Current Gap

```
1. rag_chunk = 0건
2. RagIngestionService에는 sync_evidence / sync_knowledge_facts만 존재
3. NIA Q&A / NIA annotation을 rag_chunk에 적재하는 공식 ingestion method 없음
4. 재구축해도 Evidence + IngredientKnowledgeFact만 복구, Claim RAG(Layer 1)는 안 생김
```

→ **`rag_chunk` 재구축(embedding 호출)은 이번에 보류.** Claim RAG ingestion 경로부터
확정해야, 재구축을 한 번에 올바른 방향으로 할 수 있다.

---

## 2. Historical NIA RagChunk Investigation

### A. 과거 65,196건 중 `nia_qa`(45,002건)는 어떤 형태였나

**`FOUND`** — raw NIA record를 **필드 단위로 그대로** 쪼갠 것이었다. 증거는 코드에
직접 남아 있다:

1. `data/manual_review/nia_labeling_schemas.py`의 모듈 docstring(원문 그대로 인용):

   > "`agent/rag/nia_qa_loader.py`가 만드는 `RagDocument`는 question/answer/CoT 단계를
   > 그대로 청크로 쪼갤 뿐 주체-관계-대상-조건을 구조화하지 않는다. 이 모듈은 그
   > 구조화 결과를 담는 별도 계층이며, **아직 로더·DB와 연결되지 않은 스키마 정의
   > 단계다.**"

2. `models/rag_chunk.py`의 `RagChunkField` enum이 그대로 이 설계를 반영한다:
   `NIA_QUESTION` / `NIA_ANSWER` / `NIA_COT_STEP` — 성분·효능·주의사항 같은 의미
   단위가 아니라 **원문 문서 구조(질문 1개/답변 1개/CoT 스텝 N개) 그대로**다.

3. `tests/db/test_rag_chunk_repository_sync.py`도 이 필드들로만 테스트한다
   (`NIA_QUESTION`, `NIA_ANSWER`) — statement/claim 관련 필드는 테스트에도 없다.

**결론**: 과거 45,002 청크는 **annotation statement가 아니라 원문 Q/A/CoT 필드
청크**였다. 지금 우리가 만든 `NiaLabelingDocument.statements[]`(성분 단위 구조화
claim)는 그 시점에 **존재하지도 않았다**(위 docstring이 "아직 로더·DB와 연결되지
않은 스키마 정의 단계"라고 명시).

### B. `RagChunk.source_table="nia_qa"` 설계가 의도한 것

`models/rag_chunk.py`의 `RagSourceTable.NIA_QA`는 **DB 테이블이 없는 소스**를 위한
값이다(`nia_record_id: str`가 FK가 아니라 평문 문자열인 이유 — 원본이 jsonl이라 DB
테이블 자체가 없음). 즉 이 설계는 "NIA 원문 레코드 하나"를 가리키기 위한 것이었고,
**통계는 record 단위, 청크는 그 record의 필드 단위**였다 — 지금 우리가 만들려는
"statement 단위 claim"과는 애초에 겨냥한 입도(granularity)가 다르다.

### 왜 코드가 사라졌나 — 추가로 발견한 사실

`docs/agent/AGENT_INTEGRATION_REVIEW.md`(311~312행)에 정확한 기록이 있다:

```
| loaders/nia_qa_loader.py | 대체 구현 없음 | 기존 NIA 적재 호출 제거 또는 별도 요구·계약 합의 |
| nia_labeling_schemas.py  | 대체 구현 없음 | 라벨링 산출물 소유·필요성은 data와 합의 |
```

즉 다른 세션(agent 통합 리뷰)에서 **NIA 로더를 의도적으로 제거하고 "data 파트와
별도 계약이 필요하다"고 명시적으로 남겨뒀다.** 지금 이 문서가 그 계약이다.

---

## 3. Claim Retrieval Unit Decision

| 기준 | Option A: RAW_NIA(원문 필드 청크) | Option B: ANNOTATION_STATEMENT |
|---|---|---|
| 2-Layer 책임 분리 | ❌ 원문 그대로라 "주장이 무엇인지" 구조가 없음 — 결국 Evidence 검색 때 또 해석해야 함 | ✅ statement_type 자체가 이미 case_observation/ingredient_effect_claim/precaution/usage_instruction으로 분리됨 |
| 중복 LLM 해석 여부 | ❌ retrieval 이후 다시 LLM이 "이 청크가 무슨 주장인가" 해석해야 함(이미 한 번 한 일을 반복) | ✅ 이미 `NiaLlmLabeler`가 해석 완료 — 재해석 불필요 |
| statement_id provenance | ❌ 없음(record 단위) | ✅ `statement_id`로 원문·annotation 전부 추적 가능 |
| source_span 보존 | ❌ 원문 필드 전체라 span 개념 자체가 없음 | ✅ `source_spans[]`(json_path/quote/start/end) 그대로 |
| ingredient_id 활용 | ❌ 청크에 성분 연결 자체가 없음(전체 rag_chunk에 `ingredient_id` 컬럼은 있지만 NIA_QA는 항상 NULL — "NIA Q&A는 한 성분에 매이지 않는 상황 설명"이라고 모델 주석에 명시) | ✅ `subject.ingredient_id`/`raw_name` 이미 있음 |
| case_context filtering | ❌ 없음 | ✅ `case_context`(skin_concerns_raw 등) 문서 레벨로 있음 |
| dataset_split 관리 | ⚠ record 레벨이라 이론상 가능하나 구현 안 됨 | ✅ `source.dataset_split` 이미 있음 |
| retrieval 평가 가능성 | ❌ "이 청크가 맞는 답인가" 판정 기준이 없음 | ✅ statement 단위 gold set 구성 가능(이미 `NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`에서 수동 5건 선례) |
| EvidenceQueryAnchor 연결 | ❌ 성분/주장이 구조화 안 돼 있어 anchor를 다시 추출해야 함 | ✅ `raw_name`/`ingredient_id`/`object`가 이미 anchor 재료 그대로 |

**추천: Option B (ANNOTATION_STATEMENT).** 근거는 표에 있는 8개 기준 전부에서 A가
이긴 항목이 없다는 것 자체가 근거다 — A는 "아직 로더·DB와 연결되지 않은 스키마
정의 단계"였던 B가 나오기 **이전**의 임시 방편이었고, B가 실제로 만들어진 지금
A를 다시 쓸 이유가 없다.

---

## 4. Claim Index Eligibility Policy

기준 파일: `data/processed/nia_10s_30s_claim_ingestion.jsonl`(`NiaClaimIngestionPolicy`,
[CURRENT] 코드 그대로 재사용, 새로 안 만듦).

| decision | index 여부 |
|---|---|
| `ingestible_structured` | ✅ index (구조화 anchor, `ingredient_id` 있음) |
| `ingestible_free_text` | ✅ index (free-text anchor, `raw_name`만) |
| `human_review` | ⚠ **별도 정책 필요** — 아래 참고 |
| `blocked` | ❌ index 제외 |

**`human_review` 정책 제안**: `NiaClaimIngestionPolicy.decide()`의 코드를 보면
`human_review`는 두 원인 중 하나다 — (a) semantic validator `low_confidence`
(statement 의미와 quote가 약하게만 연관), (b) span 복원이 `fuzzy`(문자 그대로
일치 안 함). 둘 다 "내용 자체가 틀렸다"가 아니라 "grounding 신뢰도가 낮다"이므로,
**index는 하되 검색 결과에 `confidence=low` 플래그를 노출해 Agent가 사용자에게
"확인이 필요한 근거"로 구분할 수 있게 하는 것을 제안한다**(index 완전 제외보다
데이터 활용도가 높음). 단, 이건 이번 문서의 제안일 뿐 구현하지 않았다 — 사람
검수 없이 자동으로 `ingestible`과 동급으로 승격하지는 않는다.

### priority=primary(핵심 4종) 기본 index 대상 여부

**적절하다고 판단.** `NiaClaimIngestionPolicy.CORE_STATEMENT_TYPES`(코드, [CURRENT])가
이미 `case_observation`/`ingredient_effect_claim`/`precaution`/`usage_instruction`
4종으로 고정돼 있고, 이건 애초에 사용자가 이전 세션에서 "Claim RAG ingestion 우선순위는
이 4종"이라고 확정한 정책과 정확히 같다 — 새로 판단할 필요 없이 기존 정책을 그대로
따르면 된다. `secondary`(cause_claim/contextual_factor/combination_claim)는 POC
index에서 제외하거나, 포함하더라도 검색 우선순위를 낮추는 것을 제안한다.

**현재 pilot(36건 통과 문서) 기준 실측**:

```
(ingestible_structured, primary)   82
(ingestible_free_text, primary)   149
(human_review, primary)            20
(blocked, primary)                  7
(ingestible_free_text, secondary)  42
(human_review, secondary)           4
(blocked, secondary)                1
```

primary 즉시 index 가능(`ingestible_*`) = **231건**, human_review 보류 = 24건,
blocked 제외 = 8건. (ingredient resolution 수정 이후 재계산된 최신 수치.)

---

## 5. Claim Document Contract

`NiaLabelingDocument`/`data/processed/nia_10s_30s_claim_ingestion.jsonl`의 **실제
필드만** 사용한다. 요청서 예시의 `claim_text`는 실제 schema에 없는 이름이라, 존재하는
필드로 정정한다.

```json
{
  "statement_id": "COT_ACN_F_O30_00525-S005",
  "record_id": "COT_ACN_F_O30_00525",
  "statement_type": "ingredient_effect_claim",
  "ingredient_id": "f90ba1bc-346b-4627-a387-8cf3759dbd7b",
  "raw_name": "나이아신아마이드",
  "matching_status": "matched",
  "object": "피지 조절 기능과 피부 장벽 강화 효과가 있어 트러블의 근본적인 원인을 개선하고...",
  "source_spans": [
    {"json_path": "$.chain_of_thought[1].content", "quote": "...", "start": 83, "end": 199}
  ],
  "skin_concerns_raw": ["여드름/뾰루지", "미백(색소침착/기미/칙칙함)"],
  "dataset_split": "training",
  "decision": "ingestible_structured",
  "priority": "primary",
  "support_status": "unverified"
}
```

**필드 출처 매핑** (임의로 만든 필드 없음):

| 필드 | 출처 |
|---|---|
| `statement_id`, `statement_type` | `NiaLabelingDocument.statements[]` |
| `record_id` | `source.record_id` |
| `ingredient_id`, `raw_name`, `matching_status` | `statements[].subject`(ingredient_effect_claim/combination_claim만) |
| `object` | `statements[].object` — **주의: case_observation/precaution은 `object`가 아니라 `subject`가 claim 내용이다. statement_type마다 다른 필드를 봐야 하며, 단일 `claim_text`로 뭉치면 정보가 소실된다**(6절에서 이 문제를 다시 다룸) |
| `source_spans` | `statements[].source_spans[]` |
| `skin_concerns_raw` | `case_context.skin_concerns_raw`(문서 레벨, statement가 상속) |
| `dataset_split` | `source.dataset_split` |
| `decision`, `priority` | `nia_10s_30s_claim_ingestion.jsonl`(같은 `statement_id`로 join) |
| `support_status` | `statements[].support_status`(항상 `unverified`) |

`statement_id`로 원문 annotation(`nia_10s_30s_annotations.jsonl`)까지 역추적
가능함을 확인했다 — `record_id` + `statement_id` 둘 다 있어 문서와 개별 statement
양쪽으로 조회 가능.

---

## 6. Embedding Text Strategy

**Embedding 후보** vs **Metadata/filter 후보** 분리:

| Embedding에 포함 | Metadata/filter로만 사용 |
|---|---|
| claim 내용(statement_type별로 아래 참고) | `statement_id`, `record_id` |
| 성분명(raw_name) | `ingredient_id` |
| 피부 고민(skin_concerns_raw) | `statement_type` |
| — | `dataset_split`(**절대 embedding 텍스트에 안 넣음** — validation leakage와 무관하지만 검색 관련성에 불필요한 노이즈) |
| — | `decision`, `priority` |

**statement_type별 representation이 필요한가 — 필요하다.** 4절에서 이미 확인했듯
claim 내용이 있는 필드가 타입마다 다르기 때문이다(`object` vs `subject`). 제안:

```
case_observation:        "{skin_concerns_raw} {subject}"
ingredient_effect_claim:  "성분: {raw_name} 효과: {object}"
precaution:                "{subject}" (relation=avoid면 "주의: " 접두)
usage_instruction:         "{action}"
```

단일 템플릿(`f"성분: {x} 효능 주장: {y} 피부 고민: {z}"`)으로 4종을 억지로
통일하면 `case_observation`/`precaution`처럼 성분이 없는 타입에서 빈 `성분:` 필드가
노이즈로 남는다 — **타입별 템플릿을 유지하는 것을 제안한다.**

---

## 7. Storage Decision

| 기준 | Option 1: 기존 `rag_chunk` 재사용 | Option 2: 별도 `claim_chunk` |
|---|---|---|
| 기존 vector search 재사용 | ✅ `HybridRetriever` 등 그대로 사용 가능 | ❌ 새 retrieval 경로 필요 |
| `source_table` 의미 불일치 | ❌ `nia_qa` 값이 이미 "raw record 필드 청크"라는 의미로 쓰였던 이력이 있어(2절), 같은 값에 statement 단위 데이터를 넣으면 과거 의미와 충돌 | ✅ 없음 |
| `statement_id` 표현 | ❌ `nia_record_id`만 있고 statement 단위 컬럼이 없음 — `chunk_field`(`NIA_QUESTION`/`NIA_ANSWER`/`NIA_COT_STEP`)도 statement_type과 안 맞음. 컬럼 추가/CHECK 제약 확장 필요 | ✅ 처음부터 statement 스키마로 설계 가능 |
| Evidence RAG와 책임 혼합 | ❌ 지금 `EvidencePort.search()` 하나가 MFDS+KnowledgeFact+NIA_QA를 다 검색한다(계약 문서 12절에서 이미 지적한 conflict) — 같은 테이블을 계속 쓰면 이 문제가 해소되지 않고 유지됨 | ✅ Claim RAG 전용 경로가 명확히 분리됨(2-Layer 구조의 원래 목적과 일치) |
| migration | ✅ 불필요(컬럼 추가 정도) | ❌ 새 테이블 필요 |
| retrieval abstraction | ✅ 기존 `EvidencePort` 재사용 가능(단, 이름이 Claim에 안 맞음) | ❌ `ClaimPort` 신규 필요 |

**추천: Option 2(별도 `claim_chunk`).** 이유: `EVIDENCE_COVERAGE_AUDIT.md` 7절에서
`evidence_chunk`를 별도로 만들자고 결론 낸 것과 **완전히 같은 논리**다 —
`rag_chunk.source_table` CHECK 제약이 이미 3개 값으로 굳어 있고, 그 중 `nia_qa`는
지금 우리가 넣으려는 것과 다른 입도(record vs statement)로 정의된 이력이 있어
"확장"이 아니라 "재정의"가 된다. 무엇보다, **이 프로젝트 전체 단계의 목적 자체가
"Claim과 Evidence를 분리하자"인데, 둘 다 같은 물리 테이블에 넣으면 그 분리가
스키마 레벨에서 실현되지 않는다.** (실제 migration/구현은 이번에 하지 않음.)

---

## 8. ClaimHit Contract

요청한 9개 필드를 현재 스키마 기준으로 확인:

| 요청 필드 | 반환 가능 여부 | 출처 |
|---|---|---|
| `statement_id` | ✅ | `statements[].statement_id` |
| `statement_type` | ✅ | `statements[].statement_type` |
| `ingredient_id` | ✅(단, `matched`일 때만 non-null) | `subject.ingredient_id` |
| `raw ingredient name` | ✅ | `subject.raw_name` |
| `claim content` | ✅(단, 타입별로 다른 필드 — 5·6절 참고) | `object` 또는 `subject` |
| `source_span` | ✅ | `source_spans[]` |
| `case_context` | ✅(문서 레벨, statement가 상속) | `case_context` |
| `support_status` | ✅ | `statements[].support_status`(항상 `unverified`) |
| `retrieval score` | ⚠ **아직 없음** — embedding/retrieval을 실행 안 해서 당연히 없음. Claim RAG 구현 시 `EmbeddingResult`/`HybridSearchResult`가 이미 이 역할(`RetrievedChunk`에 유사 개념 존재)을 하므로 새로 안 만들어도 됨 |

**`ClaimHit → EvidenceQueryAnchor` 연결 검증**: `EvidenceQueryAnchor`(`EVIDENCE_RAG_DESIGN.md`)가
필요로 하는 `claim_statement_id`/`ingredient_id`/`raw_name`/`raw_name_ko`/`claim_topic`/
`anchor_type`/`query_terms` 중, `claim_statement_id`=`statement_id`, `ingredient_id`,
`raw_name`은 ClaimHit에서 손실 없이 그대로 옮길 수 있다. `claim_topic`(effect/precaution/
usage/combination)은 `statement_type`에서 결정적으로 유도 가능(`ingredient_effect_claim`→
`effect` 등, 1:1 매핑). `anchor_type`은 `matching_status`(`matched`→`structured`, 나머지→
`free_text`)로 결정적으로 유도 가능 — **이미 `NiaClaimIngestionPolicy._has_matched_ingredient`가
정확히 이 로직**이다. `query_terms`만 새로 조합해야 하는 필드다(claim content + raw_name
조합, 6절의 embedding text와 유사).

**판정: `READY`.** 손실 없이 연결 가능하고, 필요한 로직(claim_topic/anchor_type 유도)도
이미 기존 코드(`NiaClaimIngestionPolicy`)에 사실상 구현돼 있어 재사용만 하면 된다.

---

## 9. Dataset Split Policy

**현재 pilot(36건 통과 문서) split 분포**:

```
training:   34건 (94%)
validation:  2건 (6%)
```

**정책 검증**: `training → index, validation → evaluation`은 **현재 데이터로 가능하다.**
`source.dataset_split`이 이미 문서 레벨에 있고, `NiaPilotSampler`가 층화추출할 때도
이 값을 그대로 보존했다(원본 `nia_structural_audit_9000.jsonl`의 `dataset_split`을
join). **단, validation이 2건뿐이라 이 pilot 규모로는 평가셋으로 쓰기엔 표본이
너무 작다** — 전체 3,581건(또는 그 이상)으로 확장했을 때 validation 비율이 실제로
의미 있는 평가셋 크기(최소 수십 건)를 만드는지 별도 확인이 필요하다. Training 34건
전부가 core-4-type 기준 `ingestible_*`인 것도 아니므로(4절 실측), 실제 index
대상은 34건보다 더 적다.

---

## 10. Migration / Implementation Plan (실행 안 함, 계획만)

1. `claim_chunk` 테이블 설계 (7절 Option 2 기준) — provenance: `statement_id`,
   `record_id`, `ingredient_id`, `dataset_split`, `decision`, `priority`, `content`,
   `embedding`
2. `ClaimPort`(신규, `agent/rag/ports.py`에 `EvidencePort`와 나란히) 인터페이스 설계
3. `data/processed/nia_10s_30s_claim_ingestion.jsonl` + `annotations.jsonl`을 join해
   Claim Document(5절 contract)로 변환하는 매퍼 작성
4. 위 매퍼 출력을 5·6절 기준으로 embedding text 생성(타입별 템플릿)
5. `claim_chunk` insert(이번 pilot 규모, training split만, human_review 플래그 포함)
6. validation split으로 retrieval 품질 최소 확인(gold set은 `NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`
   5건이 이미 선례)
7. 그 다음에야 `rag_chunk`(Evidence 전용) 재구축 — 두 레이어를 분리한 채로 순서대로

---

## 11. Open Decisions

1. `human_review` claim을 index는 하되 `confidence=low`로 노출할지, 아예 제외할지 —
   4절 제안(index하되 플래그)에 대한 최종 판단 필요
2. `secondary`(3종) statement를 Claim RAG에 포함할지, POC에서는 아예 제외할지
3. `claim_chunk` 실제 컬럼 설계(embedding 차원 등 — Evidence 쪽과 같은 모델/차원을
   쓸지, Claim은 짧은 문장이 많아 다른 모델이 나을지)
4. validation split이 실제 평가셋으로 쓰기에 충분한 규모가 되려면 전체 corpus를
   얼마나 확장해야 하는지(3,581건 전체 확장 여부는 별도 승인 필요, 이번 문서 범위 아님)

---

## 결과 보고

```
CLAIM_RAG_INGESTION_DESIGN_RESULT

Historical nia_qa ingestion:
FOUND
(raw record 필드 단위 청크 — NIA_QUESTION/NIA_ANSWER/NIA_COT_STEP.
nia_labeling_schemas.py 자체 docstring 및 AGENT_INTEGRATION_REVIEW.md 311~312행에서
"loaders/nia_qa_loader.py 대체 구현 없음, 기존 NIA 적재 호출 제거"로 명시적으로 확인됨)

Current Claim RAG ingestion:
MISSING

Recommended retrieval unit:
ANNOTATION_STATEMENT
(8개 비교 기준 전부에서 RAW_NIA 대비 우위 확인)

Recommended storage:
CLAIM_CHUNK
(rag_chunk의 source_table='nia_qa'는 이미 다른 입도로 쓰인 이력이 있어 재사용 시
의미 충돌. EVIDENCE_COVERAGE_AUDIT.md의 evidence_chunk 분리 결정과 동일 논리)

Index eligibility:
ingestible_structured/ingestible_free_text → index
human_review → index하되 confidence=low 플래그 제안(Open Decision 1)
blocked → 제외
priority=primary(핵심 4종) 기본 index 대상 적절 — 현재 231건(structured 82 + free_text 149)

ClaimHit → EvidenceQueryAnchor:
READY
(모든 필드 손실 없이 매핑 가능, claim_topic/anchor_type 유도 로직도 기존 코드에 이미 있음)

Dataset split policy:
training(34건)→index, validation(2건)→evaluation 가능하나 validation 표본이 너무 작음
— 전체 corpus 확장 시 재확인 필요

Implementation tasks:
1. claim_chunk 테이블 설계 및 migration
2. ClaimPort 인터페이스 설계(agent 협의 필요)
3. annotations.jsonl + claim_ingestion.jsonl → Claim Document 매퍼
4. 타입별 embedding text 템플릿 구현
5. claim_chunk insert(training만)
6. validation 기반 최소 retrieval 품질 확인
7. 그 후 rag_chunk(Evidence) 재구축

Embedding rebuild:
DEFERRED

Files Created:
docs/data/CLAIM_RAG_INGESTION_DESIGN.md

Files Modified:
(rag_pipeline_handoff.md에 보류 사유 1줄 반영 — 아래 참고)

Commit:
NOT COMMITTED
```
