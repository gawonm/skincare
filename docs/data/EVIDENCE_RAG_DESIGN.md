# Evidence RAG 설계 (구현 전 데이터 계약)

> 범위: 이 문서는 설계만 다룬다. crawling·embedding·DB 마이그레이션·retrieval 구현은
> 포함하지 않는다. Claim RAG(NIA annotation)는 1차 완료 상태로 간주하고, 여기서는
> "Claim RAG가 찾은 claim을 실제 근거 문서로 추적하는" Evidence RAG의 데이터 구조만
> 정의한다.
>
> **2026-09-15 갱신** — 모든 질문이 Claim RAG를 거치는 것은 아니다. D절(`EvidenceQueryAnchor`)이
> Claim-backed 경로 외에 direct ingredient/multi-ingredient 경로도 정의한다(아래 flow는
> 대표 경로 하나만 보여준다 — 전체 경로는 D.2/D.4 참고).

```
사용자 질문
→ [필요 시] Claim RAG (NIA annotation) → claim 추출
→ [또는 Claim 없이 직접] Intent/Entity 분석 → ingredient_refs
→ EvidenceQueryAnchor 생성 → Evidence RAG → 근거 문서 검색
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

## D. EvidenceQueryAnchor — Evidence RAG 진입 계약

**상태: 2026-09-15 4차 개정.** 3차 개정(출처·성분개수·검색모드가 `origin` 하나에 섞여
있던 버전)을 분해한다 — 출처(origin)/성분 범위(ingredient_scope)/성분 매칭 방식
(ingredient_match_mode)/검색 주제(claim_topic)를 4개의 독립 축으로 나누고, anchor 하나가
검색 목적 하나만 표현하도록(atomic) 제한한다. 이 표현만 정의하고 실제 검색(retrieval 구현)은
이번 단계에서 실행하지 않는다. `embedding` 관련 설정은 이 anchor에 넣지 않는다(D.13) —
chat/annotation LLM은 Ollama/`qwen3.5:9b`로 결정됐고, embedding은 2026-09-17 별도로
`BAAI/bge-m3`(local)/`vector(1024)`로 확정됐다(`EVIDENCE_STORAGE_ERD.md` 참고) — 둘 다
retrieval 요청 스키마인 이 anchor의 필드는 아니다.

**공용 contract 명칭 정정 반영**: `docs/contracts/two-layer-rag-agent-backend-contract.md`
6절의 레거시 명칭 `EvidenceSearchRequest`는 향후 `EvidenceQueryAnchor`로 확정된다 — 이
문서(D절)가 그 최종 형태의 기준이다. `ClaimHit.ingredient_id`(단일)라는 표현도 구버전이며,
FROZEN된 실제 Claim contract는 `ingredient_refs: list[IngredientRef]`(배열)를 쓴다 — 아래
D.3 매핑은 이 최신 형태를 기준으로 한다.

### D.1 Persistence — DB 테이블 아님

`EvidenceQueryAnchor`는 **영속화하지 않는다.** Pydantic 기반 비영속 retrieval request DTO다
(`agent`/`backend` 레이어 안에서만 생성·소비되고 끝난다, 요청 하나의 수명과 함께 사라짐).

**이유**:
- 매 질문마다 새로 만들어지는 검색 입력값이지, 그 자체로 보존할 도메인 사실이 아니다.
  저장해야 할 사실은 anchor가 아니라 그 결과(`ClaimEvidenceLink`, 이것도 3절에서 이미
  비영속으로 확정)다.
- 저장하면 Claim이 재라벨링되거나 Evidence corpus가 갱신될 때마다 오래된 anchor를 무효화
  하는 별도 유지보수가 생긴다 — 캐시가 필요해지면 그때 "anchor 자체"가 아니라 "anchor +
  retrieval 결과" 쌍을 캐시 테이블로 별도 설계한다(YAGNI, 지금은 안 함).
- 저장이 필요하다고 뒤집힐 유일한 시나리오는 "같은 anchor로 반복 검색되는 비용을 줄여야
  한다"는 성능 요구가 실측으로 확인될 때다 — 지금은 그런 근거가 없다.

### D.2 분류 축 — 4개 독립 축으로 분해

기존 프로젝트 convention 확인: 실제 코드(`agent/rag/schemas.py`)의 판별자성 enum은 전부
`StrEnum` + snake_case 값이다(`QuestionIntent`, `LookupStatus`, `ConstraintSource`,
`EvidenceSourceType` 등 — `docs/erd/app.md`/`models/`의 `_sql_enum` 관례와도 일치). 아래
4개 축 전부 이 convention을 따라 `StrEnum`으로 제안한다(코드로 만들지 않음, 설계 문서에만
기재).

```python
class EvidenceQueryOrigin(StrEnum):
    """anchor가 어떤 트리거로 만들어졌는지. 성분 개수나 검색 모드와는 무관한 축이다."""

    CLAIM_HIT = "claim_hit"        # Claim RAG가 찾은 claim을 검증하러 온 경로
    DIRECT_QUERY = "direct_query"  # Claim 없이 사용자가 성분을 이미 알고 직접 질문(단일/다중 공통)


class IngredientScope(StrEnum):
    """이 anchor가 성분 몇 개를 대상으로 하는지. origin과 독립이다 - combination_claim
    (Claim RAG)도 origin=CLAIM_HIT이면서 scope=MULTI일 수 있다."""

    SINGLE = "single"
    MULTI = "multi"


class IngredientMatchMode(StrEnum):
    """MULTI일 때만 의미가 있다(D.6). SINGLE이면 값이 있어도 검색에 영향 없음."""

    ANY = "any"
    ALL = "all"
