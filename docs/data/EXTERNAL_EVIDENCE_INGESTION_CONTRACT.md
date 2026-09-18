# External Evidence Ingestion Contract — PubMed + CIR

작성일: 2026-09-18
범위: AUDIT + DESIGN + 소규모 live source validation. Collector production 구현, DB
write, migration, NIA/Claim/Agent/Backend 코드 수정은 **하지 않았다.**

> 이 문서를 읽기 전에 먼저 `docs/data/EVIDENCE_RAG_DESIGN.md`(D절 `EvidenceQueryAnchor`)와
> `docs/data/EVIDENCE_STORAGE_ERD.md`를 읽는다. 이 문서는 그 둘이 이미 확정한 storage/anchor
> 계약을 **새로 만들지 않고** PubMed/CIR 두 source에 어떻게 적용할지만 다룬다.

---

## 1. Objective

NIA Claim(Windows 세션에서 3,581건 production annotation 진행 중, 이번 세션 시점 미완료)을
뒷받침할 External Evidence를 PubMed + CIR에서 확보해, 이미 구현·검증된
`EvidenceDocument → EvidenceChunk → evidence_chunk_ingredient → BGE-M3 → pgvector` 구조에
어떻게 적재할지 하나의 통합 contract로 확정한다. PubMed와 CIR은 서로 대체 관계가 아니라
병렬 Evidence source다. MFDS는 제거하지 않고 regulatory evidence 역할로 유지한다.

---

## 2. Current Evidence Storage (실측, origin/main 기준)

