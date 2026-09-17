# Claim (NIA) Storage ERD — DESIGN PROPOSAL, 사용자 승인 전

> **상태: PROPOSED.** `models/`·migration 미작성, DB 미적용. 이 문서는 설계·감사
> 결과물이다(2026-09-17). 사용자 승인 후에야 `models/claim_chunk.py` 등을 작성한다
> (CLAUDE.md 규칙 14 순서 그대로 — ERD 문서 → 사용자 확인 → 승인 후 구현).
>
> 범위: NIA Claim(검증 안 된 사용자 경험 기반 성분↔효능 언급) 저장 구조. Evidence
> (MFDS/CIR/PubMed)는 다루지 않는다 — `ClaimHit != EvidenceRecord`
> (`docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md` 8절). Evidence 저장 구조는
> [EVIDENCE_STORAGE_ERD.md](EVIDENCE_STORAGE_ERD.md) 참고 — 이 문서는 그 패턴을 최대한
> 그대로 따른다.
>
> **소유권 경계**: `data/scripts/nia_claim_document.py`(`ClaimDocument`/`IngredientRef`,
> FROZEN)와 ingestion policy는 Session A(`feature/claim-rag` worktree) 소유다
> (`docs/coordination/CLAUDE_SESSION_BOARD.md` §13). 이 문서는 그 FROZEN 계약을
> **입력**으로만 쓰고 수정하지 않는다 — DB 저장 구조 설계는 이 세션이 제안하지만, 실제
> `models/`/migration 작성과 병합은 Session A와 조율이 필요하다(CLAUDE.md 규칙 16, 경계
> 작업).

---

## 0. 기존 코드 조사 요약

| 대상 | 상태 | 위치 |
|---|---|---|
| `ClaimDocument`/`IngredientRef` | **FROZEN**, 실제 코드로 존재(dry-run only, DB insert 없음) | `data/scripts/nia_claim_document.py`(`feature/claim-rag` worktree) |
| `NiaClaimIngestionPolicy` | 존재, decision/priority 계산 로직 확정 | `data/scripts/nia_claim_ingestion_policy.py` |
| `ClaimHit` | **코드에 없음.** `agent/rag/schemas.py`에 개념만 주석으로 언급("Session A의 `ClaimHit`/`ClaimDocument`가 아직 이 브랜치에 없고... FROZEN, 별도 worktree") | 없음 — Session A가 아직 만들지 않음 |
| `EvidenceQueryAnchor` | **코드로 존재**(비영속 Pydantic), `origin=CLAIM_HIT`/`origin_ref: str \| None`(claim_statement_id 용도로 이미 예약됨)/`ingredient_refs: list[str]`까지 이미 구현됨 | `agent/rag/schemas.py:318` |
| Claim 전용 retrieval interface(`ClaimPort` 등) | **없음.** `agent/rag/ports.py`에는 `EvidenceRetriever`(rag_chunk 대상)만 있다 | `agent/rag/ports.py` |
| NIA production annotation 출력 | 코드 존재, 미실행(3,581건 아직 0건 완료) — 출력 형식은 pilot과 **동일**(`NiaLabelingDocument`/claim_ingestion jsonl 스키마 그대로, `annotation_version` 접두사만 `llm-production-*`) | `data/scripts/nia_production_annotation_run.py` |
| `EvidenceDocument`/`EvidenceChunk` | **LIVE**(2026-09-17 승인·적용, 이 문서와 같은 패턴의 선례) | `models/evidence_document.py`, `models/evidence_chunk.py` |
| Ingredient 결정적 매칭 | 기존 `IngredientNameMatcher`+`IngredientNameNormalizer` 재사용(신규 매칭 로직 없음) | `data/scripts/ingredient_name_matcher.py` |

