# Claim RAG Session Handoff (Session A)

> 이 문서만 읽고 Claim RAG 작업을 이어받을 수 있도록 작성했다. 원래 세션(이하
> "Session B")이 지금까지의 전체 맥락을 갖고 있고, 이 문서는 그중 Claim RAG에
> 필요한 부분만 추려 넘긴다. 작업 중 서로에게 필요한 결정은 코드로 직접 주고받지
> 말고 [CLAUDE_SESSION_BOARD.md](CLAUDE_SESSION_BOARD.md)에 남긴다.

---

## 1. Project Context

SKINCARE 프로젝트는 화장품 성분 기반 상담/추천 서비스다. 데이터 파트는 4개 파이프라인을
병렬로 다룬다: 성분(ingredient), 상품(product), NIA(AI Hub CoT 데이터), 그리고 이번에
새로 분리한 RAG(Claim+Evidence). 서비스 최상위 원칙: **근거를 찾는 일 = RAG, 상품을
찾는 일 = RDB, 시간표를 짜는 일 = Rule, 결과를 이해하고 조합하는 일 = LLM/Agent.**

## 2. Why 2-Layer RAG

처음엔 NIA(AI Hub CoT 데이터)를 "성분 효능·안전성 근거"로 쓰려 했다. 하지만 NIA는
**IRB 승인 피험자의 설문을 AI가 질문체로 재구성하고, AI가 CoT를 생성한 뒤 전문가
패널이 검증**한 데이터다(`RagConfidenceTier.AI_GENERATED_REVIEWED`) — 실제 논문/공식
규제기관 근거(MFDS/CIR/PubMed, `OFFICIAL_REGULATORY`/`STRUCTURED_KNOWLEDGE`급)와 신뢰도가
다르다. 그래서 역할을 쪼갰다:

```
Layer 1 — Claim RAG (NIA)
  "사용자 고민 ↔ 성분 ↔ 효능/주의/사용법"의 연결을 찾는다.
  Claim found ≠ scientifically verified.

Layer 2 — Evidence RAG (MFDS/CIR/PubMed)
  Layer 1에서 찾은 claim을 실제 공식/동료검토 근거로 검증한다.
  Evidence 없음(hits=[])도 정상 결과다.
```

**중요**: `ingredient_id`가 파이프라인 전체의 중심 키다. NIA Claim, MFDS/CIR/PubMed
Evidence, Product Ingredient Mapping이 전부 이 키로 연결된다. POC는 5개 성분
(Vitamin C/Niacinamide/Retinol/AHA/BHA)만 다루지만, **매칭 로직 자체는 특정 성분을
하드코딩하지 않고 `IngredientMaster` 전체(21,974건)에 generic하게 적용된다** — 최종
목표는 5개가 아니라 전체 성분셋이다.

## 3. Current Architecture

```
사용자 질문
        ↓
Intent / Entity 분석                      [CURRENT, agent 소유]
        ↓
[필요 시] Claim RAG (NIA)                  [DESIGNED, 이 handoff의 대상]
        ↓
Ingredient Resolution                      [CURRENT(deterministic 매칭, data 소유) + CURRENT(agent 자체 로직, 별도)]
        ↓
Evidence RAG (MFDS 지금 / CIR·PubMed 예정)  [CURRENT: MFDS만, Session B 담당]
        ↓
Product RDB / Rule Engine / Answer Generation → Agent/Backend
```

전체 계약: `docs/contracts/two-layer-rag-agent-backend-contract.md`(Session B가 작성,
[CURRENT]/[DESIGNED]/[PROPOSED]/[NOT_IMPLEMENTED] 태그 체계 사용).

## 4. NIA Claim Pipeline (지금까지 만든 것)

```
nia_qa_10s_30s.jsonl(3,581건, 10~30대 필터링된 raw corpus, 미라벨링)
  ↓ NiaLlmLabeler (LLM structured output, provider 교체 가능: openai/ollama/local)
  ↓ NiaSourceSpanBuilder (LLM 출력 quote → 원문 deterministic 위치 복원, exact/fuzzy)
  ↓ NiaUsageInstructionNormalizer (usage_instruction의 time_of_day/frequency 보강)
  ↓ NiaIngredientMatchingStage (raw_name/raw_name_ko → ingredient_id deterministic 매칭)
  ↓ NiaSemanticSpanValidator (statement 의미 ↔ quote 의미 일치 검사, substring coverage)
  ↓ NiaReferenceLinker (현재 no-op — 자동연결 위험 확인돼 비활성화)
  ↓ NiaLabelingParser (data/manual_review/, **freeze된 기존 계약, 수정 금지**)
  ↓ NiaClaimIngestionPolicy (blocked/human_review/ingestible_structured/ingestible_free_text 판정)
  ↓
nia_10s_30s_annotations.jsonl (통과 문서) + review_queue.jsonl + labeling_failures.jsonl
  + claim_ingestion.jsonl (statement별 ingestion 결정)
```

