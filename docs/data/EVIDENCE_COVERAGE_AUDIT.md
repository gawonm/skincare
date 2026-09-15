# Evidence Coverage Audit — Evidence RAG 구현 전 실사

> 목적: Evidence RAG 구현을 시작하기 전에, 실제 repository/DB에 있는 데이터가 MVP 5개
> 핵심 성분과 주요 claim을 얼마나 커버하는지 **직접 조회해서** 확인한다. 코드 구현은
> 하지 않는다. 기준 설계 문서: [EVIDENCE_RAG_DESIGN.md](EVIDENCE_RAG_DESIGN.md).

MVP 5개 핵심 성분: Vitamin C(아스코빅애씨드) / Niacinamide(나이아신아마이드) /
Retinol(레티놀) / AHA(글라이콜릭애씨드) / BHA(살리실릭애씨드)

---

## 0. 먼저 발견한 중요한 사실 — 현재 DB의 embedding 인덱스는 비어 있음

`docs/data/rag_pipeline_handoff.md`는 "rag_chunk 65,196건 임베딩 완료"라고 기록돼 있지만,
**이번 작업의 로컬 DB(`postgresql://app:app@localhost:5432/app`)를 직접 조회한 결과
`rag_chunk` 테이블은 0행**입니다.

```
Evidence 원본 행: 8,288건 (문서 기록과 일치)
IngredientKnowledgeFact 원본 행: 2,411건 (문서 기록과 일치)
rag_chunk(임베딩 인덱스): 0건 (문서 기록 65,196건과 불일치)
```

즉 **원본 데이터(Evidence/IngredientKnowledgeFact)는 이 DB에 그대로 있지만, 임베딩
인덱스는 이 환경에서 아직 만들어진 적이 없거나 다른 워크트리/DB 인스턴스에서만
만들어졌습니다.** 이 문서의 "coverage"는 전부 **원본 데이터 존재 여부** 기준이며,
"지금 당장 검색 가능한가"와는 별개입니다 — 실제 retrieval을 켜려면 이 gap부터
해소해야 합니다(이번 작업 범위 밖, embedding 재실행 필요).

---

## 1. MFDS Coverage (DB 직접 조회 결과)

| 성분 | Evidence 행 수 | 관할국 | 규제유형 | 비고 |
|---|---:|---|---|---|
| Vitamin C | **0** | — | — | 데이터셋에 아예 없음(화장품 배합제한 대상이 아니라는 뜻으로 해석되며 매칭 실패 아님, 기존 조사와 일치) |
| Niacinamide | **0** | — | — | 위와 동일 |
| Retinol | 3 | EU 1, 캐나다 2 | limited 3건 | **캐나다 2건은 내용까지 완전 동일한 중복**(원본 API 응답 자체의 중복, 적재 오류 아님 — 기존 조사와 일치) |
| AHA | 3 | 아세안 1, 캐나다 1, 대만 1 | limited 3건 | |
| BHA | **30** | EU/대만/아르헨티나/아세안/중국/일본/캐나다/한국/브라질 | limited 16, prohibited 14 | **5개 성분 중 유일하게 한국 기준 직접 확보**(살리실릭애씨드 0.5%, 인체세정용 2%) |

**MFDS가 실제로 담는 정보 유형**: `topic`이 전부 `cosmetic_use_restriction` 하나뿐이라,
**배합 한도/금지(=concentration_regulation)만** 다룹니다. efficacy, 일반적인 피부 자극
경고(precaution), usage, combination은 **MFDS 데이터 구조상 원천적으로 없음**
(`NOT_APPLICABLE`, 데이터 누락이 아니라 이 소스가 다루는 주제가 아님).

**Provenance 상태**: 전 행에 `source_url`(공식 출처), `jurisdiction`, `regulate_type`
확보됨. `ingredient_id`는 전 행 연결 완료(FK 필수 컬럼). **즉시 Evidence RAG에 쓸 수 있는
행과 없는 행의 구분은 없음 — 있는 행은 전부 바로 쓸 수 있는 상태.** 문제는 커버리지가
좁다는 것(Vitamin C/Niacinamide 전무, Retinol/AHA도 3건뿐)이지 품질이 아님.