`git fetch origin` 후 확인한 `origin/main` HEAD: `252be14`(PR #37 머지). 최근 관련 merge:

| PR | 내용 |
|---|---|
| #33 | MFDS evidence document/chunk ingestion pipeline |
| #34 | NIA annotation version 안정화 |
| #35 | MFDS evidence BGE-M3 embedding pipeline |
| #37 | PubMed/CIR source acquisition research(이전 세션, 이 문서의 전 단계) |
| #38 | NIA labeling schema import fix |

**과거 문서(`docs/data/EVIDENCE_SOURCE_ACQUISITION_RESEARCH.md`, 이전 세션 작성)가 가정했던
"`Evidence` 단일 테이블만 존재, `EvidenceDocument`/`EvidenceChunk` 없음" 상태는 더 이상 사실이
아니다.** 그 사이 PR #33/#35로 2-레이어 구조가 실제로 구현·마이그레이션·insert smoke까지
끝났다. 이번 문서는 현재 코드를 기준으로 한다.

### 2.1 EvidenceDocument (`models/evidence_document.py`)

문서 단위 메타데이터. `source_type ∈ {mfds, cir, pubmed_abstract, regulatory_other}`,
UNIQUE `(source_type, source_id)`. CIR 전용(`document_status`), PubMed 전용
(`study_type`, `formulation_type`) 필드가 **이미 존재**한다. Ingredient FK 없음(4절 참고).

### 2.2 EvidenceChunk (`models/evidence_chunk.py`)

검색·임베딩 단위. `document_id` FK(CASCADE), `chunk_id`(자연키, UNIQUE), `page`/`section`
(CIR/PubMed 대비 이미 존재), `content`/`content_hash`/`parser_version`, `embedding
vector(1024)`. `source_type`/`source_title`/`url`/`doi`/`pmid`/`jurisdiction`/`evidence_level`은
document에서 비정규화.

### 2.3 evidence_chunk_ingredient

`evidence_chunk` ↔ `ingredient_master` 순수 다대다 조인 테이블(`Table`, ORM 엔티티 아님).
복합 PK `(evidence_chunk_id, ingredient_id)`. 문서 전체가 아니라 **청크 단위로 성분을
연결**한다(13절 참고).

### 2.4 Embedding

- provider: local
- model: `BAAI/bge-m3`
- dimension: 1024 (`EVIDENCE_EMBEDDING_DIMENSION`, `models/evidence_chunk.py`)
- `rag_chunk`(`text-embedding-3-small`/1536)와 완전히 분리된 별도 인덱스/경로

### 2.5 Migration

`11cdc111cf27_add_evidence_document_evidence_chunk_...`(2026-09-15) — `evidence_document`,
`evidence_chunk`(HNSW 인덱스 포함), `evidence_chunk_ingredient` 3개 테이블 생성. 실제
컬럼/제약을 위 2.1~2.3과 대조 확인했다(migration 파일 직접 읽음, 코드와 일치).

### 2.6 이미 완료된 검증 (재작업 금지)

- MFDS legacy evidence 8,288건 → `EvidenceDocument`/`EvidenceChunk` 매핑 로직
  (`data/scripts/mfds_evidence_mapper.py`) 구현 완료
- Mac local DB: `EvidenceDocument` 11건, `EvidenceChunk` 50건, `evidence_chunk_ingredient`
  50건 실제 insert smoke 검증 완료
- **니아신아마이드 PubMed 실 데이터 3건으로 BGE-M3 embedding smoke도 이미 PASS**
  (`EVIDENCE_STORAGE_ERD.md` 헤더, 2026-09-17) — 즉 PubMed 청크가 실제로 storage에
  들어간 전례가 이미 있다. 이번 문서는 이 전례를 일반화된 collector 계약으로 확장한다.
- `EvidenceQueryAnchor`는 설계 문서(`EVIDENCE_RAG_DESIGN.md` D절)일 뿐 아니라 **실제 코드**로도
  존재한다: `agent/rag/schemas.py`(`EvidenceQueryAnchor`, `EvidenceQueryOrigin`,
  `IngredientScope`, `IngredientMatchMode`, `EvidenceClaimTopic`), 단위 테스트
  `tests/unit/test_evidence_query_anchor.py`로 검증됨. **새 routing schema를 만들지 않고
  이것을 그대로 재사용한다.**
- MFDS embedding pipeline(`data/scripts/mfds_evidence_embedding_pipeline.py`)이 이미
  "batch embed → document_id 조회 → idempotent chunk insert → 배치 실패 시 건별 재시도"
  패턴을 구현·테스트했다 — PubMed/CIR collector도 이 패턴을 재사용한다(17절).

**따라서 이번 세션에서 새로 설계하지 않는 것**: EvidenceDocument/EvidenceChunk 스키마 자체,
evidence_chunk_ingredient 조인 구조, embedding provider/model/dimension, EvidenceQueryAnchor
필드 구조, embedding pipeline의 배치/재시도 아키텍처.

---

## 3. Source Responsibility Matrix

| Source | 주 대상 | evidence_level | jurisdiction | 비고 |
|---|---|---|---|---|
| **PubMed** | efficacy, adverse effect/precaution, (있으면) combination | `peer_reviewed_study` | 보통 NULL | 연구설계 편차 큼(`study_type`으로 구분) |
| **CIR** | safety, irritation/sensitization, toxicity, concentration/exposure, precaution, 사용조건 | `expert_reviewed` | 보통 NULL | 성분당 보통 1건, amended/rereview 있을 수 있음 |
| **MFDS** | 사용제한/금지/최대허용량/규제조건, jurisdiction별 규제 | `official_regulatory` | 값 있음(국가) | 이미 구현 완료, 역할 변경 없음 |

PubMed와 CIR은 대체 관계가 아니다 — 같은 성분·같은 claim_topic이라도 "과학적 관찰"(PubMed)과
"전문가 패널의 안전성 평가 결론"(CIR)은 서로 다른 provenance를 가진 **독립적인 Evidence**다
(15절에서 다시 다룬다).

---

## 4. Evidence Collection Target Contract

**결론: 새 schema를 만들지 않는다.** `agent/rag/schemas.py`의 `EvidenceQueryAnchor`가 이미
"ingredient × claim_topic → source 검색"을 표현하는 계약이다. "Evidence Collection Target"이라는
이름의 새 영속 테이블이나 DTO는 **불필요하다** — 이유:

- `EvidenceQueryAnchor`는 이미 `ingredient_refs`(성분), `claim_topic`(주제), `query_text`
  (검색어), `source_types`(선택적 source 필터, `EVIDENCE_RAG_DESIGN.md` D.5) 필드를 갖고
  있어, "ingredient × claim_topic → source routing" 요구를 그대로 만족한다.
- `EvidenceQueryAnchor`는 의도적으로 **비영속**(D.1, `EVIDENCE_RAG_DESIGN.md`)이다 — 매
  질문마다 새로 만들어지는 검색 입력이지 저장할 도메인 사실이 아니라는 기존 결정을 이
  문서에서 뒤집지 않는다.
- collector(PubMed/CIR)가 "무엇을 수집해야 하는가"를 결정하는 시점은 retrieval-time이 아니라
  **배치 수집 시점**이라 성격이 다르지만, 입력 형태(ingredient + claim_topic)는 동일하다 —
  collector는 `EvidenceQueryAnchor`를 그대로 만들어 쓰거나, `ingredient_refs`+`claim_topic`
  두 필드만 뽑아 쓰면 된다. 별도 schema를 새로 정의할 이유가 없다.

**collector 입력 계약(신규 코드 없음, 이번 문서가 명시만 함)**:

```
CollectionTarget = (ingredient_id: str, claim_topic: EvidenceClaimTopic)
```

이 튜플은 `EvidenceQueryAnchor`의 `ingredient_refs[0]`(SINGLE scope 기준) +
`claim_topic` 필드와 동일한 형태다. NIA Claim이 확정되면 `ClaimHitToEvidenceQueryAnchorAdapter`
(설계만 존재, 코드 미작성 — `EVIDENCE_RAG_DESIGN.md` D.3)와 같은 방식으로, Claim에서
`(ingredient_id, claim_topic)` 쌍 목록을 뽑아 collector에 넘기는 별도의 작은 어댑터가
필요해질 수 있다 — 이건 이번 세션 범위 밖이며, NIA 완료 후 별도 설계한다.

---

## 5. PubMed Source Contract

### Access

- NCBI E-utilities(`esearch`/`esummary`/`efetch`), REST, 공식 API. API key 불필요(있으면
  3→10 req/sec). 이번 세션에서도 실제로 키 없이 라이브 호출 성공.
- Automation feasibility: 높음. 이전 세션 조사(`EVIDENCE_SOURCE_ACQUISITION_RESEARCH.md`)와
  이번 재검증 결과 동일.

### Metadata

PMID, DOI, title, abstract, journal, publication date, MeSH terms, publication type, authors —
전부 확보 가능(이전 세션 실측 + 이번 세션 재확인, 12절).

### Document identity

**PMID를 primary natural key로 채택한다.** `source_id = f"PMID:{pmid}"` 형태(이미
`NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md` 5절에서 이 형식으로 실제 사용된 전례 있음,
`"PMID:16766489"`). 이유:

- `evidence_document` UNIQUE 제약이 `(source_type, source_id)`이므로, `source_type='pubmed_abstract'`
  고정에 `source_id`만 유일하면 된다 — PMID는 PubMed 색인 논문 전부에 부여되는 필수
  식별자라 커버리지 공백이 없다.
- DOI는 없는 논문이 실제로 존재한다(이전 세션 실측: PMID 22206073은 `doi=null`,
  `NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md` 5절). DOI를 primary key로 쓰면 이런 논문을
  아예 적재할 수 없거나 대체 키 로직이 추가로 필요해진다 — 불필요한 복잡도.
- `EvidenceDocument.pmid` 컬럼이 이미 별도로 존재하므로(2.1), `source_id`에 PMID를 넣고
  `pmid` 컬럼에도 같은 값을 중복 저장하는 게 이상해 보일 수 있으나, 이는 MFDS/CIR도 같은
  패턴을 따른다(`evidence_chunk`가 document 필드를 비정규화하는 것과 같은 이유 — citation
  조합 시 조인 없이 `pmid` 컬럼만 보면 되게 하려는 것) — `source_id`는 UNIQUE 제약용
  자연키, `pmid`는 citation 조합용 비정규화 컬럼으로 역할이 다르다.

### Chunk strategy

**Abstract 전체 = 1 chunk (옵션 A 채택).**

| 옵션 | 장점 | 단점 |
|---|---|---|
| A. Abstract 전체 = 1 chunk | 구현 간단, 문맥 손실 없음, provenance 1:1 | abstract가 길면 여러 주제가 섞일 수 있음 |
| B. Structured abstract section(BACKGROUND/METHODS/RESULTS/CONCLUSION) | Results/Conclusion만 검색 가능 | PubMed abstract가 항상 구조화 라벨을 갖지 않음(라벨 없는 논문은 결국 A와 동일) — 파싱 실패/누락 위험 |
| C. Claim-supporting sentence/span | 최고 정밀도, 정확한 citation | 구현 복잡도 최고, 문장 하나만 떼면 조건(연구 population, 농도 등)이 사라져 hallucination 위험 오히려 증가 가능 |

**결정 근거**: `EVIDENCE_RAG_DESIGN.md` C절이 이미 "논문 초록 — 청킹 없음(초록 전체 = 1 청크,
section='abstract')"로 확정했고(PubMed abstract는 보통 200~300단어로 이미 짧음), 실제
니아신아마이드 vertical slice(`NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md` 5절)도 이 형식으로
청크를 만들어 BGE-M3 smoke까지 통과시켰다. **이 문서가 새로 결정하는 게 아니라 이미 실행된
결정을 재확인하는 것이다.** `evidence_chunk.section = "abstract"` 고정값(2.2, ERD 7절과 일치).

