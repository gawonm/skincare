# Evidence RAG 설계 (구현 전 데이터 계약)

> 범위: 이 문서는 설계만 다룬다. crawling·embedding·DB 마이그레이션·retrieval 구현은
> 포함하지 않는다. Claim RAG(NIA annotation)는 1차 완료 상태로 간주하고, 여기서는
> "Claim RAG가 찾은 claim을 실제 근거 문서로 추적하는" Evidence RAG의 데이터 구조만
> 정의한다.

```
사용자 질문
→ Claim RAG (NIA annotation) → claim 추출
→ Claim → Evidence query 생성
→ Evidence RAG → 근거 문서 검색
→ 답변 생성 (citation은 LLM이 아니라 코드가 metadata로 렌더링)
```

---

## A. Source 전략

| source | 역할(적합한 claim) | 신뢰도 | 형식 | page/section | DOI/PMID/URL | 수집 난이도 | MVP 우선순위 |
|---|---|---|---|---|---|---|---|
| **MFDS** | `precaution`(배합제한·주의) | 최상(공식 규제기관) | API(JSON), 이미 `Evidence` 테이블로 구조화 완료 | 해당 없음(원문서가 아니라 API 응답 자체가 atomic fact) | URL 있음, DOI/PMID 없음 | 낮음(이미 8,288건 적재 완료) | **1 — 이미 존재, 확장만 필요** |
| **CIR** | `ingredient_effect_claim`/`precaution`(안전성 평가) | 높음(전문 패널 리뷰) | PDF 보고서(cir-safety.org) | 있음(PDF page, "Safety Assessment/Discussion/Conclusion" section) | URL 있음, DOI/PMID 없음(보고서 자체 식별자만) | **높음** — 벌크 API 없어 성분 단위 개별 조회만 가능(data.md 기존 조사 결과), 이용약관 확인 선행 필요 | **2 — 핵심 성분 5종만 우선** |
| **논문(PubMed abstract)** | `ingredient_effect_claim`(효능 근거), `combination_claim`(병용 효과) | 편차 큼(저널·연구설계별) | PubMed API(초록만 무료), 원문은 대부분 유료 | 초록 단계는 없음(원문 확보 시에만 의미 있음) | PMID/DOI 둘 다 확보 쉬움 | 중간(API 무료, 초록만) | **3 — 초록만, 성분 1~2종 시범** |
| **기타 공식 regulatory(EU CosIng, ECHA 등)** | `precaution`/`usage_instruction`(국가별 규제 차이) | 최상 | 사이트별 상이 | 사이트별 상이 | URL만 | 중간~높음 | **4 — MVP 밖.** MFDS가 이미 한국 기준을 커버해 국내 서비스엔 우선순위 낮음 |

**claim type과의 궁합 요약**

- `ingredient_effect_claim` → CIR(안전성 관점 효능 언급) + 논문(효능 직접 근거)이 핵심, MFDS는 배합 여부만 확인 가능(효능 근거 아님)
- `precaution` → MFDS(배합제한) + CIR(안전성 평가)가 강함
- `usage_instruction` → 공식 문서가 사용법을 세세히 규정하는 경우는 드묾 — Evidence RAG로 강하게 뒷받침하기 어려운 claim type. **근거보다는 claim 자체(NIA 원문)로 남기는 게 현실적**
- `combination_claim` → 병용 조합 자체를 다루는 공식 문서가 매우 드묾. Evidence RAG 매칭률이 가장 낮을 것으로 예상 — MVP에서 이 타입은 기대치를 낮게 잡는다

---

## B. Evidence document / chunk schema

기존 `models/rag_chunk.py`(`RagChunk`)의 관례(원본 테이블 join을 피하려 `source_title`/`source_url`/`citation_refs`를 청크에 비정규화해서 그대로 들고 있음)를 그대로 따른다 — 새 개념을 만들지 않는다. 다만 **CIR/논문 PDF·HTML은 page/section이 있는 진짜 "문서"라서, MFDS처럼 "API 응답 1건 = 청크 1건"으로 끝나지 않는다.** 그래서 문서 단위(`EvidenceDocument`)와 청크 단위(`EvidenceChunk`)를 분리한다.

