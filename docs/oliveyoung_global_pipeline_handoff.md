# 올리브영 글로벌 가격·이미지 수집 파이프라인 — 인수인계 문서

작성일: 2026-09-10 (전성분 원문 수집·파싱·옵션 연결 추가로 갱신). 이 문서는
`docs/data.md`가 정의한 "가격·이미지 데이터" 파이프라인 중 **제품 후보 수집 단계**
(가격·이미지·기본 메타데이터·전성분 원문 수집·파싱·옵션 연결까지)를 다룬다.
전성분(INCI) **`IngredientMaster` 표준 성분 매칭·DB 저장·RAG 근거 연결**·챗봇 로직은
**다른 세션(RAG 파이프라인)** 담당이며 이 문서 범위 밖이다 — 10절에 두 세션의 역할
경계와 인계 상태를 정리해 뒀다. (2026-09-10 갱신 전에는 전성분 원문 자체가 아예 없었다
— `product/description-info` 라는 미탐색 엔드포인트를 사용자가 직접 발견해 추가했다.
4절 참고.)

## 1. 왜 이 파이프라인이 필요했나

원래 계획은 네이버 쇼핑 검색 API(`scripts/naver_shopping_*.py`)로 제품 가격·이미지를
모으는 것이었다. 하지만 **네이버 쇼핑 API 인증이 막혀 있어 사용 불가**로 확정됐다
(`docs/data.md` 참고). 대체 수단으로 올리브영 글로벌(global.oliveyoung.com)을 크롤링해
같은 역할을 하도록 새로 만든 게 이 파이프라인이다.

한국 올리브영(oliveyoung.co.kr)과 화해(hwahae) 등 국내 사이트는 접근 자체가 막혀 있어
(curl 403, 브라우저로도 접속 거부 확인함) 크롤링 대상에서 제외했다.

## 2. 전체 흐름

```
검색어(성분군별) → 올리브영 글로벌 검색 → 상품 ID 목록
                                              ↓
                  상품 상세 조회(정가·옵션·카테고리·이미지 경로) + 전성분 원문 조회
                                              ↓
                    옵션이 여러 개면 → 성분 키워드로 정확한 옵션 매칭 시도
                                              ↓
                  USD → KRW 환율 변환, 이미지 다운로드, 상품명 한글 번역 매핑
                                              ↓
                        ProductCandidateRow 생성 (검토 사유 자동 태깅)
                                              ↓
              product_candidates.csv 에 저장 (다른 소스 행은 보존, 이 소스 행만 교체)
```

## 3. 실행 방법

```bash
cd /Users/moon/projects/skincare-rag-pipeline
uv run python -m scripts.collect_oliveyoung_global_candidates
```

- 최초 1회 `uv sync` 후 `uv run playwright install chromium` 필요 (검색 API 우회에 헤드리스
  브라우저를 씀).
- 실행에 30~60초 정도 걸린다(상품마다 상세 API 호출 + 이미지 다운로드 때문).
- 출력: `data/processed/product_candidates.csv`(구조화 데이터), `data/raw/images/`+
  `data/processed/images/`(다운로드한 상품 이미지).
- 재실행하면 **올리브영 글로벌 소스에 해당하는 행만 교체**된다. 네이버 등 다른 소스가
  나중에 같은 CSV 에 쓴 행은 안 지워진다(`ProductCandidateCsvWriter` 의 병합 로직).

## 4. 핵심 기술적 발견 (재작업 시 꼭 알아야 할 것)