```

**왜 이전 버전(3차)의 `origin={CLAIM_HIT, DIRECT_INGREDIENT, MULTI_INGREDIENT}`을 버리는가**:
"성분이 1개인 직접 질문"과 "성분이 여러 개인 직접 질문"은 트리거 관점에서 같은 경로
(Claim 없이 Intent/Entity 분석이 직접 만듦)인데, 성분 개수 차이 때문에 `origin` 값 자체를
나눴었다 — 이러면 "이 anchor가 Claim에서 왔는가"를 물을 때마다 3개 값을 다 검사해야 했다.
이제 `origin`은 `{CLAIM_HIT, DIRECT_QUERY}` 2값이고, "성분이 몇 개인가"는 `ingredient_scope`
가 전담한다.

**`anchor_type`("structured"/"free_text")은 제거한다.** D.6에서 정의하듯 유효한 anchor는
**항상** `ingredient_refs`가 1개 이상이어야 하므로(구조화 안 된 성분만으로는 애초에 anchor를
만들지 않음, `NO_ANCHOR` 상태로 처리) `anchor_type="free_text"`에 대응하던 경우 자체가 더 이상
anchor 스키마 안에 존재하지 않는다 — 그 구분은 "anchor가 만들어졌는가 아닌가"(D.6)로
옮겨간다.

**`claim_topic`**: 기존 `EvidenceClaimTopic`(`models/evidence_document.py`, 이미 코드로
존재하는 enum)을 그대로 재사용한다 — 새 값을 추가하지 않는다.

| 요청하신 검색 목적 | 매핑되는 `EvidenceClaimTopic` 값 | 비고 |
|---|---|---|
| 효능 | `EFFICACY` | |
| 안전성/주의사항 | `PRECAUTION` | |
| 사용법 | `USAGE_INSTRUCTION` | |
| 농도 | `CONCENTRATION_REGULATION` | |
| 병용·충돌 | `COMBINATION` | `ingredient_scope=MULTI`와 별개 축 — `COMBINATION` topic이어도 scope=SINGLE일 수 있다(예: "레티놀은 다른 성분과 같이 쓰면 안 된다는 게 있나요?" 처럼 한 성분의 상호작용 "주의사항"을 묻는 경우) |
| 규제 | `CONCENTRATION_REGULATION` | MFDS가 다루는 유일한 topic이 배합 한도/금지라 별도 값을 안 만든다(`EVIDENCE_COVERAGE_AUDIT.md` 1절) |
| 추천 이유 | (신규 값 없음) | "제품 추천 이유"는 그 자체로 검색 주제가 아니라, `EFFICACY`/`PRECAUTION`/`COMBINATION` 등 다른 topic들의 anchor 결과를 Backend가 조합해서 만드는 산출물이다(요청하신 원칙 "제품 후보는 RDB, 추천 이유는 Evidence RAG") — anchor 레벨에 `recommendation_reason` topic을 새로 만들면 검색 대상이 불분명해진다 |

### D.3 ClaimHit → EvidenceQueryAnchor 매핑

**`ClaimDocument`/`ClaimHit` contract는 FROZEN이다 — 이 문서도, 어떤 Claim 쪽 파일도
바꾸지 않는다.** 매핑은 Evidence 쪽에 있는 별도 어댑터(`ClaimHitToEvidenceQueryAnchorAdapter`
같은 이름, 코드는 이번 단계에서 작성하지 않음)가 전담한다 — Claim 쪽 필드가 나중에 늘어나도
이 어댑터 하나만 고치면 된다. **Claim 쪽 필드명을 Evidence 쪽에서 임의로 재정의하지 않는다**
— 아래 표의 왼쪽 열은 Claim contract 그대로, 오른쪽 열만 Evidence 쪽 이름이다.

`ClaimHit` 필드는 두 문서를 합쳐서 본다: 개별 필드는
`docs/contracts/two-layer-rag-agent-backend-contract.md` 5절(제안 당시 표, 단 거기 적힌
단일 `ingredient_id`는 구버전 — 아래 표가 최신),
다중 성분 표현은 `docs/coordination/CLAUDE_SESSION_BOARD.md`의 `IngredientRef` 합의
(`ingredient_refs: list[IngredientRef]`, `IngredientRef{ingredient_id, raw_name,
matching_status, role}`)를 canonical로 따른다.

| `ClaimHit` 필드 | `EvidenceQueryAnchor` 필드 | 매핑 규칙 |
|---|---|---|
| `statement_id` | `origin_ref` | 그대로 복사(D.11) |
| — (고정값) | `origin` | 항상 `CLAIM_HIT` |
| `ingredient_refs: list[IngredientRef]` | `ingredient_refs: list[str]`, `ingredient_scope` | D.12에 정의된 순서로 adapter가 먼저 관련 성분을 고르고, `matching_status == matched`인 `IngredientRef.ingredient_id`만 문자열로 추려 담는다(agent 쪽 id류 필드는 전부 `str`, D.5 5차 개정 참고). 1개면 `scope=SINGLE`, 2개 이상이면 `scope=MULTI`. **`matched`가 0개면 anchor를 만들지 않는다**(`NO_ANCHOR`, D.6) |
| `IngredientRef.role`(primary/secondary/unspecified) | 매핑 없음(단, D.12 순서 준수) | anchor의 최종 필드에는 안 남지만, scope/match_mode/query_text를 정하기 전까지 adapter 내부에서 버리지 않는다(D.12) |
| `statement_type` | `claim_topic` | `ingredient_effect_claim→EFFICACY`, `precaution→PRECAUTION`, `usage_instruction→USAGE_INSTRUCTION`, `combination_claim→COMBINATION`. `case_observation`/`cause_claim`/`contextual_factor`는 매핑 대상 아님(Evidence 검증이 필요한 statement_type이 아니므로 애초에 adapter 호출 전 필터링) |
| `claim`(statement_type별 object/subject) | `query_text` | 검색 입력 문자열로만 쓴다(citation 아님, D.10). **하나의 anchor에 하나의 topic만**(D.4) — 원본 claim이 여러 주제를 담고 있으면 topic별로 anchor를 쪼갠다 |
| `case_context`(전체 아님) | `query_terms`(보조) | **원문 그대로 복사하지 않는다.** whitelist 기반 결정적 추출만 허용(D.8) |
| `support_status` | 매핑 없음 | Claim 쪽의 "아직 검증 안 됨" 표시일 뿐 anchor에 넣을 정보가 아니다 — Evidence 쪽 판정은 `ClaimEvidenceLink.support_level`이 별도로 만든다(D.9) |
| `annotation_status` | 매핑 없음 | `rejected`면 애초에 adapter를 호출하지 않는다(Claim ingestion 정책이 이미 필터링, Board Shared Decisions #6) |

**Claim contract 변경 필요**: NO. 위 매핑은 전부 기존 필드를 읽기만 한다 — Claim 쪽에 새
필드를 요구하지 않는다.

### D.4 Atomic anchor 규칙 — anchor 하나 = 검색 목적 하나

**`EvidenceQueryAnchor` 하나는 `claim_topic` 하나만 표현한다.** 사용자 질문 하나에 검색
목적이 여러 개면(예: "나이아신아마이드 효과랑 주의사항 알려줘") 이 경계에서 anchor를
분해한다 — 한 `query_text`/`claim_topic`에 두 주제를 섞지 않는다.

```
사용자 요청 1개
  → EvidenceQueryAnchor N개(topic별로 분리, 같은 request_id로 묶임 — D.11)
    → anchor별 retrieval(각자 독립 실행)
      → 결과 병합(Backend/Agent 책임, 이 문서 범위 밖)