---

## 2. CIR Coverage

**5개 성분 전부 repository 안에 실제 CIR 문서 파일이 없습니다.** `grep`으로 저장소
전체를 확인한 결과, CIR 관련 내용은 전부 "CIR을 인용했다"는 태그(`cites_cir` 필드,
`IngredientKnowledgeFact.copyright_resolution`/`source_reference`에 "CIR" 문자열이
있는지만 확인한 1단계)뿐이고, **실제 CIR 리포트 원문·URL·페이지 수를 담은 파일이나
스크립트는 존재하지 않습니다**(`data/scripts/`, `data/raw/`, `data/manual_review/`
전체 확인함).

| ingredient | document title | URL | status | local file | ingestion status |
|---|---|---|---|---|---|
| Vitamin C | 미확인 | 미확인 | 미확인 | 없음 | 미착수 |
| Niacinamide | 미확인 | 미확인 | 미확인 | 없음 | 미착수 |
| Retinol | 미확인 | 미확인 | 미확인 | 없음 | 미착수 |
| AHA(Glycolic Acid) | 미확인 | 미확인 | 미확인 | 없음 | 미착수 |
| BHA(Salicylic Acid) | 미확인 | 미확인 | 미확인 | 없음 | 미착수 |

**`final`/`amended_final`/`tentative`/`draft`/`rereview` 등 문서 상태도 확인 불가** —
애초에 어떤 CIR 보고서를 쓸지조차 아직 안 정했기 때문입니다.

**CIR 이용약관/수집 방식**: `docs/data/rag_pipeline_handoff.md`, `docs/data/data.md`에
기존 조사 기록이 있습니다 — "포털(`cir-safety.org`)에 성분 단위 조회만 가능하고 벌크
API가 없어, 이용약관 확인이 먼저 필요해 미착수"라고 이미 명시돼 있습니다. 이 문서를
넘어서는 새로운 ToS 조사는 하지 않았습니다.

**판정: `NEEDS_SOURCE_DECISION`** — 이용약관을 확인하기 전에는 5개 성분 중 단 1개도
착수할 수 없습니다.

`EvidenceDocument.document_status` 필드는 **필요합니다** — CIR 문서가 실제로
수집되면 draft/tentative 상태의 문서를 production 근거로 잘못 쓰는 걸 막을 방법이
지금 설계에 없습니다(6-D 참고).

---

## 3. PubMed Coverage

**repository에 PubMed 관련 데이터/코드/PMID 목록이 전혀 없습니다.**
`docs/data/EVIDENCE_RAG_DESIGN.md`(이번 세션에서 제가 작성한 설계 문서) 외에는
"pubmed"라는 문자열이 등장하는 파일이 없습니다 — 즉 **완전히 미착수 상태**입니다.

**우선 수집 성분 제안**: `Niacinamide` — 이유는 이번 39건 NIA pilot에서 **5개 성분 중
유일하게 실제 claim이 나온 성분**이기 때문입니다(아래 4절). Retinol/Vitamin C는 문헌
자체는 많지만 이번 pilot 데이터에서 claim이 아직 안 보여서, 어떤 claim을 논문으로
보완해야 하는지 근거가 약합니다.

**선정 기준(요청하신 8가지)을 그대로 채택**하고, 추가로 다음을 제안합니다:

- 복합 제형(formulation) 연구와 단일 성분 연구를 PMID 수집 단계에서부터 태그 구분
  (`study_type` 필드, 6-D 참고) — 나중에 필터링이 아니라 **수집 시점에 미리 구분**해야
  제품 효과를 성분 효과로 오인하는 실수를 원천 차단할 수 있음

**판정: `NEEDS_SOURCE_DECISION`** — 코드/쿼리 설계는 가능하지만 실제 PMID 후보를
아직 하나도 선정하지 않았습니다.