```python
class EvidenceSourceType(StrEnum):
    MFDS = "mfds"
    CIR = "cir"
    PUBMED_ABSTRACT = "pubmed_abstract"
    REGULATORY_OTHER = "regulatory_other"


class EvidenceLevel(StrEnum):
    """RagConfidenceTier와 같은 목적, Evidence RAG 전용 문서 신뢰도."""
    OFFICIAL_REGULATORY = "official_regulatory"      # MFDS 등
    EXPERT_REVIEWED = "expert_reviewed"               # CIR
    PEER_REVIEWED_STUDY = "peer_reviewed_study"        # 논문


class EvidenceDocument(BaseModel):
    """문서 단위 메타데이터. 청크가 이 값을 비정규화해서 그대로 상속한다."""
    source_id: str                       # 안정적 자연키: CIR 성분코드, PMID, MFDS 게시글ID 등
    source_type: EvidenceSourceType
    source_title: str
    publisher: str | None = None
    document_date: date | None = None
    url: str | None = None
    doi: str | None = None
    pmid: str | None = None
    jurisdiction: str | None = None      # MFDS="한국", CIR/논문은 보통 None
    language: str = "ko"
    evidence_level: EvidenceLevel
    ingredient_ids: list[UUID] = []      # 문서 전체가 다루는 성분(문서 레벨 태깅)
    raw_ingredient_names: list[str] = []


class EvidenceChunk(BaseModel):
    """검색·임베딩 대상 단위. document 메타데이터를 비정규화해서 들고 있다
    (RagChunk의 source_title/source_url 관례와 동일)."""
    chunk_id: str                        # 결정적 조합: f"{source_id}:{page}:{section}:{chunk_index}"
    source_id: str                       # EvidenceDocument.source_id
    source_type: EvidenceSourceType
    source_title: str
    page: int | None = None
    section: str | None = None
    chunk_index: int
    content: str                         # 원문 그대로. 요약 안 함
    url: str | None = None
    doi: str | None = None
    pmid: str | None = None
    jurisdiction: str | None = None
    evidence_level: EvidenceLevel
    ingredient_ids: list[UUID] = []       # 청크가 실제로 언급하는 성분(문서 레벨보다 좁을 수 있음)
```

이 스키마는 향후 실제 DB 테이블(`evidence_chunk` 같은)로 옮길 때의 필드 설계이지, 이번 단계에서 테이블을 만들지는 않는다.

**기존 `rag_chunk` 테이블과의 관계 — 판단 필요**: 현재 `RagChunk`는 `source_table` CHECK 제약이 `evidence`/`ingredient_knowledge_fact`/`nia_qa` 세 값으로 하드코딩돼 있고 `page`/`section` 필드 자체가 없다. CIR/논문처럼 page 단위 인용이 필요한 소스를 같은 테이블에 넣으려면 제약과 컬럼을 확장해야 한다. 이번 설계에서는 **기존 `rag_chunk`를 확장할지, `evidence_chunk`를 별도 테이블로 둘지 결정하지 않았다** — 다음 단계(실제 DB 스키마 작업) 시작 전 확인이 필요하다.

---

## C. Chunking 전략

| source | 전략 | 이유 |
|---|---|---|
| MFDS | 청킹 없음(1 API 응답 = 1 청크) | 이미 원자적 사실(claim+conditions). 기존 `Evidence`/`RagChunk` 방식 그대로 유지 |
| CIR(PDF) | **page-aware 우선, 그 안에서 section 제목 감지 시 section 경계로 세분화** | PDF 페이지가 이미 물리적 인용 단위("p.24"). "Safety Assessment/Discussion/Conclusion" 같은 고정 섹션 제목이 있으면 그 경계도 같이 기록 |
| 논문 초록 | 청킹 없음(초록 전체 = 1 청크, section="abstract") | PubMed 초록은 보통 200~300단어로 이미 짧아 더 쪼갤 이유가 없음 |
| (참고) fixed-size chunking | **채택 안 함** | citation 경계(페이지/섹션)와 무관하게 잘라 metadata가 청크 내용과 어긋날 위험. 사용자가 요청한 "요약보다 원문 span 유지" 원칙과도 상충 |

우선순위: **section-aware 가능하면 최우선 → 없으면 page-aware → 그래도 너무 길면 paragraph 단위로만 보조적으로 세분화**(paragraph 단위로 나눌 때도 페이지 경계를 넘지 않는다). 요약은 이번 설계에 포함하지 않는다 — 정말 청크가 임베딩 모델 한도를 넘길 때만 후순위로 검토한다.

---

## D. Claim → Evidence Query Bridge

Claim RAG의 `nia_10s_30s_claim_ingestion.jsonl`(statement_id/decision/priority)과 실제 annotation(`ingredient_effect_claim.subject` 등)을 합쳐 아래 anchor를 만든다. **이번 단계에서는 이 표현만 정의하고 실제 검색은 실행하지 않는다.**

```python
class EvidenceQueryAnchor(BaseModel):
    claim_statement_id: str
    claim_topic: Literal["effect", "precaution", "usage", "combination"]
    anchor_type: Literal["structured", "free_text"]   # Case A / Case B
    ingredient_id: UUID | None = None                  # anchor_type=structured일 때만
    raw_name: str | None = None
    raw_name_ko: str | None = None
    query_terms: list[str]                              # en/ko 둘 다, 검색 실행 전 후보 문자열
```

**예시 (Case A, ingredient_id 있음)**

입력 — `ingredient_effect_claim`: `subject={raw_name: "NIACINAMIDE", raw_name_ko: "나이아신아마이드", ingredient_id: "<uuid>", matching_status: "matched"}`, `object="피지 조절"`

```json
{
  "claim_statement_id": "COT_ACN_F_O30_00221-S002",
  "claim_topic": "effect",
  "anchor_type": "structured",
  "ingredient_id": "<uuid>",
  "raw_name": "NIACINAMIDE",
  "raw_name_ko": "나이아신아마이드",
  "query_terms": ["niacinamide sebum control", "나이아신아마이드 피지 조절"]
}
```