| 발견 | 내용 |
| --- | --- |
| **상품 상세 API는 인증 불필요** | `POST global.oliveyoung.com/product/detail-data` 는 쿠키 없이 순수 `curl`/`httpx` 로 열림. |
| **검색 API는 브라우저 세션 필수** | `POST cbe-external-api.oliveyoung.com/.../unified-search` 는 Cloudflare 봇 관리가 걸려 있다. `cf_clearance` 쿠키를 httpx 로 재사용해도 403 — 봇 관리가 **브라우저의 실제 JS 실행 컨텍스트에서 나온 fetch만** 통과시키기 때문. 그래서 Playwright 로 연 페이지 안에서 `page.evaluate(fetch(...))` 로 호출한다(`oliveyoung_global_client.py`). |
| **한국 올리브영은 완전 차단** | `oliveyoung.co.kr`, `m.oliveyoung.co.kr`, `global.oliveyoung.com/kr/...` 전부 curl·브라우저 모두 403/거부 확인함. 공식 한글 상품명 매칭이 불가능한 이유. |
| **원화 미지원** | 올리브영 글로벌은 `/common/currencies` 에 KRW 자체가 없다(USD/AUD/CAD 등 18개 통화만). 가격은 Frankfurter API(무료, 키 불필요)로 USD→KRW 환율을 곱해 계산한 값이다(`exchange_rate_client.py`). |
| **이미지 확장자가 거짓말할 때가 있다** | CDN 이 URL 경로(`.png`)와 `Content-Type` 헤더(`image/png`) 둘 다 실제로는 JPEG 인 상품을 내려준 적이 있다. 파일 매직바이트로 직접 판별하도록 함(`image_downloader.py`). |
| **대표 옵션이 검색 성분과 무관할 수 있다** | 옵션이 여러 개인 상품은 `detail-data` 가 대표 옵션(`rprstYn=Y`) 하나의 가격·이름만 상품 레벨에 준다. 이 대표 옵션이 검색에 쓴 성분과 아예 다를 수 있다(예: "나이아신아마이드"로 검색했는데 대표 옵션은 "어성초"). `product_option_matcher.py` 가 옵션명(`snglOptnNameEn`)에서 성분 키워드를 찾아 올바른 옵션을 고른다. |
| **가격 범위/배수 표기는 텍스트만으로 총용량 추정 불가** | "30ml\*2ea", "50ml+Refill 50ml" 같은 표기는 단품 용량인지 총 용량인지 제목만으론 확정 불가. 억지로 추정하지 않고 `None` 처리(`product_volume_parser.py`). |
| **전성분(INCI)은 `detail-data`가 아니라 별도 `description-info`에 있다** | `POST global.oliveyoung.com/product/description-info` (body: `{"prdtNo", "langCode"}`)는 법정 고시 항목(용량·전성분·사용법·주의사항 등)을 준다. `codeDtlName == "Ingredients"` 항목의 `itemCont`가 전성분 원문 — 인증 불필요, curl로 바로 열림(`detail-data`와 동일). 옵션이 여러 개인 상품은 `[옵션명]` 단위로 옵션별 전성분이 한 문자열에 이어져 있고("[Niacinamide]\n성분,...\n\n[Retinol]\n성분,..."), 옵션이 하나뿐인 상품은 구간 표시 없이 단일 배합 하나만 온다. 이 구분을 이용해 `option_quantity_variant_only`(구간 0개 = 진짜 단일 배합) 검증에도 썼다. 단, `description` 배열 자체가 빈 상품도 있다(세트/번들 SKU, prdtNo 접두사 `GS`; 아래 6절 참고) — 그럴 땐 `raw_ingredients_text=None`. |
| **`candidate_id`는 실행마다 안 바뀐다는 보장이 없다** | 검색 결과 순서(수집 순서)대로 순번을 매기므로, 라이브 사이트의 검색 결과 순서가 바뀌거나(신상품 진입 등) 상품이 검색 결과에서 빠지면 같은 `source_product_id`도 재실행 시 다른 `candidate_id`를 받는다. 실제로 이번 갱신에서 아누아 마스크팩(`GA240925750`)이 검색 결과에서 빠졌다. 재실행 후 특정 행을 다시 찾을 땐 `candidate_id`가 아니라 `source_product_id` 기준으로 찾을 것 — `review_reason_overrides.csv`도 그래서 `source_product_id` 키를 쓴다. |

## 5. 파일 구조

### 올리브영 글로벌 전용

| 파일 | 역할 |
| --- | --- |
| `scripts/oliveyoung_global_schemas.py` | API 원본 응답을 그대로 반영하는 Pydantic 모델. `*_krw` 필드만 클라이언트가 계산해서 채움. |
| `scripts/oliveyoung_global_client.py` | 검색(Playwright)·상품상세(httpx)·전성분 원문(`get_ingredients_text`, httpx) API 호출. |
| `scripts/oliveyoung_global_candidate_builder.py` | 상품 상세 1건 → `ProductCandidateRow` 1건. 옵션 매칭·번역·용량파싱·이미지다운로드·검토사유 태깅을 여기서 조립. |
| `scripts/oliveyoung_global_candidate_collector.py` | 성분군별 검색어 순회 + 그룹 간 중복상품 후처리(`DUPLICATE_PRODUCT_ACROSS_GROUPS`). |
| `scripts/collect_oliveyoung_global_candidates.py` | 진입점. 검색어 목록(`TARGET_GROUP_SEARCH_QUERIES`)이 여기 있다. |