39건 stratified pilot 최신 결과(ingredient fix 반영 후): parser 통과 36/39,
claim_ingestion 기준 primary(핵심4종) 즉시 index 가능 231건, human_review 24건,
blocked 8건.

## 5. Ingredient Resolution Fix (이번 세션에서 완료)

**Root cause**: LLM이 `raw_name_ko`를 비우고 한글 성분명을 `raw_name`(원래 INCI/영문용)에
넣는 경우가 많았다(59건 중 51건). `IngredientNameNormalizer.normalize_en()`은 한글을
그대로 통과시켜 영문 표준명 색인과 절대 매칭 안 됨 — 6단계 매칭 전부 실패.

**Fix**: `NiaIngredientMatchingStage.resolve()`에 fallback 추가 — `raw_name_ko`가
없고 `raw_name`에 한글이 있으면 그 문자열을 `raw_name_ko`로도 한 번 더 시도(같은
deterministic 파이프라인 재사용, fuzzy 승격 없음, 성분 하드코딩 없음).

**결과**: matched 58→97, unresolved 59→20. Niacinamide claim 5건 전부
`ingredient_id` 확정(`f90ba1bc-346b-4627-a387-8cf3759dbd7b`). Regression: **222 passed,
0 failed**(신규 7개 포함).

**주의**: 이 fix는 이미 완료·검증됐다 — 다시 고치지 말 것. `nia_reresolve_ingredients.py`로
기존 annotation을 재해석해 `annotations.jsonl`/`review_queue.jsonl`/`claim_ingestion.jsonl`을
이미 갱신해뒀다(새 LLM 호출 없음, 순수 재계산).

## 6. Current Data / Files

전부 아래 "13. Files Session A May Edit"에도 나열. 핵심만:

| 파일 | 내용 |
|---|---|
| `data/processed/nia_qa_10s_30s.jsonl` | 3,581건 raw corpus(10~30대) |
| `data/processed/nia_10s_30s_annotations.jsonl` | 36건 통과 문서(ingredient fix 반영됨) |
| `data/processed/nia_10s_30s_review_queue.jsonl` | blocking/non_blocking 사유 |
| `data/processed/nia_10s_30s_labeling_failures.jsonl` | 3건(그중 2건은 OpenAI spend limit, 1건 실질 실패) |
| `data/processed/nia_10s_30s_claim_ingestion.jsonl` | statement별 decision/priority |
| `docs/data/NIA_ANNOTATION_JSON_GUIDE.md` | 팀원용 JSON 구조 설명 |
| `docs/data/CLAIM_RAG_INGESTION_DESIGN.md` | **다음 작업의 설계 기준 문서(7~10절 필독)** |

## 7. Claim RAG Problem (지금 없는 것)

`rag_chunk` 테이블(`models/rag_chunk.py`)은 **statement 단위 Claim을 담을 수 없다.**
`RagChunkField`가 `NIA_QUESTION`/`NIA_ANSWER`/`NIA_COT_STEP`(원문 필드 단위)뿐이고
`nia_record_id`도 record 전체를 가리킨다 — `statement_id` 개념 자체가 없다. 과거
65,196건 중 45,002건(`nia_qa`)은 **원문 그대로 청킹한 것**이었지, 지금 우리가 만든
`NiaLabelingDocument.statements[]`(성분 단위 구조화 claim)가 아니었다(당시엔 이
구조 자체가 없었음 — `nia_labeling_schemas.py` 자체 docstring에 명시).
`agent/rag/loaders/nia_qa_loader.py`도 다른 세션의 통합 리뷰에서 "대체 구현 없이
제거, data 파트와 별도 계약 필요"로 명시적으로 남겨졌다(`docs/agent/AGENT_INTEGRATION_REVIEW.md`
311~312행).

**즉 Claim RAG 저장/검색 경로는 설계만 있고 구현이 전혀 없다.**

## 8. Decisions Already Made (되돌리지 말 것)

