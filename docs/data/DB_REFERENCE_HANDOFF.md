# Data/DB 기준본 전달 문서

> 목적: Data 담당자 없이도 팀원이 기준 DB와 NIA Data 산출물을 받아 바로 이어서 개발할 수 있게 한다.
> 범위: AI Hub 원본 loader, NIA Case Document, IngredientMaster, IngredientKnowledgeFact, Product,
> ProductIngredient까지. BGE embedding, 벡터 인덱스, retriever, hybrid 검색, reranker, Top-K 검색, Agent
> 연결은 **Agent/RAG 담당 범위**이며 이 문서가 다루지 않는다.

## 1. DB 기준본 (source of truth)

| 항목 | 값 |
| --- | --- |
| dump 파일 | `skincare_latest_2026-09-17.dump` (PostgreSQL custom format, 8,817,775 bytes) |
| SHA-256 | `534e41c6e65c8bedab53dfbce1acc2c888bc2e79afc458c630a413002f16d91f` |
| 생성 | 2026-09-17 06:18 UTC, `pg_dump` 17.6, DB명 `app` |
| Alembic revision | `3165318c750d` (현재 저장소 migration head와 동일. `alembic upgrade`가 필요 없다) |
| 서버 | `paradedb/paradedb:0.18.6-pg17` (compose의 `postgres`). 그보다 낮은 PostgreSQL 버전에는 복원되지 않는다 |

| 테이블 | 행 수 |
| --- | --- |
| `product` | 2,262 |
| `product_ingredient_snapshot` | 2,216 |
| `product_ingredient` | 84,390 (confirmed 78,280 / needs_review 2,693 / unmatched 3,417) |
| confirmed 매핑이 있는 상품 | 2,180 |
| `ingredient_master` | 21,974 |
| `ingredient_knowledge_fact` | 2,411 |

**개발자 로컬의 기존 `app` DB를 기준본으로 쓰지 않는다.** 92 snapshot / 5,244 `product_ingredient`만 가진
별도 부분 데이터다(`product_candidates.csv` 범위만 적재됨). dump가 없으면 이 문서의 수치는 재현되지 않는다.

dump는 용량과 성격상 git에 올리지 않는다(`.gitignore`가 `skincare_latest_2026-09-17.dump`를 제외한다).
## 2. 전달 방법 (Google Drive)

기준 dump는 팀 Google Drive로 전달한다. 저장소에는 dump가 없다.

- Google Drive: https://drive.google.com/drive/u/0/folders/1BprrOow_A461_lnjf6rtPpXpY_Zm3-nl
- 폴더에는 파일 두 개가 있다.
  - `skincare_latest_2026-09-17.dump`
  - `skincare_latest_2026-09-17.dump.sha256` (내용 한 줄: `534e41c6e65c8bedab53dfbce1acc2c888bc2e79afc458c630a413002f16d91f  skincare_latest_2026-09-17.dump`)
- 내려받은 뒤 SHA-256이 위 표의 값과 **일치할 때만** 복원한다. 다르면 복원하지 말고 Data 담당자에게 알린다.

## 3. 복원 방법

기존 DB를 덮어쓰지 않도록 **빈 새 DB**에 복원한다. `<TARGET_DB>`는 각자 정한다.

```bash
# Drive 에서 받은 dump 를 data/ 아래(gitignored)에 둔다
shasum -a 256 data/skincare_latest_2026-09-17.dump   # 534e41c6…f16d91f 와 같을 때만 다음 단계로

docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" <TARGET_DB>'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d <TARGET_DB> --exit-on-error --no-owner' \
  < data/skincare_latest_2026-09-17.dump
```

- `--exit-on-error`: 일부만 복원된 채로 조용히 끝나는 것을 막는다.
- `--no-owner`: dump 소유자 role이 각자 환경에 없어도 복원되게 한다.
- 복원한 DB를 쓰려면 `config.yaml`의 `database.url` 끝의 DB명을 `<TARGET_DB>`로 바꾼다. 이 파일은 gitignored이다.

## 4. 복원 후 검증

```sql
SELECT version_num FROM alembic_version;   -- 3165318c750d

SELECT
  (SELECT count(*) FROM product)                                                     AS product,                   -- 2262
  (SELECT count(*) FROM product_ingredient_snapshot)                                 AS snapshot,                  -- 2216
  (SELECT count(*) FROM product_ingredient)                                          AS product_ingredient,        -- 84390
  (SELECT count(*) FROM product_ingredient WHERE match_acceptance = 'confirmed')     AS confirmed,                 -- 78280
  (SELECT count(*) FROM ingredient_master)                                           AS ingredient_master,         -- 21974
  (SELECT count(*) FROM ingredient_knowledge_fact)                                   AS ingredient_knowledge_fact; -- 2411
```

값이 하나라도 다르면 진행하지 말고 Data 담당자에게 알린다. 복원 직후 확인한 무결성: `product_ingredient`의
`ingredient_id`/`snapshot_id` orphan 0건, confirmed인데 `ingredient_id`가 NULL인 행 0건, 상품 없는
snapshot 0건, `ingredient_knowledge_fact` orphan 0건.

