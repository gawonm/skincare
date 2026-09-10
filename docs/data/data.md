# 데이터 파이프라인

`models/`, `migrations/`, `config.yaml`의 `database.model_modules`, 그리고 데이터 수집·정제
스크립트(`scripts/`)를 다룬다. 폴더 구조와 의존 방향은 [STRUCTURE.md](../STRUCTURE.md), 코드
작성 규칙은 [CLAUDE.md](../CLAUDE.md)를 따른다.

## 담당 범위

이 문서가 다루는 담당 범위는 다음까지다.

- 데이터 수집 (성분 근거 문서, 제품 가격·이미지)
- 정제·정규화
- 데이터 품질 검증
- 성분 근거 문서의 RAG 적재 (Document 생성 → Chunking → Embedding → pgvector)

다음은 이 담당 범위 밖이며, 이 문서와 이 파트의 작업 목록에 포함하지 않는다.

- 챗봇 구현
- 추천 API 구현
- 제품 랭킹 엔진 구현
- 프론트엔드 구현
- 사용자 발화 의도 분류
- 스케줄링 엔진 구현

이 파트의 최종 산출물은 **검증된 가격 데이터와 성분 근거 RAG**이며, 이를 다른 파트(추천·랭킹·챗봇
담당)에 전달하는 데까지만 수행한다. 제품 비교와 가격 기반 랭킹 자체는 서비스 차원에서 허용된
기능이지만, 그 로직 구현은 이 파트의 책임이 아니다.

## MVP 데이터셋

| 데이터셋 | 용도 | 파이프라인 |
| --- | --- | --- |
| Knowledgedata (`data/Knowledgedata.xlsx`) | 성분 효능 근거 | RAG |
| CIR (Cosmetic Ingredient Review) | 성분 안전성 근거 | RAG |
| MFDS(식약처) 성분 데이터 | 성분 주의사항·규제 근거 | RAG |
| KCIA 표준화명칭 (`data/별첨1. 표준화명칭목록_260831.pdf`) | 성분명 정규화 | RAG 전처리 |
| 네이버 쇼핑 검색 API | 제품 가격·이미지 | 구조화 데이터 |

> **제외된 항목**: NIA AI Hub 리뷰 데이터(`data/03.스킨케어 성분-효능 추천 데이터/.../2.데이터(NIA)/`)는
> MVP 데이터셋에서 제외한다. 리뷰 데이터, 리뷰 키워드 추출, Aspect/Sentiment 분석 파이프라인은
> 이 프로젝트에서 사용하지 않는다. 저장소에 남아 있는 NIA zip 파일은 참고용 원본일 뿐 파이프라인
> 입력이 아니다.

## 두 파이프라인의 분리

가격·이미지 데이터와 성분 근거 데이터는 목적과 저장 방식이 다르므로 파이프라인을 분리한다.

```
가격 · 제품 이미지 · 쇼핑 링크
  → 구조화 데이터
  → PostgreSQL 또는 CSV/Parquet
  → 추천·랭킹 담당 파트에 전달

Knowledgedata + CIR + MFDS
  → 성분명 정규화 (KCIA 표준화명칭 기준)
  → Document 생성
  → Chunking
  → Embedding
  → pgvector
```

가격 데이터는 **문서 청킹이나 임베딩 대상이 아니다.** RAG에는 성분 효능·안전성·주의사항 등
근거 문서만 적재하고, 가격·제품 이미지·쇼핑 링크는 구조화 데이터로만 저장한다.

## 네이버 쇼핑 API 수집

### 사용 API

```
GET https://openapi.naver.com/v1/search/shop.json
```

용도는 제품 가격과 제품 이미지 수집으로 한정한다. 리뷰·평점 등 이 API가 제공하지 않는 항목을
다른 수단으로 보완하지 않는다.

### 인증

인증 정보는 환경변수로만 관리하고, 코드에 하드코딩하거나 로그에 출력하거나 Git에 커밋하지 않는다.

```env
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
```

### 수집 대상 필드

| 필드 | 의미 |
| --- | --- |
| `productId` | 네이버 쇼핑 상품 ID |
| `title` | 검색 결과 상품명 (HTML 태그 제거 후 저장) |
| `link` | 네이버 쇼핑 상품 링크 |
| `image` | 상품 이미지 URL |
| `lprice` | 조회 시점의 최저가 |
| `hprice` | 조회 시점의 최고가 |
| `mallName` | 판매처 |
| `maker` | 제조사 |
| `brand` | 브랜드 |
| `category1`~`category4` | 상품 카테고리 |
| `productType` | 가격비교·일반상품·중고·단종 등의 상품 유형 |

### 수집 시 제외 규칙

- 중고·렌탈·해외직구 상품은 검색 요청 단계에서 제외한다 (`exclude=used:rental:cbshop`).
- `lprice=0`인 결과는 유효한 가격 데이터에서 제외한다.

### 검색 및 매칭

서비스의 `ProductMaster`(추천·랭킹 파트가 관리하는 제품 마스터)에 포함된 제품을 기준으로
네이버 쇼핑 API를 검색한다. 이 파트는 `ProductMaster`를 정의하거나 구현하지 않고, 입력으로만
사용한다.

