# Data/DB 기준본 전달 문서

> 목적: Data 담당자 없이도 팀원이 기준 DB와 NIA Data 산출물을 받아 바로 이어서 개발할 수 있게 한다.
> 범위: AI Hub 원본 loader, NIA Case Document, IngredientMaster, IngredientKnowledgeFact, Product,
> ProductIngredient, MFDS Evidence 저장소까지. BGE embedding 이후의 NIA 처리, 벡터 인덱스, retriever, hybrid 검색,
> reranker, Top-K 검색, Agent 연결은 **Agent/RAG 담당 범위**이며 이 문서가 다루지 않는다.

## 1. DB 기준본 (source of truth)

현재 기준본은 **`skincare_reference_2026-09-20.dump`** 이다.

| 항목 | 값 |
| --- | --- |
| dump 파일 | `skincare_reference_2026-09-20.dump` |
| 크기 | 54,391,839 bytes |
| SHA-256 | `9c9bb2dd7b0f8e359364262029a90c907ac1a51a89ef67cc0214383b9102291d` |
| 형식 | PostgreSQL custom format (`pg_dump -Fc --no-owner --no-acl`) |
| 생성 | 2026-09-20 09:44 UTC, `pg_dump` 17.x, 원본 DB명 `skincare_data_finalize` |
| Alembic revision | `2063ce3feae3` (현재 main의 migration head와 동일. chat history 테이블 migration까지 포함, `alembic upgrade`가 필요 없다) |
| 서버 | `paradedb/paradedb:0.18.6-pg17` (compose의 `postgres`, `vector`/`pg_search` 확장 포함). 그보다 낮은 PostgreSQL 버전에는 복원되지 않는다 |
| 복원 검증 | **PASS** — 새 빈 DB에 `pg_restore --exit-on-error --no-owner`로 복원해 revision과 핵심 행 수 22개 지표가 원본과 모두 일치함을 확인했다 |

### 이전 dump는 SUPERSEDED (사용 중단)

`skincare_latest_2026-09-17.dump` (8,817,775 bytes, SHA-256 `534e41c6e65c8bedab53dfbce1acc2c888bc2e79afc458c630a413002f16d91f`,
revision `3165318c750d`)는 **더 이상 쓰지 않는다.** 이유는 다음과 같다.

- Product `display_title`이 2,262건 중 83건만 한글화돼 있다(현재 기준본은 2,259건 반영).
- MFDS Evidence가 `evidence_document`/`evidence_chunk`에 적재되지 않았다(신규 저장소에는 시범 3건뿐).
- chat history 테이블(`chat_room`, `chat_message`, `chat_turn_state`)이 없다.

Drive나 로컬에 이 파일이 남아 있으면 삭제하거나 "구버전"으로 구분해 두고, 새 dump만 복원한다.

### 최종 행 수

| 테이블 | 행 수 |
| --- | --- |
| `product` | 2,262 |
| `product_ingredient_snapshot` | 2,216 |
| `product_ingredient` | 84,390 (confirmed 78,280 / needs_review 2,693 / unmatched 3,417) |
| confirmed 매핑이 있는 상품 | 2,180 |
| `ingredient_master` | 21,974 |
| `ingredient_knowledge_fact` | 2,411 |
| `evidence` (legacy MFDS) | 8,288 |
| `evidence_document` | 14 (MFDS 11 + PubMed 3) |
| `evidence_chunk` | 8,291 (MFDS 8,288 + `pubmed_abstract` 3) |
| `evidence_chunk_ingredient` | 8,291 |
| `rag_chunk` | 0 |
| `chat_room` / `chat_message` / `chat_turn_state` | 0 / 0 / 0 (schema only) |
| `claim_document` / `claim_chunk` | 1 / 5 (2-Layer RAG 시범 데이터) |

**개발자 로컬의 기존 `app` DB를 기준본으로 쓰지 않는다.** 92 snapshot / 5,244 `product_ingredient`만 가진
별도 부분 데이터다. dump가 없으면 이 문서의 수치는 재현되지 않는다.

dump와 체크섬 파일은 용량과 성격상 git에 올리지 않는다. `data/` 아래(`.gitignore`가 `/data/*`를 제외한다)에 둔다.

### Product `display_title`

| `title_source` | 건수 |
| --- | --- |
| `translated` | 2,236 |
| `oliveyoung_kr` | 23 |
| `untranslated` | 3 (`display_title = raw_title` 그대로) |

빈 `display_title`은 0건이다. 품질 기준은 "완전히 자연스러운 한국어 상품명"이 아니라 **검색과 구분에 충분한 한국어
친화형 표시명**이다. 영문 고유명과 라인명이 일부 남는 것은 정상이며 추가 localization QA는 하지 않는다.
`untranslated` 3건은 검토 대기(needs_review)로 남긴 상품이다(`GA260540664`, `GA260238129`, `GA221116814`).

### Evidence

- legacy `evidence` 8,288건은 그대로 남아 있고, 이를 MFDS 관할(jurisdiction)별 `evidence_document` 11건과
  `evidence_chunk` 8,288건으로 **전량 적재**했다. 나머지 `evidence_document` 3건/`evidence_chunk` 3건은 PubMed
  smoke/pilot 데이터(`pubmed_abstract`)이며 삭제하지 않았다.
- 임베딩: `BAAI/bge-m3`, 1,024차원, 전 행 동일. embedding NULL 0건, 중복 `chunk_id` 0건, orphan 0건.
- `evidence_chunk_ingredient`는 chunk마다 1건씩 연결돼 있다(8,291건).

### Claim 시범 데이터, chat, rag_chunk

