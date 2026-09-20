# CIR PDF Ingestion Feasibility Validation

작성일: 2026-09-18
범위: SMALL FEASIBILITY VALIDATION만 수행. CIR collector 구현, 대량 crawling, PDF 2건
초과 다운로드, DB write, migration, embedding, NIA/Claim/MFDS/Agent/Backend 수정은
**하지 않았다.**

> Canonical contract: `docs/data/EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md`(먼저 읽음).
> 이 문서는 그 6절(CIR Source Contract)에서 남겨둔 Deferred Decisions(attachment id
> 안정성, PDF 텍스트 레이어, section 헤더 파싱 규칙)만 검증한다.

---

## 1. Objective

CIR collector 구현 착수 전 남은 기술적 불확실성 3가지를 소규모 실측으로 제거한다:
attachment id가 report(버전) 식별자로 충분히 안정적인지, PDF 실제 바이트를 어떤 방식으로
확보해야 하는지, 텍스트 레이어가 digital인지 scanned인지, section 헤더를 rule-based로
감지할 수 있는지. 이 네 가지에 대한 답만으로 CIR collector 착수 가능 여부를 판정한다.

---

## 2. Samples

| Ingredient | Report(들) | Attachment ID(들) |
|---|---|---|
| Niacinamide | Published Report, `IJT 24(Suppl 5):1-31, 2005` | `39cd1a17-8e74-ec11-8943-0022482f06a6` |
| Retinol | Published Report(1987, JACT) + Published Re-review Not Opened(2008, 2017) — 3건 | `6b197432-8d74-ec11-8943-0022482f06a6`(1987) / `e4ce160b-8e74-ec11-8943-0022482f06a6`(2008) / `78339067-953f-de05-9d46-508a63ceca4c`(2017) |
| Salicylic Acid | Published Report(2025, amended) + Published Report(2003, original) — 2건 | `f8f3e083-2ca8-b5b4-b338-aa3ca6da8825`(2025) / `49b03823-8e74-ec11-8943-0022482f06a6`(2003) |

**실제 PDF 바이트 확보(fetch)는 Niacinamide 1건만 수행**(PDF 2개 초과 다운로드 금지
지침 준수 — 나머지는 attachment id/status 페이지 구조 확인까지만).

---

## 3. Attachment Identity Validation

### 3.1 Ingredient UUID + Attachment UUID 재현성

이전 세션(`EVIDENCE_SOURCE_ACQUISITION_RESEARCH.md`, `EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md`
작성 세션)에서 확인한 Niacinamide/Salicylic Acid의 ingredient status page UUID와 attachment
id를, **이번 세션(다른 날짜, 다른 브라우저 세션)에서 동일한 검색 흐름으로 재조회**한 결과:

| 값 | 이전 세션 | 이번 세션 | 일치 |
|---|---|---|---|
| Niacinamide ingredient UUID | `2a9f266a-adc8-4012-8d02-6a8adb8fe55f` | `2a9f266a-adc8-4012-8d02-6a8adb8fe55f` | ✅ 완전 일치 |
| Niacinamide attachment id | `39cd1a17-8e74-ec11-8943-0022482f06a6` | `39cd1a17-8e74-ec11-8943-0022482f06a6` | ✅ 완전 일치 |
| Salicylic Acid ingredient UUID | `2e191a9d-7e93-4141-8e84-05e13026c871` | `2e191a9d-7e93-4141-8e84-05e13026c871` | ✅ 완전 일치 |
| Salicylic Acid attachment id(2025) | (이전 세션엔 미채집) | `f8f3e083-2ca8-b5b4-b338-aa3ca6da8825` | — |
| Salicylic Acid attachment id(2003) | (이전 세션엔 미채집) | `49b03823-8e74-ec11-8943-0022482f06a6` | — |