---

## 4. Ingredient × Claim Coverage Matrix

전체 표는 [data/processed/evidence_coverage_matrix.json](../../data/processed/evidence_coverage_matrix.json)에 있습니다(machine-readable). 아래는 요약입니다.

| Ingredient | Claim/Topic | NIA(39건 pilot) | MFDS | CIR | PubMed | Knowledgedata* | Status |
|---|---|---:|---|---|---|---|---|
| Vitamin C | efficacy | 0 | N/A | 미수집 | 미수집 | 있음 | PARTIAL |
| Vitamin C | precaution | 0 | 없음 | 미수집 | N/A | 있음 | PARTIAL |
| Vitamin C | concentration/regulation | 0 | 없음 | 미수집 | N/A | 없음 | **NO_EVIDENCE** |
| Vitamin C | usage_instruction | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| Vitamin C | combination | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| Niacinamide | efficacy | **5** | N/A | 미수집 | 미수집 | 있음 | PARTIAL |
| Niacinamide | precaution | 0 | 없음 | 미수집 | N/A | 있음 | PARTIAL |
| Niacinamide | concentration/regulation | 0 | 없음 | 미수집 | N/A | 있음(2~5%) | PARTIAL |
| Niacinamide | usage_instruction | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| Niacinamide | combination | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| Retinol | efficacy | 0 | N/A | 미수집 | 미수집 | 있음 | PARTIAL |
| Retinol | precaution | 0 | 없음 | 미수집 | N/A | 있음(임신부 금지 등) | PARTIAL |
| Retinol | concentration/regulation | 0 | 3건(중복 포함 2개 관할) | 미수집 | N/A | 있음 | PARTIAL |
| Retinol | usage_instruction | 0 | N/A | N/A | N/A | 있음(저녁 사용 권장) | PARTIAL |
| Retinol | combination | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| AHA | efficacy | 0 | N/A | 미수집 | 미수집 | 있음 | PARTIAL |
| AHA | precaution | 0 | 없음 | 미수집 | N/A | 있음 | PARTIAL |
| AHA | concentration/regulation | 0 | 3건(3개 관할) | 미수집 | N/A | 없음 | PARTIAL |
| AHA | usage_instruction | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| AHA | combination | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| BHA | efficacy | 0 | N/A | 미수집 | 미수집 | 있음 | PARTIAL |
| BHA | precaution | 0 | 없음 | 미수집 | N/A | 있음 | PARTIAL |
| BHA | concentration/regulation | 0 | **30건(9개 관할, 한국 포함)** | 미수집 | N/A | 있음 | **SUPPORTED** |
| BHA | usage_instruction | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |
| BHA | combination | 0 | N/A | N/A | N/A | 없음 | **NO_EVIDENCE** |

`*Knowledgedata`(`IngredientKnowledgeFact`)는 사용자가 지정한 MFDS/CIR/PubMed 3대 소스는
아니지만, 이미 DB에 있고 5개 성분 전부 1건씩 존재해 참고용으로 같이 표시했습니다 —
`RagConfidenceTier.STRUCTURED_KNOWLEDGE` 등급으로, `OFFICIAL_REGULATORY`(MFDS)보다
신뢰도가 낮습니다.

**NIA claim 관련 중요한 제약**: 위 "NIA" 열은 **39건 pilot 전체**를 뒤진 결과이며, 5개
성분 중 **Niacinamide만 실제로 등장**했습니다(5건, 전부 efficacy 관련: 피지조절/장벽강화/
색소침착 예방). 나머지 4개 성분은 이번 pilot 표본에 claim 자체가 없습니다 — **이건
Evidence 부재가 아니라 NIA claim 표본 부재입니다.** 전체 3,581건을 돌리면 달라질 수
있으나 확인 전입니다.

---

## 5. Coverage 판정 기준