옵션 B/C는 "우리 목적은 일반 논문 검색이 아니라 NIA Claim support retrieval"이라는 기준에서
평가하면, abstract 자체가 이미 충분히 짧고 A로도 claim support 신호(효능 방향성, 부작용 유무)를
얻기에 충분하다고 판단된다 — 정량적 근거(농도별 효과 크기 등)가 필요해지는 시점에만 옵션 C
재검토(Deferred, 20절).

### Ingredient linkage

`evidence_chunk_ingredient`를 그대로 재사용한다(새 matching architecture 불필요). 기존
`NiaIngredientMatchingStage`(NIA Claim의 raw_name → ingredient_id 매칭에 쓰이는 것과 동일
계열의 매칭 로직, `agent`/`data` 어느 쪽 기존 코드든 이미 있는 정규화 로직)를 재사용해
PubMed abstract에서 언급된 성분명을 `ingredient_master`에 매핑한다.

**Chunk 단위 연결**(Document 단위 아님) — 13절 사양대로. 한 논문이 여러 성분을 비교하는
경우(예: niacinamide vs retinol) chunk(=abstract 전체)가 두 성분과 모두 연결될 수 있다 —
abstract를 문장 단위로 안 쪼개므로(위 chunk strategy A) 완전한 "이 문장은 이 성분만"
분리는 안 되지만, `formulation_type=combination_formulation`(2.1에 이미 존재하는 필드)으로
"복합 언급"임을 표시해 단일 성분 효과로 오인되지 않게 한다(이미 확정된 필드 재사용, 신규
필드 없음).

### Citation

| PubMed 필드 | 저장 위치 | DIRECT/DERIVED/NOT_AVAILABLE |
|---|---|---|
| PMID | `evidence_document.pmid`, `evidence_chunk.pmid`(비정규화) | DIRECT |
| DOI | `evidence_document.doi`, `evidence_chunk.doi`(비정규화) | DIRECT (nullable — 일부 논문 없음) |
| title | `evidence_document.source_title` | DIRECT |
| journal | `evidence_document.publisher` | DIRECT |
| publication date | `evidence_document.document_date` | DIRECT |
| URL | `evidence_document.url` = `https://pubmed.ncbi.nlm.nih.gov/{pmid}/` | DERIVED(PMID로 조합) |
| MeSH terms | — | **NOT_AVAILABLE as a dedicated column** (아래 16절 schema gap 참고, 단 lossless 대안 있음) |
| publication type | `evidence_document.study_type`(근사 매핑) | DERIVED (publication type → study_type enum 값 매핑 규칙 필요, 완전 1:1 아님) |
| authors | — | **NOT_AVAILABLE** (아래 16절) |

### Schema gap

**NO_SCHEMA_CHANGE_REQUIRED** (16절 상세 판정 참고). PMID/DOI/publication_type은 기존 컬럼에
직접 매핑된다. MeSH/authors는 전용 컬럼이 없지만, `EvidenceDocument`에 JSON/구조화 컬럼이
없어도 **retrieval/citation에 필수가 아니므로**(citation 최소 후보는 PMID/DOI/title/
journal/date/URL이지 MeSH/authors가 아님 — 16절 요구사항 원문 기준) schema gap으로
보고하지 않는다. MeSH를 나중에 검색 필터로 쓰고 싶어지면 그때 별도 컬럼/조인 테이블을
검토한다(YAGNI).

---

## 6. CIR Source Contract

### Access

- 공식 API 없음. 두 사이트 확인(이전 세션 실측 재확인): `www.cir-safety.org`(현재 심사중
  draft PDF 직링크), `cir-reports.cir-safety.org`(완료된 성분의 최종보고서 상태조회 +
  PDF 뷰어, Power Apps/Dynamics 365 기반).
- robots.txt: `Crawl-delay: 10`, `/search/` 명시적 금지(실측: "Access denied" 확인됨).
  개별 성분 페이지/PDF는 disallow 목록에 없음.
- Automation feasibility: PubMed보다 낮음. `/view-attachment` PDF 엔드포인트가 세션 쿠키
  기반 301 리다이렉트 + 브라우저 JS 렌더링에 의존(이전 세션 실측: `curl`만으로는 HTML
  셸만 받아짐, headless 브라우저 필요 가능성 높음).

### Report identity

**후보 비교**:

| 후보 | 평가 |
|---|---|
| ingredient 이름 자체 | **부적합.** Salicylic Acid 사례(이전 세션 실측)처럼 한 ingredient에 원본(2003) + amended(2025) 두 건의 "Published Report"가 존재 — ingredient명만으로는 어느 버전인지 구분 불가 |
| CIR ingredient/report UUID (`cir-ingredient-status-report?id=<uuid>`) | 안정적으로 보이나, **이 UUID는 ingredient 단위이지 report(버전) 단위가 아니다** — 같은 UUID 페이지 안에 원본/amended 두 report가 같이 나열됨(이전 세션 실측: Salicylic Acid 페이지 하나에 2건) |
| attachment id (`/view-attachment?id=<uuid>`) | **report(버전) 단위로 유일.** 이전 세션 실측: Niacinamide report의 attachment id(`39cd1a17-...`)가 report 1건에 정확히 대응 |
| 저널 인용 문자열(`IJT 24(Suppl 5):1-31, 2005`) | 사람이 읽는 citation이지 안정적 자연키로 파싱하기엔 형식이 일정치 않음(그룹 리뷰는 페이지 범위가 다른 패턴) |

**채택: attachment id를 primary identity로 쓴다.** `source_id = f"cir_attachment:{attachment_id}"`.
근거: report(버전) 단위로 유일함이 실측 확인됐고, amended/rereview가 생겨도 새 attachment id를
받는 것으로 보여(다른 report=다른 PDF=다른 attachment) 버전 구분이 자연스럽게 된다.
ingredient UUID는 `raw_ingredient_names`(2.1, 이미 존재하는 배열 컬럼)에 원본 표기를 저장하는
용도로만 쓰고, primary key로는 쓰지 않는다.

**미해결**: attachment id가 CIR 내부적으로 항상 안정적인지(재크롤링해도 같은 id를 주는지)는
1회 관측만으로는 확정할 수 없다 — 실제 collector 구현 전 재확인 필요(20절 Deferred).

### PDF availability

접근 가능(이전 세션 실측: Niacinamide 최종보고서 PDF를 브라우저에서 실제로 렌더링,
탭 제목이 "Final Report of the Safety Assessment of Niacinamide and Niacin"으로 확인).
`curl`만으로는 HTML 셸만 받아지고 실제 PDF 콘텐츠는 브라우저 JS 실행이 필요해 보인다 —
headless 브라우저(Playwright 등) 기반 collector가 필요할 가능성이 높다.

### Chunk strategy

**page-aware 우선, section 제목 감지 시 세분화 (옵션 B/C 혼합, `EVIDENCE_RAG_DESIGN.md` C절과
동일한 결정 유지)**:

| 옵션 | 평가 |
|---|---|
| A. PDF page 단위 | 구현 쉬움, page 인용은 확보되나 안전성 결론(Conclusion)이 여러 페이지에 걸치면 청크가 결론을 완전히 못 담을 수 있음 |
| B. report section 단위 | Summary/Conclusion/Safety Assessment 등 CIR 보고서 관행적 섹션 구조를 살릴 수 있음(가설 — 이번 세션에서 실제 PDF 본문 텍스트 레이어는 열어보지 않아 섹션 헤더가 파싱 가능한 형태인지 미검증, 20절 Deferred) |
| C. section + paragraph/span | 가장 정밀하지만, page-aware보다 구현 난이도가 훨씬 높고, 레이아웃(2단 컬럼 등)에 따라 paragraph 경계 추출이 불안정할 위험 |

**결정: page-aware를 기본으로 하고, 파싱 가능한 section 제목을 만나면 그 경계로 추가
세분화한다.** LLM 요약문을 content로 만들지 않는다 — 원문 span 그대로 보존
(`EvidenceChunk.content` 규약과 동일, 2.2). `evidence_chunk.page`(2.2, 이미 존재하는
컬럼)에 페이지 번호를, `section`에 감지된 섹션 제목(Summary/Conclusion/Safety Assessment/
Use-Concentration/Irritation/Sensitization/Toxicity/Clinical Studies/Discussion 등)을 넣는다.

**미검증**: 이번 세션에서는 PDF 뷰어 렌더링(탭 제목 확인)까지만 했고, 실제 텍스트 레이어
추출(스캔 이미지 vs 디지털 텍스트, 섹션 헤더 파싱 가능 여부)은 확인하지 못했다 — 20절
Deferred Decisions로 남긴다.

### Ingredient linkage

`evidence_chunk_ingredient` 재사용. CIR 보고서는 대부분 단일(또는 성분군) 대상이라
"문서 전체 ingredient = 거의 모든 chunk에 연결"이 실제로 타당한 경우가 많지만, **무조건
전체 연결을 강제하지 않는다** — 보고서 안에 비교 성분/대사물(예: niacinamide 보고서에
niacin과의 관계 언급)이 등장하면 그 chunk에만 추가 ingredient를 연결한다. "문서 전체
ingredient를 모든 chunk에 무조건 연결"하는 자동 규칙은 만들지 않는다(요청사항 그대로
반영, 실제 판단은 collector 구현 시점에 chunk content를 보고 결정).

### Citation

| CIR 필드 | 저장 위치 | DIRECT/DERIVED/NOT_AVAILABLE |
|---|---|---|
| report title | `evidence_document.source_title` | DIRECT (PDF 뷰어 탭 제목에서 확인됨) |
| CIR report identity | `evidence_document.source_id`(attachment id 기반) | DIRECT |
| report status | `evidence_document.document_status`(2.1, 이미 CIR 전용으로 존재) | DIRECT — status 페이지의 "Published Report" 등 라벨을 enum 값으로 매핑 |
| publication/citation(저널 인용문자열) | `evidence_document.publisher`(예: "International Journal of Toxicology") + `document_date`(연도 파싱) | DERIVED (citation 문자열 파싱 필요) |
| URL | `evidence_document.url`(status 페이지 또는 attachment URL) | DIRECT |
| page | `evidence_chunk.page` | DIRECT (PDF page 단위 청킹 시) |
| section | `evidence_chunk.section` | DERIVED (섹션 헤더 감지 성공 시에만, 실패 시 NULL) |

