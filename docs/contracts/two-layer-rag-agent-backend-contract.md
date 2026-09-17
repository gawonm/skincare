# 2-Layer RAG(Claim + Evidence) ↔ Agent/Backend 계약

> 상태: **DESIGNED — Agent/Backend와 협의 전.** 이 문서는 Data/RAG 파트가 작성한
> 제안이며, 실제 구현은 Agent/Backend 담당자와 합의 후 진행한다(규칙 16). 이번
> 작업은 문서만 작성했고 코드·schema·DB migration·Agent/Backend 구현은 건드리지
> 않았다.

태그 정의(문서 전체에서 사용):

```
[CURRENT]        지금 코드/DB에 실제로 존재하고 동작한다
[DESIGNED]        Data 파트에서 데이터 스키마 설계까지 끝냈으나 Agent/Backend엔 없다
[PROPOSED]        Agent/Backend와 합의가 필요한 신규/확장 인터페이스
[NOT_IMPLEMENTED] 설계도 코드도 없다
```

---

## 1. Purpose

지금 Agent/Backend가 가진 `EvidencePort.search()` 하나가 MFDS(구조화 규제 데이터)와
NIA Q&A(원문 그대로 청킹한 것)를 **구분 없이 같은 `rag_chunk` 풀에서** 검색한다
([CURRENT] — 아래 4절에서 코드로 확인). 이 문서는 그 둘을 **Claim(NIA, 검증 안 된
사용자 고민↔성분↔효능 연결)**과 **Evidence(MFDS/CIR/PubMed, 공식·동료검토 근거)**로
명확히 분리하는 2-Layer 구조를 제안하고, 그 경계에서 Data/RAG ↔ Agent ↔ Backend가
주고받을 데이터와 책임을 정의한다.

---

## 2. Architecture Overview

```
사용자 질문
        ↓
Intent / Entity 분석                          [CURRENT] agent/nodes.py, QuestionIntent
        ↓
[필요 시]
Claim RAG (NIA)                                [DESIGNED] 데이터만, Agent 연동 [NOT_IMPLEMENTED]
        ↓
Ingredient Resolution                          [CURRENT] IngredientResolveResult (agent)
        ↓                                       ⚠ 단, NIA raw_name → ingredient_id
        ↓                                         결정적 매칭은 data 쪽에만 있음(6절)
Evidence RAG (MFDS 지금 / CIR·PubMed 예정)      [CURRENT: MFDS만] EvidencePort.search()
        ↓
 ┌───────────────┬────────────────┐
 ↓               ↓                ↓
Product RDB      Rule Engine      Answer Generation
[CURRENT]        [CURRENT]        [CURRENT]
 ↓               ↓                ↓
 └────────────── Agent / Backend ─┘
                 ↓
              사용자 응답
```

**가장 중요한 현재 상태**: `RagChunk.source_table`은 `evidence`/`ingredient_knowledge_fact`/
`nia_qa` 3개 값을 갖고([CURRENT], `models/rag_chunk.py`), 셋 다 같은 `EvidencePort.search()`
호출 하나로 섞여 검색된다. 즉 **지금 시스템에는 "Claim RAG"라는 별도 레이어가 없다** —
NIA도 그냥 "신뢰도가 `ai_generated_reviewed`로 낮게 표시되는 Evidence 한 종류"로
취급되고 있다(`RagConfidenceTier.AI_GENERATED_REVIEWED`, [CURRENT]). 이 문서가 제안하는
분리는 이 상태를 바꾸자는 것이다.

---

## 3. Responsibility Boundary

### Data / RAG

**책임**:
- Claim retrieval을 위한 원본 준비 — NIA annotation(`NiaLabelingDocument`, [DESIGNED])
- Ingredient resolution 지원 — `IngredientNameMatcher`(deterministic, [CURRENT], `data/scripts/`)
- Evidence corpus 준비 — MFDS(`Evidence` 테이블, [CURRENT]), CIR/PubMed([DESIGNED] 스키마만, 수집 [NOT_IMPLEMENTED])
- Evidence provenance 보존 — source_url/jurisdiction/doi/pmid 등
- Claim ↔ Evidence 연결 — `EvidenceQueryAnchor`/`ClaimEvidenceLink`([PROPOSED], 7절)