**예시 (Case B, ingredient unresolved)**

입력 — `subject={raw_name: "BAMBUSA VULGARIS EXTRACT 등 4종 표기", matching_status: "unresolved_ambiguous_family"}`, `object="보습"`

```json
{
  "claim_statement_id": "COT_RED_M_O50_03216-S003",
  "claim_topic": "effect",
  "anchor_type": "free_text",
  "ingredient_id": null,
  "raw_name": "BAMBUSA VULGARIS EXTRACT",
  "raw_name_ko": "대나무 추출물",
  "query_terms": ["bamboo extract moisturizing", "대나무 추출물 보습"]
}
```

`precaution`/`usage_instruction`은 `ingredient_id`가 스키마상 없을 수 있으므로(주체가 자유 텍스트, `subject: str`) 그 경우 `anchor_type="free_text"`로 `subject` 원문을 `query_terms`에 그대로 쓴다.

---

## E. Retrieval output contract

```python
class EvidenceHit(BaseModel):
    chunk_id: str
    content: str
    score: float
    source_type: EvidenceSourceType
    source_title: str
    page: int | None = None
    section: str | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    jurisdiction: str | None = None
    evidence_level: EvidenceLevel


class ClaimEvidenceLink(BaseModel):
    """Claim ↔ EvidenceHit[] 관계. 나중에 answer generation이 이 객체를 그대로 받아
    citation을 코드로 렌더링한다 — LLM에는 content만 넘기고 metadata는 따로 보존."""
    claim_statement_id: str
    query_anchor: EvidenceQueryAnchor
    hits: list[EvidenceHit]              # score 내림차순, 빈 리스트면 "근거 없음"
```

`hits=[]`는 정상적인 결과다(모든 claim이 공식 근거를 갖는 게 아니다) — 이 경우 답변 생성 단계는 "NIA claim은 있으나 검증된 근거는 아직 없음"으로 표현해야지, 근거가 있는 것처럼 꾸미면 안 된다(현재 `support_status=unverified` 정책과 일관).

---

## F. Citation metadata 보존 전략

| source | 보존 방법 |
|---|---|
| MFDS | 이미 `Evidence.source_url`/`jurisdiction`/`regulate_type`로 보존됨. page/section 없음(구조화 API라 원본 문서 개념 자체가 없음) |
| CIR(PDF) | PDF에서 페이지 단위로 텍스트를 뽑을 때(`anthropic-skills:pdf` 스킬 등으로) 페이지 번호를 청크에 그대로 심는다. 보고서 제목·다루는 성분명은 문서 메타데이터로 한 번만 저장하고 청크가 상속. `url`은 보고서 링크 |
| 논문(PubMed) | PMID는 API 응답에서 직접 확보, DOI는 있으면 같이 저장. 초록 단계에서는 `page` 없음(원문 확보 시에만 의미 생김). `url`=PubMed 링크 |
| 공통 원칙 | citation 필드는 **파싱 시점에 한 번 채우고 이후 절대 고치지 않는다**(freeze). `chunk_id`는 결정적으로 계산해(`source_id:page:section:index`) 재수집 시 같은 청크가 같은 ID로 안정적으로 매칭되게 한다. content는 원문 그대로 — 전처리 단계에서 요약하지 않는다(요청하신 원칙) |

---

## G. MVP 범위

1. **MFDS** — 이미 존재(`Evidence` 테이블, 8,288건). 추가 수집 없이 그대로 Evidence RAG의 1차 소스로 재사용
2. **CIR** — POC 핵심 성분 5종(Vitamin C/Niacinamide/Retinol/AHA/BHA)만, 벌크 API가 없어 성분 단위 개별 조회로 시작. **착수 전 CIR 이용약관 확인 필요**(data.md에 이미 기록된 미해결 항목)
3. **논문(PubMed abstract)** — MVP는 성분 1~2종 시범 수준으로만. 초록만으로는 근거력이 약하고 검증 이슈도 있어 본격 확장은 CIR/MFDS 안정화 이후로 미룸
4. **기타 regulatory(EU/ECHA 등)** — MVP 밖

---

## 확정 안 된 것 (다음 단계 시작 전 결정 필요)

- 기존 `rag_chunk` 테이블을 확장할지, `evidence_chunk`를 새 테이블로 분리할지
- CIR 이용약관 — 벌크 스크래핑 가능 여부, 저작권 조건
- `evidence_level`과 기존 `RagConfidenceTier`를 통합할지 별도로 둘지(개념은 겹치지만 소스 구성이 다름)

## 판정

**`EVIDENCE_RAG_DESIGN_READY`**

Source 전략·스키마·청킹·query bridge·retrieval 계약·citation 보존 전략까지는 확정 가능한 수준으로 설계했다. 다만 위 "확정 안 된 것" 3가지(특히 CIR ToS)는 설계가 아니라 외부 확인·의사결정이 필요한 항목이라 `NEEDS_SOURCE_DECISION`에 걸릴 수도 있는 유일한 리스크로 남겨둔다 — 이 문서의 스키마/계약 자체는 그 결정과 무관하게 그대로 쓸 수 있다.
