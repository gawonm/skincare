# Evidence Storage ERD

> 범위: Evidence(MFDS/CIR/PubMed) 저장 구조 설계 문서. Claim(NIA)은 다루지 않는다 —
> `ClaimHit != EvidenceRecord`(`docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md` 8절).
> 이 문서는 `docs/erd/app.md`에 이미 반영된 `evidence_document`/`evidence_chunk`/
> `evidence_chunk_ingredient` 설계를 Evidence 저장 구조 하나만 놓고 정리한 참조 문서다 —
> `docs/erd/app.md`가 DB 전체 ERD의 단일 소스이고, 이 문서는 그중 Evidence 부분만 뽑아
> 설계 근거·의사결정 이유를 한곳에 모은 것이다. 둘이 어긋나면 `docs/erd/app.md`가 우선한다.
>
> **현재 상태 (2026-09-17 갱신)**: 사용자 승인 완료, `alembic upgrade`로 live `app` DB에
> 적용 완료. `evidence_document`/`evidence_chunk`/`evidence_chunk_ingredient` 테이블이 live에
> 존재하고, 니아신아마이드 PubMed 실 데이터 3건으로 BGE-M3 smoke도 PASS했다. embedding은
> 최초 승인 당시(`text-embedding-3-small`/`vector(1536)`)에서 `BAAI/bge-m3`(local)/
> `vector(1024)`로 변경 확정됐다 — 아래 설계는 이 최신 상태와 일치한다.
>
> **2026-09-21 갱신**: MFDS 전량 적재(11문서/8,288청크), CIR 10문서/56청크, PubMed 25문서/25청크를
> 합쳤다. 최종 합계는 `evidence_document` 46 / `evidence_chunk` 8,369 /
> `evidence_chunk_ingredient` 8,377이며 기준 dump는 `skincare_reference_2026-09-21_v4.dump`다.
> `rag_chunk`는 0건이며 MFDS를 재적재하지 않았다. 설계에
> 있던 `ix_evidence_chunk_content_bm25`는 실제 DB에 만들어지지 않았다(`docs/erd/app.md` 참고). 저장·적재 완료와
> runtime RAG(검색·Agent 연결·citation 표시) 완료는 별개이며, 후자는 Backend/Agent 문서를 따른다.

---

## 1. EvidenceDocument

MFDS/CIR/PubMed 근거 **문서** 단위 메타데이터. 근거 문서 하나(MFDS API 응답 1건, CIR
리포트 1건, PubMed 논문 1건)에 행 하나.

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | uuid | N | PK |
| source_id | text | N | 자연키(`PMID:16766489`, CIR 성분코드, MFDS 게시글ID). 단독 UNIQUE 아님 |
| source_type | text(enum) | N | `mfds`/`cir`/`pubmed_abstract`/`regulatory_other` |
| source_title | text | N | 문서 제목 |
| publisher | text | Y | 발행 기관/저널 |
| document_date | date | Y | 원 출처 발행/개정일 |
| url / doi / pmid | text | Y | 출처 식별자 |
| jurisdiction | text | Y | MFDS만 값 있음 |
| language | text | N | 기본 `'ko'` |
| evidence_level | text(enum) | N | `official_regulatory`/`expert_reviewed`/`peer_reviewed_study` — **문서 자체의 출처 신뢰도**(아래 5절) |
| raw_ingredient_names | text[] | N | 원본 표기 그대로(성분 FK 연결은 여기 없음, 4절) |
| document_status | text(enum) | Y | CIR 전용(`final`/`draft`/… ) |
| study_type | text(enum) | Y | PubMed 전용(`human_study`/`in_vitro`/… ) |
| formulation_type | text(enum) | Y | PubMed 전용(`single_ingredient`/`combination_formulation`, 7절) |
| claim_topics | text[] | N | 이 문서가 다루는 claim 주제 목록 |
| retrieved_at | timestamptz | N | 원문·metadata를 가져온 시각(`created_at`=DB 레코드 생성 시각과 분리) |
| created_at / updated_at | timestamptz | N | 공통 |

**Ingredient과의 직접 관계 없음** — 4절 참고.

---

## 2. EvidenceChunk