### 소스 공통(네이버/올리브영이 같이 씀)

| 파일 | 역할 |
| --- | --- |
| `scripts/product_candidate_schemas.py` | `TargetGroup`, `DataSource`, `TitleSource`, `ReviewReason`, `PriceBand`, `MatchStatus`, `ProductCandidateRow` — 최종 CSV 스키마. |
| `scripts/product_candidate_csv_writer.py` | CSV 저장. 소스별 병합 로직, `review_reasons` 의 `\|` 직렬화. |
| `scripts/product_price_band_classifier.py` | `lowest_price` → 가격대 분류. |
| `scripts/product_title_translator.py` | `raw_title` → `display_title` 조회 전용(번역 자체는 안 함). |
| `scripts/product_volume_parser.py` | 제목에서 단품 용량 추출. 애매하면 `None`. |
| `scripts/product_option_matcher.py` | 옵션이 여러 개인 상품에서 성분 키워드로 정확한 옵션 찾기. |
| `scripts/review_reason_overrides.py` | 코드가 자동 판단 못 하는 검토 사유(원문-공식명 충돌 등) 수동 등록 조회. |
| `scripts/image_downloader.py` | 이미지 다운로드 + raw/processed 이중 저장 + 매직바이트 확장자 판별. |
| `scripts/exchange_rate_client.py` | USD→KRW 환율 조회(Frankfurter API). |

### 수동 관리 데이터 파일

| 파일 | 역할 |
| --- | --- |
| `data/manual_review/product_title_translations.csv` | `raw_title → display_title` 매핑. 94개 전부 채워져 있음(`title_source=translated`, 공식명 아님). 새 상품이 수집되면 `untranslated` 로 떨어지니 채워 넣어야 함. |
| `data/manual_review/review_reason_overrides.csv` | `source_product_id → ReviewReason` 수동 등록. 조선미녀 1건 등록돼 있음. |

### 네이버 (비활성 상태로 유지)

`scripts/naver_shopping_*.py`, `scripts/collect_naver_shopping_candidates.py` — 코드는
남아 있지만 API 인증 실패로 실행 안 됨. 인증이 풀리면 그대로 재사용 가능(스키마는 이미
올리브영과 공유하도록 리팩터링해 둠).

## 6. 최종 산출물 (2026-09-10 전성분 원문 수집 갱신 후 재수집 기준)

- `data/processed/product_candidates.csv`: **올리브영 글로벌 96행** (라이브 검색이라 최초
  94행에서 재수집 시 변동됨 — 위 "candidate_id는 실행마다 안 바뀐다는 보장이 없다" 참고)
  - `raw_ingredients_text` 채워진 행 94/96. 비어있는 2행은 세트/번들 SKU(`GS` 접두사, 예:
    "BEYOND Bodytamin Wash & Lotion Set")로, `description-info` 자체가 빈 배열을 준다 —
    버그 아니고 실제 데이터 부재.
  - 상품명 한글 번역은 최초 94행 기준 완료돼 있었음. 재수집으로 늘어난 상품은
    `title_source=untranslated` 로 떨어질 수 있어 `product_title_translations.csv` 보강 필요.
  - `review_reasons` 있는 행은 아래 7절 참고. 세부 케이스 태그는 재수집해도
    `source_product_id` 기준으로 자동 유지된다(실제로 이번 재수집에서 확인함).
- `data/raw/images/`, `data/processed/images/`: 상품 수만큼(중복 이미지 공유분 제외)

## 7. `ProductCandidateRow` 필드 설명