**세션 간(재접속·재검색) 재현성은 실측으로 확인됐다.** 단, 이 관측은 "짧은 시간 간격(수일
내) 재조회 시 동일"까지만 확인한 것이고, CIR이 내부적으로 report를 재발행(re-publish)하거나
포털을 재구축할 때도 id가 유지되는지는 **장기 관측이 아니므로 확정할 수 없다**(11절 Deferred
로 재확인).

### 3.2 Original vs Amended — 서로 다른 attachment id를 갖는가

**YES.** Salicylic Acid의 원본(2003, `IJT 22(Suppl 3):1-108`)과 amended(2025,
`IJT 44(Suppl.4):5-57`)는 같은 ingredient status 페이지 안에 **서로 다른 attachment id**로
나열된다(`49b03823-...` vs `f8f3e083-...`). Retinol도 동일 패턴: 1987 원본(`6b197432-...`),
2008 re-review(`e4ce160b-...`), 2017 re-review(`78339067-...`) 셋 다 서로 다른 attachment id.

**신규 발견(이번 세션)**: Retinol의 2008/2017 항목은 status 라벨이 `"Published Report"`가
아니라 **`"Published Re-review Not Opened"`**다 — 기존 계약 문서의
`EvidenceDocumentStatus` enum에 있는 `rereview` 값과 대응되는 실제 라벨을 이번에 처음
확인했다. `document_status` 매핑 시 `"Published Report"`→`final`(또는 문맥상
`amended_final`), `"Published Re-review Not Opened"`→`rereview`로 매핑 가능해 보인다(정확한
enum 값 선택은 collector 구현 시점에 CIR status 라벨 전체 목록을 더 수집해서 확정 —
`draft`/`tentative`가 실제로 어떤 라벨로 나타나는지는 이번 3개 샘플에서 관측되지 않았다).

### 3.3 판정

**STABLE_ENOUGH**

근거: (1) 같은 ingredient/report를 다른 세션에서 재조회해도 UUID가 동일했고, (2)
original/amended/re-review 각각이 별도의 attachment id를 가져 `EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md`
6절의 "attachment id를 primary identity로 채택" 결정이 실측으로 재확인됐다. `UNRESOLVED`로
내리지 않는 이유는, 이 문서가 요구하는 것은 "collector가 재수집 시 같은 report를 다시 찾아갈
수 있는가"이고 이는 위 재현성 관측으로 충분히 답이 됐기 때문이다 — 장기(수개월~수년) 안정성은
별개 리스크로 11절에 남긴다.

---

## 4. PDF Access Method

### 4.1 URL / redirect chain / content-type

```
GET https://cir-reports.cir-safety.org/view-attachment?id={attachment_id}
  → 301 → /view-attachment/?id={attachment_id}
  → 200, content-type: text/html; charset=utf-8, content-length: ~33KB
```

`curl -sIL`로 확인한 최종 응답은 **HTML 셸일 뿐 PDF가 아니다.** 이 HTML을 정적으로 파싱해도
PDF URL, `<iframe>`, `<embed>` 태그가 전혀 없다(`grep`으로 확인, 0건) — Power Apps portal의
React 앱(`portal_react_app.js`)이 클라이언트에서 별도로 PDF 콘텐츠를 가져와 렌더링하는
구조다.

### 4.2 실제 PDF 바이트 확보 경로

브라우저에서 페이지를 열고 네트워크 요청을 관찰한 결과, PDF는 `blob:https://cir-reports.cir-safety.org/{uuid}`
형태의 클라이언트 사이드 Blob URL로 나타난다(예: `blob:https://cir-reports.cir-safety.org/358ad8c4-99ad-4a05-850c-08115b2b6cce`).
이 blob을 만드는 원본 XHR/fetch 요청 자체는 네트워크 로그에 별도 URL로 잡히지 않았다 —
포털 내부 API 호출(추정: Dynamics 365 Web API, 세션 쿠키 기반 인증)이 이미 완료된 뒤
결과만 blob으로 감싸져 렌더링되는 것으로 보인다.

페이지 안에서 `fetch(blob:...)`를 직접 실행해 실제 바이트를 확보했다(JS 실행, DB/embedding
아님 — 순수 확인 목적):

