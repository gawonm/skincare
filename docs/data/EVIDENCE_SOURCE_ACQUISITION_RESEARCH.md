# Evidence Source Acquisition Research: PubMed / CIR

작성일: 2026-09-18
작성 목적: NIA Claim(현재 Windows 세션에서 3,581건 production annotation 진행 중, 미완료)을
뒷받침할 External Evidence를 PubMed / CIR에서 어떤 방식으로 확보할 수 있는지 실측 조사한다.
**코드 구현, DB 변경, 대량 수집은 하지 않았다.** 실제 공식 API/사이트를 대상으로 소규모 검증만
수행했다.

관련 기존 산출물:
- `models/evidence.py` — 현재 `Evidence` 테이블 스키마 (MFDS 전용, 단일 테이블. 문서에 적힌
  `EvidenceDocument`/`EvidenceChunk` 2-테이블 구조나 `docs/data/EVIDENCE_RAG_DESIGN.md` /
  `EVIDENCE_STORAGE_ERD.md`는 **저장소에 존재하지 않는다.** 아래 매핑은 이 사실을 반영해
  "현재 스키마 기준"과 "2-레이어 구조가 나중에 생긴다면"을 구분해서 적는다.
- `data/scripts/evidence_schemas.py` — MFDS 수집 단계 Pydantic 모델
- `agent/evidence_query_policy.py` — Evidence 검색 fallback 정책 (agent 파트, 이번 조사와
  직접 관련 없음)

---

## PubMed

### Official access method

**NCBI E-utilities** (`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`). 공식 REST API. 실제로
`esearch.fcgi`, `esummary.fcgi`, `efetch.fcgi` 세 엔드포인트를 호출해 확인했다 (아래 "Sample
searches" 참고). 키 없이 즉시 동작했다.

| 항목 | 결과 |
|---|---|
| API | NCBI E-utilities (esearch/esummary/efetch), REST, XML/JSON 응답 |
| API key | **선택.** 없어도 전부 동작 확인. 있으면 rate limit만 올라간다 |
| Rate limit | 공식 문서(NCBI Bookshelf NBK25497) 기준 **키 없음: 3 req/sec, 키 있음(무료 NCBI 계정 발급): 10 req/sec**. 대량 작업(하루 대량 요청)은 이메일 등록 및 사전 협의 권장이라고 명시돼 있음 |
| Metadata 확보 가능 | PMID, DOI, title, abstract, authors, journal, publication date, MeSH terms, publication type — **전부 실측 확인** (아래 참고) |
| Abstract 확보 | 가능. `efetch`에 `rettype=abstract&retmode=xml`로 `<AbstractText>` 그대로 나옴 |
| Full text | E-utilities 자체는 abstract까지만 보장. Full text는 PMC(오픈 액세스 서브셋)에 있을 때만 가능하고, PubMed 레코드 자체에는 없음 |
| PMC 관계 | PubMed(서지/초록 DB)와 PMC(본문 저장소)는 별개 시스템. PubMed 레코드의 `ArticleIdList`에 PMC ID가 있으면 PMC full text가 존재한다는 뜻이고, 없으면 존재하지 않거나 유료 저널이라 PMC에 안 실린 것 |
| Automation feasibility | 높음. 인증 불필요, 요청 형태 단순(GET), JSON/XML 파싱 용이. `requests` + `time.sleep(0.34)`(키 없을 때 3/sec 준수) 정도로 구현 가능 |

### Sample searches (실측, 2026-09-18 기준)

키워드는 단순 AND 조합으로 보냈고, NCBI가 자동으로 MeSH 용어로 번역(`querytranslation`)하는 것을
확인했다 — 즉 별도로 MeSH 문법(`[MeSH Terms]`)을 안 써도 Automatic Term Mapping이 관련 MeSH를
붙여준다. 정밀 검색이 필요하면 `[MeSH Terms]`를 명시해서 automatic mapping을 우회할 수 있다.

- **Niacinamide AND acne** — count: 94. 최상위 3개 PMID: 42406361, 41923969, 41537948.
  MeSH 번역: `"niacinamide"[Supplementary Concept] OR ... AND ("acne vulgaris"[MeSH Terms] OR ...)`.
  **노이즈 확인됨**: 최상위 결과(PMID 42406361)는 "여드름 흔적(색소침착)용 세럼의 멜라스마·PIH
  임상시험"으로, niacinamide가 여러 성분 중 하나로 들어간 복합 제제 논문이었다. acne 자체의
  치료 기전 논문이 아니었다 — **단일 성분 + 단일 claim_topic 키워드 조합만으로는 관련성이 낮은
  복합 제제/부수적 언급 논문이 상위에 섞인다.** relevance filtering이 별도로 필요하다는 뜻.
- **Niacinamide AND sebum** — count: 20. PMID: 42402180, 41187240, 41088896.
- **Retinol AND photoaging** — count: 256. PMID: 42430369, 42355603, 42332430.
  MeSH 번역이 "vitamin a"로 확장됨(`retinol` = vitamin A의 동의어 취급) — ingredient 이름과
  MeSH 개념명이 다를 수 있음에 유의.
- **Salicylic acid AND acne** — count: 281. PMID: 42514618, 42509804, 42504447.

### 상세 metadata 실측 (PMID 42406361, esummary + efetch)

| 필드 | 값 | 확보 방법 |
|---|---|---|
| PMID | 42406361 | esearch/esummary/efetch 공통 |
| DOI | 10.36849/JDD.9644 | efetch XML의 `ArticleId[@IdType='doi']` |
| Title | "Efficacy and Tolerability of a Topical Pigment-Correcting Serum in Melasma and Postinflammatory Hyperpigmentation." | esummary/efetch |
| Journal | Journal of drugs in dermatology : JDD | efetch |
| Publication date | 2026 Jul 01 | efetch `PubDate` |
| Authors | Grimes P, Dias S, Huang P, Cheng T, Makino E | esummary |
| Abstract | 320자 텍스트 존재 확인 | efetch `AbstractText` |
| Publication type | Journal Article, Clinical Trial | efetch `PublicationType` |
| MeSH terms | Humans, Female, Melanosis, Hyperpigmentation, Adult, Young Adult, Treatment Outcome, Quality of Life, Administration Cutaneous, Niacinamide 등 | efetch `MeshHeading` |
| URL | `https://pubmed.ncbi.nlm.nih.gov/42406361/` (PMID로 구성 가능, 공식 canonical URL 패턴) | 조합 |

즉 요청한 9개 metadata 필드(PMID, DOI, title, abstract, authors, journal, pub date, MeSH,
pub type, URL) **전부 공식 API로 확보 가능함을 실측 확인했다.**

### Abstract만으로 Evidence 구성 가능한가

가능하다고 판단한다. 이유:

- Evidence RAG의 목적은 "NIA Claim을 뒷받침"하는 것이지 논문 전체를 요약하는 게 아니다. 대부분의
  피부과 임상 논문 abstract는 Background/Methods/Results/Conclusion 구조라 결론(Claim을
  뒷받침하는 핵심 문장)이 abstract 안에 있다.
- Full text를 원문 그대로 수집하려면 PMC 오픈 액세스 서브셋에 없는 논문은 출판사 사이트에서
  긁어야 하는데, 이는 각 저널사 이용약관에 걸릴 가능성이 높고 자동화 난이도도 훨씬 높다.
- 다만 abstract만으로는 다음이 안 된다: 구체적 수치(농도, dosage, 부작용 발생률 등)가
  abstract에 생략된 경우, 방법론 세부사항이 필요한 경우. 이런 요구가 나중에 생기면 PMC full
  text로 확장을 검토해야 한다 (지금은 미정으로 남긴다).

### PubMed vs PMC 역할 구분

| | PubMed | PMC |
|---|---|---|
| 성격 | 서지/초록 데이터베이스 (거의 모든 생의학 논문의 citation + abstract) | 본문 저장소 (오픈 액세스 서브셋만 free full text) |
| 우리 Evidence corpus에서 역할 | **1차 소스.** abstract 기반 EvidenceChunk 생성 | **선택적 보강.** PubMed 레코드에 PMC ID가 있고 결론 검증에 abstract만으로 부족할 때만 참조 |
| coverage | 거의 전체 | PubMed의 일부 (오픈 액세스 저널 또는 저자가 기탁한 논문만) |

### Ingredient + claim_topic 검색 구성 제안

- 기본형: `(ingredient_term) AND (claim_topic_term)` — Automatic Term Mapping이 MeSH를
  자동으로 붙여줘서 별도 MeSH 매핑 테이블 없이도 어느 정도 recall 확보됨 (실측 확인).
- 정밀형(권장, 나중 단계): ingredient는 `[Supplementary Concept]` 또는 성분명 그대로,
  claim_topic은 `[MeSH Terms]`를 명시해서 붙이면 automatic mapping의 과확장(예: retinol →
  vitamin A 전체)을 통제할 수 있다. 예: `"niacinamide"[Supplementary Concept] AND "acne
  vulgaris"[MeSH Terms]`.
- Publication type 필터(`AND (Clinical Trial[pt] OR Randomized Controlled Trial[pt] OR
  Review[pt])`)를 걸면 사설/편지/증례보고 노이즈를 줄일 수 있다 — 위 니아신아마이드 사례처럼
  "성분이 언급됐을 뿐인 복합제제 임상시험"은 이 필터로도 못 거르므로, 결국 abstract 내용 기반
  relevance 판정이 별도로 필요하다.
- **NIA Claim이 확정되기 전에는 이 쿼리 템플릿을 확정하지 않는다.** claim_topic 어휘가 NIA
  annotation 결과에 따라 달라질 수 있기 때문이다.

### PubMed → EvidenceDocument mapping

프로젝트의 실제 `Evidence` 테이블은 아래 컬럼을 갖고 있다: `ingredient_id, topic, claim,
conditions, jurisdiction, regulate_type, cas_no, ingredient_synonym, notice_ingredient_name,
source_type, source_title, source_url, published_at, collected_at`. PubMed는 `regulate_type`
(MFDS 전용), `notice_ingredient_name`(MFDS 전용) 같은 필드와 맞지 않는다 — **PubMed를 담으려면
스키마 자체를 확장해야 한다**(현재 CheckConstraint가 `source_type IN ('mfds_restricted_ingredient')`,
`topic IN ('cosmetic_use_restriction')`로 MFDS만 허용하도록 하드코딩돼 있음). 이는 이번 조사
범위를 넘는 스키마 변경이라 규칙 14(ERD 문서 선공유)를 따라야 하고, 임의로 진행하지 않는다.

아래는 "PubMed 필드가 무엇에 대응되는가"를 개념적으로 정리한 것이다. 실제 컬럼 설계는 ERD 문서
작성 시 사용자와 합의한다.

| 개념적 필드 | PubMed에서 확보 가능한가 | 상태 |
|---|---|---|
| source_type | "pubmed" 같은 새 enum 값 필요 | DERIVED (우리가 정의) |
| source_id (PMID) | esearch/efetch | DIRECT |
| source_title (논문 제목) | efetch ArticleTitle | DIRECT |
| source_url | `https://pubmed.ncbi.nlm.nih.gov/{pmid}/` | DERIVED (PMID로 조합) |
| publisher (저널명) | efetch Journal/Title | DIRECT |
| document_date (발행일) | efetch PubDate | DIRECT |
| retrieved_at (수집 시각) | 수집 스크립트가 기록 | DERIVED |
| doi | efetch ArticleId[@IdType=doi] | DIRECT (없는 논문도 있음 — nullable 처리 필요) |
| pmid | esearch/efetch | DIRECT |
| jurisdiction | 해당 없음(국가 규제 개념이 아님) | NOT_AVAILABLE |
| evidence_level (근거 수준: RCT/리뷰/증례 등) | efetch PublicationType으로 유추 가능 | DERIVED (publication type → evidence_level 매핑 규칙을 우리가 정의해야 함, 자동 산출 아님) |

### PubMed → EvidenceChunk 옵션 (결정하지 않음, 장단점만 제시)

1. **Abstract 전체를 하나의 chunk로**
   - 장점: 구현 간단, 문맥 손실 없음(짧은 abstract는 통째로도 임베딩 품질 괜찮음), chunk-문서
     매핑이 1:1이라 provenance 추적이 쉬움.
   - 단점: abstract가 길면(구조화된 abstract, 300~500 단어) 여러 주제가 섞여 검색 정밀도가
     떨어질 수 있음. 하나의 abstract에 여러 claim_topic이 섞여 있으면 특정 topic만 뽑기 어려움.

2. **Abstract를 section 단위로 (Background/Methods/Results/Conclusion)**
   - 장점: Results/Conclusion만 별도로 임베딩하면 "효능 주장"에 더 집중된 검색 가능.
   - 단점: PubMed abstract가 항상 구조화돼 있지 않음(구조화 라벨이 없는 논문도 많음) — 라벨
     파싱 규칙이 논문마다 달라 파싱 실패/누락 위험. 섹션이 없는 논문은 결국 1번과 동일해짐.

3. **문장/스팬 단위**
   - 장점: 가장 세밀한 검색 정밀도, 특정 문장 하나를 citation으로 정확히 짚을 수 있음(Citation
     보존 원칙에 유리).
   - 단점: 구현 복잡도 최고(문장 분리기 필요, 문맥 단절 위험 — 문장 하나만 떼면 "이 결과가 어떤
     조건에서 나왔는지"가 사라질 수 있음), chunk 수가 급증해 임베딩/저장 비용 증가.

이번 조사에서는 최종 선택하지 않는다. NIA Claim의 granularity(문장 단위 statement Claim RAG와
동일 수준인지)가 정해진 뒤 결정하는 게 맞다고 판단한다.

---

## CIR (Cosmetic Ingredient Review)

### Official access method

**공식 API 없음.** 두 개의 사이트가 실제로 존재하는 것을 확인했다:

1. `https://www.cir-safety.org` — 메인 사이트(Drupal 기반). "CURRENTLY UNDER REVIEW"(현재
   심사 중, 아직 최종 확정 안 된) 성분의 draft 보고서를 정적 PDF로 직접 링크한다. 예:
   `https://www.cir-safety.org/sites/default/files/Kojic%20Acid_0.pdf` (실측 확인, 응답 200).
2. `https://cir-reports.cir-safety.org` — 별도 서브도메인, Microsoft Power Apps/Dynamics 365
   Portal 기반(`ARRAffinity`, `Dynamics365PortalAnalytics` 쿠키로 실측 확인). 이미 검토 완료된
   전체 성분의 **최종(Published/Final) 보고서 상태 조회 + PDF 뷰어**를 제공한다.

두 사이트 다 "성분명 → 보고서" 자동 매핑용 API가 아니라 **사람이 보는 웹 UI**다. 자동화하려면
HTML 파싱(스크래핑)이 필요하다.

### robots.txt / 이용약관 결과 (실측)

`https://www.cir-safety.org/robots.txt` 확인 결과:

```
User-agent: *
Crawl-delay: 10
Disallow: /admin/ /search/ /user/... (관리자, 검색, 로그인 경로 등)
```

- **Crawl-delay: 10초**가 명시돼 있음 — 요청 사이 최소 10초 간격을 지켜야 한다는 뜻으로,
  대량 수집을 사실상 강하게 제한한다(성분 수백 개를 이 규칙대로 돌면 하루 이상 소요).
- `/search/` 경로는 명시적으로 **금지**돼 있음. 실제로 `www.cir-safety.org/search/node/...`를
  호출했더니 "Access denied" 페이지가 반환되는 것을 확인했다 — robots.txt를 서버가 실제로
  강제하고 있다는 뜻이다.
- 성분 보고서 페이지(`/sites/default/files/*.pdf`, `cir-reports.cir-safety.org/*`)는 disallow
  목록에 없음 — 개별 페이지 접근 자체는 막혀 있지 않다.
- **Terms of Use 페이지를 별도로 찾지는 못했다**(이번 조사에서 명시적 ToS 문서를 확인하지
  못함 — Open question으로 남긴다). robots.txt 수준의 크롤링 정책만 확인했다.

**결론: 소량/느린 속도(성분 하나씩, 10초 이상 간격)의 자동 조회는 robots.txt상 허용 범위로
보이지만, 대량 크롤링(수백~수천 성분을 짧은 간격으로)은 Crawl-delay 위반이라 하면 안 된다.**
이 판단이 법적 검토를 대체하지는 않는다 — 실제 자동화 전에 사람이 한 번 더 확인 권장.

### Sample reports (실측, 2026-09-18)

`cir-reports.cir-safety.org`의 실제 검색창(알파벳 브라우즈 아래 텍스트 입력 + 버튼, AI 챗봇
검색창과는 별개 UI — 주의: 이 서브도메인 루트에 진입 직후 별도의 "AI summary" 챗봇 검색창이
있는데 이건 안 됨, 실측 시 "I'm sorry, I'm unable to process your question"만 반환했다.
알파벳 브라우즈 섹션의 텍스트박스가 실제로 동작하는 검색이다) 로 조회:

| Ingredient | 결과 | Report URL (status 페이지) | PDF 존재 |
|---|---|---|---|
| Niacinamide | "Niacinamide" 단독 항목 존재, Status: Published Report, Date/Reference: `IJT 24(Suppl 5):1-31, 2005` | `https://cir-reports.cir-safety.org/cir-ingredient-status-report?id=2a9f266a-adc8-4012-8d02-6a8adb8fe55f` | 있음 — `/view-attachment?id=39cd1a17-8e74-ec11-8943-0022482f06a6`, 실제로 열어보니 PDF 뷰어 렌더링되고 문서 제목이 "Final Report of the Safety Assessment of Niacinamide and Niacin"으로 표시됨 (실측) |
| Retinol | "Retinol" 단독 항목 존재 (Retinyl Palmitate와 별개 항목) | 확인만 함(status 페이지는 열지 않음, PDF는 이번 조사에서 미확인) | 미확인(패턴상 있을 것으로 추정하지만 실측 안 함) |
| Salicylic Acid | "Salicylic Acid" 단독 항목 존재. **보고서가 2건**: `IJT 44(Suppl.4):5-57, 2025`(최신, amended) 와 `IJT 22(Suppl 3):1-108, 2003`(원본, Salicylates 그룹 리뷰) | `https://cir-reports.cir-safety.org/cir-ingredient-status-report?id=2e191a9d-7e93-4141-8e84-05e13026c871` | 미확인(PDF 링크는 열지 않음, 대량 다운로드 금지 지침에 따라 이번엔 1건만 열었다) |

**중요 발견**: Salicylic Acid처럼 **한 성분에 보고서가 여러 건(원본 + amended/update)** 있을
수 있다. Provenance 설계 시 "이 성분의 최신 보고서인지"를 판단할 `published_at`/버전 필드가
필요하다 — 오래된 보고서만 인용하면 최신 안전성 결론과 어긋날 위험이 있다.

### Document 구조 / ingredient mapping 난이도

- `cir-reports.cir-safety.org`는 성분마다 **고유 UUID**(`id=` 쿼리 파라미터)를 가진 status
  페이지가 있고, 그 안에 PDF에 대한 `/view-attachment?id=...` 링크가 있다 — 이 링크는
  기본 HTML 렌더링에는 안 보이고(`get_page_text`로는 안 나옴) accessibility tree/DOM을 직접
  읽어야 찾을 수 있었다. 즉 단순 텍스트 스크래핑으로는 놓치기 쉬운 구조다.
- 성분명 검색은 정확한 INCI 명칭 매칭에 의존한다("Niacinamide" 검색 시 "Niacin"도 같이
  나옴 — 부분 문자열 매칭). 별칭(synonym) 처리가 필요할 수 있다.
- 그룹 리뷰(Salicylates 그룹처럼 여러 성분을 한 보고서에서 다루는 경우)가 있어 "성분 1개 =
  보고서 1개"가 항상 성립하지 않는다 — mapping 시 many-to-one 관계를 고려해야 한다.
- `/view-attachment` 엔드포인트는 301 리다이렉트 + 세션 쿠키(`ARRAffinity`,
  `Dynamics365PortalAnalytics`) 기반 응답이다. `curl`로 헤더만 확인했을 때는 HTML 셸만
  받아지고 실제 PDF 렌더링은 브라우저의 JS 실행이 필요했다(실측: `curl -sIL`로는 200 text/html
  content-length 33450만 보이고, 브라우저로 열어야 탭 제목이 "Final Report of the Safety
  Assessment of Niacinamide and Niacin"으로 바뀌며 PDF가 나타남). **httpx 같은 단순 HTTP
  클라이언트만으로는 PDF를 못 받을 가능성이 높고, headless 브라우저(Playwright 등)가 필요할
  수 있다** — data 파트가 올리브영 글로벌 검색 API에서 이미 겪은 것과 유사한 패턴
  (`docs/data/README.md`의 Cloudflare 봇 관리 사례 참고).

### PDF에서 확보 가능한 metadata

실제로 연 PDF(Niacinamide 최종 보고서)의 렌더링 결과 기준:

| 항목 | 확보 가능 여부 |
|---|---|
| report title | 가능 — PDF 자체 제목(문서 title 메타데이터로 브라우저 탭에 표시됨): "Final Report of the Safety Assessment of Niacinamide and Niacin" |
| ingredient(s) | 가능 — 제목/본문에 명시 |
| publication/review date | 가능 — status 페이지의 "Date/Reference" 컬럼(`IJT 24(Suppl 5):1-31, 2005` 형태, 저널 인용 형식이라 파싱 필요) |
| conclusion / safety assessment | PDF 본문 안에 있음 — 이번 조사에서는 PDF 전체 텍스트를 추출/파싱하지 않았다(대량 처리 금지 지침 준수, 뷰어 렌더링 확인까지만 함). **실제 conclusion 텍스트 추출 가능 여부(PDF가 텍스트 레이어를 가진 디지털 PDF인지, 스캔 이미지인지)는 미확인 — Open question으로 남긴다** |
| page / section | PDF 뷰어가 페이지 단위 렌더링을 하는 것은 확인했으나, section(예: "Discussion", "Conclusion" 챕터) 좌표 추출은 미확인 |
| source URL | 가능 — status 페이지 URL + view-attachment URL 둘 다 안정적인 것으로 보임(UUID 기반, 재현 가능했음) |

### CIR → EvidenceDocument / EvidenceChunk mapping

| 개념적 필드 | CIR에서 확보 가능한가 | 상태 |
|---|---|---|
| source_type | "cir" 같은 새 enum 값 필요 | DERIVED |
| source_id | UUID(`id=` 파라미터) | DIRECT |
| source_title | PDF 제목 / status 페이지의 성분명 | DIRECT |
| source_url | status 페이지 URL + PDF view-attachment URL | DIRECT |
| publisher | "Cosmetic Ingredient Review" 고정값 | DIRECT |
| document_date | 저널 인용 문자열(`IJT 24(Suppl 5):1-31, 2005`)에서 연도 파싱 | DERIVED (파싱 필요, 형식이 일정하진 확인했으나 group review는 "1-108" 같은 페이지 범위까지 포함돼 정규식 설계 필요) |
| doi | 최종보고서가 International Journal of Toxicology에 게재되므로 저널 자체 DOI가 있을 수 있으나, **CIR 사이트 자체에서는 DOI를 노출하지 않는 것으로 보임(이번 조사에서 못 찾음)** | NOT_AVAILABLE (CIR 페이지 기준. IJT 저널 사이트에서 별도 조회하면 가능할 수 있음 — 미확인) |
| jurisdiction | 미국(FDA 자율규제 패널) 고정값으로 유추 가능하나 CIR 자체가 "jurisdiction" 개념을 명시하지 않음 | DERIVED |
| page/section | 이번 조사에서 미확인 | NOT_AVAILABLE (현재까지) |

**CIR → EvidenceChunk 옵션 (결정 안 함)**

1. **PDF 전체 텍스트를 하나의 문서로, 섹션(Discussion/Conclusion) 단위 chunk**
   - 장점: safety assessment 보고서는 구조가 일정함(Chemistry, Use, Toxicology, Discussion,
     Conclusion 순서가 관행적으로 유지됨) — 섹션 기반 chunk가 논문보다 안정적으로 될 가능성.
   - 단점: 섹션 헤더 파싱 규칙을 PDF 텍스트 레이어에서 뽑아야 함(레이아웃이 2단 컬럼일 수
     있어 PDF-to-text 라이브러리에 따라 순서가 깨질 위험 — 이번 조사에서 실제 텍스트 추출은
     안 해봤으므로 확인 필요).
2. **Conclusion 문단만 별도로 추출**
   - 장점: Claim 뒷받침에 가장 직접적으로 쓰이는 부분만 정밀 추출.
   - 단점: "Conclusion"이라는 제목이 보고서마다 정확히 같은 표현인지 확인 안 됨, 추출 실패 시
     전체 보고서를 못 쓰게 될 위험.

---

## 2. Evidence 목적 구분 — claim_topic별 source 특성

| Source | ingredient_effect_claim (efficacy) | usage_instruction | combination_claim | precaution | regulatory |
|---|---|---|---|---|---|
| **PubMed** | **적합.** 임상시험/기전 연구가 많아 "성분 X가 Y에 효과가 있다"는 주장을 직접 뒷받침하는 1차 문헌이 많음(실측: Retinol AND photoaging 256건, Niacinamide AND sebum 20건) | **부분 적합.** 사용법(농도, 시간대, 병용 순서 등)을 다루는 논문도 있지만 "임상시험 프로토콜"에 부수적으로 실린 경우가 많아 usage_instruction 자체가 논문의 핵심 주제인 경우는 적음 | **부분 적합.** 두 성분 병용 연구(`ingredient A + ingredient B` 검색)는 존재하지만 검색량이 단일 성분보다 훨씬 적을 것으로 예상됨(이번 조사에서 조합 검색은 실측 안 함 — Open question) | **적합.** 부작용/자극성/광독성 연구(RCT의 adverse event 보고, 리뷰 논문)가 많음 | **부적합.** PubMed는 학술 문헌이지 각국 규제 데이터베이스가 아님 |
| **CIR** | **부분 적합.** Safety assessment 보고서는 "안전하다/위험하다"는 결론은 있지만 "효과가 있다"는 efficacy 주장을 목적으로 하지 않음 — CIR은 안전성 평가 기관이지 효능 평가 기관이 아니다 | **적합.** 최종 보고서에 "이 농도까지는 안전", "이 사용 형태(leave-on/rinse-off)에서는" 같은 조건부 결론이 명시적으로 실림(MFDS의 `conditions` 필드와 유사한 성격) | **부적합~미정.** CIR 보고서는 개별 성분(또는 성분군) 단위 평가라 "성분 A와 B를 같이 쓰면"이라는 조합 평가는 거의 없음(그룹 리뷰는 화학적으로 유사한 성분 묶음이지 제형 내 병용 평가가 아님) | **매우 적합.** CIR 보고서의 핵심이 안전성 한계·주의사항·금지 조건이므로 precaution claim과 가장 직접적으로 대응됨 | **부적합.** CIR은 미국 산업 자율규제 패널 결론이지 각국 정부 규제 그 자체가 아님(MFDS와는 성격이 다름 — 참고 자료로만 인용 가능, "규제"로 표기하면 오해 소지) |
| **MFDS** (기존 8,288건 실측 확인됨) | **부적합.** 사용제한/금지 성분 목록이라 효능 주장이 없음 | **부적합~약함.** `LIMIT_COND`(한도 조건)가 사용조건과 유사할 수 있으나 "사용법 안내"가 목적이 아니라 "규제 한도"가 목적 | **부적합.** 병용 관련 정보 없음 | **적합.** `PROHIBITED`/`LIMITED` 자체가 precaution의 가장 강한 형태(금지/한도) | **가장 적합.** 원래 목적 그 자체(한국 정부 공식 규제 데이터) |

**요약**: PubMed는 efficacy/precaution, CIR은 precaution/usage(조건부), MFDS는 regulatory가
각각의 강점이다. 세 소스 다 combination_claim은 약하다 — 이 claim_topic은 별도 소스(예: 임상
가이드라인, 화장품 배합 안정성 연구)를 찾아야 할 수 있음(Open question).

---

## Recommended acquisition architecture

```
NIA Claim (Windows 세션 완료 후 확정)
    ↓
evidence_collection_target  (claim_topic + ingredient + 우선순위)
    ↓
source selection (claim_topic 특성에 따라 분기, 위 표 기준)
    ├─ PubMed   (efficacy, precaution 우선)
    ├─ CIR      (precaution, usage 조건 우선)
    └─ MFDS     (regulatory — 이미 구현됨, 8,288건 적재 완료)
    ↓
source search
    ├─ PubMed: E-utilities esearch → esummary/efetch (자동화 가능, rate limit 준수)
    └─ CIR: 알파벳 브라우즈/텍스트 검색 → status 페이지 → PDF (headless 브라우저 필요 가능성, Crawl-delay 10초 준수)
    ↓
EvidenceDocument  (스키마 확장 필요 — 현재 Evidence 테이블은 MFDS 전용 CheckConstraint로 잠겨 있음)
    ↓
EvidenceChunk  (chunk 단위는 미정 — abstract 전체 vs section vs sentence)
    ↓
BGE-M3
    ↓
pgvector
```

**이번 조사에서 확인한 가장 큰 구조적 이슈**: 문서에서 전제한 `EvidenceDocument`/`EvidenceChunk`
2-테이블 스키마는 아직 존재하지 않는다. 현재 `models/evidence.py`의 `Evidence`는 단일 테이블이고
`source_type`/`topic`이 MFDS 값으로 하드코딩(CheckConstraint)돼 있다. PubMed/CIR를 실제로
적재하려면:

1. `EvidenceSourceType`에 `PUBMED`, `CIR` 추가 (또는 2-테이블 구조로 재설계)
2. CheckConstraint 갱신
3. PubMed/CIR 전용 필드(pmid, doi, publisher 등) 추가 여부 결정
4. Chunk 단위 결정에 따라 별도 `EvidenceChunk` 테이블 신설 여부 결정

이는 규칙 14(ERD 문서 선공유 → 사용자 확인 → models 작성 → 마이그레이션)를 따라야 하는 스키마
변경이라 **이번 조사 범위에서 진행하지 않았다.**

---

## Open questions

1. **CIR 이용약관(ToS) 원문을 못 찾았다.** robots.txt 수준의 크롤링 정책만 확인했다 —
   실제 자동 수집 전에 ToS 페이지를 별도로 찾아 확인이 필요하다.
2. **PubMed 조합 검색(`ingredient A + ingredient B`, combination_claim용)의 실제 검색량과
   relevance를 실측하지 않았다** — 이번 조사는 단일 성분 + 단일 topic 조합만 검증했다.
3. **CIR PDF의 텍스트 레이어 추출 가능 여부(스캔 이미지 vs 디지털 텍스트)를 확인하지 않았다** —
   OCR이 필요할 수도 있다.
4. **CIR 보고서의 page/section 좌표를 안정적으로 뽑을 수 있는지 미확인** — provenance 요구사항
   중 "page/section 보존"은 현재 기준 확답 불가.
5. **PubMed 결과의 relevance 필터링 전략(단순 publication type 필터 vs abstract 내용 기반
   재순위화)을 정하지 않았다** — 니아신아마이드 사례처럼 성분이 부수적으로만 언급된 논문을
   거르는 규칙이 필요하다.
6. **combination_claim을 어떤 source로 뒷받침할지 셋 다 약하다** — 별도 source 조사가 필요할
   수 있다(이번 조사 범위 밖).

---

## READY_FOR_PUBMED_COLLECTOR_IMPLEMENTATION: NO

이유: (1) NIA Claim이 아직 확정되지 않아 evidence_collection_target을 만들 수 없음, (2) 현재
`Evidence` 스키마가 MFDS 전용으로 잠겨 있어 PubMed 데이터를 넣을 자리가 없음(스키마 변경은
규칙 14에 따라 ERD 선공유 필요), (3) EvidenceChunk 단위(abstract/section/sentence)가 미정,
(4) relevance 필터링 전략 미정.

## READY_FOR_CIR_COLLECTOR_IMPLEMENTATION: NO

이유: 위 1~2와 동일하게 스키마 이슈가 있고, 추가로 (1) PDF 텍스트 추출 가능성 미검증, (2)
page/section 보존 가능 여부 미확인, (3) ToS 원문 미확인, (4) headless 브라우저 자동화가
필요할 가능성이 있어 구현 난이도가 PubMed보다 높음 — 별도 기술 검토가 먼저 필요.