```

예시("나이아신아마이드 효과랑 주의사항 알려줘", `ingredient_refs=[<niacinamide-uuid>]`):

```
anchor 1: origin=DIRECT_QUERY, scope=SINGLE, claim_topic=EFFICACY,   query_text="나이아신아마이드 효능"
anchor 2: origin=DIRECT_QUERY, scope=SINGLE, claim_topic=PRECAUTION, query_text="나이아신아마이드 주의사항"
```

두 anchor는 `ingredient_refs`는 같지만 `claim_topic`/`query_text`가 다른 별개 요청이다 —
검색도, 결과도 따로 취급한다(한쪽 결과가 없다고 다른 쪽까지 실패로 취급하지 않는다).

### D.5 `EvidenceQueryAnchor` 필드

**2026-09-15 5차 개정(구현 착수 전 타입 정합화)** — 실제 코드베이스 convention을 확인한 결과
(`agent/rag/schemas.py`), 이 파일의 모든 id류 필드는 `UUID`가 아니라 `str`이다
(`IngredientRecord.ingredient_id: str`, `ProductRecord.ingredient_ids: list[str]`,
`docs/contracts/backend-to-agent.md`의 `Turn.request_id: str` 등). 아래 스니펫을 그 convention에
맞춰 `UUID` → `str`로 정정한다 — 실제 UUID 파싱/검증은 backend/repository 경계에서 한다,
agent 쪽 DTO는 문자열로만 주고받는다(기존 코드 전체가 이미 이 방식). **`ingredient_match_mode`
의 canonical 규칙도 이번에 확정**: `ingredient_scope=SINGLE`이면 "무시되는 기본값"이 아니라
**반드시 `None`**이어야 한다(빈 값을 허용하면 서로 다른 요청이 같은 검색으로 취급돼 재현성이
깨진다는 지적 반영) — `ingredient_scope=MULTI`이면 `ANY`/`ALL` 중 하나가 **필수**다.

```python
class EvidenceQueryAnchor(BaseModel):
    anchor_id: str                                      # D.11, 이 anchor 하나만의 식별자
    request_id: str                                     # D.11, 같은 사용자 요청에서 나온 N개 anchor를 묶음
    origin: EvidenceQueryOrigin
    origin_ref: str | None = None                       # D.11, origin=CLAIM_HIT일 때 필수

    ingredient_refs: list[str]                            # D.6, 최소 1개(빈 리스트면 애초에 anchor 자체가 없음), 중복 금지
    ingredient_scope: IngredientScope                     # len(ingredient_refs)와 정확히 일치해야 함(D.6)
    ingredient_match_mode: IngredientMatchMode | None = None  # SINGLE→반드시 None, MULTI→반드시 ANY/ALL(D.6)

    query_text: str                                       # 검색 입력. citation 아님(D.10). 공백만이면 거부
    query_terms: list[str] = []                            # whitelist 추출만(D.8), 중복·공백 제거

    claim_topic: EvidenceClaimTopic                        # anchor당 정확히 1개(D.4) - list 아님

    # --- optional filters(아래 표) ---
    source_types: list[EvidenceDocumentSourceType] = []
    jurisdiction: str | None = None
    document_status: list[str] = []
    study_type: list[str] = []
    formulation_type: list[str] = []
    evidence_level: list[str] = []
    language: str | None = None

    # --- retrieval option: 기존 EvidenceSearchRequest/ProductSearchRequest와 동일 관례
    # (DEFAULT_SEARCH_LIMIT=5, 상한 없음) 재사용 ---
    limit: int = 5
```

| 구분 | 필드 | 비고 |
|---|---|---|
| **core**(항상 필요) | `anchor_id`, `request_id`, `origin`, `ingredient_refs`(≥1, 중복 금지), `ingredient_scope`, `query_text`(공백만 거부), `claim_topic`(단수) | 이게 없으면 검색 자체가 성립 안 함 |
| **core, 조건부 필수** | `origin_ref`(origin=CLAIM_HIT일 때 필수, DIRECT_QUERY면 반드시 `None`), `ingredient_match_mode`(scope=SINGLE이면 반드시 `None`, scope=MULTI이면 ANY/ALL 필수) | D.6/D.11, **canonical 정정**: "없어도 되는 값"이 아니라 scope에 따라 상태가 결정된다 |
| **optional filter**(있으면 좁히고, 없으면 전체 대상) | `source_types`, `jurisdiction`, `document_status`, `study_type`, `formulation_type`, `evidence_level`, `language` | 전부 빈 리스트/None이 기본값 |
| **retrieval option** | `limit`, `ingredient_match_mode` | `limit`은 상한이지 결과 개수 보장 아님(`hits=[]`가 정상, D.10) |
| **제외**(이 anchor에 안 넣음) | `support_level`(D.9), citation 문자열(D.10), embedding vector(D.14), `IngredientRef.role`(D.3/D.12) | 각 항목 이유는 해당 절 참고 |

### D.6 `ingredient_refs` validation과 3가지 상태

**Evidence RAG는 성분 중심이다 — 유효한 모든 anchor는 `ingredient_refs`가 최소 1개다.**

- `ingredient_scope=SINGLE` ⟺ `len(ingredient_refs) == 1`
- `ingredient_scope=MULTI` ⟺ `len(ingredient_refs) >= 2`
- `ingredient_scope`와 `len(ingredient_refs)`가 안 맞으면 validation error.

**성분을 하나도 식별 못 했을 때는 `EvidenceQueryAnchor`를 아예 만들지 않는다** — upstream
(Claim adapter 또는 Agent의 ingredient entity resolution)의 실패 결과로 처리하고, 이걸
"anchor는 유효한데 검색 결과가 없다"(`hits=[]`)와 절대 혼동하지 않는다. 세 가지 상태를
구분한다(semantics만 — 실제 enum/응답 코드는 이번 단계에서 만들지 않음):

| 상태 | 의미 | anchor 존재 여부 |
|---|---|---|
| `NO_ANCHOR` | 성분 식별 실패, 또는 애초에 Evidence 검증 대상이 아닌 질문(statement_type 필터 탈락 등) | anchor 자체가 생성되지 않음 |
| `VALID_ANCHOR_WITH_NO_HITS` | anchor는 정상 생성됐지만 MFDS/CIR/PubMed에서 근거를 못 찾음 | anchor 있음, retrieval 결과 `hits=[]` |
| `VALID_ANCHOR_WITH_HITS` | anchor 생성 + 근거 검색 결과 존재 | anchor 있음, `hits` 비어있지 않음 |

`NO_ANCHOR`와 `VALID_ANCHOR_WITH_NO_HITS`는 사용자에게 보여줄 메시지도 달라야 한다(전자는
"이 성분/질문은 근거를 찾을 수 있는 형태가 아님", 후자는 "근거를 찾아봤지만 없음") — 다만
실제 메시지 문구·enum 구현은 이번 범위 밖이다.

### D.7 다중 성분 분해 — interaction anchor와 per-ingredient anchor

병용/충돌/비교 질문은 필요에 따라 **별도 anchor 두 종류**를 만들 수 있다(D.4의 atomic 규칙과
같은 이유 — 서로 다른 검색 목적이라 섞지 않는다).

**A. Interaction anchor** — `ingredient_scope=MULTI`, `ingredient_match_mode=ALL`. 같은
`evidence_chunk`가 `ingredient_refs` 전부와 연결돼야 통과한다(D.13) — "두 성분을 동시에
직접 다룬" 근거만 찾는다.

**B. Per-ingredient anchor** — 성분마다 `ingredient_scope=SINGLE` anchor를 하나씩 만든다.
각 성분의 독립적인 효능/안전성 근거를 각자 찾는다(같은 `request_id`로 묶임, D.11).

**금지**: `ALL` 결과가 없다고 `ANY`(또는 per-ingredient 결과)를 interaction evidence처럼
쓰지 않는다. `ALL` 결과가 비었으면 "직접적인 상호작용 근거 없음" + "각 성분의 개별 근거는
있음(있다면)"으로 **분리해서** 전달한다 — 둘을 합쳐 "병용해도 된다는 근거가 있다"로
표현하지 않는다(`rag_pipeline_handoff.md` 6절 기존 원칙과 동일한 이유).

### D.8 `case_context` 사용 제한 — whitelist만 허용

`ClaimHit.case_context` 원문 전체를 `query_terms`에 복사하지 않는다.

**허용**:
- 정규화된 성분명(`raw_name`/`raw_name_ko`, 이미 `IngredientRef`에 있는 필드)
- `claim_topic`에 대응하는 검색어(예: EFFICACY topic이면 "효능"류 키워드)
- formulation/농도/사용 시점 등 검색에 직접 필요한 **구조화된** 조건 필드(자유 서술이 아닌
  이미 필드로 분리된 값)
- 개인정보가 제거된, 검색 목적에 한정된 제한적 검색 용어

**금지**:
- NIA `case_context` 원문 전체(피험자 서술)
- 개인 식별 가능 정보
- Evidence claim과 무관한 사례 서술
- LLM이 임의로 확장·해석한 사실(질문에 없는 내용을 만들어 검색어에 넣는 것)

`ClaimHitToEvidenceQueryAnchorAdapter`가 `case_context`를 쓴다면, **whitelist 기반의
결정적(deterministic) 추출만** 허용한다 — LLM 호출로 요약·확장하지 않는다. 이 원칙은
어댑터 구현 시점에 그대로 지켜야 한다(코드는 이번 단계에서 작성하지 않음).

### D.9 `support_level`은 anchor에 없다

`DIRECT`/`PARTIAL`/`UNSUPPORTED`(또는 `WEAK`)는 **anchor 필드도, `EvidenceDocument`/
`EvidenceChunk` 필드도 아니다.** anchor는 "무엇을 찾을지"를 기술하는 검색 요청일 뿐이고,
`support_level`은 **retrieval이 끝난 뒤** 찾아온 `EvidenceHit`들을 원래 claim과 비교해서
매기는 평가 결과다 — 그래서 `ClaimEvidenceLink.support_level`(`EVIDENCE_STORAGE_ERD.md`
3/5절에서 이미 비영속으로 확정)에만 존재한다. **anchor 단계에서 `support_level`로 문서를
미리 걸러내지 않는다** — 그건 아직 계산되지 않은 값이라 걸러낼 수가 없다(순서상 불가능).

### D.10 Citation provenance는 anchor 바깥

anchor는 `url`/`doi`/`pmid`/`page`/`section` 같은 citation 문자열을 담지 않는다 — 그건
검색 **결과**(`EvidenceHit`)의 속성이지 검색 **입력**의 속성이 아니다. `query_text`는
검색 입력일 뿐 citation source가 아니다 — 예를 들어 `query_text="니아신아마이드 피지
조절"`이 검색됐다고 해서 그 문자열이 답변의 출처로 표시되는 일은 없다. 출처는 어디까지나
retrieved `EvidenceDocument`/`EvidenceChunk`의 metadata를 Backend가 조합해서 만든다
(`EVIDENCE_STORAGE_ERD.md` 7절 "Citation 조합 원칙"). LLM은 이 과정에 관여하지 않는다.