**하지 않는 것**: 제품 최종 추천 결정, 루틴 최종 scheduling, citation 문장 생성, 최종 자연어 응답 생성 — 전부 기존 Agent/Backend 소유([CURRENT]).

### Agent / LLM

**책임**([CURRENT], `agent/nodes.py`, `agent/schemas.py`):
- Intent classification, entity extraction
- Tool routing(`EvidencePort`/`ProductLookupPort`/`RoutinePort` 등, [CURRENT])
- 검색 결과 조합 — `EvidenceBundle`(search+assessments+generated, [CURRENT])
- Evidence content 기반 자연어 설명 — `ClaimGenerationRequest`→`GeneratedClaims`([CURRENT])
- 근거 부재 시 표현 — `UnverifiableReason`([CURRENT], 9절)

**하지 않는 것**: DOI/PMID/URL/page/section 생성, 존재하지 않는 Evidence 보완 — 이 원칙은
이미 `ClaimGenerationRequest`의 시스템 프롬프트에 있다("제공된 records만 근거로... 출처에
없는 내용은 생성하지 마세요", `agent/rag/generation/openai_generator.py`, [CURRENT]).
**이번 계약에서 새로 강조하는 것은 딱 하나: Claim(NIA)만 가지고 효능을 "검증된 사실"처럼
확정적으로 말하지 않는다** — 지금은 NIA도 Evidence 풀에 섞여 있어 이 구분이 코드로 강제되지
않는다([CURRENT의 gap], 12절 conflict 참고).

### Backend

**책임**([CURRENT], `backend/services/`, `backend/repositories/`):
- Tool/service orchestration, DTO 전달
- Product RDB 호출(`ProductRepository`류, product 파트 소유)
- Rule Engine 호출(`RoutinePort`, [CURRENT])
- Citation metadata 보존·rendering — **현재는 citation을 코드로 렌더링하는 전용 계층이
  안 보인다**([PROPOSED], 8절)
- empty Evidence 정상 처리 — `LookupStatus.NO_RESULTS`가 이미 있음([CURRENT])

---

## 4. Request Routing by Intent

`QuestionIntent`([CURRENT], `agent/rag/schemas.py`)는 이미 `EFFICACY`/`SKIN_TYPE`/
`CONCENTRATION`/`PRECAUTION`/`REGULATION`/`USAGE_FREQUENCY`/`COMBINATION` 7종을 갖고 있다.
아래 A~E는 이 enum에 "Claim RAG를 타는가"라는 축을 하나 더 얹는 제안이다([PROPOSED]).

### A. 피부 고민 기반 성분 탐색 — "피지가 많은데 어떤 성분이 좋아?"

```
Intent/Concern → Claim RAG[PROPOSED 연동] → Ingredient Resolution[CURRENT]
→ Evidence RAG[CURRENT, MFDS만] → Answer[CURRENT]
```

Claim RAG 없이는 "피지"라는 자유 텍스트 고민에서 후보 성분을 고를 근거가 없다 — 지금은
이 경로가 없어서 이런 질문에 답하려면 NIA 청크를 Evidence 검색어로 그대로 쓰는 수밖에
없다(4절 CURRENT gap).

### B. 특정 성분 효과 질문 — "나이아신아마이드 효과가 뭐야?"

```
Ingredient Resolution[CURRENT] → Evidence RAG[CURRENT] → Answer[CURRENT]
```

Claim RAG는 보조적(optional) — 성분이 이미 특정됐으므로 필수 아님. **이 경로는 지금도
기본적으로 동작한다**(`EvidenceSearchRequest.target_ids`로 성분 지정).

### C. 제품 탐색 — "나이아신아마이드 들어간 세럼 찾아줘."

```
Ingredient Resolution[CURRENT] → Product RDB[CURRENT]
```

효능/추천 이유까지 요청하면 `Evidence RAG`와 `Product RDB`를 둘 다 호출해 Agent가
조합([CURRENT], `ProductCandidate.reasons`가 이미 이 용도로 있음).

### D. 피부 고민 기반 제품 추천 — "고민은 피지고 세럼 추천해줘."

```
Claim RAG[PROPOSED] → Ingredient[CURRENT] → Evidence RAG[CURRENT]
Ingredient → Product RDB[CURRENT]
Evidence + Product → Agent[CURRENT]
```

### E. 루틴 생성

```
User Products → Product Ingredient Mapping[CURRENT, product_ingredient 테이블]
→ Ingredient[CURRENT] → Evidence-derived usage constraints[PROPOSED, 10절]
→ Rule Engine[CURRENT, RoutinePort] → Routine[CURRENT]
```

`RoutineConstraint`(`source: ConstraintSource`)는 이미 있고 `PRODUCT_DIRECTIONS`/`USER`/
`SERVICE_POLICY` 3종을 구분한다([CURRENT]) — 여기에 "Evidence 근거 기반 제약"을 추가하는
것이 10절의 제안이다.

---

## 5. Claim RAG Contract

**상태: [DESIGNED] 데이터 스키마만, Agent 쪽 대응 타입 [NOT_IMPLEMENTED]**

Source: `NiaLabelingDocument`(`data/manual_review/nia_labeling_schemas.py`, freeze된 계약,
[CURRENT]이지만 Agent가 모름). 필드 매핑은 임의로 새로 만들지 않고 **실제 스키마 그대로**
적는다.

| ClaimHit(제안) 필드 | `NiaLabelingDocument` 매핑 | 비고 |
|---|---|---|
| `statement_id` | `statements[].statement_id` | |
| `statement_type` | `statements[].statement_type` | 7종 그대로(`case_observation`/`ingredient_effect_claim`/`precaution`/`usage_instruction`/`cause_claim`/`combination_claim`/`contextual_factor`) |
| `ingredient_id` | `statements[].subject.ingredient_id`(ingredient_effect_claim만) | `matching_status=matched`일 때만 non-null |
| `raw_name` | `statements[].subject.raw_name` | ingredient_id가 없어도 항상 있음(free-text anchor용) |
| `matching_status` | `statements[].subject.matching_status` | `matched`/`unresolved`/`unresolved_ambiguous_family`/`rejected` — **agent는 `matched` 외 값도 anchor로 써야 함**(7절) |
| `claim` | `statements[].object`(ingredient_effect_claim) 또는 `subject`(case_observation/precaution) | statement_type마다 어느 필드인지 다름 — 하나의 `claim: str`로 뭉치지 말고 type별 필드 유지를 권장 |
| `source_span` | `statements[].source_spans[]` | `json_path`/`quote`/`start`/`end`, 원문 재검증 가능 |
| `support_status` | `statements[].support_status` | **항상 `unverified`** — 3.1절 원칙의 근거 필드 |
| `annotation_status` | `statements[].annotation_status` | `rejected`면 애초에 ClaimHit 후보에서 제외(6절) |
| `case_context` | `NiaLabelingDocument.case_context` | 피부고민 검색 필터링용(`skin_concerns_raw` 등) |

**예시가 실제 schema와 안 맞는 부분**: 요청서 예시의 `"claim": "피지 조절"`은
`ingredient_effect_claim`의 `object` 필드에 해당하지만, `case_observation`/`precaution`은
`object`가 아니라 `subject`가 그 역할을 한다 — **단일 `claim` 필드로 합치면 정보가
소실되므로, ClaimHit를 만든다면 statement_type별 discriminated union으로(이미 있는
`NiaStatement` union을 최대한 그대로 재사용) 유지할 것을 제안한다.**

---

## 6. Evidence RAG Contract

**상태: [CURRENT] MFDS만 / [DESIGNED] CIR·PubMed 스키마만 / 수집 [NOT_IMPLEMENTED]**

기존 타입을 그대로 재사용한다 — 새로 안 만든다:

| 요청서의 제안 이름 | 실제 재사용할 타입 | 상태 |
|---|---|---|
| `EvidenceQuery`/`EvidenceQueryAnchor` | `EvidenceSearchRequest`(`query`, `target_ids`, `known_conditions`, `combination_target_ids`) | [CURRENT], 단 `claim_statement_id`/`claim_topic`/`anchor_type` 필드는 없음 — [PROPOSED] 확장 |
| `EvidenceHit` | `EvidenceRecord` + `RetrievedChunk`(`EvidenceSearchResult.chunks`) | [CURRENT], 단 `page`/`section`/`doi`/`pmid`가 없음 — [PROPOSED] 확장(아래) |
| `ClaimEvidenceLink` | `EvidenceBundle`(search+assessments+generated) | [CURRENT] 구조는 있으나 "이 claim의 근거"라는 연결 개념이 없음 — Evidence만 있고 Claim이 없어서 |

### `EvidenceRecord`에 없는 필드 — [PROPOSED] 확장

`EVIDENCE_RAG_DESIGN.md`/`EVIDENCE_COVERAGE_AUDIT.md`/`NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`
(전부 [DESIGNED], data 파트 작성)에서 CIR/PubMed를 넣으려면 필요하다고 확인된 필드:

```
page: int | None
section: str | None
doi: str | None
pmid: str | None
study_type: Literal["human_study","in_vitro","mixed_in_vitro_and_human","review","unknown"] | None
document_status: Literal["final","amended_final","tentative","draft","rereview","unknown"] | None
formulation_type: Literal["single_ingredient","combination_formulation"] | None
```

`EvidenceRecord.source_type`은 이미 `CIR`/`PAPER` 값을 갖고 있다([CURRENT] — 값만 있고
실제로 채워지는 경로는 없음, `EvidenceSourceType`). 즉 **enum은 미래를 이미 예상해뒀지만
실제 CIR/PubMed 수집·매핑 코드가 없는 상태**다 — 새 enum을 만들 필요는 없고, 위 7개
필드만 `EvidenceRecord`에 추가하면 된다(이번엔 하지 않음, [PROPOSED]로만 기록).

`hits=[]`(또는 `EvidenceSearchResult.records=[]`)는 **이미 정상 값이다** — `LookupStatus.NO_RESULTS`가
`ERROR`와 별도로 존재([CURRENT]). Backend가 이걸 HTTP 500으로 처리하면 안 된다는 원칙은
지금 타입 설계에 이미 반영돼 있다.

---

## 7. Product RDB Contract

**상태: [CURRENT]**

```
어떤 성분을 왜 추천하는가 → Claim[제안] + Evidence[CURRENT]
어떤 실제 제품이 그 조건을 만족하는가 → Product RDB[CURRENT]
```

`ProductCandidate.reasons: list[str]`([CURRENT])가 "왜 추천하는가"를 담는 자리다 — 지금은
자유 텍스트 문자열이라, Evidence/Claim에서 온 근거인지 Product 속성 매칭 근거인지 구분이
안 된다. **"제품에 성분이 포함됨 ≠ 완제품 효능이 임상적으로 입증됨"** 원칙은 코드 타입에
아직 강제되지 않는다 — `ProductRecord.ingredient_ids`(포함 사실, [CURRENT])와
`IngredientVerificationResult.claims`(성분 단위 근거, [CURRENT])가 별도 타입이라는
점에서 구조적으로는 이미 분리돼 있지만, `ProductCandidate.reasons`를 만들 때 Agent가 이
둘을 섞어 문장화하지 않도록 이 계약 문서에 명시하는 것이 이번 작업의 실질적 산출물이다.

---

## 8. Citation Contract

**상태: [CURRENT] 부분적 — LLM이 citation을 안 만든다는 원칙은 있음, rendering 전용
계층은 [PROPOSED]**

```
EvidenceRecord.text  → ClaimGenerationRequest.records → LLM → GeneratedClaim.sentence
EvidenceRecord.(source_id/source_title/url/...) → Backend → citation rendering[PROPOSED]
```

`GeneratedClaim`은 이미 `evidence_ids: list[str]`만 갖고 문장 자체엔 출처 문자열을 안 담는다
([CURRENT], `agent/rag/schemas.py:488`) — **"citation을 LLM이 생성하지 않는다"는 원칙이
이미 타입 레벨에서 지켜지고 있다.** 다만 그 `evidence_ids`를 실제 "CIR Report, p.24" 같은
표시 문자열로 바꾸는 **전용 rendering 함수/서비스는 저장소에서 못 찾았다**([PROPOSED],
Backend 소유 제안 — `backend/services/`).

보존 가능한 metadata(6절의 [PROPOSED] 확장 필드 포함): `evidence_id`, `source_type`,
`source_title`, `url`, `pmid`(신규), `doi`(신규), `page`(신규), `section`(신규),
`jurisdiction`, `regulatory_confidence`/`evidence_level`.

---

## 9. Empty / Error Handling

**상태: [CURRENT] 골격 있음, Claim 관련 행은 [PROPOSED]**

| 상황 | 처리 | 근거 |
|---|---|---|
| Claim 없음 | `NO_RESULT`(Claim RAG 자체가 없어 검증 불가, [PROPOSED]) | — |
| Claim 있음 + Evidence 없음 | `NO_RESULT` — `UnverifiableReason.NO_EVIDENCE_FOUND` | [CURRENT] enum 존재 |
| Evidence 일부만 존재 | 있는 것만 `EvidenceSearchResult.records`에 채움, 나머지는 자연히 빔 | [CURRENT] |
| Ingredient unresolved | `IngredientResolveResult.status=NO_RESULTS` + `ambiguous_candidates` | [CURRENT] |
| Product 없음 | `ProductSearchResult.status=NO_RESULTS` | [CURRENT] |
| Product는 있으나 Evidence 없음 | Product는 반환, `ProductCandidate.unresolved`에 사유 기록 | [CURRENT] 필드 있음, 채우는 로직은 [PROPOSED] |
| Evidence retrieval 실패(DB/네트워크 등) | `LookupStatus.ERROR` + `error_message` | [CURRENT] — `NO_RESULTS`와 값 자체가 분리돼 있어 `NO_RESULT ≠ SYSTEM_ERROR` 원칙이 이미 타입으로 강제됨 |

**결론**: 사용자가 요청한 "NO_RESULT ≠ SYSTEM_ERROR" 구분은 **이미 `LookupStatus`
enum으로 구현돼 있다**([CURRENT]) — 이번 계약에서 새로 만들 필요가 없고, Claim RAG가
생기면 같은 enum을 그대로 재사용하면 된다.

---

## 10. Rule Engine Handoff

**상태: [CURRENT] 골격 있음(`RoutineConstraint`), Evidence 연동은 [PROPOSED]**

```
RoutineConstraint(description, source: ConstraintSource, source_id)   [CURRENT]
```

`ConstraintSource`는 이미 `PRODUCT_DIRECTIONS`/`USER`/`SERVICE_POLICY` 3종을 구분한다
([CURRENT]) — Evidence 유래 제약(예: "레티놀은 저녁 사용 권장")을 위한 4번째 값이 없다.
요청서 예시(`rule_type`/`value`/`evidence_refs`)를 그대로 쓰기보다, **기존
`RoutineConstraint`에 `EVIDENCE_DERIVED` 소스 하나만 추가하는 쪽이 최소 변경**이라고
판단한다:

```python
class ConstraintSource(StrEnum):
    PRODUCT_DIRECTIONS = "product_directions"
    USER = "user"
    SERVICE_POLICY = "service_policy"
    EVIDENCE_DERIVED = "evidence_derived"  # PROPOSED
```

`source_id`(이미 있는 필드, `str | None`)에 `evidence_id`를 넣으면 새 필드 없이도
추적 가능하다 — **[PROPOSED], 코드는 만들지 않음.**

---

## 11. Example End-to-End Flows

4절 A~E와 동일. 추가로 하나, **지금 실제로 동작하는 flow(NIA 분리 전)**를 대조군으로
남긴다:

```
[CURRENT, 2026-09 기준 실제 동작]
사용자 질문 → Intent → EvidenceSearchRequest(target_ids=[ingredient_id])
→ EvidencePort.search() → rag_chunk 전체(MFDS+Knowledgedata+NIA_QA 섞임)에서 검색
→ EvidenceBundle → GeneratedClaims → 응답

[PROPOSED, 이 문서가 제안하는 이후 상태]
사용자 질문 → Intent → (필요 시) ClaimSearchRequest → NIA 전용 검색
→ ClaimHit[] → Ingredient Resolution → EvidenceSearchRequest(claim 유래 query 포함)
→ EvidencePort.search() → MFDS(+향후 CIR/PubMed)에서만 검색 → EvidenceBundle
→ GeneratedClaims(단, "unverified NIA claim" 표시 별도 유지) → 응답
```

---

## 12. Current Implementation Status

### Conflicts found(현재 구현과 이 설계가 어긋나는 지점)

1. **Claim/Evidence 미분리** — `RagChunk.source_table='nia_qa'`가 `EvidencePort.search()`
   한 경로로 MFDS와 같이 검색된다. `RagConfidenceTier.AI_GENERATED_REVIEWED`로 신뢰도는
   구분되지만, "Claim(검증 안 됨)"과 "Evidence(공식 근거)"라는 **범주 자체의 분리는 없다.**
2. **NIA는 record 단위, Claim은 statement 단위** — `RagChunk.nia_record_id`는 레코드
   전체를 가리키고 `chunk_field`가 `nia_question`/`nia_answer`/`nia_cot_step` 세 종류뿐이다
   ([CURRENT], `models/rag_chunk.py`). Data 파트가 만든 `NiaLabelingDocument.statements[]`
   (성분 단위로 쪼갠 세분화 claim)와는 **입도(granularity)가 다르다** — 지금 chunk된
   NIA_QA를 Claim RAG로 그냥 승격할 수 없고, `statements[]` 기준으로 새로 청킹해야 한다.
3. **`rag_chunk`가 현재 0건이다**(별도 세션 보고, `rag_pipeline_handoff.md` 갱신 참고) —
   위 두 conflict를 실제로 해소하기 전에 재적재하면 같은 구조적 문제가 반복된다.

### Proposed interfaces (요약)

- `ClaimHit`/Claim RAG 검색 경로 — 전부 [PROPOSED]/[NOT_IMPLEMENTED]
- `EvidenceRecord` 확장 필드 7개(page/section/doi/pmid/study_type/document_status/formulation_type) — [PROPOSED]
- `ConstraintSource.EVIDENCE_DERIVED` — [PROPOSED]
- Citation rendering 서비스(Backend) — [PROPOSED]

---

## 13. Open Decisions

1. **Claim RAG를 별도 `rag_chunk`류 테이블로 분리할지, 기존 `rag_chunk`에
   `chunk_field`를 세분화(예: statement_type별)해서 넣을지** — 6절의 evidence_chunk
   분리 논의(`EVIDENCE_COVERAGE_AUDIT.md` 7절)와 같은 성격의 결정이 Claim 쪽에도 필요하다.
2. **`IngredientVerificationResult`/`EvidenceBundle`을 Claim까지 포함하도록 확장할지,
   아니면 `ClaimBundle`을 별도로 만들지** — Agent 파트 판단 필요.
3. **NIA raw_name → ingredient_id 매칭을 Agent가 다시 하지 않고 Data가 만든 결과를
   그대로 받을지** — 현재 deterministic 매칭(`IngredientNameMatcher`)은 `data/scripts/`
   전용이고 Agent는 `IngredientResolveResult`를 자체적으로 만든다. 두 매칭 로직이 서로
   다른 결과를 낼 위험이 있어 하나로 합칠지 결정 필요.
4. **`ConstraintSource.EVIDENCE_DERIVED` 도입 시점** — CIR/PubMed 근거가 실제로 생기기
   전까지는 MFDS 단독으로도 의미가 있는지(예: "임신부 사용금지"는 이미 Knowledgedata에 있음).

---

## Files referenced

- `docs/data/EVIDENCE_RAG_DESIGN.md`, `EVIDENCE_COVERAGE_AUDIT.md`,
  `NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`, `NIA_ANNOTATION_JSON_GUIDE.md`(전부 Data 파트, [DESIGNED])
- `docs/contracts/backend-to-agent.md`(기존, [CURRENT] 조립 계약)
- `agent/rag/schemas.py`, `agent/rag/ports.py`(전부 [CURRENT])
- `models/rag_chunk.py`, `data/manual_review/nia_labeling_schemas.py`(전부 [CURRENT]/[DESIGNED])
