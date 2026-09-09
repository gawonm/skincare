# 올리브영 글로벌 가격·이미지 수집 파이프라인 — 인수인계 문서

작성일: 2026-09-10. 이 문서는 `docs/data.md`가 정의한 "가격·이미지 데이터" 파이프라인 중
**제품 후보 수집 단계**(가격·이미지·기본 메타데이터 수집, 아직 전성분 검증 전)를 다룬다.
전성분(INCI) 수집·RAG 근거 연결·챗봇 로직은 **다른 세션에서 별도로 진행 중**이며 이 문서
범위 밖이다.

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
                            상품 상세 조회(정가·옵션·카테고리·이미지 경로)
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

## 5. 파일 구조

### 올리브영 글로벌 전용

| 파일 | 역할 |
| --- | --- |
| `scripts/oliveyoung_global_schemas.py` | API 원본 응답을 그대로 반영하는 Pydantic 모델. `*_krw` 필드만 클라이언트가 계산해서 채움. |
| `scripts/oliveyoung_global_client.py` | 검색(Playwright)·상품상세(httpx) API 호출. |
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

## 6. 최종 산출물 (2026-09-10 기준)

- `data/processed/product_candidates.csv`: **94행**
  - 성분군 분포: 레티놀 32 / 나이아신아마이드 29 / 아스코빅애씨드 26 / 살리실릭애씨드 4 / 글라이콜릭애씨드 3
  - 상품명 전부 한글 번역 완료(`title_source=translated`, 94/94)
  - 용량 확정 57/94 (나머지는 세트·옵션형이라 의도적으로 미확정)
  - `review_reasons` 있는 행 10개 (아래 7절 참고)
- `data/raw/images/`, `data/processed/images/`: 각 93개 파일 (94행 중 2행이 같은 원본
  상품 이미지를 공유해서 93개)

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
| `match_status` | 항상 `manual_review_required` (자동으로 `matched` 안 됨) |
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

1. **전성분(INCI) 데이터 없음.** 이 파이프라인은 가격·이미지·검색기반 카테고리만 모은다.
   실제 성분표는 다른 세션의 RAG 파이프라인 작업 영역 — 여기서 임의로 손대지 않았다.
2. **다이어그램(챗봇 플로우) 요구사항 미충족.** 사용자가 제시한 서비스 플로우(성분 확인·
   상품 추천·루틴 만들기)는 전성분+근거 연결+피부타입 데이터가 있어야 동작하는데, 지금
   데이터는 `docs/data.md` 가 정의한 "검증 전 후보" 단계에 머물러 있다. 94행 전부
   `match_status=manual_review_required`.
3. **한국 올리브영 공식 상품명 매칭 불가.** `title_source=oliveyoung_kr` 인 행이 0개 —
   접근 자체가 막혀 있어서. 접근이 풀리면 `product_title_translations.csv` 를 승격시키면
   된다(구조는 이미 준비돼 있음).
4. **`option_ambiguous` 3건, `duplicate_product_across_groups` 6건** 은 남아있는 상태로
   CSV 에 있다 — 사람이 최종 검토해야 함.
5. **화해(hwahae)** 크롤링은 아예 손 못 댔다(이번 세션 범위 밖으로 결정됨).
6. **네이버 쇼핑 인증 실패**는 여전히 미해결. 코드만 유지 중.

## 9. 다음 작업 후보 (우선순위 미정, 사용자 확인 필요)

- 남은 `option_ambiguous`/`duplicate_product_across_groups` 건 개별 검토
- 다른 세션의 전성분/RAG 산출물과 이 CSV 를 어떻게 연결할지 설계
- 새로 수집되는 상품의 `product_title_translations.csv` 지속 보강
- (선택) 화해 크롤링 재시도