빈 결과(`hits=[]`)는 정상적인 retrieval 결과다(D.6의 `VALID_ANCHOR_WITH_NO_HITS`). anchor
자체에는 "결과가 없으면 이렇게 한다"는 fallback 로직이 없다 — anchor는 순수 요청 객체이고,
빈 결과 처리(임의 근거 생성 금지, `UnverifiableReason.NO_EVIDENCE_FOUND` 반환 등)는 anchor를
소비하는 서비스(`backend/services/`)의 책임이다.

### D.11 식별자 3종 — `anchor_id` / `request_id` / `origin_ref`

세 성격을 분리한다 — 하나로 합치면 "이 검색 한 건을 추적하려는 목적", "같은 사용자 요청에서
나온 여러 검색을 묶는 목적", "이 검색이 어느 도메인 객체에서 왔는지"가 섞인다.

- **`anchor_id: str`** — **원자적 anchor 하나**의 요청 내 식별자. anchor 인스턴스가 생성될
  때마다 새로 발급한다(같은 claim으로 재검색해도, 같은 요청 안에서 topic별로 쪼개져도 전부
  다른 `anchor_id`). DB에 저장하지 않으므로 FK도 아니다 — domain persistence key처럼 쓰지
  않는다(재실행마다 값이 달라지는 임시 식별자라는 뜻).
- **`request_id: str`** — **동일 사용자 요청에서 생성된 복수 anchor를 묶는** correlation ID.
  기존 Backend contract에 이미 같은 이름·같은 목적의 필드가 있어 그대로 재사용한다
  (`docs/contracts/backend-to-agent.md`의 `Turn.request_id` — "한 사용자 요청의 중복 방지
  키, 재전송 시 유지"). D.4에서 하나의 사용자 요청이 여러 anchor로 쪼개질 때, 이 anchor들이
  전부 같은 `request_id`를 공유한다 — 새 필드를 만들지 않고 기존 필드를 그대로 흘려보낸다.
- **`origin_ref: str | None`** — anchor가 어느 도메인 객체에서 파생됐는지 가리키는 **안정
  참조**. `origin=CLAIM_HIT`이면 `claim_statement_id`를 그대로 담아 필수값이 된다(D.3).
  `origin=DIRECT_QUERY`는 파생 근거가 되는 Claim 레코드가 없으므로 `None`이다.

### D.12 `IngredientRef.role` 처리 순서 — adapter 안에서는 버리지 않음

**Claim contract는 바꾸지 않는다.** `ClaimHitToEvidenceQueryAnchorAdapter`가
`ClaimHit.ingredient_refs`의 `role`(primary/secondary/unspecified)을 최종 anchor 필드에
그대로 저장하지는 않지만(anchor는 `list[str]`만 가짐, D.3), **아래 4가지를 결정하기 전까지는
`role`을 버리지 않는다**:

1. 이 claim과 실제로 관련된 ingredient를 고르는 단계(예: `role=unspecified`인 부수 언급을
   주 대상에서 뺄지 판단)
2. `ingredient_scope`(SINGLE/MULTI) 결정
3. `ingredient_match_mode`(ANY/ALL) 결정 — 예를 들어 `role=primary`/`secondary`가 뚜렷하게
   구분된 `combination_claim`이면 `ALL`(상호작용 근거), 단순 나열(`role=unspecified`만
   있음)이면 `ANY`부터 시도하는 식의 판단 근거로 쓸 수 있다
4. `query_text` 구성(주 성분을 먼저 언급하는 등)

즉 `role`은 anchor의 **입력 신호**로만 쓰이고 **출력 필드**로는 안 나타난다 — "role을 아무
판단 없이 단순 제거"하지 않는다는 요청을 어댑터 설계 원칙으로 명문화한다(코드는 이번 단계
에서 작성하지 않음).

### D.13 기존 schema와의 조회 관계(semantics만, 코드 없음)

이번 단계는 설계까지만 — 아래는 `evidence_document`/`evidence_chunk`/
`evidence_chunk_ingredient`(`EVIDENCE_STORAGE_ERD.md`)를 anchor 필드가 어떻게 걸러내는지
**의미**만 정의한다. 실제 SQL/repository 코드는 작성하지 않는다. (`anchor_type`이 없어졌으므로
"free_text 전용 경로"는 이제 `NO_ANCHOR`로 처리돼 이 목록에 없다 — 여기 아래는 전부
`ingredient_refs`가 1개 이상 있는, 즉 실제로 생성된 anchor만 다룬다.)

1. **`ingredient_scope=SINGLE`** (또는 `MULTI`+`ingredient_match_mode=ANY`): "`ingredient_refs`의
   성분 중 하나라도 연결된 `evidence_chunk_id` 집합"을 `evidence_chunk_ingredient`에서
   `ingredient_id`로 필터링해 구하고, 그 집합 안에서 `query_text`/`query_terms`로 content
   검색(벡터+BM25 하이브리드, `rag_chunk`와 같은 방식) + optional filter(D.5)를 적용한다.
2. **`ingredient_scope=MULTI`, `ingredient_match_mode=ALL`**: "`ingredient_refs`의 **모든**
   성분이 각각 연결된 `evidence_chunk_id` 집합"(연결된 서로 다른 `ingredient_id` 개수가
   `len(ingredient_refs)`와 같은 청크만)을 구한 뒤, 그 집합 안에서 content 검색 + optional
   filter를 적용 — 이 결과가 곧 "상호작용/병용을 실제로 같이 다룬" 근거 후보다(D.7 interaction
   anchor).