## 5. NIA Data 산출물

```
AI Hub 배포 원본 Q-CoT-A 전체 (ZIP/JSONL)
  → NiaOriginalLoader          → NiaOriginalEntry    (손실 없는 원본, 필터 없음)
  → NiaOriginalAgeFilter       → 10 <= meta.age <= 39 만 통과
  → NiaCaseDocumentBuilder     → NiaCaseDocument     (사례 1건 = 문서 1건)
```

**NIA 원본 corpus는 dump에 포함되지 않는다.** 각자 보유한 AI Hub Q-CoT-A 전체 원본을 `NiaOriginalLoader`로 읽은 뒤,
`meta.age` 기준 10~39세(10대~30대)만 걸러 `NiaCaseDocumentBuilder`로 변환한다. 연령 필터는 loader 내부가 아니라
loader 이후 Data 단계(`NiaOriginalAgeFilter`)에서 적용한다. loader는 항상 전체를 읽는다.
로컬 확보분 기준으로 전체 9,000건 중 10~39세는 3,581건이었다(코드에 고정된 값이 아니라 loader 출력으로 계산한 결과다).

| 역할 | 파일 |
| --- | --- |
| 원본 loader | `data/scripts/nia_original_loader.py` |
| 원본 스키마 | `data/scripts/nia_original_schemas.py` |
| 연령 필터 (10~39세) | `data/scripts/nia_original_age_filter.py` |
| Document builder | `data/scripts/nia_case_document_builder.py` |
| Document 스키마 | `data/scripts/nia_case_document_schemas.py` |
| 계약 | `docs/contracts/data-to-agent.md` ("NIA 사례 Document 계약") |

`NiaCaseDocument` 필드: `case_id`, `page_content`, `embedding_text`, `text_version`, `metadata`.

- **page_content**: question + answer + 전체 CoT. `[질문]` / `[답변]` / `[추론]` 라벨과 `{step}. {title}` 줄바꿈만 붙이고 원문은
  바꾸지 않는다. `initial_skin_condition`, `external`은 넣지 않는다.
- **embedding_text**: v1에서는 `page_content`와 같다. `text_version`은 `nia_case_text/v1`.
- **metadata**: `case_id`, `source_survey_id`, `target_concern`, `gender`, `age`, `skin_type`, `skin_concerns`,
  `initial_skin_condition`, `external`, `image_filename`, `evidence_sources`. 저장소와 무관한 논리 구조이며 list/객체를
  펴는 일은 벡터 저장소 어댑터가 한다.
- embedding, 벡터 적재는 Data가 하지 않았다.

사용 예:

```python
loader = NiaOriginalLoader()
builder = NiaCaseDocumentBuilder()
age_filter = NiaOriginalAgeFilter()                # 기본 10 <= age <= 39
for entry in age_filter.filter(loader.iter_entries(zip_paths)):   # 제너레이터, 전체를 메모리에 올리지 않는다
    document = builder.build(entry.record)
```

원본 ZIP은 저장소에 없다(AI Hub 배포본, `03.스킨케어 성분-효능 추천 데이터/.../02.라벨링데이터/*.zip`). 로컬 확보분은 15개 ZIP,
9,000건이며 공식 배포 규모와 같은지는 확인하지 않았다. 원본 이용조건(비영리 연구 목적, 재배포 금지)은
[data.md](data.md)를 따른다.

**이어받을 지점**: `NiaCaseDocument` 이후(embedding, 인덱스, 검색, Top-3, 성분 추출)는 Agent/RAG 담당이다. agent는 data를
import하지 않으므로 `NiaCaseDocument`를 agent 입력으로 넘기는 방식은 backend mapper 경유가 될 것이며 아직 정해지지 않았다.

## 6. 알려진 데이터 특성

- **지식 없음은 정상 상태다.** confirmed 성분 2,832개 중 `ingredient_knowledge_fact`가 있는 것은 972개(행 기준 약 51%)뿐이다.
  추천 성분에 근거가 없을 수 있고, 이는 오류가 아니다. 근거 없음과 상품 없음을 구분해서 다뤄야 한다.
- **상품 없음도 정상 상태다.** knowledge fact가 있는 성분 2,399개 중 confirmed 상품이 연결된 것은 972개다.
- `product` 2,262개 중 46개는 snapshot이 없다(전성분 텍스트가 없는 상품으로 추정, CSV로 대조하지는 않았다).
- `needs_review` 2,693건, `unmatched` 3,417건은 성분이 확정되지 않은 토큰이다. 성분 → 상품 조회는 `confirmed`만 쓴다.
- `product.source`는 전부 `oliveyoung_global`이다.
- dump에는 2-Layer RAG 시범 데이터(`claim_document` 1건, `evidence_document` 3건)와 `rag_chunk` 0건이 함께 들어 있다.
  이 문서의 범위 밖이다.
- `docs/backend/README.md`는 "현재 코드 head가 `d4c2a7e91b30`이고 저장소는 `3165318c750d`를 모른다"고 적고 있으나,
  지금 main의 head는 `3165318c750d`이다. 그 문서의 해당 문장은 낡았다(이 PR에서 고치지 않았다).