| 상태 | 기준 |
|---|---|
| `SUPPORTED` | Evidence 원본 행이 존재하고 provenance(URL/jurisdiction 등) 확보, 여러 관할에 걸쳐 근거 충분(예: BHA 배합규제 — 9개국, 한국 포함) |
| `PARTIAL` | 관련 자료는 있으나 단일 출처·소수 관할뿐이거나(MFDS 1~3건), Knowledgedata 같은 낮은 신뢰도 소스로만 있음 |
| `SOURCE_EXISTS_NOT_INGESTED` | CIR/PubMed처럼 외부에 소스가 존재한다고 알려져 있으나 이 repository/DB에는 아직 없음 |
| `NO_EVIDENCE` | 확보한 어떤 소스에서도 이 claim topic에 대한 근거를 못 찾음(Vitamin C/Niacinamide의 concentration_regulation 등) |
| `NOT_APPLICABLE` | 그 소스가 애초에 그 claim type을 다루지 않음(MFDS는 efficacy/usage/combination을 원천적으로 안 다룸) |
| `NEEDS_REVIEW` | 문서 상태·claim 해석에 사람 판단 필요(CIR/PubMed는 아직 이 단계에도 못 감 — 소스 자체 미확보) |

---

## 6. Evidence RAG 구현 전 Gap 분석

### A. MFDS

- **충분한 claim type**: `concentration_regulation`뿐. 그마저 BHA만 `SUPPORTED`고 Retinol/AHA는 `PARTIAL`(3건), Vitamin C/Niacinamide는 `NO_EVIDENCE`(0건)
- **coverage 빈 성분**: Vitamin C, Niacinamide — MFDS만으로는 이 두 성분에 대해 낼 수 있는 답이 없음(다른 소스 필수)

### B. CIR

- **반드시 수집해야 하는 문서**: 5개 성분 각 1건 이상의 final safety assessment report. 특히 MFDS가 비어 있는 Vitamin C/Niacinamide가 최우선
- **성분당 최소 문서 수**: 1건(CIR은 성분당 보통 하나의 통합 리포트를 발행하므로 여러 개 모을 필요는 없음, 단 재평가(rereview)로 개정판이 있으면 최신 `final`/`amended_final`만 채택)
- **PDF parsing/page citation 구현 가능성**: 가능. `anthropic-skills:pdf` 등 PDF 텍스트 추출 도구로 페이지 단위 추출은 기술적으로 문제없음 — **막고 있는 건 기술이 아니라 이용약관 확인**

### C. PubMed

- **보완이 필요한 claim**: efficacy(효능) — MFDS는 원천적으로 못 다루고, Knowledgedata는 있지만 신뢰도가 낮음(구조화는 됐으나 공식 근거 아님)
- **우선 수집 성분/이유**: Niacinamide(이번 pilot에서 실제 claim이 나온 유일한 성분) → 피지조절(sebum control)/피부장벽(barrier)/색소침착(pigmentation) 관련 검색어로 시작
- **Abstract만으로 POC 가능한가**: **가능하다고 판단.** page 인용이 필요 없는 claim topic(효능 방향성 확인)이라 초록 수준으로도 "이 효능 주장을 뒷받침하는 연구가 있다/없다"는 1차 신호는 만들 수 있음. 단, 정량적 근거(농도별 효과 크기 등)가 필요하면 원문이 필요해 후순위로 남겨야 함

### D. Schema — 필드 추가 필요 여부

기존 `EvidenceDocument`(`EVIDENCE_RAG_DESIGN.md`)에 다음 3개 필드 추가를 제안합니다
(중복 필드는 만들지 않음 — `evidence_level`은 이미 있어 유지, `jurisdiction`도 이미 있음):

