# 데이터 파이프라인 (파트 진입 문서)

담당 범위·스키마·품질 기준 등 전체 내용은 [`docs/data/data.md`](data.md)를 따른다. 이 문서는
`data.md`에 정리하기 애매한, 실제로 개발하면서 부딪힌 특성과 상황만 적는다 — 같은 내용을 두
곳에 적지 않는다.

## 개발 시 특별한 특성 및 상황

### 올리브영 글로벌(global.oliveyoung.com) API는 엔드포인트마다 필요한 실행 환경이 다르다

같은 사이트인데 호스트별로 봇 차단 수준이 다르다.

- `cbe-external-api.oliveyoung.com`의 검색 API(`unified-search`)만 Cloudflare 봇 관리가 걸려
  있다. `cf_clearance` 쿠키를 httpx로 재사용해도 403이 난다 — 브라우저의 실제 JS 실행
  컨텍스트에서 나온 `fetch`만 통과시키기 때문(Playwright의 `APIRequestContext`로 같은 쿠키를
  써도 막힘, 직접 확인함). 그래서 검색은 Playwright로 연 페이지 안에서 `page.evaluate`로
  실행한다(`scripts/oliveyoung_global_client.py`).
- `global.oliveyoung.com`의 상품 상세(`product/detail-data`), 전성분(`product/description-info`),
  **카테고리 목록(`display/category/product-data/`)**은 쿠키 없이 일반 httpx로 호출된다. 새
  엔드포인트를 추가할 때 "올리브영이니까 Playwright가 필요하다"고 넘겨짚지 말고, 호스트가
  `global.oliveyoung.com`인지부터 확인한다.
- 카테고리 목록 API(`ctgrNo`, `pageNum`, `rowsPerPage`)는 문서화된 자료가 없어 브라우저
  네트워크 탭으로 직접 조사해서 찾았다(`scripts/oliveyoung_global_category_client.py`). 최상위
  카테고리 하나(`1000000008` = Skincare)가 하위 카테고리 전체의 합집합이라, 하위 카테고리를
  따로 순회하면 상품이 최대 4번 중복 처리된다 — 반드시 상위 카테고리 하나만 페이지 순회한다.

### 대량 수집(수천 건)은 반드시 증분 저장한다

끝까지 실행돼야 결과를 한 번에 쓰는 구조로 처음 만들었다가, 실제 3,700개짜리 카테고리 전체
수집 중 Windows 환경 문제로 두 번 죽으면서 그 위험을 직접 겪었다(아래 항목). 상품 하나를
처리할 때마다 즉시 CSV에 반영하도록 고친 뒤로는 중단돼도 그 시점까지 결과가 남았고, 재실행하면
이미 처리한 상품(출력 CSV에 이미 있는 `source_product_id`)은 건너뛰는 것만으로 재개가 됐다 —
별도 체크포인트 파일 없이 출력 파일 자체가 진행 상태다(`scripts/oliveyoung_global_catalog_crawler.py`
의 `on_row_collected` 콜백 참고).

### Windows 개발 환경에서 실제로 겪은 크래시 두 가지

둘 다 실제 실행에서 재현했다 — 추측이 아니라 확인된 문제다.

1. **파일 잠금**: 매 상품마다 CSV 전체를 다시 쓰는 구조라, 그 순간 백신/색인 프로그램이
   파일을 잠가 `PermissionError`가 발생했다(3,700개 중 672번째 처리 중). 몇 초 뒤엔 보통
   풀리므로 짧게 재시도한다.
2. **콘솔 인코딩**: Windows 콘솔 기본 인코딩(cp949)으로 못 쓰는 문자(억양 부호 등)가 해외
   브랜드명에 섞여 나오면 `print()` 자체가 `UnicodeEncodeError`로 죽는다(1,268번째 상품).
   국제 브랜드명을 다루는 스크립트는 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
   를 진입점에서 먼저 걸어 둔다.

둘 다 원인을 숨기지 않고 재시도/치환으로 흡수하되, 계속 실패하면 그대로 실패시킨다(규칙 7).

### 성분 키워드 검색과 카테고리 전수 수집은 CSV를 분리했다

`product_candidates.csv`(5개 성분 키워드 검색, `TargetGroup` 필수)와 `catalog_products.csv`
(카테고리 순회, 특정 성분에 안 묶임)는 별도 파일이다. 카테고리로 모은 상품을 억지로 하나의
`TargetGroup`에 배정하지 않기 위해서다 — 대신 `ProductCandidateRow.target_group`을
`TargetGroup | None`으로 완화했다(`scripts/product_candidate_schemas.py`). 두 CSV는
`ingest_product_ingredients.py`/`inspect_ingredient_parsing.py` 단계에서만 합쳐서 처리한다
(전성분 적재 DB의 중복 방지 키가 `source_product_id` 기준이라 어느 CSV 출신인지와 무관하게
동작하기 때문). 새 CSV를 추가할 일이 생기면 이 두 스크립트에 읽기 경로만 추가하면 된다 —
파서·링커·서비스·리포지토리·DB 모델은 건드릴 필요가 없다.

### 전성분 적재는 상품 전체를 하나의 트랜잭션으로 커밋한다

`ProductIngredientService`/`ProductIngredientRepository`는 커밋하지 않고, `ingest_product_ingredients.py`
가 전체 상품을 다 처리한 뒤 딱 한 번 `session.commit()`한다 — 의도된 설계다(부분 반영보다
전체 성공/실패를 택함). 수천 건 규모에서는 중간 실패 시 전부 롤백되는 비용이 있지만, 이건
기존에 합의된 트랜잭션 경계라 이번 작업에서 임의로 바꾸지 않았다. 바꾸려면 먼저 사용자·팀과
논의한다(규칙 3, 8).

## 관련 문서

- 전체 스키마·품질 기준·담당 범위: [`docs/data/data.md`](data.md)
- 올리브영 글로벌 키워드 검색 파이프라인 인수인계: `docs/oliveyoung_global_pipeline_handoff.md`
- 전성분 파싱·매칭·RAG 인수인계: `docs/SKINCARE_DATA_RAG_HANDOFF.md`