검색·임베딩 **단위**. 문서 하나가 여러 청크(page/section)로 쪼개질 수 있어 문서(1)와
청크(N)를 분리했다(`rag_chunk`는 "행 1개 = 문서 1개"만 가능해 이 구조를 못 씀 — 6절).

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | uuid | N | PK |
| document_id | uuid | N | FK → evidence_document.id, `ON DELETE CASCADE` |
| chunk_id | text | N | 결정적 자연키 `"{source_id}:{page}:{section}:{chunk_index}"`. **재수집 매칭 전용**, citation 조합에는 안 씀(7절) |
| source_type / source_title / url / doi / pmid / jurisdiction / evidence_level | — | — | document에서 비정규화(조인 회피, `rag_chunk` 관례와 동일) |
| page | int | Y | CIR PDF만 값 있음 |
| section | text | Y | PubMed는 `'abstract'` 고정, MFDS는 NULL |
| chunk_index | int | N | 같은 document 안 순번 |
| content | text | N | 임베딩 대상 원문(요약 안 함) |
| content_hash | text | N | `content`의 sha256(재수집 시 불변 여부 확인) |
| parser_version | text | N | 이 청크를 만든 파서 버전 |
| embedding | vector(1024) | N | `BAAI/bge-m3`(local), rag_chunk(`text-embedding-3-small`/1536)와 별도 확정(2026-09-17). 저장 테이블·검색 경로도 이미 분리 |
| embedding_model | text | N | 벡터를 만든 모델명 |
| created_at / updated_at | timestamptz | N | 공통 |

**Ingredient과의 직접 관계 없음** — 4절 참고.

---

## 3. `ClaimEvidenceLink`의 persistence 여부

**영속화하지 않는다.** DB 테이블이 없다.

- `ClaimEvidenceLink`(`claim_statement_id` + `query_anchor` + `hits: list[EvidenceHit]`)는
  Claim RAG 검색 결과와 Evidence RAG 검색 결과를 **런타임에 묶는 응답 객체**다
  (`docs/data/EVIDENCE_RAG_DESIGN.md` E절). 질문마다 검색이 다시 실행되므로 "이 claim의
  근거"라는 관계 자체를 미리 저장해 둘 이유가 없다 — 저장하면 Claim 쪽 재라벨링이나 Evidence
  쪽 재수집이 있을 때마다 무효화된 링크를 정리해야 하는 별도 유지보수 부담이 생긴다.
- **`support_level`(DIRECT/PARTIAL/UNSUPPORTED 등, `NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md`
  4절의 "Match" 열)도 이 객체가 소유한다.** 같은 evidence 문서도 어떤 claim과 짝지어지냐에
  따라 지지 강도가 달라질 수 있어(관계 속성), `EvidenceDocument`/`EvidenceChunk`에는 이
  컬럼이 없다 — `evidence_level`(문서 자체의 출처 신뢰도)과 절대 혼동하지 않는다(5절).
- 향후 "자주 나오는 claim-evidence 쌍을 캐시해서 재검색을 줄이자"는 필요가 생기면 그때
  별도 캐시 테이블을 검토한다(YAGNI — 지금 설계에는 없음).

---

## 4. Ingredient 관계 — 조인 테이블 `evidence_chunk_ingredient`

### 왜 단일 FK가 아닌가

최초 설계(1차)는 `evidence_document`/`evidence_chunk`에 각각 단일 `ingredient_id`
nullable FK를 두는 안이었다(`rag_chunk.ingredient_id`와 같은 패턴). **Session A가
`EvidenceQueryAnchor`가 병용/충돌/비교 질문(예: "레티놀이랑 AHA 같이 써도 되나요?")을 표현
하려면 단일 성분이 아니라 다중 `ingredient_refs`를 받아야 한다고 전달**했고, PM 세션이
이를 BLOCKER로 지정해 아래처럼 확정했다.

### `evidence_chunk_ingredient`

`evidence_chunk` ↔ `ingredient_master`의 순수 다대다 조인 테이블. 추가 속성이 없어
`EntityBase`를 상속하는 ORM 엔티티가 아니라 `sqlalchemy.Table`로 선언한다
(`models/evidence_chunk.py`).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| evidence_chunk_id | uuid | FK → evidence_chunk.id, `ON DELETE CASCADE` |
| ingredient_id | uuid | FK → ingredient_master.id, `ON DELETE CASCADE` |

- PK **복합** `(evidence_chunk_id, ingredient_id)` — 청크 하나가 여러 성분 행을 가질 수
  있고(병용 근거), 같은 성분을 같은 청크에 두 번 연결하는 중복만 막는다.
- 인덱스 `(ingredient_id, evidence_chunk_id)` — "이 성분과 관련된 모든 evidence_chunk"
  조회(검색 필터의 실제 사용 경로)를 PK의 역방향으로 지원.
- `EvidenceChunk.ingredient_ids: list[UUID]`(Pydantic, `EVIDENCE_RAG_DESIGN.md`)는 이
  테이블의 `(evidence_chunk_id=이 청크, ingredient_id)` 행 집합과 매핑한다.

### `EvidenceDocument`는 Ingredient과 직접 연결하지 않는다