- **Claim retrieval unit = `ANNOTATION_STATEMENT`**(raw NIA record 청크 아님) — 8개 비교
  기준 전부에서 우위 확인(`CLAIM_RAG_INGESTION_DESIGN.md` 3절)
- **Storage = 별도 `claim_chunk`**(기존 `rag_chunk` 재사용 안 함) — `source_table='nia_qa'`가
  이미 다른 입도로 쓰인 이력이 있어 재사용하면 의미 충돌(`CLAIM_RAG_INGESTION_DESIGN.md` 7절)
- **Index 대상**: `ingestible_structured`/`ingestible_free_text` → index, `blocked` → 제외,
  `human_review` → index하되 confidence=low 플래그(제안, 최종 확정은 Open Decision)
- **Ingredient matching은 fuzzy를 자동 확정에 안 쓴다** — exact/정규화/annotation-stripped만
- **Reference 자동 연결은 하지 않는다**(`NiaReferenceLinker` no-op, false positive 위험이
  unlinked 손실보다 크다고 판단)
- **NIA reference는 record-level metadata로만 보존** — claim-level evidence는 Evidence RAG(Session B)가 별도로 찾는다
- **`ClaimHit != EvidenceRecord`** — 절대 같은 타입으로 합치지 않는다(agent 쪽 `EvidenceRecord`는
  MFDS/CIR/PubMed 전용으로 유지, Claim은 새 타입)
- **`NiaLabelingDocument`/`NiaLabelingParser`/`nia_labeling_guide.md`는 freeze된 계약** —
  schema/taxonomy를 임의로 바꾸지 않는다

## 9. Decisions Still Open (Session A가 결정하거나 Board에 제안)

1. `human_review` claim: index+confidence=low 플래그 vs 완전 제외
2. `secondary` statement type(cause_claim/contextual_factor/combination_claim) 포함 여부
3. `claim_chunk` 실제 컬럼/embedding 차원(Evidence와 같은 모델 쓸지)
4. validation split(현재 2건뿐, 너무 작음) — 전체 corpus 확장 시 재확인 필요, 지금은 판단 보류
5. `ClaimPort`(신규 agent 인터페이스) 시그니처 — Agent 파트와 협의 필요(Board에 기록)

## 10. Work Completed

- NIA raw corpus 나이 필터(10~30대, 3,581건)
- NIA LLM labeling pipeline(provider-agnostic: openai/ollama/local)
- Source span deterministic 복원(exact+fuzzy, record 전체 텍스트 대상)
- Usage instruction 정규화(time_of_day/frequency, reconcile 포함)
- Semantic span validator(성분명 일치만으로 통과 안 시킴, predicate 비교)
- Ingredient resolution fix(한글 raw_name fallback)
- Claim ingestion policy(blocking/non-blocking 분리, decision/priority 산출)
- 39건 pilot 최신 재실행 완료(36/39 통과)
- 전체 unit test 222개 통과

## 11. Work Not Started

- `claim_chunk` 테이블 설계/migration(설계 방향만 확정, 실제 스키마 미작성)
- `ClaimPort` 인터페이스
- Claim Document 매퍼(annotations+claim_ingestion → 5절 contract 형태로 변환하는 코드)
- Embedding text 템플릿 구현(설계는 `CLAIM_RAG_INGESTION_DESIGN.md` 6절에 있음)
- 실제 embedding 생성/색인(전부 미실행)
- 전체 3,581건 확장(39건 pilot만 완료)

## 12. Exact Next Task

`CLAIM_RAG_INGESTION_DESIGN.md`의 §10 Migration/Implementation Plan을 따른다:

1. `claim_chunk` 테이블 설계(컬럼: `statement_id`, `record_id`, `ingredient_id`,
   `dataset_split`, `decision`, `priority`, `content`, `embedding` — 확정 전 Board에
   초안 공유 권장, DB 스키마는 공유 자원이라 Session B도 알아야 함)
2. `annotations.jsonl` + `claim_ingestion.jsonl`을 join해 Claim Document(5절 contract,
   `CLAIM_RAG_INGESTION_DESIGN.md` §5)로 변환하는 매퍼 작성
3. statement_type별 embedding text 템플릿 구현(§6)
4. **이 단계까지는 embedding 실행 없이 dry-run으로 결과물만 만들어 확인할 것을 권장** —
   비용이 드는 단계(embedding 호출, DB 적재)는 반드시 Board에 계획을 남기고 Session B와
   순서 조율 후 진행(Session B도 별도로 Evidence RAG embedding을 계획 중일 수 있어, 같은
   시점에 동시에 API 비용을 쓰면 spend limit 충돌 위험 — 이번 세션에서 실제로 2번 겪었다)