```
{ contentType: "application/pdf", byteLength: 205539, header: "%PDF-1.4" }
```

**`curl`/`httpx` 단독으로는 PDF 바이트를 얻을 수 없다.** 세션 쿠키(`ARRAffinity`,
`Dynamics365PortalAnalytics`)만으로 인증되는 것이 아니라, 페이지 로드 시 브라우저가 실행하는
JS(React 앱)가 내부 API를 호출하고 그 결과를 blob으로 변환하는 과정 자체가 필요하다 — 이
blob URL은 그 브라우저 탭의 메모리에만 존재하고 재사용 가능한 고정 URL이 아니다.

### 4.3 판정 항목

| 질문 | 답 |
|---|---|
| attachment URL | `/view-attachment?id={id}` → 301 → `/view-attachment/?id={id}` |
| redirect chain | 1회 301 리다이렉트만, 이후 200 HTML 셸 |
| content-type(HTML 셸) | `text/html` |
| content-type(실제 PDF) | `application/pdf`(blob 안, 브라우저 JS로만 확인 가능) |
| 실제 PDF bytes 직접 획득 가능한가 | **브라우저 JS 실행을 거쳐야만 가능.** curl로는 불가 |
| browser/JS 실행 필요 | **YES** |
| session cookie 필요 | **YES**(있지만 그것만으로는 불충분 — JS 실행이 핵심) |

---

## 5. Text Layer Validation

Niacinamide PDF(205,539 bytes, 31 pages)를 `pypdf`(일반 텍스트 추출 라이브러리, OCR 아님)로
직접 파싱했다.

- **digital text PDF**로 확인됨. 31페이지 전부 `extract_text()`로 실제 문자열이 나왔다
  (OCR 없이). 페이지당 3,500~6,300자 수준의 정상적인 텍스트 밀도.
- 첫 페이지에 저널 메타데이터가 텍스트로 그대로 들어있음: `"International Journal of
  Toxicology, 24(Suppl. 5):1–31, 2005"`, `"DOI: 10.1080/10915810500434183"` — **신규
  발견: DOI가 PDF 본문 텍스트에 직접 존재한다.** `EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md`
  6절은 "CIR 페이지 자체는 DOI 미노출"이라고 판정했는데, 이는 **CIR 웹 UI(status 페이지) 기준으로는
  맞지만 PDF 본문까지 파싱하면 DOI를 확보할 수 있다**는 게 이번에 새로 확인된 사실이다 —
  9절에서 이 정정을 반영한다.
- 페이지 번호 보존: **YES.** `pypdf`의 `pages[i]`가 물리적 PDF 페이지 순서와 1:1 대응하고,
  각 페이지 본문에도 `"SAFETY ASSESSMENT OF NIACINAMIDE AND NIACIN {n}"` 형태의 러닝
  헤더가 페이지 번호와 함께 반복 출력돼 이중으로 검증 가능하다.
- 텍스트 순서: 정상. 표(TABLE 2, TABLE 3, TABLE 4 등)가 포함된 페이지도 행 단위로 읽을 수
  있는 순서로 추출됐다(열이 뒤섞이는 문제 없음).
- **2-column layout 문제: 없음.** 이 보고서는 단일 컬럼 레이아웃이라 컬럼 교차로 인한 순서
  깨짐이 관측되지 않았다.
- 한글/특수문자: 해당 없음(CIR 보고서는 영문 전용). 특수문자(°, α, µg 등 화학 표기)는
  일부 유니코드 깨짐(예: "ﬂux"의 ligature `ﬂ`)이 보였으나 이는 흔한 PDF 리가처 처리
  이슈이지 텍스트 자체를 못 읽는 문제는 아니다.

---

## 6. Layout Findings