| 필드 | 타입 | 왜 필요한가 |
|---|---|---|
| `document_status` | `Literal["final","amended_final","tentative","draft","rereview","unknown"]` | CIR 전용 문제. `draft`/`tentative` 문서를 production 근거로 잘못 쓰는 걸 막을 필드가 현재 설계에 없음 |
| `study_type` | `Literal["human_study","in_vitro","animal_study","review","unknown"] \| None` | PubMed 전용. 복합 제형 연구와 단일 성분 연구, RCT와 비RCT를 구분 못 하면 "제품 효과를 성분 효과로 일반화"하는 실수(요청하신 금지 원칙)를 코드로 막을 수 없음 |
| `claim_topics` | `list[Literal["efficacy","precaution","concentration_regulation","usage_instruction","combination"]]` | 문서 하나가 여러 claim topic을 다룰 수 있어(예: CIR 리포트가 효능+안전성을 같이 다룸), 검색 시 claim topic으로 사전 필터링하려면 필요 |

세 필드 다 MFDS(이미 완료된 구조)에는 굳이 필요 없고(`document_status`는 항상 `final`,
`study_type`은 해당 없음), **CIR/PubMed를 실제로 수집할 때부터 필요**합니다 — 지금
당장 스키마를 바꾸지 않고 문서에만 반영해도 됩니다.

---

## 7. `rag_chunk` vs `evidence_chunk` 의사결정

| 기준 | 기존 `rag_chunk` 확장(Option A) | 새 `evidence_chunk`(Option B) |
|---|---|---|
| page/section provenance | **불가능** — 컬럼 자체가 없음, 추가하려면 마이그레이션+기존 65,196건(다른 환경) 전부 영향 | 처음부터 `page`/`section` 컬럼으로 설계 가능 |
| source document 개념 | 없음 — MFDS/KnowledgeFact/NIA 전부 "행 1개 = 문서 1개"로 가정, CIR/PubMed의 "문서 1개 = 여러 페이지/청크"와 근본적으로 안 맞음 | `EvidenceDocument`/`EvidenceChunk` 분리 설계와 자연스럽게 대응 |
| MFDS atomic evidence vs PDF document 차이 | `source_table` CHECK 제약이 `evidence`/`ingredient_knowledge_fact`/`nia_qa` 3개로 **하드코딩**돼 있어, CIR/PubMed를 추가하려면 이 제약 자체를 뜯어고쳐야 함(기존 3개 소스에 영향 위험) | 새 제약이라 위험 없음 |
| Claim RAG(NIA) vs Evidence RAG 책임 분리 | 섞임 — 지금도 NIA Q&A와 MFDS가 한 테이블에 같이 있어, "이건 claim이고 이건 evidence"라는 구분이 테이블 레벨에서 안 보임 | 명확히 분리됨 — Claim RAG는 여전히 `rag_chunk`(또는 NIA 전용), Evidence RAG는 `evidence_chunk` |
| migration 복잡도 | 낮아 보이지만, **기존 3개 소스 CHECK 제약과 FK unique 참조 구조를 다 건드려야 해서 실제로는 위험도가 큼** | 새 테이블 생성만 하면 됨, 기존 테이블 무영향 |
| retrieval filtering | source_table 값으로 구분 가능하나 이미 3개 값이 있어 쿼리가 더 복잡해짐 | Evidence 전용 쿼리로 단순 |
| citation 구현 | page/section이 없어 CIR/PubMed 인용을 codes-level로 렌더링할 필드 자체가 없음 | 설계대로 가능 |
| 향후 확장성 | MFDS/KnowledgeFact/NIA 3개 소스에 고정된 설계를 계속 우회해야 함 | 새 소스 추가가 기존 구조에 영향 없음 |

**추천: Option B(별도 `evidence_chunk` 테이블).** 근거: `models/rag_chunk.py`를 직접
확인한 결과 `source_table` CHECK 제약이 3개 값으로 하드코딩돼 있고 page/section
컬럼이 처음부터 없어서, Option A는 "확장"이 아니라 사실상 "기존 테이블 재설계"에
가깝습니다. 반면 Option B는 기존 Claim RAG(`rag_chunk`)를 전혀 건드리지 않고 독립적으로
진행할 수 있어 리스크가 낮습니다. (실제 테이블 생성/마이그레이션은 이번 작업 범위 밖.)

---