## 13. Files Session A May Edit

```
data/scripts/nia_llm_label_schemas.py
data/scripts/nia_llm_labeler.py
data/scripts/nia_chat_model_client.py
data/scripts/nia_source_span_builder.py
data/scripts/nia_semantic_span_validator.py
data/scripts/nia_usage_instruction_normalizer.py
data/scripts/nia_ingredient_matching_stage.py
data/scripts/nia_reference_linker.py
data/scripts/nia_claim_ingestion_policy.py
data/scripts/nia_record_provenance.py
data/scripts/nia_pilot_runner.py
data/scripts/nia_reresolve_ingredients.py
data/scripts/nia_qa_age_filter.py
tests/unit/test_nia_*.py (전부)
data/processed/nia_qa_10s_30s.jsonl
data/processed/nia_10s_30s_annotations.jsonl
data/processed/nia_10s_30s_review_queue.jsonl
data/processed/nia_10s_30s_labeling_failures.jsonl
data/processed/nia_10s_30s_claim_ingestion.jsonl
docs/data/NIA_ANNOTATION_JSON_GUIDE.md
docs/data/CLAIM_RAG_INGESTION_DESIGN.md
docs/coordination/CLAUDE_SESSION_BOARD.md (본인 섹션만)
신규: claim_chunk 관련 model/migration/service 파일(작성 시 파일명을 Board에 먼저 기록)
```

## 14. Files Session A Must Not Edit

```
data/manual_review/nia_labeling_schemas.py     — freeze, 절대 수정 금지
data/manual_review/nia_labeling_parser.py      — freeze, 절대 수정 금지
data/manual_review/nia_labeling_guide.md       — freeze, 절대 수정 금지
data/scripts/ingredient_name_matcher.py        — 공용(성분 매칭 코어), 수정 필요시 Board에 제안
data/scripts/ingredient_name_normalizer.py     — 공용
data/scripts/ingredient_schemas.py             — 공용
data/scripts/export_ingredient_dataset.py      — Session B 소유
data/scripts/build_product_datasets.py         — Session B 소유
data/scripts/product_ingredient_mapping_*.py   — Session B 소유
docs/data/EVIDENCE_RAG_DESIGN.md               — Session B 소유
docs/data/EVIDENCE_COVERAGE_AUDIT.md           — Session B 소유
docs/data/NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md — Session B 소유(claim 예시 5건 포함하지만 Evidence 매핑이 본문)
docs/data/rag_pipeline_handoff.md              — Session B 소유
docs/data/POC_DATASET_HANDOFF.md               — Session B 소유(ingredient/product/NIA 통합 문서)
docs/contracts/two-layer-rag-agent-backend-contract.md — 공유 contract, PROPOSE만(Board에 제안 → Session B가 최종 반영)
models/*.py, migrations/                        — DB 소유권 미정, 이번 단계에서 아무도 migration 실행 금지(사용자 승인 필요)
backend/, agent/                                — 이번 handoff 범위 밖(각 파트 소유)
```

## 15. Tests to Run

```bash
uv run pytest tests/unit/test_nia_*.py -v   # Claim RAG 관련만 빠르게
uv run pytest tests -q                       # 전체 regression(현재 222 passed 기준선)
```

새 코드 추가 시 LLM/API 호출 없는 unit test부터 작성(이번 세션의 관례 — 예:
`NiaClaimIngestionPolicy`, `NiaSemanticSpanValidator` 전부 fake/fixture 기반 테스트).
39건 pilot 재실행(`nia_pilot_runner.py`)은 실제 OpenAI 비용이 드니 Board에 먼저
공유하고 진행할 것.

## 16. Definition of Done (이번 workstream 1차 목표)

- `claim_chunk`(또는 합의된 이름) 테이블에 39건 pilot의 `ingestible_*` statement가
  실제로 적재됨(embedding 포함)
- `ClaimPort` 인터페이스가 최소 하나의 검색 메서드로 정의됨(agent와 형식 합의, 구현은
  agent 쪽이 담당할 수도 있음 — Board에서 조율)
- Claim → `EvidenceQueryAnchor` 변환이 실제 코드로 동작(설계는 이미 완료,
  `CLAIM_RAG_INGESTION_DESIGN.md` §8 READY 판정)
- 모든 신규 코드에 unit test, 전체 regression 통과
- 진행 상황이 `CLAUDE_SESSION_BOARD.md`에 계속 갱신됨