3. **optional filter 적용 대상**: `source_types`/`evidence_level`은 `evidence_chunk`에
   이미 비정규화돼 있어 청크 테이블만 봐도 된다. `document_status`/`study_type`/
   `formulation_type`/`jurisdiction`은 `evidence_document`에만 있으므로 `document_id`로
   조인해야 한다(`evidence_chunk.document_id` FK).
4. **`formulation_type` 필터와 `ingredient_match_mode`는 서로 다른 축이다** — 헷갈리지
   않도록 명시한다. `formulation_type`은 **문헌(연구)이 실제로 무엇을 실험했는지**
   (`single_ingredient` vs `combination_formulation`, 예: PMID 22206073의
   niacinamide+glycerin 연구)를 뜻하는 `EvidenceDocument` 속성이고, **사용자가 만드는
   완제품의 제형(크림/세럼 등)과는 무관하다.** `ingredient_match_mode`는 **사용자가 무엇을
   묻고 있는지**(성분 여러 개를 각각 묻는지, 같이 쓰는 걸 묻는지)를 뜻하는 anchor 속성이다.
   예를 들어 `ingredient_match_mode=ALL`으로 찾은 청크라도 그 문서의
   `formulation_type=single_ingredient`일 수 있다(단일 성분 연구인데 논의 중에 다른
   성분을 언급만 한 경우) — 이 경우 "직접적인 병용 연구 근거"로 격을 올리면 안 되고, 그
   구분은 `ClaimEvidenceLink.support_level`(D.9) 평가 시점에 반영한다.

### D.14 Embedding 상태 — 이번에도 변경 없음

- chat/annotation LLM: Ollama / `qwen3.5:9b`(총괄 결정, config.yaml `agent.chat.provider`)
- embedding provider/model: **2026-09-17 확정 — `BAAI/bge-m3`(local), `vector(1024)`.**
  `config.yaml`의 전역 `agent.embedding.provider`(현재 `openai`, `rag_chunk`용)는 이 결정과
  무관하게 유지된다 — 이건 Evidence 저장소(`evidence_chunk`)에만 적용되는 별도 확정이다.
- `EvidenceQueryAnchor`에는 embedding vector를 포함하지 않는다 — retrieval service가
  `query_text`로 실행 시점에 생성하는 것을 기본안으로 유지한다.
- `evidence_chunk.embedding`은 `vector(1024)`다(`EVIDENCE_STORAGE_ERD.md`/`models/
  evidence_chunk.py`의 `EVIDENCE_EMBEDDING_DIMENSION` 참고). `rag_chunk`의
  `vector(1536)`/`text-embedding-3-small`은 이 결정과 무관하게 그대로 둔다.

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

## H. Corpus 구성과 source 역할 분리 (2026-09-21)

> 전체 Evidence chunk 수는 scientific evidence coverage를 의미하지 않는다.
> 현재 corpus의 대부분은 MFDS regulatory record이며,
> 효능/추천 근거 coverage는 PubMed와 CIR을 별도로 봐야 한다.

```
Evidence
├─ Scientific / efficacy
│  ├─ PubMed
│  └─ CIR
└─ Regulatory / restriction
   └─ MFDS
```

MFDS 사용제한 원료정보는 사용제한·배합제한·규제 조건·jurisdiction별 regulatory/safety 확인용이다.
성분 효능이나 피부 고민에 대한 scientific evidence가 아니므로, A절 표의 "MFDS 8,288건 적재"를
"효능 근거 8,288건"으로 읽으면 안 된다. 효능·추천 이유·안전성의 scientific evidence는 PubMed/CIR이 맡는다.

### H.1 [CURRENT] 현재 DB 구조와 규모

- 기준 dump: `skincare_reference_2026-09-21_v4.dump` (Agent 쪽에서 생성, 팀 공용 canonical)
  - SHA-256: `8c3eb724f86f706614dbf2c37d6fb156591e9dbb85166cee423ac213abe30111`
  - Alembic head: `9f4c2a7d8e61`
- `evidence_document`/`evidence_chunk`에 `source_type`이 이미 보존돼 있다. **스키마·데이터 구조 변경은 없다.**
  MFDS를 삭제하거나 별도 테이블로 옮기지 않는다.

| 테이블 | 합계 | MFDS | CIR | PubMed |
| --- | ---: | ---: | ---: | ---: |
| `evidence_document` | 46 | 11 | 10 | 25 |
| `evidence_chunk` | 8,369 | 8,288 | 56 | 25 |
| `evidence_chunk_ingredient` | 8,377 | - | - | - |

(`evidence_chunk_ingredient`는 청크-성분 연결 행이라 source별 분해는 이 문서에 기록하지 않았다.)
source별로 단위가 다르므로 합산하지 않는다: CIR은 10 documents / 56 chunks, PubMed는 25 documents / 25 chunks
(abstract 1건 = chunk 1건), MFDS는 11 documents / 8,288 chunks다. 전체 chunk 8,369건 중 MFDS regulatory chunk가
8,288건을 차지하므로, 전체 chunk 수를 scientific evidence coverage 지표로 쓰면 안 된다.

### H.2 [PROPOSED / AGREEMENT NEEDED] source별 retrieval lane

**아직 Agent/Backend 코드에 반영되지 않았다.** 저장 구조가 아니라 retrieval policy(`EvidenceQueryAnchor.source_types`
채우는 규칙) 수준의 제안이며, Agent/Backend 담당자와 합의가 필요하다(계약 변경이므로 규칙 16 대상).

| 검색 목적(`claim_topic`) | 제안 lane |
| --- | --- |
| efficacy / 피부 고민 / 추천 근거 | PubMed + CIR |
| precaution / safety | CIR + PubMed. 규제·사용제한이 관련될 때 MFDS 추가 |
| regulation / restriction | MFDS 우선 |
| concentration | scientific 농도 근거는 CIR/PubMed, 법적·규제 농도 제한은 MFDS |

함께 합의가 필요한 항목:

- Agent/Backend의 source filter 적용 방식(anchor의 `source_types` 필터를 lane에 맞춰 채울지, 별도 정책 객체를 둘지)
- MFDS를 efficacy 검색 후보에서 기본 제외하는 정책

### H.3 [DATA NEXT] PubMed/CIR coverage gap 보강

corpus를 무작정 늘리지 않고 coverage gap을 메운다. 우선순위:

1. PubMed/CIR 근거가 0건인 성분
2. NIA에서 자주 언급되는 성분
3. confirmed 제품 연결이 많은 성분
4. efficacy / safety / usage 등 핵심 claim topic이 비어 있는 성분

원칙:

- 성분당 논문 수 quota를 채우지 않는다. 동일 claim의 중복 논문을 여러 편 넣지 않고, 대표성이 충분한 1~3편을 우선한다.
- CIR은 최신 final/amended report 중심으로 쓴다.
- full paper 전체를 embedding하지 않는다.
- PubMed는 abstract 기반 compact evidence, CIR은 relevant section/page 단위 chunk 원칙을 유지한다
  ([COMPACT_EVIDENCE_COLLECTOR.md](COMPACT_EVIDENCE_COLLECTOR.md)).

---

## Audit result: scientific evidence coverage (2026-09-21)

`data/scripts/evidence_coverage_audit.py`(읽기 전용)로 산출. 이 audit은 **수집 우선순위 후보표까지**이며
신규 수집·API 호출·embedding·DB write는 하지 않았다. **다음 단계는 "수집"이고 아직 수행하지 않았다.**