`evidence_document`에는 `ingredient_id` 컬럼도, 별도 document-ingredient 조인 테이블도
없다. 문서의 성분 목록이 필요하면 **그 문서에 속한 청크들의 `evidence_chunk_ingredient`
관계에서 파생**한다(`SELECT DISTINCT ingredient_id FROM evidence_chunk_ingredient WHERE
evidence_chunk_id IN (해당 document의 chunk id들)`). 별도 테이블을 안 두는 이유는
document-level 성분 목록이 항상 chunk-level 목록의 합집합이라 중복 저장할 이유가 없고,
중복 저장하면 청크가 추가/삭제될 때마다 두 곳을 같이 갱신해야 하는 동기화 문제가 생기기
때문이다(YAGNI + 단일 진실 소스 원칙).

---

## 5. `evidence_level` vs `support_level` — 절대 혼동 금지

이 프로젝트에서 반복적으로 확인이 필요했던 지점이라 별도로 명시한다.

| 개념 | 소유 위치 | 성격 | 예시 값 |
|---|---|---|---|
| `evidence_level` | `EvidenceDocument`/`EvidenceChunk` 컬럼 | **문서 자체**의 출처 신뢰도(`rag_chunk.confidence_tier`와 같은 성격) | `official_regulatory`/`expert_reviewed`/`peer_reviewed_study` |
| `support_level` | `ClaimEvidenceLink`(비영속, 3절) | **claim-evidence 관계**의 지지 강도. 같은 문서도 짝지어진 claim에 따라 달라질 수 있음 | `DIRECT`/`PARTIAL`/`WEAK`/`UNSUPPORTED` |

`evidence_document`/`evidence_chunk` ORM에는 `support_level` 컬럼이 **존재하지 않는다**
(`tests/unit/test_evidence_storage_schema.py`가 이를 회귀 검증한다).

---

## 6. 기존 `evidence`/`rag_chunk`와의 관계

### `evidence`(기존 테이블, MFDS 8,288건)

- **원본 데이터는 그대로 둔다.** `evidence` 테이블을 삭제하거나 구조를 바꾸지 않는다.
- MFDS는 `evidence_document`/`evidence_chunk`로 **신규 적재**한다(재수집이 아니라
  기존 `evidence` 행을 문서/청크로 재투영하는 변환. **2026-09-20 전량 완료**) — `EvidenceDocument.source_id`에
  MFDS 자연키, `EvidenceChunk`는 MFDS의 "청킹 없음(1 API 응답 = 1 청크)" 원칙을 그대로
  따른다(`EVIDENCE_RAG_DESIGN.md` C절).
- 이 변환은 `data/scripts/mfds_evidence_backfill.py`와 `mfds_evidence_embedding_run.py`로 구현·실행됐다
  (이 문서를 쓸 당시에는 코드가 없었다).

### `rag_chunk`(기존 통합 임베딩 인덱스)

- **MFDS를 `rag_chunk`에 다시 적재하지 않는다.** Evidence RAG의 신규 쿼리 경로는
  `evidence_chunk` 하나만 본다 — Claim 검색(`rag_chunk`, 향후 Session A `claim_chunk`)과
  Evidence 검색의 이중 경로를 만들지 않는다는 원칙(PM 확정)에 따른다.
- `rag_chunk`에 이미 있는 과거 MFDS/Knowledgedata/NIA 청크는 이번 결정과 무관하게 그대로
  둔다(삭제·이관하지 않음) — 다만 신규 Evidence RAG 검색은 이를 쓰지 않는다.
- **왜 같은 테이블을 확장하지 않고 분리했는가**: `rag_chunk`는 "행 1개 = 문서 1개"를
  전제해 `page`/`section` 컬럼 자체가 없고, `source_table` CHECK 제약이 3개 값
  (`evidence`/`ingredient_knowledge_fact`/`nia_qa`)으로 하드코딩돼 있다. CIR(PDF page
  인용)/PubMed를 넣으려면 사실상 기존 테이블 재설계가 필요해 위험이 크다
  (`EVIDENCE_COVERAGE_AUDIT.md` 7절, Option A vs B 비교, Option B 채택).

### Knowledgedata(`IngredientKnowledgeFact`)

공식 Evidence corpus·citation source에서 **제외**한다(확정). `evidence_level` enum에
`structured_knowledge`가 없다는 점에서 스키마 레벨로도 이미 배제돼 있다.

---

## 7. PK / FK / UNIQUE 제약, page/section/DOI/PMID/formulation_type 저장 위치

### 제약 요약