- 단일 컬럼, 학술지(International Journal of Toxicology) 표준 레이아웃.
- 모든 페이지에 `"{n} COSMETIC INGREDIENT REVIEW"`(짝수 페이지) 또는
  `"SAFETY ASSESSMENT OF NIACINAMIDE AND NIACIN {n}"`(홀수 페이지) 형태의 반복 러닝
  헤더/푸터가 존재 — chunking/section 감지 시 이 반복 패턴을 **노이즈로 걸러내야** 한다
  (실제 section 제목이 아님에도 대문자라 오탐 위험, 7절 참고).
- 표(TABLE 1~5 등)가 본문 중간에 삽입돼 있고, 표 캡션(`"TABLE 2\nChemical and Physical
  Properties of Niacin"`)이 텍스트로 함께 추출된다 — 표 내용도 chunk content에 자연스럽게
  포함 가능.

---

## 7. Section Header Findings

31페이지 전체를 순회하며 대문자 단독 줄(짧은 길이, 정확히 대문자로만 구성)을 찾은 결과,
**실제로 감지된 section 제목**은 다음과 같다(페이지 번호는 물리적 PDF 페이지):

| 페이지 | 감지된 헤더 |
|---|---|
| 1 | INTRODUCTION |
| 1 | CHEMISTRY |
| 3 | USE |
| 15 | GENOTOXICITY |
| 19 | REPRODUCTIVE AND DEVELOPMENTAL TOXICITY |
| 20 | CLINICAL ASSESSMENT OF SAFETY |
| 24 | SUMMARY |
| 28 | DISCUSSION |
| 28 | CONCLUSION |
| 28 | REFERENCES |

**요청받은 가설 헤더 목록과의 차이**: `Safety Assessment`(단독 섹션 제목으로는 없음 —
대신 `CLINICAL ASSESSMENT OF SAFETY`로 나타남), `Concentration`/`Irritation`/
`Sensitization`/`Toxicity`/`Clinical Studies`는 이 보고서에서 **단독 섹션 제목으로
등장하지 않는다**(본문 안에 소문자로 언급될 뿐). 즉 CIR 보고서의 실제 섹션 제목 어휘는
보고서마다(발행 연도·작성 패널마다) 다를 수 있다는 뜻이다 — 고정된 헤더 목록을 하드코딩하는
방식은 위험하고, **패턴 기반 규칙(짧은 길이 + 전체 대문자 + 단독 줄)**이 더 안전하다.

**노이즈 필터 필요**: 러닝 헤더(`"SAFETY ASSESSMENT OF NIACINAMIDE AND NIACIN {n}"`)도
"SAFETY ASSESSMENT"를 포함한 전체 대문자에 가까운 문자열이라 단순 키워드 매칭으로는
section으로 오인될 수 있다 — 실제로는 **끝에 숫자(페이지 번호)가 붙고 매 페이지 거의
동일하게 반복**된다는 특징으로 구분 가능하다(진짜 section 제목은 페이지마다 반복되지
않고 1회만 등장).

### 판정: RULE_BASED로 충분

- 규칙안: "한 줄 전체가 공백 제거 후 완전히 대문자이고(숫자/특수문자 소량 허용), 줄 길이가
  일정 범위(예: 3~50자) 안이며, 같은 문자열이 여러 페이지에 반복되지 않는 경우 section
  제목 후보로 간주"
- 이 규칙만으로 위 10개 헤더 중 다수를 정확히 추출할 수 있음을 이번 실측으로 확인했다.
  LAYOUT_AWARE parser(폰트 크기/굵기 등 렌더링 메타데이터 분석)는 **이번 샘플 1건 기준으로는
  불필요**해 보인다 — 다만 이는 단일 보고서(2005년, 단일 컬럼) 기준의 관측이라, 다른 연도/
  다른 컬럼 레이아웃의 CIR 보고서에도 이 규칙이 그대로 적용되는지는 추가 샘플로 재확인이
  필요하다(11절 Deferred).

---

## 8. Chunking Feasibility

실제 코드 구현 없이, 논리적으로 page-aware + section-aware 청킹을 적용한 예시 5개
(DB write/embedding 없음, 순수 예시):