## 8. Next Implementation Tasks (제안, 실행 안 함)

1. `rag_chunk` 임베딩 인덱스가 이 환경에서 0건인 이유 확인 — 다른 워크트리 DB인지,
   재실행이 필요한지 사용자 확인
2. CIR 이용약관 확인 → 착수 가능 여부 결정(`NEEDS_SOURCE_DECISION` 해소)
3. PubMed: Niacinamide PMID 후보 5~10개 선정(수집은 다음 단계)
4. `EvidenceDocument`에 `document_status`/`study_type`/`claim_topics` 3개 필드 추가(스키마 문서 갱신, 코드 미착수)
5. `evidence_chunk` 신규 테이블 설계(마이그레이션은 실행하지 않고 설계만)

---

## 산출물

- 이 문서: `docs/data/EVIDENCE_COVERAGE_AUDIT.md`
- Machine-readable matrix: `data/processed/evidence_coverage_matrix.json`

---

## 최종 보고

```
EVIDENCE_COVERAGE_AUDIT

MFDS:
PARTIAL — 원본 데이터 품질은 좋으나(provenance 완비) 5개 성분 중 2개(Vitamin C, Niacinamide)는
데이터셋에 아예 없고, concentration_regulation 외 claim type은 구조적으로 못 다룸.
BHA만 SUPPORTED 수준.

CIR:
NOT_READY — repository에 실제 문서 0건. 이용약관 확인이 먼저 필요(NEEDS_SOURCE_DECISION).

PubMed:
NOT_READY — repository에 관련 데이터/코드 전혀 없음. 완전 미착수.

5-Ingredient Coverage:
  Vitamin C:    MFDS 없음 / CIR·PubMed 미수집 / NIA claim 0건 / Knowledgedata만 있음 → 근거 가장 약함
  Niacinamide:  MFDS 없음 / CIR·PubMed 미수집 / NIA claim 5건(유일하게 있음) / Knowledgedata 있음
  Retinol:      MFDS 3건(중복 2건 포함) / CIR·PubMed 미수집 / NIA claim 0건
  AHA:          MFDS 3건 / CIR·PubMed 미수집 / NIA claim 0건
  BHA:          MFDS 30건(한국 포함, 5개 중 최고) / CIR·PubMed 미수집 / NIA claim 0건

Critical Gaps:
1. 이 로컬 DB의 rag_chunk(임베딩 인덱스)가 0건 — 원본 데이터는 있지만 지금 당장 검색 자체가 안 됨
2. Vitamin C·Niacinamide는 MFDS에 아예 없어 CIR/PubMed 없이는 공식 근거를 하나도 못 냄
3. efficacy claim type은 5개 성분 전부 MFDS로 커버 불가 — CIR/PubMed 없이는 구조적으로 채울 수 없음
4. CIR·PubMed 둘 다 완전 미착수(문서 0건) — Evidence RAG의 실질 소스는 지금 MFDS 하나뿐
5. NIA claim도 39건 pilot 기준 5개 성분 중 4개가 아예 안 나와서, "Claim → Evidence" 흐름을
   테스트할 실제 claim 자체가 부족함

Recommended Next Step:
1. rag_chunk 0건 원인부터 확인(다른 환경 DB인지 재실행 필요한지) — 이게 안 풀리면 Evidence RAG를
   붙여도 기존 Claim RAG(NIA)조차 지금 검색이 안 됨
2. CIR 이용약관 확인(사용자 의사결정 필요) → 가능하면 Vitamin C/Niacinamide 우선 수집
3. PubMed는 Niacinamide로 소규모 시범(PMID 5~10개) 먼저 — 근거: 이번 pilot에서 실제 claim이
   나온 유일한 성분
4. evidence_chunk 신규 테이블 설계 확정(Option B) 후 실제 마이그레이션은 별도 승인 받고 진행

Files Created:
- docs/data/EVIDENCE_COVERAGE_AUDIT.md
- data/processed/evidence_coverage_matrix.json
```