- **기준**: canonical v4 (`skincare_reference_2026-09-21_v4.dump` 복원 DB, revision `9f4c2a7d8e61`) +
  기존 NIA relevance 산출물 `nia_ingredient_relevance_summary.csv`(102개 성분, 재계산 안 함).
- **MFDS 제외**: 규제/사용제한 근거라 효능·안전성 scientific evidence가 아니다(H절). 집계 SQL이
  `cir`/`pubmed_abstract`만 조회하므로 MFDS는 섞일 수 없다.
- **coverage 정의**: 성분에 연결된(`evidence_chunk_ingredient`) DISTINCT 문서 수. topic은 문서에
  **저장된 `claim_topics`만** 사용(추론 안 함). 과학 근거 문서에는 `efficacy`/`precaution`(=safety)만
  실제 저장돼 있어 gap 판정은 이 둘만 한다. usage/concentration/combination은 전 성분 0건이라
  "없음"이 아니라 "산출 불가"이며 gap으로 해석하지 않는다. 저장 topic 중 enum 밖 값
  (`pigmentation`/`sebum_control`/`barrier`, PubMed 3건)은 gap 계산에 쓰지 않았다.
- **교차**: NIA는 `case_count`(=nia_case_count)/`answer_case_count`/`target_concern_unique_count`,
  product는 `product_ingredient.match_acceptance='confirmed'` 기준 DISTINCT product 수
  (`ProductBackedIngredientReader` 재사용). needs_review/unmatched는 제외. 대상 성분 = confirmed 제품 연결
  ∪ NIA 언급 ∪ 근거 연결 = 2,872개(IngredientMaster 전체가 아님).
- **status**: `NO_SCIENTIFIC_EVIDENCE`(CIR 0·PubMed 0) / `SINGLE_SOURCE_ONLY`(한쪽만) /
  `HAS_SCIENTIFIC_EVIDENCE`(둘 다).
- **priority rule**(점수식 없음): NIA 높음 = `nia_case_count >= 170`(NIA 성분 상위 25%),
  제품 높음 = `confirmed_product_count >= 100`. P1 = 근거 0 ∧ NIA 높음 ∧ 제품 ≥1, P2 = 근거 0 ∧ NIA 높음 ∧
  제품 0, P3 = 근거 있으나 efficacy/safety 공백 ∧ (NIA 높음 ∨ 제품 높음), 나머지 P4.
  정렬: tier → nia_case_count↓ → confirmed_product_count↓ → scientific_document_count↑.
  두 임계값은 임의 기준이라 팀 확인이 필요하다.
- **결과**: 근거 0건 2,858 / 단일 source 8 / 둘 다 6. P1 12, P2 15, P3 5.
  - P1(근거 0·NIA 높음·제품 연결): Mineral Salts, Melanin, Hexapeptide-2, Momordica Charantia Fruit
    Extract, Sulfur, Collagen(제품 67), BHA, Aloe Barbadensis Leaf Juice Powder, Carapa Guianensis Seed
    Oil, Elastin, Arctium Lappa Root Extract, 3-O-Ethyl Ascorbic Acid(제품 110).
  - P2(제품 연결 없음): Aloesin, Tyrosinase, Sodium Thiosulfate, Anthocyanins 외 11개.
  - P3(efficacy 공백): Centella Asiatica Extract, Squalane, Sodium Hyaluronate, Tocopherol, Beta-Glucan.
- **해석 주의**: (1) NIA 언급이 1,000건 이상인 Melanin·Tyrosinase·Sulfur 등은 템플릿성 문구일 수 있고
  (`nia_product_backed_relevance.HIGH_NIA_CASE_MIN`), 제품 1~4개뿐이라 Tier A 자동 후보가 아니라 사람 검토
  대상이다. (2) 이미 근거가 있는 Niacinamide(CIR 1·PubMed 6), Retinol(NIA 167로 임계 바로 아래)은 P4다.
  (3) P3의 Sodium Hyaluronate·Tocopherol은 NIA 0이고 제품 수만으로 올라온 기본 성분이라 Notion의
  "단순 보조성분" 구분이 필요하다. (4) 근거 0·NIA 낮음·제품 ≥100인 성분 133개는 P4로 남긴다(글리세린 등).
- 산출물(`data/outputs/evidence_coverage/`, `/data/*` gitignore라 커밋되지 않으며 스크립트로 재생성):
  `ingredient_scientific_evidence_coverage.csv`, `evidence_collection_priority.csv`,
  `ingredient_topic_source_coverage.csv`(ingredient × topic × source).

---

## Tier A manual review (2026-09-21)

Audit의 P1/P2/P3/P4는 최종 가치등급이 아니라 후보를 좁히는 routing label이다. P1 12개 + P3 5개 +
threshold 참고(Retinol) + 이상치 확인(Tyrosinase) = 19개를 NIA mention 패턴, 제품 토큰, canonical 단위를
기준으로 손으로 검토했다. 임계값(NIA 170, 제품 100)과 routing 규칙은 바꾸지 않았고 새 점수식도 없다.
PubMed/CIR 검색·수집은 하지 않았다. 전체 표: `data/outputs/evidence_coverage/tier_a_manual_review.csv`(gitignore, 아래 표가 기록본).

판정 근거의 한계: NIA 원문을 다시 읽지 않고 `nia_case_ingredient_mentions.csv`의 매칭 alias·answer/question 비율·
concern 수 패턴으로 "템플릿성 반복"을 **추정**했다(예: 소문자 INCI 한 형태가 한 concern에서 1,000회 안팎 반복).
확정이 아니므로 DEFER 후보는 원문 표본 확인으로 뒤집힐 수 있다.

| 성분 | NIA case / answer / concern | 제품 | CIR / PubMed | routing | mention 성격 | 판정 | target topics |
|---|---:|---:|---:|---|---|---|---|
| Collagen | 940 / 68 / 5 | 67 | 0 / 0 | P1 | 효능·사용 언급(질문 중심) | **INCLUDE** | efficacy |
| 3-O-Ethyl Ascorbic Acid | 170 / 170 / 1 | 110 | 0 / 0 | P1 | 효능·사용 언급 | **INCLUDE** | efficacy, precaution, concentration |
| Centella Asiatica Extract | 13 / 7 / 2 | 590 | 1 / 0 | P3 | 효능·사용 언급 | **INCLUDE** | efficacy |
| Retinol (threshold 참고) | 167 / 105 / 5 | 74 | 0 / 3 | P4 | 효능·사용 언급 | **INCLUDE** | precaution, usage, combination |
| Hexapeptide-2 | 1023 / 1021 / 1 | 12 | 0 / 0 | P1 | 템플릿 의심 | DEFER | (재검토 시) efficacy |
| Sulfur | 1003 / 848 / 1 | 1 | 0 / 0 | P1 | 템플릿 의심 | DEFER | (재검토 시) precaution, concentration |
| Elastin | 421 / 7 / 4 | 14 | 0 / 0 | P1 | 질문 중심 | DEFER | (재검토 시) efficacy |
| Arctium Lappa Root Extract | 280 / 279 / 1 | 11 | 0 / 0 | P1 | 템플릿 의심 | DEFER | - |
| Aloe Barbadensis Leaf Juice Powder | 481 / 291 / 1 | 4 | 0 / 0 | P1 | 템플릿 의심 | DEFER | - |
| Squalane | 1 / 0 / 1 | 366 | 1 / 0 | P3 | 언급 1건 | DEFER | - |
| Sodium Hyaluronate | 0 | 1145 | 1 / 0 | P3 | NIA 없음 | DEFER | - |
| Tocopherol | 0 | 807 | 1 / 0 | P3 | NIA 없음 | DEFER | - |
| Beta-Glucan | 0 | 363 | 1 / 0 | P3 | NIA 없음 | DEFER | - |
| Mineral Salts | 1268 / 852 / 2 | 11 | 0 / 0 | P1 | 템플릿 의심 | EXCLUDE | - |
| Melanin | 1243 / 1228 / 1 | 1 | 0 / 0 | P1 | 기전 용어 | EXCLUDE | - |
| Momordica Charantia Fruit Extract | 1004 / 865 / 1 | 3 | 0 / 0 | P1 | 템플릿 의심 | EXCLUDE | - |
| BHA | 503 / 330 / 4 | 8 | 0 / 0 | P1 | 계열명 | EXCLUDE | - |
| Carapa Guianensis Seed Oil | 456 / 260 / 1 | 4 | 0 / 0 | P1 | 템플릿 의심 | EXCLUDE | - |
| Tyrosinase | 581 / 1 / 1 | 0 | 0 / 0 | P2 | 기전 용어 | EXCLUDE | - |