검색어 형식:

```
{brand} {product_name} {volume_value}{volume_unit}
```

예: `라운드랩 자작나무 수분크림 80ml`

검색 결과 첫 번째 항목을 무조건 연결하지 않는다. 다음 값으로 실제 제품과의 일치 여부를
판단한다.

- 브랜드 일치
- 정규화한 제품명 일치 또는 높은 유사도
- 용량 일치
- 카테고리 일치
- 본품 여부
- 세트·리필·미니 여부
- 중고·단종·판매예정 등 상품 유형

매칭 결과는 다음 상태로 관리하며, 자동 매칭이 불확실한 결과는 임의로 연결하지 않고 수동 검토
큐(`data/manual_review/product_match_queue.csv`)로 보낸다.

```
matched
manual_review_required
rejected
```

## Raw 데이터

API 원본 응답은 변경하지 않고 수집 시각별로 보존한다.

```
data/
└── raw/
    └── naver_shopping/
        ├── 2026-09-09/
        │   ├── P001.json
        │   ├── P002.json
        │   └── P003.json
        └── collection_manifest.json
```

원본 파일에는 다음 메타데이터를 함께 저장한다.

| 필드 | 의미 |
| --- | --- |
| `query` | 검색에 사용한 문자열 |
| `product_id` | 매칭 대상 내부 제품 ID (`ProductMaster` 참조) |
| `requested_at` | 요청 시각 |
| `response_status` | API 응답 상태 |
| `result_count` | 검색 결과 수 |
| `source` | 데이터 출처 식별자 (예: `naver_shopping`) |

> 위 경로의 파일명(`P001.json` 등)과 날짜(`2026-09-09`)는 구조를 보여주기 위한 예시이며,
> 실제 수집 전까지는 fixture로 표시한다.

## 정제된 가격 데이터

### `ProductPriceSnapshot` 스키마

다른 파트에 전달할 최종 데이터셋의 스키마다.

| 필드 | 설명 |
| --- | --- |
| `price_snapshot_id` | 스냅샷 고유 ID |
| `product_id` | 내부 제품 ID (`ProductMaster` 참조) |
| `naver_product_id` | 네이버 쇼핑 `productId` |
| `matched_product_title` | 매칭된 검색 결과 상품명 |
| `brand` | 브랜드 |
| `maker` | 제조사 |
| `category1`~`category4` | 상품 카테고리 |
| `lowest_price` | 최저가 (`lprice`) |
| `highest_price` | 최고가 (`hprice`) |
| `currency` | 통화 |
| `price_band` | 가격대 파생 변수 |
| `mall_name` | 판매처 |
| `shopping_url` | 쇼핑 링크 |
| `image_url` | 상품 이미지 URL |
| `product_type` | 상품 유형 |
| `observed_at` | 수집 시각 |
| `match_status` | `matched` / `manual_review_required` / `rejected` |
| `match_score` | 매칭 신뢰도 점수 |
| `source_type` | 데이터 출처 |

기본값:

```
currency = KRW
source_type = NAVER_SHOPPING_API
```

동일 제품의 가격을 새로 수집할 때 기존 스냅샷 행을 덮어쓰지 않고 새로운 행을 추가한다.
가격 이력을 그대로 보존하기 위함이다.

### 가격대(`price_band`) 파생 규칙

`lowest_price` 기준으로 다음 구간으로 분류한다. 경계값이 겹치지 않도록 코드와 문서에서
동일하게 정의한다.

| 구간 | 조건 |
| --- | --- |
| 1만원 미만 | `price < 10,000` |
| 1만원대 | `10,000 ≤ price < 20,000` |
| 2만원대 | `20,000 ≤ price < 30,000` |
| 3~4만원대 | `30,000 ≤ price < 50,000` |
| 5만원 이상 | `price ≥ 50,000` |

이 파트는 위 구간에 맞는 `price_band` 값을 제공할 뿐, 이 값을 이용한 필터링·정렬·랭킹
로직(예: "2만원 이하 제품", "기존 추천보다 저렴한 제품", "가격을 반영한 랭킹")은 추천·랭킹
담당 파트가 구현한다.

### 용량과 단위 가격

제품 용량을 확보할 수 있는 경우 다음 파생 필드를 추가로 생성한다.

```
volume_value
volume_unit
unit_price
unit_price_basis
```

예:

```
lowest_price = 20,000
volume_value = 50
volume_unit = ml
unit_price_basis = 10ml
unit_price = 4,000
```

용량 정보가 없거나 제품 간 단위가 다른 경우, 임의로 단위 가격을 계산하지 않고 해당 필드를
비워 둔다.

## 데이터 품질 검증

### 수집 품질

- `ProductMaster` 대상 제품 수
- API 호출 성공률
- 검색 결과 존재율
- `lprice > 0` 비율
- 이미지 URL 확보율
- 쇼핑 링크 확보율

### 매칭 품질

- 자동 매칭 성공률
- 수동 검토 대상 비율
- 매칭 실패율
- 브랜드 불일치 건수
- 용량 불일치 건수
- 세트·리필·미니 오매칭 건수