| 테이블 | PK | UNIQUE | FK |
|---|---|---|---|
| `evidence_document` | `id` | `(source_type, source_id)` 복합 | 없음 |
| `evidence_chunk` | `id` | `chunk_id` | `document_id` → evidence_document.id (CASCADE) |
| `evidence_chunk_ingredient` | `(evidence_chunk_id, ingredient_id)` 복합 | (PK가 곧 UNIQUE) | `evidence_chunk_id` → evidence_chunk.id (CASCADE), `ingredient_id` → ingredient_master.id (CASCADE) |

`source_id` 단독 UNIQUE는 쓰지 않는다 — 같은 자연키 문자열이라도 `source_type`이 다르면
다른 문서일 수 있어서 `source_type`과 묶는다.

### page / section / DOI / PMID / formulation_type 저장 위치

| 필드 | 저장 위치 | 비고 |
|---|---|---|
| `page` | `evidence_chunk.page` (int, nullable) | CIR PDF만 값 있음 |
| `section` | `evidence_chunk.section` (text, nullable) | PubMed는 `'abstract'` 고정, MFDS는 NULL |
| `doi` / `pmid` | `evidence_document`에 원본, `evidence_chunk`에 **비정규화 복사**(조인 없이 citation 조합) | 두 테이블 다 있음(문서 레벨 원본 + 청크 레벨 비정규화) |
| `formulation_type` | `evidence_document.formulation_type`(enum, nullable) | **문서 레벨에만 있음**(청크에는 없음) — PubMed 전용, 복합 제형 연구(예: niacinamide+glycerin)를 단일 성분 효과로 일반화하지 않기 위한 구분 |

**Citation 조합 원칙**(2차 승인 조건, 7절): Backend는 `chunk_id` 문자열을 파싱하지 않는다.
`document_id`/`page`/`section`/`chunk_index`/`content_hash`/`parser_version`이 각각 독립
컬럼으로 있고, `url`/`doi`/`pmid`/`jurisdiction`도 (document에서 비정규화된) 독립 컬럼이므로
citation rendering은 검색 결과로 돌아온 `evidence_chunk`(+필요 시 `evidence_document`) row의
이 컬럼들을 그대로 조합해서 만든다. `chunk_id`는 재수집 시 매칭용 자연키로만 쓴다.

---

## 8. 이번 단계 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 성분 연결 | 단일 FK 아님 — `evidence_chunk_ingredient` 다대다 조인 테이블 |
| 문서 식별 | `UNIQUE(source_type, source_id)` 복합(단독 아님) |
| support_level | `ClaimEvidenceLink`(비영속) 소유, `EvidenceDocument`/`EvidenceChunk`에 없음 |
| embedding | `BAAI/bge-m3`(local), `vector(1024)` — 2026-09-17 확정. `rag_chunk`(`text-embedding-3-small`/1536)와 더 이상 모델·차원을 통일하지 않는다(저장 테이블·검색 경로는 애초부터 분리) |
| MFDS | `evidence_document`/`evidence_chunk`로 신규 적재, `rag_chunk` 재적재 안 함 |
| Knowledgedata | Evidence corpus·citation source에서 제외 |
| chunk identity vs citation locator | `chunk_id`(자연키, 매칭 전용) / `document_id`+`page`+`section`+`chunk_index`+`content_hash`+`parser_version`(citation 조합용 독립 컬럼) 분리 |
| retrieved_at | `evidence_document.retrieved_at`(신규 canonical 명칭). legacy `evidence.collected_at` 명칭 계승 안 함 |

---

## 관련 문서

- [docs/erd/app.md](../erd/app.md) — DB 전체 ERD(단일 소스). Evidence 부분은 이 문서와 동기화돼 있어야 한다
- [docs/data/EVIDENCE_RAG_DESIGN.md](EVIDENCE_RAG_DESIGN.md) — Pydantic 스키마 원안(`EvidenceDocument`/`EvidenceChunk`/`EvidenceQueryAnchor`/`EvidenceHit`/`ClaimEvidenceLink`)
- [docs/data/EVIDENCE_COVERAGE_AUDIT.md](EVIDENCE_COVERAGE_AUDIT.md) — `rag_chunk` vs 별도 테이블(Option B) 의사결정 근거
- [docs/data/NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md](NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md) — `support_level`(DIRECT/PARTIAL/WEAK) 실제 사례
- [docs/contracts/two-layer-rag-agent-backend-contract.md](../contracts/two-layer-rag-agent-backend-contract.md) — Claim/Evidence 레이어 분리 계약
- [docs/coordination/CLAUDE_SESSION_BOARD.md](../coordination/CLAUDE_SESSION_BOARD.md) — BLOCKER/NON-BLOCKER 최종 확정 상태(PM 세션 소유)