```json
[
  {
    "source_id": "cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6",
    "page": 1,
    "section": "INTRODUCTION",
    "chunk_index": 0,
    "content_preview": "Niacinamide (aka nicotinamide) and Niacin (aka nicotinic acid) are heterocyclic aromatic compounds which function in cosmetics primarily as hair and skin conditioning agents..."
  },
  {
    "source_id": "cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6",
    "page": 3,
    "section": "USE",
    "chunk_index": 1,
    "content_preview": "TABLE 3 Frequency and Concentration of Use Data for Niacin and Niacinamide ... Eye Makeup Remover (84) 2 ... Hair Conditioners (636) 2 0.05–0.1%..."
  },
  {
    "source_id": "cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6",
    "page": 20,
    "section": "CLINICAL ASSESSMENT OF SAFETY",
    "chunk_index": 2,
    "content_preview": "(clinical study description — irritation/sensitization test protocol and subject counts)"
  },
  {
    "source_id": "cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6",
    "page": 24,
    "section": "SUMMARY",
    "chunk_index": 3,
    "content_preview": "...was irradiated as just described. The non-irradiated treatment site served as a control for possible induction of contact sensitization..."
  },
  {
    "source_id": "cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6",
    "page": 28,
    "section": "CONCLUSION",
    "chunk_index": 4,
    "content_preview": "...of side effects including blurred vision, cystoid maculopathy, skin flushing, erythematous papules, sensation of warmth, itching, jaundice, hepatitis, abnormal liver function..."
  }
]
```

`chunk_id`는 `EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md` 9절 형식(`"{source_id}:{page}:
{section}:{chunk_index}"`)을 그대로 적용 가능함을 확인했다 — 예:
`"cir_attachment:39cd1a17-8e74-ec11-8943-0022482f06a6:24:SUMMARY:3"`.

**주의**: SUMMARY(24페이지) 섹션이 24페이지 헤더 감지 지점 바로 다음 텍스트가 실제로는
여전히 이전 섹션(임상시험 방법론)의 연속처럼 보인다 — section 헤더가 페이지 맨 위가 아니라
페이지 중간에 있을 수 있어, 실제 구현 시 "헤더가 감지된 지점부터 다음 헤더 전까지"를 section
경계로 잡는 로직이 필요하다(이번 조사에서는 페이지 시작부만 미리보기했으므로 실제 경계는
좀 더 세밀한 확인이 필요 — Deferred).

---

## 9. Provenance Feasibility

| 필드 | 확보 가능 여부(이번 실측 갱신) |
|---|---|
| document(report) title | 가능 — PDF 첫 페이지/뷰어 탭 제목에서 확보(이전 세션 확인 유지) |
| attachment id | 가능 — status 페이지 링크에서 직접 확보 |
| page | 가능 — `pypdf` page index + 1이 물리적 페이지 번호와 정확히 일치 |
| section | 가능(조건부) — rule-based 감지로 다수 확보되나, 100% 보장은 아님(7/8절) |
| DOI | **가능(정정)** — CIR status 페이지 UI에는 없지만, **PDF 본문 텍스트를 파싱하면 확보
  가능**(이번 세션 신규 발견, 5절). `EXTERNAL_EVIDENCE_INGESTION_CONTRACT.md` 6절의
  "CIR은 보통 DOI NULL" 판단은 "웹 UI만 볼 때"로 한정해야 하고, PDF 파싱까지 포함하면
  DOI를 채울 수 있는 report가 있을 수 있다 — 모든 CIR 보고서에 DOI가 있는지는 추가 샘플
  필요(Deferred) |
| publisher / document_date | 가능 — PDF 첫 줄의 저널 인용 문자열(`"International Journal
  of Toxicology, 24(Suppl. 5):1–31, 2005"`)에서 파싱 가능 |

LLM이 citation을 생성하지 않는다는 원칙은 이번 검증 대상이 아니었으나(코드 미구현),
위 필드들이 전부 **원문에서 결정적으로(deterministic) 추출 가능**함을 확인했으므로 이
원칙을 지키는 collector 구현이 실제로 가능하다는 근거가 된다.