| 필드 | 의미 |
| --- | --- |
| `candidate_id` | 소스별 접두사 + 일련번호 (`OY0001`, 네이버는 `C0001`). CSV 전체에서 유일. |
| `source` | `naver_shopping` \| `oliveyoung_global` |
| `target_group` | KCIA/Knowledgedata 표준 국문 성분명 (`아스코빅애씨드` 등). **검색용 분류일 뿐 전성분 검증 결과 아님.** |
| `search_query` | 실제로 쓴 검색어 |
| `source_product_id` | 소스 내 상품 ID |
| `raw_title` | 수집 원문. **절대 수정 금지** — 재매칭·추적 기준 |
| `display_title` / `title_source` | 화면 노출용 한글명 / 신뢰도(`native_kr`\|`oliveyoung_kr`\|`translated`\|`untranslated`) |
| `lowest_price` / `highest_price` | 올리브영: 할인가/정가(KRW). 네이버: 판매처간 최저/최고가 |
| `price_band` | `lowest_price` 기준 가격대 |
| `volume_value` / `volume_unit` | 단품 용량. 세트·옵션형은 `None` |
| `image_url` / `local_image_path` | 원본 URL / 다운로드된 로컬 경로(`data/processed/images/...`) |
| `raw_ingredients_text` | 전성분(INCI) 원문(`product/description-info`). **아직 파싱·성분 단위 분리·`IngredientMaster` 매칭 전** — 옵션이 여러 개인 상품은 `[옵션명]` 구간이 이어진 원문 그대로. 세트/번들 SKU 등 소스가 안 주면 `None`. 네이버 쇼핑 소스는 항상 `None`(전성분 API 자체가 없음). |
| `match_status` | 항상 `manual_review_required` (자동으로 `matched` 안 됨) — `raw_ingredients_text`가 채워져 있어도 마찬가지. 원문 존재가 파싱·매칭 완료를 뜻하지 않는다. |
| `review_reasons` | 검토가 필요한 구체적 이유들(아래 참고). `\|` 구분 |

### `ReviewReason` 값

- `option_ambiguous`: 옵션 2개 이상인데 성분 키워드로 특정 옵션을 못 골라 대표 옵션을 씀 (3건).
  실제 옵션 목록을 확인한 결과 이 3건은 성분이 다른 옵션이 섞인 게 아니라 수량/세트
  옵션만 달라 성분 오매칭 위험은 없음(`option_quantity_variant_only` 참고). 단, 옵션명만
  확인한 것이라 전성분(INCI) 자체가 동일한지는 미검증 — 가격은 유지하되 그 가격이
  가리키는 정확한 옵션·구성의 연결은 확인이 필요하다.