핵심 발견: **`ClaimHit`는 아직 어디에도 구현돼 있지 않다.** Agent 쪽은 `EvidenceQueryAnchor`를
받을 준비(`origin_ref`, `ingredient_refs`)까지는 해놨지만, 그 앞단(Claim 검색 → `ClaimHit`
생성)은 통째로 비어 있다 — 이번 설계가 그 빈 자리를 채우는 첫 단계다.

---

## 1. 저장 단위 — `ClaimDocument`는 이미 statement 단위다

`ClaimDocument`(FROZEN)는 이름과 달리 **NIA 원본 레코드 하나가 아니라 statement 하나**를
표현한다(`statement_id`가 identity, `source_record_id`는 그 statement가 속한 레코드를
가리키는 FK 성격 필드). 즉 Evidence의 "문서 1개 = 청크 여러 개"(page/section 분할)와
달리, **Claim은 이미 최소 retrieval 단위(statement)로 원자화돼 있다** — 추가로 쪼갤
필요가 없다.

그래도 document/chunk 2계층으로 나누는 이유는 Evidence와 다르다:

- Evidence: 문서 1개가 여러 페이지/섹션 청크로 **실제로 나뉜다**(1:N, 진짜 분할)
- Claim: statement 하나가 곧 청크 하나(사실상 1:1)이지만, **레코드 단위 provenance**
  (`source_record_id`, `annotation_version`, `dataset_split`, `skin_concerns_raw` —
  `NiaLabelingDocument`가 갖고 `ClaimDocument`에는 없는 필드 포함)를 statement마다
  중복 저장하면 레코드 하나에 딸린 statement 5~10개마다 같은 값이 반복된다. Evidence의
  "document에서 비정규화해서 chunk가 들고 있는" 관례(조인 회피)와 반대로, Claim은
  **document에 record-level 정보를 한 번만 두고 chunk가 FK로 참조**하는 쪽이 낫다 —
  중복 저장할 이유가 없다(Evidence의 evidence_document/evidence_chunk 도 결국
  "chunk가 필요한 필드만 비정규화"이지 전부 중복은 아니다, 같은 원칙).

---

## 2. `claim_document` — NIA 원본 레코드 단위 provenance

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | uuid | N | PK |
| source_record_id | text | N | `NiaLabelingDocument.source.record_id`. **UNIQUE** — 레코드당 1행 |
| schema_version | text | N | `ClaimDocument.schema_version`(레코드 내 모든 statement가 동일) |
| annotation_version | text | N | `NiaLabelingDocument.annotation_version`(pilot: `llm-pilot-*`, production: `llm-production-*`) — **`ClaimDocument`엔 없는 필드**, mapper 호출 시점에 `NiaLabelingDocument`에서 직접 가져와야 함(주의사항 4절) |
| dataset_split | text(enum) | N | `ClaimDocument.dataset_split`(`training`/`validation`) |
| skin_concerns_raw | text[] | N | `ClaimDocument.skin_concerns_raw`(레코드 내 모든 statement가 동일 — `NiaLabelingDocument.case_context.skin_concerns_raw`) |
| production_ready | boolean | N | `NiaLabelingDocument.production_ready` — 사람 최종 검수 여부. Claim은 전부 `unverified`이므로 이 값과 무관하게 검색은 되지만, UI 필터링에 필요할 수 있어 보존 |
| created_at / updated_at | timestamptz | N | 공통 |

**Ingredient과 직접 관계 없음** — 3절 참고(Evidence의 `evidence_document`와 동일 원칙).

---