- `claim_document` 1건, `claim_chunk` 5건은 기존 2-Layer RAG **pilot/smoke 데이터**이며 삭제하지 않았다.
  NIA production corpus로 해석하면 안 된다.
- `chat_room`, `chat_message`, `chat_turn_state`는 테이블(제약 포함)만 있고 행은 0건이다. 정상 상태이다.
- `rag_chunk`는 재적재하지 않아 0건이다.

## 2. 전달 방법 (Google Drive)

기준 dump는 팀 Google Drive로 전달한다. 저장소에는 dump가 없다.

- Google Drive: https://drive.google.com/drive/u/0/folders/1BprrOow_A461_lnjf6rtPpXpY_Zm3-nl
- 폴더에는 새 기준본 파일 두 개가 있어야 한다.
  - `skincare_reference_2026-09-20.dump`
  - `skincare_reference_2026-09-20.dump.sha256` (내용 한 줄: `9c9bb2dd7b0f8e359364262029a90c907ac1a51a89ef67cc0214383b9102291d  skincare_reference_2026-09-20.dump`)
- 폴더에 `skincare_latest_2026-09-17.dump`가 보이면 **구 기준본(SUPERSEDED)** 이므로 받지 않는다. 파일명을 꼭 확인한다.
- 내려받은 뒤 SHA-256이 위 표의 값과 **일치할 때만** 복원한다. 다르면 복원하지 말고 Data 담당자에게 알린다.

## 3. 복원 방법

기존 DB를 덮어쓰지 않도록 **빈 새 DB**에 복원한다. `<TARGET_DB>`는 각자 정한다.

```bash
# Drive 에서 받은 dump 를 data/ 아래(gitignored)에 둔다
shasum -a 256 data/skincare_reference_2026-09-20.dump   # 9c9bb2dd…2291d 와 같을 때만 다음 단계로

docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" <TARGET_DB>'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d <TARGET_DB> --exit-on-error --no-owner' \
  < data/skincare_reference_2026-09-20.dump
```

- `--exit-on-error`: 일부만 복원된 채로 조용히 끝나는 것을 막는다.
- `--no-owner`: dump 소유자 role이 각자 환경에 없어도 복원되게 한다.
- 복원한 DB를 쓰려면 `config.yaml`의 `database.url` 끝의 DB명을 `<TARGET_DB>`로 바꾼다. 이 파일은 gitignored이다.
- 복원한 DB에는 이미 최신 migration이 적용돼 있으므로 `alembic upgrade`를 다시 실행하지 않는다.

## 4. 복원 후 검증

```sql
SELECT version_num FROM alembic_version;   -- 2063ce3feae3

SELECT
  (SELECT count(*) FROM product)                                                     AS product,                    -- 2262
  (SELECT count(*) FROM product WHERE title_source = 'translated')                   AS title_translated,           -- 2236
  (SELECT count(*) FROM product WHERE title_source = 'oliveyoung_kr')                AS title_oliveyoung_kr,        -- 23
  (SELECT count(*) FROM product WHERE title_source = 'untranslated')                 AS title_untranslated,         -- 3
  (SELECT count(*) FROM product_ingredient_snapshot)                                 AS snapshot,                   -- 2216
  (SELECT count(*) FROM product_ingredient)                                          AS product_ingredient,         -- 84390
  (SELECT count(*) FROM product_ingredient WHERE match_acceptance = 'confirmed')     AS confirmed,                  -- 78280
  (SELECT count(*) FROM ingredient_master)                                           AS ingredient_master,          -- 21974
  (SELECT count(*) FROM ingredient_knowledge_fact)                                   AS ingredient_knowledge_fact,  -- 2411
  (SELECT count(*) FROM evidence)                                                    AS evidence_legacy,            -- 8288
  (SELECT count(*) FROM evidence_document)                                           AS evidence_document,          -- 14
  (SELECT count(*) FROM evidence_chunk)                                              AS evidence_chunk,             -- 8291
  (SELECT count(*) FROM evidence_chunk_ingredient)                                   AS evidence_chunk_ingredient,  -- 8291
  (SELECT count(*) FROM evidence_chunk WHERE embedding IS NULL)                      AS embedding_null,             -- 0
  (SELECT count(*) FROM rag_chunk)                                                   AS rag_chunk,                  -- 0
  (SELECT count(*) FROM chat_room)                                                   AS chat_room,                  -- 0
  (SELECT count(*) FROM claim_document)                                              AS claim_document,             -- 1
  (SELECT count(*) FROM claim_chunk)                                                 AS claim_chunk;                -- 5
```

값이 하나라도 다르면 진행하지 말고 Data 담당자에게 알린다. 복원 직후 확인한 무결성: `product_ingredient`의
`ingredient_id`/`snapshot_id` orphan 0건, `evidence_chunk`→`evidence_document` orphan 0건,
`evidence_chunk_ingredient` orphan 0건, 중복 `chunk_id` 0건, 1,024차원이 아닌 embedding 0건.

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
- Evidence는 저장소 적재까지만 끝났다. 검색(retrieval), citation 표시, reranker는 이 dump의 범위 밖이다.
- **NIA 원본은 dump에 없다.** 원본 ZIP은 재배포가 금지된 AI Hub 데이터이고, embedding/index/retrieval은 Agent/RAG 단계라서
  각자 5절 방식으로 원본을 읽어 처리한다. dump의 Claim 시범 데이터(1/5건)와 혼동하지 않는다.
- 타 파트 문서 중 이 dump를 가리키는 곳(`docs/backend/README.md`, `docs/contracts/backend-to-agent.md` 등)은 각 담당자가
  갱신한다. 이 문서가 기준이며, 그 문서들이 구 dump나 구 revision(`3165318c750d`)을 적고 있으면 낡은 내용이다.