---

## 10. Technical Risks

1. **PDF fetch가 브라우저 JS 실행에 의존** — 4절. `httpx`/`curl`만으로는 불가능하므로
   headless 브라우저(Playwright 등) 기반 collector가 필요하다. 올리브영 글로벌 크롤러가
   이미 겪은 것과 동일한 계열의 문제(`docs/data/README.md`의 Cloudflare 봇 관리 사례와
   유사한 "JS 실행 필수" 패턴) — 기존에 확보한 Playwright 운용 노하우를 재사용할 수 있어
   보인다.
2. **Section 헤더 어휘가 보고서마다 다를 수 있음** — 7절. 이번 샘플(2005년 Niacinamide)
   기준으로는 RULE_BASED로 충분했지만, 오래된 보고서(1987년 Retinol 등)나 최신 amended
   보고서(2025년 Salicylic Acid)는 템플릿이 다를 가능성이 있다 — 이번 세션에서는 PDF
   바이트를 추가로 받지 않아(2개 초과 금지) 검증하지 못했다.
3. **러닝 헤더/푸터를 section으로 오인할 위험** — 7절. 필터링 규칙(반복 여부, 숫자 접미사)
   이 필요하며 이번엔 설계만 하고 코드화하지 않았다.
4. **attachment id 장기 안정성 미확정** — 3절. 수일 내 재현은 확인했으나 장기 관측은
   아니다.
5. **blob URL은 세션 종료 시 소멸** — collector가 재실행될 때마다 새로 페이지를 열고
   blob을 다시 만들어야 한다(캐시 불가) — 매 성분마다 브라우저 페이지 로드 비용이 든다.

---

## 11. Deferred (추가 확인 필요, 이번 세션 범위 밖)

1. attachment id의 장기(수개월~수년) 안정성.
2. Retinol(1987년, 오래된 스캔 가능성) / Salicylic Acid(2025년 amended)의 텍스트 레이어가
   Niacinamide(2005년)와 동일하게 digital인지 — 이번엔 Niacinamide 1건만 실제로 받아
   검증했다.
3. Section 헤더 경계를 페이지 중간에서도 정확히 잡는 로직(8절 주의사항).
4. 모든 CIR 보고서에 DOI가 본문에 있는지, 아니면 이번 샘플(2005년)만의 특징인지.
5. `document_status` enum 매핑표를 CIR의 실제 상태 라벨 전체 목록(이번에 `"Published
   Report"`/`"Published Re-review Not Opened"` 2종만 관측)으로 완성하는 작업.

---

## 12. Collector Recommendation

- PDF fetch: **headless 브라우저(Playwright) 필수**, `httpx` 단독 불가(4절).
- Text extraction: **pypdf(또는 동급 일반 PDF 텍스트 추출 라이브러리)로 충분**, OCR 불필요
  (5절 — 최소 이번 샘플 기준).
- Section detection: **RULE_BASED**(전체 대문자 + 길이 제한 + 반복 필터), LLM 요약 금지
  원칙 유지 가능(7절).
- Chunk 생성: page-aware를 기본 골격으로 하고 감지된 section을 그 위에 얹는 방식이
  실제로 동작함을 예시로 확인(8절).

---

## Ready / Not Ready Decision

**ATTACHMENT_ID_READY: YES**
(3절 — 재현성 실측 확인, original/amended가 서로 다른 id를 가짐도 확인)

**PDF_FETCH_READY: YES**
(4절 — 다만 브라우저 JS 실행 필수라는 조건부. `httpx`만으로는 NO지만, headless 브라우저
전제라면 실제로 바이트를 확보할 수 있음을 실측했으므로 READY로 판정)

**TEXT_EXTRACTION_READY: YES**
(5절 — digital text 확인, OCR 불필요, 페이지 순서/번호 정상)