## 3. `claim_chunk` — 검색·임베딩 단위(statement 1개 = 청크 1개)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | uuid | N | PK |
| claim_document_id | uuid | N | FK → claim_document.id, `ON DELETE CASCADE` |
| statement_id | text | N | `ClaimDocument.statement_id`. **UNIQUE**(자연키, evidence_chunk의 `chunk_id`와 같은 역할 — 재수집/재라벨링 시 매칭용) |
| statement_type | text(enum) | N | `ClaimDocument.statement_type`(7종: case_observation/ingredient_effect_claim/precaution/usage_instruction/cause_claim/combination_claim/contextual_factor) |
| content | text | N | `ClaimDocument.content` — 임베딩 대상 원문(이미 statement_type별 필드 차이를 흡수한 통일 텍스트, mapper가 만듦) |
| source_spans | jsonb | N | `ClaimDocument.source_spans`(json_path/quote/start/end 튜플) — 원문 재검증용, Evidence의 citation locator와 같은 성격 |
| decision | text(enum) | N | `ClaimDocument.decision`(`blocked`/`human_review`/`ingestible_structured`/`ingestible_free_text`) — **운영 검색 인덱스 필터 컬럼**(4절) |
| priority | text(enum) | N | `ClaimDocument.priority`(`primary`/`secondary`) |
| support_status | text | N | `ClaimDocument.support_status` — 현재 스키마상 항상 `'unverified'`(3.1절 원칙의 근거 필드, Evidence의 `evidence_level`과 달리 값이 하나뿐이지만 미래 확장 대비 컬럼은 유지) |
| embedding | vector(1024) | N | `BAAI/bge-m3`(local) — 5절 근거 |
| embedding_model | text | N | 벡터를 만든 모델명 |
| created_at / updated_at | timestamptz | N | 공통 |

**PK/UNIQUE/FK**: PK `id`, UNIQUE `statement_id`, FK `claim_document_id` → `claim_document.id`
(CASCADE). 인덱스: `ix_claim_chunk_document_id`(document_id), `ix_claim_chunk_embedding_hnsw`
(HNSW cosine, evidence_chunk와 동일 파라미터 `m=16, ef_construction=64` 제안),
`ix_claim_chunk_decision`(decision — 운영 인덱스 필터링에 상시 쓰임, 4절).

---

## 4. `claim_chunk_ingredient` — Claim ↔ Ingredient 연결, **Evidence와 다른 점 있음**