### 가격 품질

- 가격 누락률
- 0원 데이터 수
- 비정상적으로 낮거나 높은 가격 수
- 동일 제품 중복 수
- 가격 수집 시각 누락률
- 가격대 분류 오류 수
- 이전 스냅샷 대비 급격한 가격 변동 수

### 이미지 품질

- 이미지 URL 누락률
- 깨진 URL 비율
- 동일 이미지 중복률
- 제품과 이미지가 일치하지 않는 건수

## 산출물

```
data/raw/naver_shopping/
data/processed/product_price_snapshots.csv 또는 parquet
data/processed/products_with_latest_price.csv 또는 parquet
data/manual_review/product_match_queue.csv
data/reports/price_collection_quality_report.json
```

## 수집 스크립트 책임 범위

`scripts/`에 두는 클래스의 책임 범위는 다음과 같다. (폴더 규칙은 [STRUCTURE.md](../STRUCTURE.md) 참고)
모든 코드는 클래스 기반으로 작성한다([CLAUDE.md](../CLAUDE.md) 규칙 1). 아래는 함수가 아니라
클래스와 그 책임 메서드다.

```
NaverShoppingClient.fetch_results(query)
ShoppingItemNormalizer.normalize(item)
ProductSearchMatcher.match(product, candidates)
PriceBandClassifier.classify(price)
UnitPriceCalculator.calculate(price, volume)
RawResponseStore.save(response)
PriceSnapshotStore.save(snapshot)
PriceCollectionQualityReporter.generate()
```

추천·랭킹·챗봇 기능은 이 스크립트들의 책임 범위에 포함하지 않는다.

## 성분명 정규화 진행 상태

`scripts/import_kcia_ingredients.py`, `scripts/import_knowledgedata.py`로 실행한다. 매칭
로직(`IngredientNameMatcher`)의 우선순위는 각 스크립트 상단 docstring 참고.

| 단계 | 상태 | 결과 |
| --- | --- | --- |
| KCIA `IngredientMaster` 적재 | 완료 | 21,974건 (성분코드 최대 24,938) |
| Knowledgedata 매칭 | 완료 | 2,465행 중 2,411건 매칭, 54건 수동 검토 대기 |
| MFDS 사용제한 원료정보 매칭 | 완료 | 31,191행 중 8,288건 매칭(`Evidence`), 22,903건 수동 검토 대기 |

**MFDS 결과 관련 참고**

- `scripts/import_mfds_restricted_ingredients.py`로 실행. `getCsmtcsUseRstrcInfoService`는
  성분명 필터가 없어 전량(31,191행, numOfRows=500 기준 63페이지)을 받아온 뒤 매칭한다.
  재실행 시 upsert 대신 기존 MFDS `Evidence`를 지우고 새로 채우는 전체 새로고침 방식이다
  (안정적인 자연키가 없어서다. `scripts/mfds_importer.py` 참고).
- 매칭률이 26.6%로 Knowledgedata보다 낮다. 이 데이터셋에는 화장품에 쓰이지 않는 산업용
  화학물질도 다수 포함돼 있어 KCIA 표준화명칭목록에 없는 게 정상이다. 낮은 매칭률 자체는
  버그가 아니다.
- **Vitamin C(Ascorbic Acid)와 Niacinamide는 이 데이터셋에 아예 등장하지 않는다** (검토
  큐에도 없음). 두 성분 모두 이 API가 다루는 국가에서 배합 제한이 없다는 뜻으로 해석되며,
  매칭 실패가 아니다.
- Retinol의 캐나다 근거 2건이 내용까지 완전히 동일한 중복으로 확인됐다. 원본 API 응답
  자체의 중복이며, 적재 코드가 임의로 만든 중복이 아니다. 필요하면 나중에 dedup 규칙을
  추가한다.

**수동 검토 대기 54건**: `data/manual_review/knowledgedata_ingredient_match_queue.csv`.
자동으로 합치지 않고 그대로 남겨 둔 이유는 다음 중 하나다.

- 후보가 2~3개로 갈리는 진짜 모호한 경우 (예: 같은 계열의 다른 유도체, KCIA 안에 동명이인처럼
  중복 등록된 표준명)
- `Alpha Hydroxy Acid/AHA`, `Peptides`, `Probiotics`, `Essential Oils`처럼 특정 INCI 성분이
  아니라 총칭·카테고리인 경우
- 특이 식물 추출물 등 KCIA 표준화명칭목록에 실제로 없는 경우

사람이 각 행을 보고 KCIA 성분코드를 직접 지정해야 한다. 임의로 확정하면 서로 다른 성분을
병합할 위험이 있어 보류했다.

## 관련 문서

- 성분 근거 RAG의 문서 로딩·청킹·임베딩·검색 구현은 [docs/agent.md](agent.md)를 따른다. (미작성 시
  작성 전 사용자에게 먼저 확인한다.)
- 폴더 구조와 import 방향은 [STRUCTURE.md](../STRUCTURE.md).
- 설치·실행 명령과 모델 추가 시 마이그레이션 절차는 [SETUP.md](../SETUP.md).