**집계**: INCLUDE 4 / DEFER 9 / EXCLUDE 6 (검토 19개).

**Tier A 제안(사람 QA 우선 대상)**: Collagen, 3-O-Ethyl Ascorbic Acid, Centella Asiatica Extract, Retinol
(이후 Salicylic Acid·Ascorbic Acid 추가, 아래 "수집 전략 변경" 참고). 수집 전략이 바뀌어(2,872 baseline) Tier A는
**수집 범위가 아니라 human QA 우선순위**다. 이미 근거가 있는 Niacinamide 등은 그대로 둔다.
target topics는 **수집 목표**일 뿐이다. usage/concentration/combination은 저장값이 없어 0건으로 나오지만
"현재 비어 있다"는 뜻이 아니라 "산출 불가"였다(Audit result 참고).

**Ambiguous mapping**
- **BHA**(`e48d0911-…`): 제품 토큰 `BHA` 8건은 레티놀 제품이 대부분이라 butylated hydroxyanisole(산화방지제)일
  가능성이 있고, NIA의 `bha`는 beta hydroxy acid 문맥이다. 지식 데이터 설명은 살리실산 쪽이다. 이 ID로는 수집하지 않는다.
- **Salicylic Acid**(`5c3fa47f-…`): 제품 178개, NIA 3건, 근거 0건인데 audit routing에서는 P4다.
  BHA 대신 각질·모공 근거를 맡을 후보로 사용자 판단이 필요하다. Ascorbic Acid(제품 179, NIA 36, 근거 0건)도 같은 성격이다.
- **Aloe / Hyaluronate**: 알로에(잎즙·추출물·분말 등)와 히알루론산 계열이 여러 canonical로 쪼개져 있다.
  계열 통합 단위를 정하기 전에는 개별 성분으로 근거를 쌓지 않는다.
- **Centella**: `Centella Asiatica Extract`와 Madecassoside·Asiaticoside 등이 별도 성분이다. 근거를 어느 단위에 붙일지 확인이 필요하다.
- **Carapa Guianensis Seed Oil**: 제품은 `Guaianensis` 철자(old name)로 매칭됐다.

**Threshold-sensitive reference**: Retinol(NIA 167, 임계값 170 아래)은 routing 상 P4지만 검토 결과 INCLUDE다.
같은 이유로 임계값 근처 다른 성분이 놓쳤을 수 있으나 이번에는 임계값을 바꾸지 않았다.

**결정 반영**: (1) Salicylic Acid·Ascorbic Acid는 검토에 추가(둘 다 QA_PRIORITY), (2) 알로에·히알루론산·병풀 계열은 ID를 합치지 않고 query resolution 용도로만 묶는다, (3) Hexapeptide-2는 INCLUDE로 올리지 않고 candidate discovery smoke 표본으로 쓴다.

---

## 수집 전략 변경: 2,872 baseline 후보 + 수집 자격 검토 (2026-09-21)

### [CURRENT]
- DB: v4, `evidence_document` 46(MFDS 11 / CIR 10 / PubMed 25). audit universe 2,872 중 scientific 근거 0건
  2,858, 단일 source 8, CIR+PubMed 6(Audit result 참고). 이 수치가 baseline이며 수집 후 같은 audit를 다시 돌려 비교한다.
- 이전 전략("Tier A 10~20개만 수집 → 이후 long tail")은 폐기한다.

### [DECISION]
- baseline coverage 시도 대상은 **audit universe = confirmed product ingredient ∪ NIA 언급 ∪ 기존 근거 연결(2,872)**이며,
  IngredientMaster 21,974 전체가 아니다. 단, **2,872는 사전 확정된 최종 수집 대상이 아니다.** 제품에 들어간다는 이유만으로
  전부 수집하지 않도록 아래 수집 자격 규칙을 거쳐 최종 collection universe를 정한다.
- MFDS 8,288 chunk는 유지하고 scientific count에 넣지 않는다. 삭제·재수집 없음.

### 수집 자격 규칙 (`data/scripts/evidence_collection_universe.py`, 이름 규칙 + 기존 NIA/제품 수, LLM 없음)
결정 4종: `COLLECT_BASELINE` / `QA_PRIORITY`(수집하되 사람이 먼저 검수) / `DEFER` / `EXCLUDE_FROM_SCIENTIFIC_COLLECTION`.
순서: ① 사람 결정(Tier A manual review + Salicylic/Ascorbic Acid) → ② 계열명·기전 용어 EXCLUDE →
③ base/보존/폴리머/계면활성·에몰리언트/pH 조절 범주는 EXCLUDE(NIA 언급이 있으면 DEFER) → ④ 향료 알레르겐 DEFER →
⑤ NIA 0건이면서 제품 5개 미만(long tail)은 DEFER → ⑥ NIA ≥170 / P1·P3 / 제품 ≥100인 active / smoke 표본은 QA_PRIORITY →
⑦ 나머지 COLLECT_BASELINE. 제품 5개 기준(`MIN_PRODUCTS_FOR_BASELINE`)은 임의 값이라 확인이 필요하다.

| 결정 | 개수 |
|---|---:|
| COLLECT_BASELINE | 1,019 |
| QA_PRIORITY | 49 |
| DEFER | 1,219 |
| EXCLUDE_FROM_SCIENTIFIC_COLLECTION | 585 |

수집 가능 후보(COLLECT+QA) 1,068개. 범주별로는 botanical/ferment 597, active/functional 387, peptide/protein 84가 대부분이고,
polymer 163·surfactant/emollient 336·preservative 31·base 36·pH 13 등 약 580개는 자동 제외된다.
**한계**: 범주는 이름 정규식이라 오분류가 있다(예: 잔여 "active"에 폼·왁스·염류·수(水)류가 섞임). 결과는 제안이며 QA로 교정한다.

### 성분 family 처리 (canonical ID는 합치지 않는다)
family는 **query expansion 전용**이다. 근거가 family 전체를 다뤄도 특정 파생형에 자동 귀속하지 않고, 파생형 고유 근거만 그
`ingredient_id`에 연결한다. universe 안 멤버: hyaluronic 23, centella 21, vitamin_c 15, bha_aha 12, aloe 9, retinoid 5
(`ingredient_family_candidates.csv`).