`evidence_chunk_ingredient`를 그대로 본뜨되, **한 가지 구조적 차이**가 있다:
`IngredientRef`(FROZEN)는 `ingredient_id`가 **없어도** 성립한다(raw_name만 있는
unresolved/unresolved_ambiguous_family 케이스가 실제로 존재하고, ingestion policy는
이걸 `ingestible_free_text`로 그대로 색인 대상에 포함시킨다 — "raw_name으로 free-text
검색은 가능하다"는 게 이미 확정된 운영 정책, `nia_claim_ingestion_policy.py` 주석 참고).
Evidence 쪽 `evidence_chunk_ingredient`는 이런 "미해결 성분 언급" 개념이 아예 없어서
`(evidence_chunk_id, ingredient_id)` 둘 다 NOT NULL 복합 PK가 가능했지만, Claim은 그럴 수
없다.

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | uuid | N | PK(서러게이트 — `ingredient_id`가 NULL일 수 있어 복합 PK 불가) |
| claim_chunk_id | uuid | N | FK → claim_chunk.id, `ON DELETE CASCADE` |
| ingredient_id | uuid | Y | FK → ingredient_master.id, `ON DELETE CASCADE`. `matching_status='matched'`일 때만 non-null |
| raw_name | text | Y | `IngredientRef.raw_name` — unresolved든 matched든 원문 표기 있으면 항상 보존(원문 재검증·추후 재매칭용) |
| matching_status | text(enum) | N | `IngredientRef.matching_status`(`matched`/`unresolved`/`unresolved_ambiguous_family`/`rejected`) |
| role | text(enum) | N | `IngredientRef.role` — 현재 전부 `unspecified`(FROZEN 계약이 그렇게 확정함, 2절 참고), 컬럼은 미래 확장 대비 유지 |

**CHECK 제약**: `ingredient_id IS NOT NULL OR raw_name IS NOT NULL`
(`IngredientRef._check_has_some_identity`와 동일 불변조건을 DB 레벨에서도 강제).
**인덱스**: `ix_claim_chunk_ingredient_ingredient_id`(ingredient_id, claim_chunk_id) — "이
성분과 관련된 모든 claim_chunk" 조회용(evidence_chunk_ingredient와 동일 패턴). **UNIQUE
없음** — evidence_chunk_ingredient는 PK 자체가 UNIQUE였지만 여기는 서러게이트 PK라
`(claim_chunk_id, ingredient_id)` 부분 UNIQUE(ingredient_id가 non-null일 때만)를
추가로 고려할 수 있다 — 한 statement가 같은 성분을 두 번 언급하는 입력이 현재 mapper
로직상 발생하지 않아(`_ingredient_refs_of`가 매번 다른 subject에서 하나씩만 만듦)
필수는 아니라고 판단, 승인 시 재검토 여지로 남긴다.

---

## 5. Embedding contract — `BAAI/bge-m3`(local) 권장, `rag_chunk`/Evidence 어느 쪽도 "그냥 따라가기"로 정하지 않음

**비교 기준**(사용자 지시대로 — 단순히 어느 한쪽 값을 복사하지 않는다):

| 기준 | OpenAI `text-embedding-3-small`/1536 | `BAAI/bge-m3`(local)/1024 |
|---|---|---|
| **Claim → Evidence 2-layer 흐름에서 query embedding 재사용** | ❌ Evidence가 이미 BGE-M3로 확정돼 있어, Claim만 OpenAI를 쓰면 사용자 질의 하나당 **임베딩을 두 번**(Claim 검색용 OpenAI 1회 + Evidence 검색용 BGE-M3 1회) 호출해야 한다 — 매 query마다 반복되는 비용/지연 | ✅ 사용자 질의를 **BGE-M3로 한 번만** 임베딩해서 `claim_chunk` 검색과 `evidence_chunk` 검색 모두에 재사용 가능(둘 다 같은 벡터 공간) |
| **런타임 의존성** | Evidence 검색 때문에 어차피 `LocalBgeM3Embedder`(sentence-transformers, 로컬 프로세스 상주)가 이미 로드돼 있어야 함 — 여기에 OpenAI 클라이언트까지 추가하면 런타임에 임베딩 provider가 2종류 공존 | ✅ 추가 런타임 의존성 없음 — Evidence용으로 이미 로드된 모델을 그대로 재사용 |
| **비용** | 3,581건 corpus(레코드당 statement 5~10개 추정, 약 2~3만 chunk) + 개발 중 반복 재임베딩(매칭 로직/ingestion policy가 바뀔 때마다) 시 API 비용 누적 | ✅ 로컬 추론 — API 비용 없음. 반복 재임베딩 부담 없음 |
| **다국어(한국어) 성능** | 한국어 지원되지만 다국어 특화 모델은 아님 | ✅ BGE-M3는 100+ 언어 지원 설계, 한국어 비중이 높은 NIA 원문(claim content가 거의 전부 한국어)에 적합 |
| **기존 `rag_chunk`(1536, legacy)와의 호환** | ✅ 맞음 — 하지만 `rag_chunk` 전환 자체가 현재 DEFERRED(미결정)라 이 장점이 실제로 쓰일지 불확실 | ❌ 다름 — 단, `rag_chunk`와 Claim/Evidence는 이미 저장 테이블·검색 경로가 분리돼 있어(2-layer 설계 자체의 전제) 애초에 같은 테이블에서 안 만난다 |

**결론(권장)**: `BAAI/bge-m3`(local), `vector(1024)`. 근거는 "Evidence가 BGE니까"가 아니라
**Claim→Evidence 2-layer retrieval 구조에서 query embedding을 한 번만 계산해 재사용할 수
있다는 것**이 핵심이다(위 표 1행) — 이건 저장 방식이 아니라 **검색 경로의 실제 동작 방식**에서
나오는 이유라 "그냥 맞춘다"와는 다르다. `rag_chunk`(1536)는 이 결정과 무관하게 그대로 둔다
(전환 여부는 별도 결정, 이미 DEFERRED 상태 — `docs/coordination/CLAUDE_SESSION_BOARD.md`
참고).

---

## 6. Query Flow 검증 — `EvidenceQueryAnchor`와의 연결점

```
User query
  → Claim vector retrieval (신규, [NOT_IMPLEMENTED])
      claim_chunk를 embedding 유사도로 검색, decision IN
      ('ingestible_structured','ingestible_free_text')로 필터(운영 인덱스 정책 — Shared
      Decisions #6, CLAUDE_SESSION_BOARD.md)
  → ClaimHit 생성 ([NOT_IMPLEMENTED] — 타입 자체가 아직 없음)
      claim_chunk + claim_chunk_ingredient JOIN 결과로 구성 가능
  → Ingredient (claim_chunk_ingredient.ingredient_id, matching_status='matched'인 것만)
  → EvidenceQueryAnchor 생성 ([PROPOSED] adapter 필요, 아래 참고)
      origin=CLAIM_HIT
      origin_ref=claim_chunk.statement_id  ← 이미 딱 맞는 필드가 있음(agent/rag/schemas.py:340)
      ingredient_scope=SINGLE|MULTI        ← matched ingredient 개수로 결정
      ingredient_refs=[str(ingredient_id), ...]  ← 이미 list[str] 타입으로 준비돼 있음
      claim_topic=EvidenceClaimTopic       ← statement_type → claim_topic 매핑 필요(아래)
      query_text=claim_chunk.content       ← 자연스럽게 그대로 사용 가능
  → Evidence vector retrieval (evidence_chunk 대상 — 이것도 현재 [NOT_IMPLEMENTED],
      `EvidenceRetriever.search()`는 지금 rag_chunk만 봄, 별도 이슈)
  → Evidence metadata/citation (이미 evidence_chunk/evidence_document 컬럼으로 충분 - LIVE)
```

이 저장 구조(`claim_document`/`claim_chunk`/`claim_chunk_ingredient`)는 위 흐름에 필요한
데이터를 전부 표현할 수 있다 — **단, 저장 구조만으로는 흐름이 자동으로 동작하지 않는다.**
아래 3가지 Agent 코드가 없으면 이 storage는 그림의 떡이다(전부 이번 작업 범위 밖,
Backend/Agent 구현 변경 금지 지시에 따라 설계만 기록):

1. **`ClaimRetriever`/`ClaimPort`**(신규) — `agent/rag/ports.py`에 `EvidenceRetriever`와
   나란히 추가할 인터페이스. `claim_chunk`를 벡터 검색해 `ClaimHit`를 반환.
2. **`ClaimHit` 타입**(신규) — 지금 어디에도 없다. `docs/contracts/
   two-layer-rag-agent-backend-contract.md` 5절의 제안 필드 매핑을 그대로 따르면 된다
   (`statement_id`/`ingredient_id`/`raw_name`/`matching_status`/`claim`/`source_span`/
   `support_status`/`annotation_status`/`case_context` — 이 문서의 `claim_chunk`/
   `claim_chunk_ingredient` 컬럼과 거의 1:1 대응).
3. **`ClaimHitToEvidenceQueryAnchorAnchorAdapter`**(신규, 이름은 `agent/rag/schemas.py:325`
   주석이 이미 예고함) — `statement_type → EvidenceClaimTopic` 매핑이 특히 필요:
   `ingredient_effect_claim→EFFICACY`, `precaution→PRECAUTION`, `usage_instruction→
   USAGE_INSTRUCTION`, `combination_claim→COMBINATION`, 나머지(`case_observation`/
   `cause_claim`/`contextual_factor`)는 Evidence 검색 트리거로 안 쓰거나 별도 정책 필요
   (이번 설계 범위 밖, Agent 담당자 판단 필요 — Open Question 처리).

**Agent adapter 필요: YES.** 위 3가지 전부.

---

## 7. Production ingestion 경로(3,581건) — 스키마 변경 없이 그대로 확장 가능한지

**확인 결과: 그대로 확장 가능하다.** `nia_production_annotation_run.py`의 출력
(`nia_10s_30s_annotations_production.jsonl`, `nia_10s_30s_claim_ingestion_production.jsonl`)은
pilot의 `nia_10s_30s_annotations.jsonl`/`nia_10s_30s_claim_ingestion.jsonl`과 **완전히 같은
스키마**다(`NiaLabelingDocument`/`{record_id, statement_id, statement_type, decision,
priority}` 그대로, `annotation_version` 접두사만 `llm-production-*`로 다름). 즉:

```
production annotation(3,581건)
  → NiaClaimDocumentMapper.map_documents()  [기존 코드 그대로, 수정 없음]
  → ClaimDocument 리스트                     [FROZEN, 수정 없음]
  → decision 필터(운영 인덱스 정책)           [기존 정책 그대로]
  → claim_document/claim_chunk/claim_chunk_ingredient INSERT  [신규, 이번 설계]
  → BGE-M3 embedding                         [신규, 이번 설계]
```

이번 pilot smoke(12건, `backups/skincare_nia_evidence_smoke_2026-09-17.dump` 등)에서 쓴
"임시 smoke-only 테이블" 대신 이 정식 스키마가 만들어지면, **같은 매핑 코드로 그대로 3,581건
전체를 적재할 수 있다** — 스키마 변경이 production 규모 확장을 막는 요인이 아니다.

---

## 8. Open Questions

1. **`statement_type → EvidenceClaimTopic` 매핑의 나머지 4종**(`case_observation`/
   `cause_claim`/`contextual_factor`/`precaution`은 매핑했지만 `precaution`이 Evidence
   검색을 트리거해야 하는지도 재확인 필요) — Agent 담당자 확인 필요.
2. **`claim_chunk_ingredient`에 `(claim_chunk_id, ingredient_id)` 부분 UNIQUE를 넣을지** —
   현재 mapper 로직상 중복이 안 생기지만, 방어적으로 넣을지는 승인 시 결정.
3. **`rag_chunk`의 `nia_qa` 슬롯(현재 0건, 과거 문서 기준 최대 45,002건 언급)을 이
   신규 구조로 완전히 대체할지, 당분간 병존시킬지** — `rag_chunk` 전환 자체가 DEFERRED라
   이 질문도 함께 보류. 최소한 신규 Claim 검색 경로는 `claim_chunk`만 본다는 원칙은
   Evidence 쪽 결정(6절, `docs/erd/app.md` "결정 확정" 3번)과 동일하게 적용 가능해 보임.
4. **`production_ready`/사람 최종 검수 완료 여부를 `claim_document`에 저장했는데, 운영
   인덱스 필터에 반영할지** — 현재는 `decision` 컬럼만으로 필터링 계획. 검수 완료 전
   데이터를 이미 운영 검색에 노출하는 것이 맞는지는 정책 결정 필요(현재 0건 검수 완료 상태
   이므로 지금 결정하지 않아도 급하지 않음).

---

## 관련 문서

- [EVIDENCE_STORAGE_ERD.md](EVIDENCE_STORAGE_ERD.md) — 이 문서가 패턴을 따른 선례(LIVE)
- [docs/contracts/two-layer-rag-agent-backend-contract.md](../contracts/two-layer-rag-agent-backend-contract.md) — `ClaimHit` 제안 필드 매핑(5절), Agent 책임 경계
- [docs/coordination/CLAUDE_SESSION_BOARD.md](../coordination/CLAUDE_SESSION_BOARD.md) — Session A 소유 파일 목록, Shared Decisions(운영 인덱스 정책 등)
- `data/scripts/nia_claim_document.py`(`feature/claim-rag` worktree) — FROZEN `ClaimDocument`/`IngredientRef` 원본
- `data/scripts/nia_production_annotation_run.py` — production(3,581건) 출력 형식 원본