### Schema gap

**NO_SCHEMA_CHANGE_REQUIRED.** `document_status`, `page`, `section`이 이미 존재하는 컬럼으로
필요한 필드를 전부 커버한다. attachment id 기반 `source_id`는 기존 `source_id: text` 컬럼에
그대로 문자열로 들어간다(별도 컬럼 불필요).

---

## 7. MFDS Existing Role

변경 없음. `evidence_document.source_type='mfds'`, `evidence_level='official_regulatory'`,
`jurisdiction`에 국가값, `document_status`/`study_type`/`formulation_type` 전부 NULL(2.1
주석과 일치). `data/scripts/mfds_evidence_mapper.py`/`mfds_evidence_embedding_pipeline.py`
그대로 유지 — 이번 세션에서 손대지 않았다. **역할 재확인**: MFDS는 "일반적인 NIA efficacy
Claim의 scientific support"가 아니라 REGULATORY evidence(사용제한/금지/최대허용량)로만
쓴다 — `EVIDENCE_COVERAGE_AUDIT.md` 1절이 이미 이 경계를 확정했다("MFDS는 efficacy/usage/
combination을 원천적으로 안 다룸, NOT_APPLICABLE").

---

## 8. EvidenceDocument Mapping (PubMed/CIR 요약)

5절/6절의 표를 하나로 합친 요약이다. "PubMed 논문 1편 = EvidenceDocument 1건",
"CIR safety assessment report 1개(attachment id 기준) = EvidenceDocument 1건" 두 가설
모두 **성립함을 확인했다**(PubMed는 니아신아마이드 3건 smoke로 이미 검증됨, CIR은 attachment
id의 report-level 유일성을 실측으로 확인).

| 필드 | PubMed | CIR |
|---|---|---|
| source_type | `pubmed_abstract`(고정) | `cir`(고정) |
| source_id | `PMID:{pmid}` | `cir_attachment:{attachment_id}` |
| source_title | 논문 제목 | 보고서 제목 |
| publisher | 저널명 | "International Journal of Toxicology" 등 |
| document_date | 논문 발행일 | 보고서 발행/개정 연도 |
| url | PubMed 링크(PMID로 조합) | status 페이지 또는 attachment URL |
| doi | 있으면 값, 없으면 NULL | 보통 NULL(CIR 페이지 자체는 DOI 미노출, 16절) |
| pmid | PMID | NULL |
| jurisdiction | NULL | NULL(CIR은 국가 규제 기관이 아니므로 MFDS와 다름) |
| evidence_level | `peer_reviewed_study` | `expert_reviewed` |
| document_status | NULL | `final`/`amended_final`/`tentative`/... |
| study_type | 연구설계 값 | NULL |
| formulation_type | 단일/복합 제형 구분 | NULL |
| claim_topics | 내용 기반 태깅(efficacy 등) | 내용 기반 태깅(precaution, concentration_regulation 등) |
| retrieved_at | 수집 시각 | 수집 시각 |

---

## 9. EvidenceChunk Strategy (요약)

- PubMed: abstract 전체 = 1 chunk, `section="abstract"`, `page=NULL`
- CIR: page-aware + section 감지, `page`=PDF 페이지 번호, `section`=감지된 섹션명(또는 NULL)

두 source 다 `chunk_id = "{source_id}:{page}:{section}:{chunk_index}"`(기존 자연키 패턴,
`EvidenceChunk.chunk_id` docstring과 동일 — MFDS mapper의 `build_chunk_natural_key`와
같은 패턴 재사용) 형태를 그대로 따른다.

---

## 10. Ingredient Linkage (요약)

두 source 다 `evidence_chunk_ingredient`를 그대로 재사용한다. 새 matching architecture는
만들지 않는다 — 기존 ingredient 정규화/매칭 로직(NIA Claim ingestion이 이미 쓰는 것과 동일
계열)을 collector가 호출해서 raw ingredient 표기를 `ingredient_master.id`로 resolve한다.
Document 단위 전체 연결을 기본값으로 삼되, chunk 내용에 따라 좁히거나 넓힐 수 있다(6절
CIR 절 참고, PubMed는 5절 참고).

---

## 11. Claim → Source Routing

기존 `EvidenceClaimTopic`(`agent/rag/schemas.py`, `models/evidence_document.py`에 이미
존재)을 그대로 쓴다. 새 topic 값을 추가하지 않는다.

| claim_topic | PRIMARY | SECONDARY | 비고 |
|---|---|---|---|
| `EFFICACY` | PubMed | CIR(안전성 평가 중 효능 부수 언급이 있을 때만) | MFDS는 usually not applicable(efficacy 데이터 구조 자체가 없음, `EVIDENCE_COVERAGE_AUDIT.md` 1절) |
| `PRECAUTION` | CIR | PubMed(부작용/자극성 임상 관찰) | MFDS는 해당 성분에 규제 제한이 있을 때만 추가(그 경우도 PRIMARY 급으로 격상 가능 — 규제 존재 자체가 가장 강한 precaution 신호) |
| `USAGE_INSTRUCTION` | CIR(안전성 평가가 사용조건을 support할 때) | MFDS(규제 조건이 있을 때) | PubMed는 evidence가 있을 때만 보조적으로 |
| `CONCENTRATION_REGULATION` | MFDS(배합한도/금지 데이터의 원래 목적) | CIR(안전 농도 상한 평가) | PubMed는 usually not applicable |
| `COMBINATION` | PubMed(병용 연구가 있으면) | CIR(안전성 평가가 병용/사용조건을 논의하면) | MFDS는 규제가 명시적으로 적용될 때만. **세 source 다 이 topic에서 가장 약함** — 5절/6절/기존 조사 공통 결론 |

이 매트릭스는 `EvidenceQueryAnchor.source_types`(선택적 필터, `EVIDENCE_RAG_DESIGN.md` D.5에
이미 존재하는 필드) 값을 claim_topic에 따라 어떻게 우선순위화할지 정하는 **정책**이지, anchor
schema 자체를 바꾸는 것이 아니다 — retrieval 구현 시점에 이 매트릭스를 "topic별 source_types
기본값" 형태로 코드화할 수 있다(이번 세션에서는 코드화하지 않음).

---

## 12. PubMed Query Experiment (이번 세션 live 검증)

키 없이 NCBI E-utilities 직접 호출. 대량 다운로드 없음, 쿼리당 top 1~3건만 확인.

| Query | Hit count | Top result relevance | 노이즈 | MeSH 유용성 | Publication type 유용성 |
|---|---:|---|---|---|---|
| `niacinamide AND acne` (이전 세션 재확인) | 94 | 낮음 — top 결과가 멜라스마/색소침착용 복합 세럼 임상시험(니아신아마이드는 부수 성분) | **있음**(단일 성분+topic만으로 부수 언급 논문이 상위에 옴) | 있음(자동 MeSH 번역이 `acne vulgaris`로 확장) | `Clinical Trial` 태그로 최소한 임상연구인지는 구분 가능 |
| `niacinamide AND sebum` | 20 | 이번 세션엔 top 결과 상세 미확인(건수만 재확인) | 미확인 | MeSH `sebum` 번역 확인 | — |
| `retinol AND photoaging` | 256(이전·이번 동일 count — 재현성 확인됨) | 미상세 확인 | 미확인 | `vitamin a`로 확장(retinol=vitamin A 동의어 취급, ingredient명과 MeSH 개념명 불일치 유의) | — |
| `salicylic acid AND acne` | 281(재현) | 미상세 확인 | 미확인 | `salicylic acid` MeSH 정확 매칭 | — |
| **`niacinamide AND adverse effects`(신규, 이번 세션)** | **3,778** | **매우 낮음** — top 결과가 "제초제 4종의 토양 내 분해 및 고추/담배 식물독성" 논문(완전히 무관한 환경독성학 분야) | **심각** | `adverse effects`가 MeSH Subheading으로 번역돼 니아신아마이드가 언급된 모든 물질/화합물 연구에 과확장 적용됨 | Publication type 필터 없이는 사실상 못 씀 |

**핵심 발견(신규)**: `adverse effects`처럼 일반적인 단어는 MeSH Subheading으로 번역되면서
"이 물질이 언급된 모든 논문"으로 과확장된다 — `precaution`/`adverse effect` claim_topic
쿼리를 만들 때는 반드시 도메인 제약(예: `AND (dermatology[journal] OR skin[MeSH] OR
"Skin/drug effects"[MeSH])` 또는 publication type 필터)을 같이 걸어야 한다. 이전 세션의
`niacinamide AND acne` 노이즈 사례와 같은 계열 문제이지만, 이번 사례가 훨씬 심각하다
(94건 중 관련성 낮은 논문 1건 섞임 vs 3,778건 중 top 결과부터 완전히 무관한 분야).

**결론**: PubMed automatic term mapping만으로는 precaution/adverse effect 쪽 쿼리 품질이
efficacy 쪽보다 낮다 — collector 구현 시 claim_topic별 쿼리 템플릿에 도메인 제약을 반드시
포함해야 한다(20절 Deferred: 정확한 제약 문구는 실제 구현 착수 시 결정).

---

## 13. CIR Report/PDF Experiment (이전 세션 실측 + 이번 세션 재확인)

이전 세션(`EVIDENCE_SOURCE_ACQUISITION_RESEARCH.md`)에서 이미 실측한 내용을 이번 문서의
identity/citation 설계에 그대로 반영했다(6절). 이번 세션에서는 대량 재크롤링을 하지 않고
그 결과를 재사용했다 — 핵심 재확인 사항만 요약:

- Niacinamide: 단독 항목 존재, status="Published Report", `IJT 24(Suppl 5):1-31, 2005`,
  attachment id로 PDF 실제 렌더링 확인(탭 제목 "Final Report of the Safety Assessment of
  Niacinamide and Niacin").
- Retinol: 단독 항목 존재(Retinyl Palmitate와 별개), status 페이지/PDF는 미확인(이전 세션
  범위).
- Salicylic Acid: **원본(2003) + amended(2025) 2건의 report**가 한 ingredient UUID 페이지
  안에 공존 — 이게 이번 문서 6절의 "attachment id를 report identity로 채택" 결정의 직접
  근거다.

---

## 14. Citation / Provenance

절대 원칙 재확인: **Citation은 LLM이 생성하지 않는다.** retrieved `EvidenceChunk` +
`EvidenceDocument`의 비정규화 필드(2.2)를 Backend가 코드로 조합한다(`EVIDENCE_RAG_DESIGN.md`
D.10, F절과 동일 원칙 — 이번 문서에서 재정의하지 않음).

PubMed/CIR 각각의 필드→컬럼 매핑은 5절/6절의 Citation 표를 canonical로 한다. MFDS는 기존
구현된 provenance contract(`data/scripts/mfds_evidence_mapper.py`) 그대로 유지.

---

## 15. Source Independence — 같은 Claim에 여러 source가 동시에 존재할 때

**기본 방향: 서로 다른 provenance를 가진 독립 Evidence로 보존한다.** Duplicate evidence로
취급해 하나만 남기지 않는다.

예시(Claim: "Retinol은 자극을 유발할 수 있다"):

| Source | 이 evidence가 의미하는 것 |
|---|---|
| PubMed | 임상/과학적 관찰(특정 연구의 특정 population/농도에서 관찰된 irritation) |
| CIR | 전문가 패널의 안전성 평가 결론(연구 여러 건을 종합한 authoritative 판단) |
| MFDS | 해당 시 규제 제한(공식 정부 기관의 법적 구속력 있는 조건) |

세 evidence는 신뢰도 등급(`evidence_level`)도 다르고(peer_reviewed_study < expert_reviewed
< official_regulatory 순으로 강해지는 것이 아니라, **각기 다른 종류의 authority**를
나타낸다 — `EVIDENCE_STORAGE_ERD.md` 5절이 이미 `evidence_level`을 "문서 자체의 출처
신뢰도"로 정의), retrieval 시 셋 다 반환하고 citation에 모두 표시하는 것을 기본으로 한다.
"하나로 합쳐서 보여주기"는 이 문서의 범위(storage/collector contract) 밖이며, Backend의
citation rendering 정책에서 다룬다.

---

## 16. Schema Gap Analysis

### PubMed: **NO_SCHEMA_CHANGE_REQUIRED**

| 요구 필드 | 확인 결과 |
|---|---|
| PMID | `evidence_document.pmid`, `evidence_chunk.pmid` 기존 컬럼 |
| DOI | `evidence_document.doi`, `evidence_chunk.doi` 기존 컬럼 |
| MeSH | 전용 컬럼 없음. **그러나 retrieval/citation 필수 요구사항이 아니다**(citation 최소
  후보는 PMID/DOI/title/journal/date/URL — 17절 원 요청 기준에 MeSH는 없음). 지금은
  gap으로 보고하지 않는다. 나중에 MeSH를 검색 필터로 쓰려면 `EvidenceDocument`에 JSON
  컬럼이나 별도 태그 테이블이 필요해질 수 있음(Deferred, 20절) |
| publication_type | 전용 컬럼 없음(`study_type`이 근사치이지만 1:1 매핑 아님 — 예: PubMed의
  `Clinical Trial`/`Review`/`Meta-Analysis` 태그 체계와 `EvidenceStudyType`(human_study/
  in_vitro/...)은 서로 다른 분류축). **lossless 보존은 가능**하다 — publication_type 배열
  자체를 저장할 필요는 없고, collector가 `study_type` enum으로 결정적 매핑(예: "Clinical
  Trial"→`human_study`, "Review"→`review`)만 하면 필요한 정보를 잃지 않는다. 원본
  publication_type 목록 전체를 보존하고 싶다면 `raw_ingredient_names`처럼 `text[]` 컬럼
  추가를 고려할 수 있으나, **retrieval에 필수는 아니라고 판단해 이번엔 gap 아님으로
  분류** |
| authors | 전용 컬럼 없음. citation 최소 후보(16절 원 요청: PMID/DOI/title/journal/date/URL)에
  authors가 없으므로 gap 아님 |

### CIR: **NO_SCHEMA_CHANGE_REQUIRED**

| 요구 필드 | 확인 결과 |
|---|---|
| report id (attachment id) | `evidence_document.source_id`에 문자열로 저장(전용 컬럼 불필요) |
| page | `evidence_chunk.page` 기존 컬럼 |
| section | `evidence_chunk.section` 기존 컬럼 |
| report status | `evidence_document.document_status` 기존 컬럼(CIR 전용으로 이미 존재) |
| citation(저널 인용문자열) | `publisher` + `document_date`로 분해 저장 가능(파싱 필요하지만
  컬럼 추가는 불필요) |

**두 source 다 schema 변경이 필요 없다는 결론은, 요청받은 "전용 컬럼이 없다고 곧바로
migration을 요구하지 않는다"는 원칙을 실제로 적용한 결과다** — 이미 있는 컬럼(특히 CIR 전용
`document_status`, PubMed 전용 `study_type`/`formulation_type`)이 이전 세션 설계
(`EVIDENCE_COVERAGE_AUDIT.md` 6-D)에서 제안된 그대로 이미 구현돼 있었기 때문에 이번 감사에서
추가로 막히는 지점이 없었다.

---

## 17. Idempotency

MFDS 패턴(`data/scripts/mfds_evidence_mapper.py`, `mfds_evidence_embedding_pipeline.py`)을
그대로 재사용한다 — 새 idempotency 전략을 만들지 않는다.

- **Document 레벨**: `UNIQUE(source_type, source_id)` — PubMed는 `PMID:{pmid}`, CIR은
  `cir_attachment:{attachment_id}`가 자연키이므로 재수집해도 같은 document를 다시 찾아간다
  (get-or-create).
- **Chunk 레벨**: `UNIQUE(chunk_id)`, `chunk_id = "{source_id}:{page}:{section}:{chunk_index}"`
  결정적 조합. 재수집 시 `content_hash`로 원문 불변 여부 확인(2.2에 이미 존재하는 컬럼).
- **Embedding 파이프라인**: `mfds_evidence_embedding_pipeline.py`의
  `load_existing_chunk_ids`→이미 임베딩된 chunk_id는 skip→배치 실패 시 건별 재시도 패턴을
  PubMed/CIR collector도 그대로 쓴다(`EmbedderProtocol`/`LoaderProtocol`은 source에
  무관한 일반 인터페이스로 이미 설계돼 있어 재사용 가능 — 코드 확인함, 이번 세션에서
  수정하지 않음).

---

## 18. Collector Architecture

### PubMed

```
CollectionTarget(ingredient, claim_topic)
        ↓
PubMed Query Builder (claim_topic별 쿼리 템플릿 + 도메인 제약, 12절 발견 반영)
        ↓
NCBI ESearch  (PMID candidates)
        ↓
ESummary / EFetch  (metadata + abstract)
        ↓
Relevance filtering  (publication type 필터 + 복합제형 감지 → formulation_type 태깅)
        ↓
EvidenceDocumentPlan  (MFDS mapper와 동일 패턴, source_id=PMID:{pmid})
        ↓
Abstract = 1 chunk  (section="abstract")
        ↓
EvidenceChunkStagingRecord
        ↓
Ingredient linkage  (기존 매칭 로직 재사용)
        ↓
MfdsEvidenceEmbeddingPipeline과 동일 구조의 파이프라인 재사용(BGE-M3 → pgvector)
```

### CIR

```
CollectionTarget(ingredient, claim_topic)
        ↓
CIR Ingredient Resolver  (ingredient명 → cir-reports.cir-safety.org UUID)
        ↓
Report page  (status 페이지에서 report 목록 조회, 여러 건이면 최신 final/amended_final만 채택)
        ↓
Report/PDF identity  (attachment id, 6절)
        ↓
PDF fetch  (headless 브라우저 필요 가능성 높음 — httpx만으로는 불충분, 이전 세션 실측)
        ↓
Page/section extraction  (텍스트 레이어 추출 가능 여부 미검증 — Deferred)
        ↓
EvidenceDocumentPlan  (source_id=cir_attachment:{id})
        ↓
Page-aware + section-aware chunking
        ↓
EvidenceChunkStagingRecord
        ↓
Ingredient linkage
        ↓
동일 embedding pipeline 재사용(BGE-M3 → pgvector)
```

두 collector 다 **기존 `EvidenceChunkStagingRecord`/`EvidenceDocumentPlan`
(`data/scripts/mfds_evidence_backfill_schemas.py`) 형태를 그대로 재사용**한다 — MFDS 전용
필드(`legacy_evidence_id`, `regulate_type` 등)만 빼고 공통 필드는 동일 구조이므로, 이번
세션에서 스키마를 새로 설계하지 않고 "MFDS 버전을 참고해 PubMed/CIR 버전을 만든다"는
방향만 확정한다(실제 Pydantic 모델 작성은 이번 세션 범위 밖).

---

## 19. Implementation Order

**SOURCE PRIORITY ≠ IMPLEMENTATION ORDER.** PubMed가 먼저 구현된다고 CIR Evidence의
중요도가 낮다는 뜻이 아니다 — CIR은 PRECAUTION/USAGE_INSTRUCTION topic에서 PRIMARY
source다(11절). 구현 순서는 순수하게 **기술적 난이도** 기준이다.

| 항목 | PubMed | CIR |
|---|---|---|
| API 존재 | 구조화된 공식 API(E-utilities) | 없음(웹/PDF 기반) |
| 인증/세션 | 불필요 | 세션 쿠키 기반 JS 렌더링 의존 가능성 |
| 파싱 대상 | 구조화된 XML/JSON | PDF(텍스트 레이어 미검증) |
| provenance 추출 | 직접 필드 매핑 | citation 문자열 파싱 + attachment id 관리 필요 |
| **구현 난이도** | **낮음** | **높음** |
| **Evidence 중요도(claim_topic 커버리지)** | efficacy/precaution 강함 | precaution/usage_instruction에서 PRIMARY, PubMed와 동등하게 중요 |

**권장 구현 순서**: PubMed collector 먼저(기술 리스크 낮고, 이미 니아신아마이드 3건으로
smoke 검증까지 끝난 상태라 확장이 자연스러움) → CIR collector(PDF 텍스트 추출 가능성부터
먼저 소규모로 검증한 뒤 착수). 이 순서는 **구현 착수 순서일 뿐, CIR의 evidence 가치를
낮게 평가한다는 뜻이 아니다.**

---

## 20. Implementation Checklist (NIA 완료 후, 별도 세션에서 착수)

- [ ] `ClaimHitToEvidenceQueryAnchorAdapter` 또는 유사한 "Claim → (ingredient, claim_topic)
      목록" 어댑터 구현 (4절)
- [ ] PubMed collector: claim_topic별 쿼리 템플릿 + 도메인 제약(12절 발견 반영, 특히
      precaution/adverse effect 계열 쿼리)
- [ ] PubMed `EvidenceDocumentPlan`/`EvidenceChunkStagingRecord` 변형 작성(MFDS mapper
      패턴 재사용, 18절)
- [ ] CIR: attachment id 안정성 재확인(20절 미해결 항목), PDF 텍스트 레이어 추출 가능
      여부 소규모 검증(스캔 이미지 여부)
- [ ] CIR collector: headless 브라우저 기반 PDF fetch 구현, section 헤더 감지 로직
- [ ] 두 collector 다 `MfdsEvidenceEmbeddingPipeline`과 동일한 `EmbedderProtocol`/
      `LoaderProtocol` 구조로 연결(17절)
- [ ] Claim topic별 source routing 매트릭스(11절)를 실제 retrieval 정책 코드로 반영 여부
      결정(이번 문서는 정책만 기술, 코드화는 별도 결정)

---

## Deferred Decisions

1. **CIR attachment id의 장기 안정성** — 1회 관측만으로 재크롤링 시에도 동일 id를 주는지
   확정 못 함. 실제 구현 전 재확인 필요.
2. **CIR PDF 텍스트 레이어 추출 가능 여부**(스캔 이미지 vs 디지털 텍스트) — 미검증.
3. **CIR section 헤더 파싱 규칙** — 실제 PDF 본문을 열어 Summary/Conclusion 등 섹션
   제목의 정확한 문자열 패턴을 확인해야 함.
4. **PubMed precaution/adverse effect 쿼리의 정확한 도메인 제약 문구** — 12절에서
   문제를 확인했으나 최종 필터 문법(예: MeSH qualifier 조합)은 collector 구현 착수 시
   결정.
5. **PubMed MeSH 전용 컬럼 필요 여부** — 지금은 NO_SCHEMA_CHANGE_REQUIRED로 판정했으나,
   나중에 MeSH 기반 필터링이 실제 요구사항이 되면 재검토.
6. **COMBINATION claim_topic의 구조적 약점** — 세 source 다 약함(11절). 별도 source
   조사가 필요할 수 있음(이번 세션 범위 밖).
7. **CollectionTarget을 별도 영속 테이블로 만들지 여부** — 이번 문서는 "불필요, anchor
   재사용으로 충분"으로 판단했으나(4절), 실제 배치 수집 스케줄링/추적 요구가 구체화되면
   (예: "이 ingredient×topic은 이미 수집 시도했는지" 추적 필요) 재검토될 수 있음.