| family | 대표 멤버(제품/NIA/근거) | expansion 용어 | 귀속 주의 |
|---|---|---|---|
| hyaluronic | Sodium Hyaluronate(1145/0/1), Hyaluronic Acid(517/0/2), Hydrolyzed HA(619) | hyaluronic acid, hyaluronan, sodium hyaluronate | 분자량·염·가교별 결과 상이 |
| aloe | Leaf Extract(94), Flower Extract(33), Leaf Juice(23), Leaf Juice Powder(4/481) | aloe vera, Aloe barbadensis | 잎즙/추출물/분말 별개 물질 |
| centella | Extract(590/13/1), Madecassoside(349/6/2), Asiaticoside(336), Madecassic/Asiatic Acid | Centella asiatica, gotu kola | 추출물 ≠ 단일 성분 |
| vitamin_c | Ascorbic Acid(179/36), 3-O-Ethyl(110/170), Sodium Ascorbyl Phosphate(108), Ascorbyl Glucoside(59) | ascorbic acid, vitamin C | L-AA 결과를 유도체에 귀속 금지 |
| retinoid | Retinol(74/167/3), Retinal(62/65), Hydroxypinacolone Retinoate(23), Retinyl Palmitate(18) | retinol, retinoid, retinaldehyde | 성분별 강도 상이 |
| bha_aha | Gluconolactone(218), Salicylic Acid(178/3), Capryloyl Salicylic Acid(138), Lactic(64), Glycolic(51) | salicylic acid, beta/alpha hydroxy acid | `BHA` 토큰은 butylated hydroxyanisole 가능성 |

### 개별 결정
- **Salicylic Acid**(제품 178·NIA 3·근거 0, routing P4): 추가 검토 결과 QA_PRIORITY. BHA 계열 대표 산이며 규제 농도·자극
  근거가 필요하다. BHA(ID `e48d0911-…`)는 계속 EXCLUDE(negative control).
- **Ascorbic Acid**(제품 179·NIA 36·근거 0, P4): QA_PRIORITY. 비타민C 원형이며 3-O-Ethyl 등 유도체와 귀속을 분리한다.
- **Hexapeptide-2**: DEFER 유지, candidate discovery smoke 표본(검색 가능성·noise·직접 근거 여부 확인용).

### [COLLECTION POLICY] broad discovery + compact retention
성분당 논문 quota 없음, 검색 결과 전량 적재 없음, 근거가 없으면 0건 허용. 후보는 성분당 10~20건까지 탐색하되 대표 1~3건만 남긴다.
저장 계약은 유지한다: PMID 1 = EvidenceDocument 1, abstract 전체 = EvidenceChunk 1(BGE-M3 1024, 원문 그대로);
CIR report = EvidenceDocument, 관련 section/page 원문 span = EvidenceChunk(page·section·URL·제목·status·날짜 보존).
- **PubMed 후보 발굴 설계**(구현 전): 기존 `PubmedEvidenceCollector`/`PubmedSelectionPolicy`(요청 간격 0.4초, 3회 재시도,
  질의당 15건, 출력 파일이 곧 진행 상태인 resume)를 재사용한다. 입력은 이 universe CSV(수동 목록 없음)에서 COLLECT/QA 성분을
  읽는다. query는 성분명 + alias + family expansion(한글 별칭 제외), pagination은 질의당 상한 15건, PMID 중복은 성분 간에도
  한 문서로 합쳐 성분 연결만 추가한다.
- **PubMed 필터 계약**(LLM 없음, 규칙 + 사람이 볼 수 있는 candidate 표현): abstract 필수, 제목/abstract의 성분 직접 언급,
  publication type(RCT/SR 우대, erratum·letter·case report 제외), human > in vitro > animal, 단일 성분 > 복합 제형,
  claim topic 키워드 관련성, 유사 논문 중복 제거, PMID/DOI 보존. 통과하지 못하면 `candidate`로 남겨 사람이 본다.
  LLM relevance filter는 필요하면 별도 제안으로만 남기고 실행하지 않는다.
- **CIR 가용성 발굴 설계**: 기존 `CirReportSelector`(final/amended 우선, 성분별 최신 1건, group review 처리)와
  `CirSectionChunker`를 재사용한다. **차단 요인**: robots.txt가 `/search/`를 막아 성분 → report 매핑을 자동으로 만들 수 없고
  (COMPACT_EVIDENCE_COLLECTOR.md), 지금은 사람이 status 페이지 UUID·PDF를 입력한다. 2,872 전체 availability 확인은 이
  입력 확보 방법(공식 목록 파일 등)이 정해져야 가능하다.

### [HUMAN QA]
Tier A는 **수집 gate가 아니라 QA 우선순위**다. 순서: ① 기존 P1/P3 + Tier A 후보, ② NIA 높은 성분, ③ 제품 많은 active,
④ retrieval test에서 문제가 난 성분. 목적은 query 적절성, 후보 필터, 대표 논문 선택 기준, 성분 매핑 오류 확인이다.

### Smoke 표본 (18개, 전량 실행 전 10 → 50 → 전체 순서)
Niacinamide, Retinol, Salicylic Acid, Ascorbic Acid, 3-O-Ethyl Ascorbic Acid, Sodium Ascorbyl Phosphate,
Centella Asiatica Extract, Madecassoside, Hyaluronic Acid, Sodium Hyaluronate, Hexapeptide-2, Collagen,
Acetyl Hexapeptide-8, Curcuma Longa Root Extract, Tocopherol, Glycerin(base 대조), Melanin(기전 용어 대조), BHA(모호 용어 대조).
각각 좋은 active / 파생형 / family / 모호 용어를 collector가 어떻게 처리하는지 본다.

### [NEXT IMPLEMENTATION]
① universe CSV를 collector 입력으로 읽는 어댑터 ② PubMed candidate discovery(smoke) ③ CIR availability 입력 확보 방법 결정
④ candidate 필터·대표 선택 ⑤ document/chunk 생성 ⑥ BGE-M3 embedding ⑦ DB ingest ⑧ audit 재실행 ⑨ Tier A QA ⑩ retrieval 평가.
대규모 외부 호출·embedding·DB write는 승인 전 실행하지 않았다.

---

## 확정 안 된 것 (다음 단계 시작 전 결정 필요)

- H.2의 source별 retrieval lane과 MFDS의 efficacy 검색 기본 제외 정책(Agent/Backend 합의 필요, 미반영)
- 기존 `rag_chunk` 테이블을 확장할지, `evidence_chunk`를 새 테이블로 분리할지
- CIR 이용약관 — 벌크 스크래핑 가능 여부, 저작권 조건
- `evidence_level`과 기존 `RagConfidenceTier`를 통합할지 별도로 둘지(개념은 겹치지만 소스 구성이 다름)

## 판정

**`EVIDENCE_RAG_DESIGN_READY`**

Source 전략·스키마·청킹·query bridge·retrieval 계약·citation 보존 전략까지는 확정 가능한 수준으로 설계했다. 다만 위 "확정 안 된 것" 3가지(특히 CIR ToS)는 설계가 아니라 외부 확인·의사결정이 필요한 항목이라 `NEEDS_SOURCE_DECISION`에 걸릴 수도 있는 유일한 리스크로 남겨둔다 — 이 문서의 스키마/계약 자체는 그 결정과 무관하게 그대로 쓸 수 있다.