- `duplicate_product_across_groups`: 같은 `source_product_id` 가 다른 target_group 에도
  등장 (6건, 자동 태그). **버그 아님** — 다만 원인이 다른 두 하위 케이스가 섞여 있어서
  이 사유 하나로 뭉뚱그리면 안 됨:
  - `same_product_multi_search_group`(4건: OY0015/0066, OY0022/0071 — APLB 제품 2종): 옵션
    구분 없는 진짜 동일 SKU가 여러 성분을 라벨에 같이 표기해서(예: "Retinol Vitamin C
    Vitamin E") 두 검색에 다 걸린 경우. raw_title·가격 완전히 동일.
  - `different_options_same_product`(2건: OY0040/0069 — 아누아 마스크팩): 옵션 매칭기가
    target_group 별로 서로 다른 옵션을 정확히 찾아 raw_title 은 이미 다름
    ("Niacinamide 5 TXA" vs "Retinol Niacin"). 다만 올리브영이 이 상품 옵션 8개 전부에
    동일 가격을 매겨놔서 가격만 보면 구분이 안 보임 — 옵션 정보 자체는 raw_title 에
    보존돼 있지만, 후속 작업에서 `source_product_id` 만 기준으로 중복 제거하면 이 옵션
    구분이 사라질 위험이 있으니 주의.
- `raw_title_source_conflict`: 원문이 브랜드 공식 표기와 다를 수 있다는 의심 (1건 — 조선미녀 Retinol vs 공식 Retinal)

세부 케이스 태그(`option_quantity_variant_only`/`same_product_multi_search_group`/
`different_options_same_product`)는 `data/manual_review/review_reason_overrides.csv` 에
`source_product_id` 기준으로 등록돼 있어, 재수집해도 자동 태그(`option_ambiguous`/
`duplicate_product_across_groups`)와 함께 유지된다.

## 8. 알려진 한계 / 미해결

1. **전성분(INCI) 원문 파싱·옵션 연결까지는 됐고, 표준 성분 매칭·DB 저장이 남았다.**
   `raw_ingredients_text` 파싱(구간 분리·토큰화)과 옵션 연결은 10절에 정리된 대로 이
   세션(올리브영)이 담당해 완료했다. `IngredientMaster`(KCIA 표준 성분코드)와의 매칭,
   DB 저장(`ProductIngredientSnapshot`/`ProductIngredient`), RAG 근거 연결은 RAG
   세션(`docs/rag_pipeline_handoff.md`) 담당 — 10절 참고.
2. **다이어그램(챗봇 플로우) 요구사항 미충족.** 사용자가 제시한 서비스 플로우(성분 확인·
   상품 추천·루틴 만들기)는 파싱된 전성분+근거 연결+피부타입 데이터가 있어야 동작하는데,
   지금 데이터는 `docs/data.md` 가 정의한 "검증 전 후보" 단계에 머물러 있다. 96행 전부
   `match_status=manual_review_required`.
3. **한국 올리브영 공식 상품명 매칭 불가.** `title_source=oliveyoung_kr` 인 행이 0개 —
   접근 자체가 막혀 있어서. 접근이 풀리면 `product_title_translations.csv` 를 승격시키면
   된다(구조는 이미 준비돼 있음).
4. **`option_ambiguous` 3건, `duplicate_product_across_groups` 6건** 은 남아있는 상태로
   CSV 에 있다 — 사람이 최종 검토해야 함.
5. **화해(hwahae)** 크롤링은 아예 손 못 댔다(이번 세션 범위 밖으로 결정됨).
6. **네이버 쇼핑 인증 실패**는 여전히 미해결. 코드만 유지 중.

## 9. 다음 작업 후보 (우선순위 미정, 사용자 확인 필요)

- 재수집으로 늘어난 상품(94→96)의 `product_title_translations.csv` 보강
- (선택) 화해 크롤링 재시도
- (선택) `candidate_id`를 검색 순서 대신 `source_product_id` 해시 등 안정적인 값으로
  바꿀지 검토 — 지금은 재수집마다 바뀔 수 있어 외부에서 candidate_id로 참조하면 위험

## 10. 전성분 원문 파싱·옵션 연결 (2026-09-10, 올리브영 세션 담당분 완료)

RAG 세션과 역할을 나눴다: **올리브영 세션 = 원문 수집·파싱·옵션 연결·회귀 테스트**,
**RAG 세션 = `IngredientMaster` 매칭·DB 저장(모델/repository/service)·RAG 근거 연결**.
이 절은 올리브영 세션 담당분의 최종 상태다.

### 파일

| 파일 | 역할 |
| --- | --- |
| `scripts/product_ingredient_parse_schemas.py` | 파싱 결과 Pydantic 모델·Enum. `ProductIngredientParseResult`(source+source_product_id+원문+구간들), `IngredientSectionParse`(라벨+연결상태+토큰들), `ParsedIngredientToken`(순서+원문+매칭명+함량+파싱상태) |
| `scripts/product_ingredient_text_parser.py` | 원문 → 구간·토큰 파싱. `PARSER_VERSION` 상수 있음(로직 바뀌면 올릴 것) |
| `scripts/product_ingredient_option_linker.py` | 구간 라벨(`[옵션명]`)을 실제 판매 옵션(`gds_cd`)에 연결. 라벨이 옵션명 목록 중 정확히 하나와만 겹칠 때만 `LINKED` |
| `scripts/inspect_ingredient_parsing.py` | DB 안 씀. 실제 수집 데이터 전체(고유 상품 91개)에 파서+링커를 돌려 리포트 생성(`data/manual_review/ingredient_parse_sample_report.txt`, gitignore 대상) |
| `tests/unit/test_product_ingredient_text_parser.py`, `tests/unit/test_product_ingredient_option_linker.py` | 회귀 테스트 15개(슬래시 보존, 함량 괄호 추출, 식물명 괄호 보존, 1,2-Hexanediol 재결합, 구분자 누락 오탐 방지, `@` 구분자 감지, 섹션 분리, 옵션 링크 유일/0/다중매칭) |

### 핵심 설계 결정

- **콤마·괄호·슬래시를 임의로 처리하지 않는다.** `1,2-Hexanediol`, `Ammonium
  Acryloyldimethyltaurate/VP Copolymer`, `Citrus Aurantium Dulcis (Orange) Peel Oil`
  전부 원문 그대로 보존. 함량 괄호(`(2,000 ppm)`, `(0.45%)`)만 `concentration_text`로
  분리하고 `matching_name`에서 제거한다.
- **구분자가 상품마다 다르다.** 대부분 콤마지만 2개 상품은 `@`를 썼다(원문에 `@`가
  콤마보다 훨씬 많이 나오면 그쪽을 구분자로 판정). 콤마 개수를 고정 가정하면 안 된다.
- **구분자 누락이 의심되면 억지로 안 나누고 `NEEDS_REVIEW`로 남긴다.** 예:
  `"Glycereth-261,2-Hexanediol"`은 실제로 `"Glycereth-26"` + `"1,2-Hexanediol"` 사이
  콤마가 빠진 것인데, 확신할 수 없어 두 토큰 다 검토로 남긴다(PEG-40류 정상 케이스는
  오탐하지 않도록 화이트리스트로 범위를 좁혔다 — 파서 상단 docstring 참고).
- **옵션 구간이 없다고 "모든 옵션 배합이 같다"고 확정하지 않는다.**
  `IngredientSectionLinkStatus.NO_OPTION_SECTIONS`로만 표시 — "상품 수준 단일 원문
  제공됨"이라는 사실만 기록.
- **옵션 연결은 라벨-옵션명 유일 매칭일 때만 확정한다.** `candidate_id`나 번역 상품명은
  연결키로 안 쓰고 `gds_cd` 기준. 옵션명 자체가 `"-"`(빈 placeholder)인 실제 사례처럼
  연결 근거가 없으면 `AMBIGUOUS`로 남기고, 이건 "특정 판매 옵션의 검증된 성분"으로
  쓰면 안 된다는 신호다.

### 검증 결과 (재수집 기준, 2026-09-10)

고유 상품 91개(CSV 94행 중 3행은 같은 상품이 다른 target_group에도 중복 등장 —
`duplicate_product_across_groups`, 원문 동일해 한 번만 파싱), 전체 토큰 5,152개:

- `needs_review` 토큰 4개(0.1%) — 상품 2개(위 구분자 누락 케이스)에 몰려 있음
- 옵션 구간 33개 중 `linked` 28개, `ambiguous` 2개(둘 다 옵션명이 `"-"`라 연결 불가능한
  정상 케이스)
- `linked` 결과 샘플 2건을 실제 성분 함유 여부로 직접 대조 — 라벨과 토큰 내용 일치 확인
  (예: `[Retinol Lifting]` 구간 토큰에 retinol만 있고 niacinamide/panthenol은 없음)

**주의**: 위 수치는 "파서가 이상하다고 표시한 비율"이지 "정확도 검증 결과"가 아니다.
`linked` 28개 중 직접 대조한 건 2건뿐 — 전수 검증은 아니다.

### RAG 세션이 이어받은 것 (2026-09-10 기준 진행 중, 완료 여부는 RAG 쪽 문서 확인)

- `models/product_ingredient.py`: `ProductIngredientSnapshot`(원문 스냅샷,
  source+source_product_id+원문해시로 중복 방지) / `ProductIngredient`(토큰+매칭 결과,
  미매칭도 `ingredient_id=NULL`로 보존) — 필드명이 이 세션의 Pydantic 스키마와 1:1 대응
- `scripts/product_ingredient_match_acceptance_policy.py`: 기존 `IngredientNameMatcher`는
  안 건드리고, 영문 정규화 정확일치만 자동 확정 + 나머지는 전부 검토로 돌리는 정책 레이어
- `backend/repositories/product_ingredient_repository.py`,
  `backend/services/product_ingredient_service.py`: 저장/조회 (진행 중)
- `migrations/versions/459db45c7a64_...py`: 위 테이블 마이그레이션

### 내일 이어서 할 것

1. **커밋 상태 확인부터.** 이 문서 작성 시점(2026-09-10) 기준 위 표의 올리브영 파일들은
   커밋 예정이지만, RAG 쪽 파일(`models/product_ingredient.py`,
   `backend/repositories/product_ingredient_repository.py`,
   `backend/services/product_ingredient_service.py`,
   `scripts/product_ingredient_match_acceptance_policy.py`, 마이그레이션,
   `config.yaml.sample`/`models/__init__.py`의 등록 변경)는 RAG 세션이 별도로 커밋해야
   한다 — 안 했으면 그 세션에 먼저 확인할 것.
2. RAG 세션의 repository/service 설계가 이 세션의 파싱 계약(4·6번 원칙: 미매칭 보존,
   ambiguous는 검증된 성분으로 안 씀)을 지키는지 재확인.
3. `needs_review` 토큰 4개, `ambiguous` 옵션 2개는 사람이 최종 검토(수동 확정 또는
   `review_reason_overrides.csv`류 수동 등록) — 지금은 보류 상태.
4. §9의 기존 후보(번역 매핑 보강, 화해 재시도, candidate_id 안정화)는 여전히 미착수.
