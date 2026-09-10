# 데이터 파이프라인 (파트 진입 문서)

담당 범위·MVP 데이터셋·파이프라인 설계는 [data.md](data.md)를 따른다. 이 문서는 거기 없는,
실제로 작업하면서 부딪힌 특이사항만 적는다.

## 이 저장소를 열 때 먼저 볼 것

이 프로젝트는 같은 브랜치(`feature/rag-pipeline`)를 **워크트리 여러 개로 동시에 작업 중**이다
(`.claude/worktrees/` 아래). 워크트리마다 커밋 상태가 다를 수 있으니, 작업 시작 전에
`git log --oneline -5`로 어느 워크트리가 최신인지 먼저 확인한다. 다른 워크트리에만 있는
파일(`data/processed/catalog_products.csv` 등)을 없다고 판단하지 않는다.

## DB 마이그레이션이 두 갈래로 갈라졌던 적이 있었다

`app_user` 테이블 마이그레이션(`b1f97294c64e`)이 다른 브랜치에서 만들어진 뒤 한동안 병합이
안 된 채로 남아 `alembic heads`가 2개였다. `models/user.py`는 코드에 있는데 실제 DB에는
`app_user` 테이블이 없는 상태였다는 뜻이다. `alembic merge`로 병합(`993200358dfb`)하고 나서야
새 테이블(`product`) 마이그레이션을 안전하게 만들 수 있었다. **`makemigrations` 전에
`alembic heads`로 head가 1개인지 먼저 확인하는 습관이 필요하다.**

autogenerate가 `rag_chunk`의 pg_search BM25 인덱스(`ix_rag_chunk_content_bm25`)를 "삭제
대상"으로 잘못 감지한 적도 있다 — 이 인덱스가 SQLAlchemy 모델에 선언돼 있지 않고 raw SQL로
관리되기 때문이다. `makemigrations` 결과에 이 인덱스를 지우는 `drop_index`가 보이면 실행하지
말고 지운다(SETUP.md의 "makemigrations 결과는 실행 전에 반드시 확인" 규칙이 실제로 걸린 사례).

## `product`(상품 카탈로그) vs `product_ingredient_snapshot`(전성분)은 의도적으로 분리했다

같은 상품이라도 "이름·가격·이미지"와 "전성분 원문·매칭"은 서로 다른 스크립트가 다른 시점에
채운다. FK로 묶지 않고 `(source, source_product_id)` 값으로만 느슨하게 연결한다. 설계 판단
근거는 [docs/erd/app.md](../erd/app.md)의 "왜 이렇게 나눴는지" 절 참고.

`product`는 가격·재고 이력을 안 쌓는다(현재 상태 1행 UPSERT). `docs/data/data.md`의
"정제된 가격 데이터" 절(`ProductPriceSnapshot`, 이력 저장 방식)은 **네이버 쇼핑 API 기준으로
쓰인 예전 설계이고, 네이버 경로는 API 인증 실패로 막혀 실제 구현되지 않았다.** 실제 구현은
올리브영 글로벌 기반 `ProductCandidateRow`/`product` 쪽이라 그 절과 내용이 다르다 — 문서를
아직 못 맞췄으니 헷갈리면 이 README와 `docs/erd/app.md`를 우선한다.

## backend/repositories, backend/services는 만들지 않는다

CLAUDE.md 규칙 15에 따라 `backend/` 전체가 backend 파트 소유다. data 파트가 상품 데이터를
DB에 넣는 서비스/리포지토리가 필요하면 직접 만들지 말고
[docs/contracts/data-to-backend.md](../contracts/data-to-backend.md)에 계약만 쓴다(규칙 16).

## 상품 데이터를 다른 파트에 전달할 때

- **이미지**: 파일로 전달하지 않는다. `product.image_url`(올리브영 CDN 원본)을 그대로 쓴다.
  `local_image_path`는 수집 시점 로컬 경로라 다른 환경에서 의미 없다.
- **DB**: 접속정보를 공유하지 않는다. 받는 쪽이 `SETUP.md` 그대로 자기 로컬에
  `docker compose` + `alembic upgrade head`로 동일 스키마를 재현한다.
- **원본 CSV**(`data/processed/product_candidates.csv`, `catalog_products.csv`)는 `data/`가
  `.gitignore` 대상이라 git으로 안 넘어간다. 파일 자체는 1MB 안팎으로 작으니 직접 전달한다.