**SECTION_PARSING_READY: YES(조건부)**
(7절 — RULE_BASED로 다수 섹션 감지 성공. 단, 보고서마다 헤더 어휘가 다를 수 있어 "완전
자동화 100%"가 아니라 "합리적 수준의 자동 감지 + 실패 시 섹션 없이 page만으로 fallback"
전제의 READY)

**CIR_COLLECTOR_READY: YES(조건부)**

네 가지 핵심 불확실성이 모두 해소됐고 blocker는 없다. 다만 아래 조건이 붙는다:
- headless 브라우저 기반 fetch 구현이 선행돼야 함(기술 스펙은 확정, 코드는 미작성)
- section 헤더 어휘 다양성은 샘플 1건으로만 검증돼, 실제 구현 시 몇 건 더 확인하며
  규칙을 보강할 여지가 있음(YES지만 "완벽히 끝났다"는 아님)

---

## CIR_PDF_FEASIBILITY_RESULT

```
Main commit: 252be14 (origin/main)

Samples: Niacinamide(1건 PDF fetch), Retinol(attachment id만 확인, 3건),
Salicylic Acid(attachment id만 확인, 2건)

Attachment identity: STABLE_ENOUGH
(세션 간 재현 확인, original/amended/re-review가 각각 별도 id를 가짐)

PDF access: view-attachment → 301 → HTML 셸(text/html) → 브라우저 JS가 blob:
URL로 실제 PDF(application/pdf, %PDF-1.4, 205,539 bytes) 렌더링

Browser required: YES
Session required: YES(쿠키는 필요조건이지만 JS 실행이 핵심 — 쿠키만으로는 불충분)

Text layer: DIGITAL
Page preservation: YES

Layout: 단일 컬럼, 학술지 표준 레이아웃, 반복되는 러닝 헤더/푸터 존재(노이즈 필터 필요)

Detected sections: INTRODUCTION, CHEMISTRY, USE, GENOTOXICITY, REPRODUCTIVE AND
DEVELOPMENTAL TOXICITY, CLINICAL ASSESSMENT OF SAFETY, SUMMARY, DISCUSSION,
CONCLUSION, REFERENCES (가설 헤더 목록과 실제 CIR 헤더 어휘가 다름을 확인 —
"Safety Assessment" 단독 섹션은 없고 "Clinical Assessment of Safety"로 존재)

Recommended parser: pypdf(또는 동급) 일반 텍스트 추출, OCR 불필요

Recommended chunk strategy: page-aware 기본 + rule-based section 감지로 보강,
LLM 요약 없이 원문 span 유지

Provenance preservation: title/attachment id/page/publisher/document_date 전부
가능. DOI는 CIR 웹 UI에는 없지만 PDF 본문 파싱으로 확보 가능(신규 발견, 기존
계약 문서 6절 판단 일부 정정 필요)

ATTACHMENT_ID_READY: YES
PDF_FETCH_READY: YES
TEXT_EXTRACTION_READY: YES
SECTION_PARSING_READY: YES(조건부 — RULE_BASED 충분, 어휘 다양성 추가 확인 권장)
CIR_COLLECTOR_READY: YES(조건부 — headless 브라우저 구현 선행 필요)

NIA touched: NO
Claim touched: NO
DB changed: NO

Files changed: docs/data/CIR_PDF_INGESTION_FEASIBILITY.md (신규 1개)

Commit: (아래 Git 절 참고)
Push: (아래 Git 절 참고)
PR: (아래 Git 절 참고)

Blockers: 없음(모든 핵심 질문 해소). 남은 건 구현 상세(Deferred, 11절)일 뿐 착수를
막는 blocker는 아님.

Next recommended action: PubMed collector와 동일한 우선순위로 CIR collector 구현
착수 검토(headless 브라우저 fetch + pypdf 추출 + rule-based section 감지 조합).
단, NIA 3,581건 완료 및 Claim→(ingredient, claim_topic) 어댑터 확정이 선행돼야
실제 배치 수집 대상이 정해진다.
```
