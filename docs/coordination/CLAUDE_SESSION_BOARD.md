# Claude Session Coordination Board

> 두 세션이 직접 대화할 수 없으므로 이 문서가 communication channel이다. 규칙:
> 1) 작업 시작 전 이 문서를 읽는다 2) 본인 섹션의 Status/Changed files를 갱신한다
> 3) 상대 소유 파일을 수정하지 않는다 4) 상대 결정이 필요하면 "Needs from Session X"에
> 적는다 5) shared contract는 직접 고치지 않고 "Shared Decisions"에 먼저 제안한다
> 6) merge 전에 상대 섹션의 Changed files를 확인한다.

> **운영 규칙 (2026-09-15 갱신)**: Claim/Evidence worker 세션은 이 Board를 **읽기만** 한다.
> Board 본문 갱신은 PM/총괄 세션만 수행한다. Worker 세션은 작업 종료 시
> `SESSION_A_UPDATE` / `SESSION_B_UPDATE` 형식으로 총괄 세션에 보고하고, 총괄 세션이
> 검토 후 이 문서에 반영한다. worker worktree에 남아있는 미커밋 Board 수정은 공용 Board
> 반영으로 간주하지 않는다(반영 전까지 worker 쪽 diff는 삭제하지 말고 보관).

---

## Session A — Claim RAG

**Branch**: `feature/claim-rag` (worktree `skincare-claim-rag`, `feature/rag-pipeline`의
`086a969`에서 분기)

**Owner**: 배정됨(worktree 작업 진행 중, 세션 식별자 미기록)

**Allowed files**: [CLAIM_RAG_SESSION_HANDOFF.md](CLAIM_RAG_SESSION_HANDOFF.md) §13

**Do not edit**: [CLAIM_RAG_SESSION_HANDOFF.md](CLAIM_RAG_SESSION_HANDOFF.md) §14

**Current task**: `CLAIM_RAG_INGESTION_DESIGN.md` §10 진행 중 — ClaimDocument mapper와
statement-type별 embedding text builder의 dry-run 구현·테스트까지 완료. 아래 "NEEDS_FIX 사유"
두 건을 해결한 뒤 다음 단계(실제 embedding/색인)로 진행할 것.

**Status**: `NEEDS_FIX`

**NEEDS_FIX 사유** (PM 세션이 `CLAIM_RAG_CATCHUP_FOR_CLAUDE_PM.md` 기준으로 지정, 2026-09-15):
1. `usage_instruction.ingredient_ids`가 `raw_name` 없음을 이유로 `ingredient_refs` 매핑에서
   누락됨 — canonical retrieval unit은 특정 statement type이 아니라
   `NiaLabelingDocument.statements[]` 전체이므로 제외하면 안 됨. `ingredient_id`만 있고
   `raw_name`이 없는 경우 `raw_name: null, matching_status: matched, role: unspecified`로
   채운다. `IngredientRef` 불변조건은 `ingredient_id IS NOT NULL OR non-empty raw_name`이며
   둘 다 없으면 validation error로 처리한다.
2. `combination_claim.subjects`의 첫 번째 성분을 근거 없이 `primary`, 나머지를 `secondary`로
   추론함 — annotation에 역할이 명시된 경우에만 `primary`/`secondary`를 쓰고, 단순 나열이면
   전부 `unspecified`로 둔다. 입력 순서는 tuple 또는 `ordinal`로 보존하되 semantic role
   추론과는 분리한다.

**NIA annotation 상태 (2026-09-15 정정, corpus 규모 오류 수정)**: 전체 NIA 약 9,000건을
라벨링하는 계획이 아니다. Claim 라벨링 최종 대상은 10~30대 필터링된
`data/processed/nia_qa_10s_30s.jsonl` **3,581건**이다. 현재 repository 기준 실측치:

| 항목 | 건수 |
|---|---:|
| 라벨링 대상(최종 corpus) | 3,581 |
| 라벨링 시도 | 39 |
| 라벨링 성공 | 36 |
| 라벨링 실패 | 3 |
| 미시도 | 3,542 |
| 성공 라벨 없음(실패+미시도) | 3,545 |
| `production_ready=true` | 0 |
| 사람 최종 검수 완료 | 0 |

"ClaimDocument mapper dry-run 완료"는 이 39건 시도 중 성공한 36건 표본 대상 구조 검증이며,
corpus 전체(3,581건) 라벨링 완료를 의미하지 않는다. 사람 최종 검수는 아직 0건이므로
`production_ready` 판정도 없다.

> **과거 보고값(현재 repo에서 재현되지 않음, 삭제하지 않고 구분 표시)**: 이전 세션 보고서
> (`CLAIM_RAG_CATCHUP_FOR_CLAUDE_PM.md`)는 "라벨링된 표본 58 records(training 53 /
> validation 5), ingredient matching matched 97 / unresolved 20"이라고 기록했었다. 이 수치는
> 위 실측치(시도 39 / 성공 36)와 맞지 않아 현재 repository 상태로는 재현되지 않는다. 실제
> 실험 이력 기록으로는 남겨두되, 현재 corpus 규모·진행률 판단에는 **3,581건 기준 표를
> 사용**한다.

**Last update**: 2026-09-15 — worktree에서 `data/scripts/nia_claim_document.py`,
`data/scripts/nia_claim_embedding_text.py`, 관련 유닛 테스트 신규 작성(dry-run,
embedding API 호출 없음). `pytest tests -q` 245 passed, 변경 파일 ruff/pyrefly 통과.
아직 commit/push하지 않음(worktree에만 존재).

**Changed files** (미커밋, worktree 로컬):
```
신규: data/scripts/nia_claim_document.py
신규: data/scripts/nia_claim_embedding_text.py
신규: tests/unit/test_nia_claim_document.py
신규: tests/unit/test_nia_claim_embedding_text.py
수정: docs/coordination/CLAUDE_SESSION_BOARD.md (worker worktree 로컬 수정 — 위 운영 규칙에
  따라 PM 세션이 검토 후 이 문서에 반영, worker 쪽 미커밋 diff는 별도 처리 지시 전까지 유지)
```
세션 시작 전부터 존재하던 무관한 변경(`CLAIM_RAG_SESSION_HANDOFF.md`)은 이번 워크스트림과
무관하므로 별도 처리하지 않음.

수행하지 않음: `models/` 수정, migration 생성, embedding API 호출, `claim_chunk` insert,
Evidence RAG/Agent orchestration 수정, commit/push.

**Needs from Session B**:
- `claim_chunk` 컬럼 초안 공유 시 Evidence 쪽 embedding 모델/차원과 맞출지 검토 요청
  (⚠️ 2026-09-17 갱신: Evidence는 `BAAI/bge-m3`(local) / 1024차원으로 재확정됐다 — 아래
  Shared Decisions 참고. `text-embedding-3-small`/1536차원으로 일치했다는 이 줄의 기존 기술은
  더 이상 유효하지 않다)

---

## Session B — Evidence / Existing Session

**Branch**: `feature/rag-pipeline` (origin과 동기화됨, 최신 커밋 `086a969`)

**Owner**: 이 세션(기존 세션, 전체 맥락 보유)

**Allowed files**:
```
data/scripts/export_ingredient_dataset.py
data/scripts/ingredient_dataset_csv_writer.py
data/scripts/ingredient_master_reader.py
data/scripts/build_product_datasets.py
data/scripts/product_ingredient_mapping_schemas.py
data/scripts/product_ingredient_mapping_csv_writer.py
data/scripts/product_taxonomy_backfill.py
data/scripts/ingredient_name_matcher.py       (공용 — 변경 시 Board에 먼저 공지)
data/scripts/ingredient_name_normalizer.py    (공용 — 변경 시 Board에 먼저 공지)
data/scripts/ingredient_schemas.py            (공용 — 변경 시 Board에 먼저 공지)
docs/data/EVIDENCE_RAG_DESIGN.md
docs/data/EVIDENCE_COVERAGE_AUDIT.md
docs/data/NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md
docs/data/rag_pipeline_handoff.md
docs/data/POC_DATASET_HANDOFF.md
docs/contracts/two-layer-rag-agent-backend-contract.md  (FINAL MERGE 권한)
docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md          (작성 완료, 이후 유지보수)
data/processed/ingredient_full.csv, product_candidates.csv, product_ingredient_mapping.csv,
  product_quality_report.csv, evidence_coverage_matrix.json, niacinamide_claim_evidence_candidates.json
```

**Do not edit**: Claim RAG 섹션의 "Session A Allowed files"(§13) 전부 —
`data/scripts/nia_*.py`, `tests/unit/test_nia_*.py`, `data/processed/nia_10s_30s_*.jsonl`,
`data/processed/nia_qa_10s_30s.jsonl`, `docs/data/NIA_ANNOTATION_JSON_GUIDE.md`,
`docs/data/CLAIM_RAG_INGESTION_DESIGN.md`

**Current task**: 없음 — 이 세션(handoff 작성 세션)은 여기서 종료했다. 다만 아래
"⚠️ 미승인 변경 발견"에 기록된 대로, `feature/rag-pipeline` 워크트리(`skincare`)에서
**후속 Evidence 세션으로 추정되는 활동이 사용자 승인 없이 진행됨**이 2026-09-15 확인됐다.

**Status**: `RESOLVED — Evidence storage live 적용 완료` (2026-09-17 갱신. 아래
"⚠️ 미승인 변경 발견" 절은 그 시점 기준 기록이라 삭제하지 않고 그대로 남겨두지만, 현재는
해결된 과거 상태다 — 최신 상태는 이 절 바로 아래 "✅ 2026-09-17 해결" 참고)

**✅ 2026-09-17 해결**: `docs/data/EVIDENCE_STORAGE_ERD.md` 작성 → 사용자 확인 → 승인 절차가
완료됐다(CLAUDE.md 규칙 14 그대로 준수). Embedding contract는 `BAAI/bge-m3`(local)/
`vector(1024)`로 확정(최초 승인 당시의 `text-embedding-3-small`/`vector(1536)`에서 변경 —
`rag_chunk`와 모델·차원을 통일할 필요가 없다는 판단). `11cdc111cf27` migration을 live `app`
DB에 적용 완료(`alembic_version = 11cdc111cf27`), `evidence_document`/`evidence_chunk`/
`evidence_chunk_ingredient` 테이블이 live에 존재하며 니아신아마이드 PubMed 실 데이터 3건으로
BGE-M3 smoke 완료(PASS). 아래 "미승인 변경 파일" 목록의 파일들은 이제 정식 승인·적용된
상태이며, 삭제/수정/stage/commit/push 금지 지시도 더 이상 유효하지 않다(단, 이번 정정에서는
문서 상태 서술만 고치고 실제 commit/push는 하지 않았다 — 그건 별도 결정 사항).

**중요 정정**: 별도 경로("main PR")에서 `rag_chunk`도 BGE-M3/1024로 전환하도록 이미 결정됐다는
전제가 있었으나, `origin/main` 직접 확인 결과 근거를 찾지 못해 **폐기**됐다(2026-09-17).
`rag_chunk.embedding = vector(1536)`/`text-embedding-3-small`을 그대로 유지하며(live rows
실측 0건 — 일부 문서의 "65,196건" 서술은 이 live DB의 현재 상태가 아니다), 전환 여부는
별도 후속 결정 사항으로 보류한다. Evidence(`evidence_chunk`)가 BGE-M3/1024인 것과
`rag_chunk`를 BGE-M3로 전환하는 것은 서로 다른 결정이다 — 혼동 금지.

### ⚠️ 미승인 변경 발견 (PM 세션 기록, 2026-09-15 17:2x KST)

**`git status --short --branch`** (워크트리: `C:/Users/Admin/Documents/MCP/skincare`,
branch `feature/rag-pipeline`, 커밋 `a6c9968`, 미커밋):
```
## feature/rag-pipeline...origin/feature/rag-pipeline
 M config.prod.yaml.sample
 M config.yaml.sample
 M docs/coordination/CLAUDE_SESSION_BOARD.md   (PM 세션이 이번에 반영한 정정분)
 M docs/erd/app.md                              (이번 작업과 무관한 기존 변경, 손대지 않음)
 M models/__init__.py
?? migrations/versions/11cdc111cf27_add_evidence_document_evidence_chunk_.py
?? models/evidence_chunk.py
?? models/evidence_document.py
?? tests/unit/test_evidence_storage_schema.py
```

파일별 수정 시각(로컬, 17:20:30~17:23:40 KST 사이 5분 내 연속 작성 — 한 세션의 단일 작업
흐름으로 보임):
```
17:20:30  models/__init__.py
17:20:33  config.yaml.sample
17:20:38  config.prod.yaml.sample
17:22:05  models/evidence_document.py
17:22:12  models/evidence_chunk.py
17:22:38  migrations/versions/11cdc111cf27_add_evidence_document_evidence_chunk_.py
17:23:40  tests/unit/test_evidence_storage_schema.py
```

**원인 추정**: `git worktree list` 확인 결과 워크트리는 두 개뿐이다 —
`C:/Users/Admin/Documents/MCP/skincare`(`feature/rag-pipeline`, 이 PM 세션이 사용 중인
디렉터리와 동일)와 `C:/Users/Admin/Documents/MCP/skincare-claim-rag`(`feature/claim-rag`,
Claim Session A 전용). 즉 **Claim/Evidence 워크트리 혼선은 아니다** — Claim Session A는
정상적으로 `skincare-claim-rag`만 쓰고 있다. 그러나 파일이 나타난 위치는 PM/총괄 세션이
지금 작업 중인 바로 이 `skincare` 디렉터리이며, 파일 이름·내용(`evidence_document`,
`evidence_chunk` ORM model, 대응 migration, storage schema 테스트)으로 볼 때 **Evidence
RAG 저장 구조 구현 세션이 같은 `skincare` 워크트리에서 PM 세션과 동시에 작업하며 만든
것으로 추정**된다(작성자를 코드 자체로는 특정 불가 — git 미커밋 상태라 author 기록 없음).
Board상 "Session B — SESSION_ENDED"로 표기돼 있던 세션과는 별개의, 뒤이어 같은 브랜치/워크트리에서 시작된 세션으로 보인다.

**문제**: `evidence_document`/`evidence_chunk` model과 migration은 CLAUDE.md 규칙 14 및
두 전달 문서(§7/§12) 모두에서 "ERD 문서 작성 → 사용자 확인 → 승인 후 구현"으로 명시한
항목이다. ERD 문서(`docs/erd/`에 Evidence storage용 문서 없음, `docs/erd/app.md`만 존재하며
이번 세션에서 그 파일을 만들거나 확인한 이력 없음) 승인 없이 model/migration이 먼저
생성됐다 — 순서가 뒤바뀐 미승인 작업이다.

**조치**: 사용자 지시에 따라 위 4개 신규/수정 파일은 그대로 보존한다(PM 세션은 삭제·수정·
stage·commit·push 어느 것도 하지 않음). Evidence storage 구현은 아래 순서로 재정렬한다.

```
Evidence storage requirements
→ ERD / table relationship design (docs/erd/ 신규 문서, 사용자 승인 대상)
→ 사용자 확인
→ 승인 후 model / migration 구현
```

**동시 워크트리 사용 권고**: PM/총괄 세션과 Evidence Session B가 같은 `skincare` 디렉터리를
동시에 쓰면 이번처럼 서로의 변경을 실시간으로 못 보고 충돌 원인 파악이 어려워진다. 위
"운영 규칙(2026-09-15 갱신)"에 따라 Board 본문 수정은 PM 세션만 하지만, **코드/모델 작업
디렉터리 자체는 Evidence Session B 전용으로 두고 PM 세션은 별도로 분리하는 방안을
사용자가 검토**할 것을 권한다(예: PM 세션도 read-only 목적의 별도 checkout 사용).

**Last update**: 2026-09-15 — 커밋 `086a969`(`chore(rag): checkpoint claim-rag handoff state`)로
§13 목록 전체(NIA 스크립트, 테스트, coordination/설계 문서)를 push 완료, `origin/feature/rag-pipeline`과 동기화됨

**Changed files** (이 세션 전체 기준, `086a969` 커밋 내용):
```
data/scripts/nia_*.py (전체), data/scripts/nia_labeling_parser.py / nia_labeling_schemas.py
  (data/manual_review 원본은 유지한 채 .gitignore상 커밋 가능한 data/scripts/로 사본 추가)
tests/unit/test_nia_*.py (전체)
docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md, CLAUDE_SESSION_BOARD.md
docs/data/CLAIM_RAG_INGESTION_DESIGN.md, EVIDENCE_COVERAGE_AUDIT.md, EVIDENCE_RAG_DESIGN.md,
  NIACINAMIDE_EVIDENCE_VERTICAL_SLICE.md, NIA_ANNOTATION_JSON_GUIDE.md,
  POC_DATASET_HANDOFF.md, rag_pipeline_handoff.md (일부 갱신)
```
(`data/processed/*.csv`, `*.jsonl` 등 산출물은 `.gitignore`로 커밋 대상 아님 — 로컬에만 존재)

**Needs from Session A**:
- `claim_chunk` 컬럼 초안 공유 시 Evidence 쪽 embedding 모델/차원과 일치시킬지 여부 확인 요청
- `ClaimPort` 인터페이스 초안이 나오면 `docs/contracts/two-layer-rag-agent-backend-contract.md`의
  `EvidencePort`와 이름/패턴 일관성 검토를 위해 공유 요청

---

## Shared Decisions

(둘 다 동의한 확정 사항 — 근거는 각 설계 문서 참고)

1. Claim(NIA)과 Evidence(MFDS/CIR/PubMed)는 별도 레이어로 분리한다 — `ClaimHit != EvidenceRecord`
2. `ingredient_id`가 전체 파이프라인의 중심 키다. 5개 POC 성분은 시작점일 뿐 — 매칭
   로직은 `IngredientMaster` 전체에 generic하게 적용돼야 한다(하드코딩 금지)
3. `rag_chunk` 재구축(embedding)은 두 레이어 저장 구조가 각각 확정될 때까지 보류한다
4. DB migration은 이번 handoff 단계에서 어느 세션도 실행하지 않는다(사용자 승인 필요)
5. `data/manual_review/nia_labeling_schemas.py`/`nia_labeling_parser.py`/
   `nia_labeling_guide.md`는 freeze — 두 세션 다 수정 금지
6. Claim ingestion 정책은 Open Decision이 아니라 확정 사항이다(PM 세션 반영, 2026-09-15):
   `ingestible_structured`/`ingestible_free_text` → 운영 인덱스 포함,
   `human_review` → 기본 인덱스 제외, `blocked` → 인덱스 제외,
   `training` → 운영 인덱스 대상, `validation` → retrieval evaluation 전용,
   secondary ingredient는 손실 없이 보존. POC embedding은 당시 `text-embedding-3-small`/
   1536차원(Claim/Evidence 공통)으로 기록됐었으나 **2026-09-17 Evidence 쪽만 `BAAI/bge-m3`
   (local)/1024차원으로 재확정**됐다(아래 Cross-session Decisions Needed #1 참고, Claim은
   아직 실제 storage 자체가 없어 재확정 대상 아님). 실제 embedding 실행은 Evidence 쪽만
   수행됨 — smoke(니아신아마이드 PubMed 3건)와 live 적용 모두 완료(2026-09-17, 위 "✅
   2026-09-17 해결" 참고). Claim은 여전히 storage 자체가 없어 embedding 실행 대상 아님.

## Evidence ERD 결정 상태 (Session B 제안, PM 세션이 BLOCKER/NON-BLOCKER 구분, 2026-09-15)

✅ 2026-09-17: ERD 승인 완료, `models`/migration 생성·live 적용까지 끝났다(위 "✅ 2026-09-17
해결" 참고). 아래 BLOCKER/NON-BLOCKER 구분은 승인 당시(2026-09-15) 기록이라 그대로 남겨둔다 —
전부 사용자 승인을 받아 해소됐다.

**BLOCKER** (사용자 ERD 승인 없이는 진행 불가):
- Evidence를 Claim의 `rag_chunk`와 분리된 별도 저장 구조로 분리
- 단일 `ingredient_id` FK 대신 `evidence_chunk_ingredient` 조인 테이블로 다중 성분 지원
  (`Pydantic EvidenceChunk.ingredient_ids: list[UUID]` ↔ 조인 테이블 매핑)
- `DIRECT/PARTIAL/UNSUPPORTED`는 문서 속성이 아니라 `ClaimEvidenceLink.support_level`(관계)로 결정
- 문서 식별 제약 `UNIQUE(source_type, source_id)`
- chunk identity와 citation locator 분리

**NON-BLOCKER** (ERD 승인과 별개로 이미 확정/합의 가능):
- Evidence embedding은 `BAAI/bge-m3`(local), `vector(1024)` — 2026-09-17 재확정(과거
  `text-embedding-3-small`/`vector(1536)`, Claim POC와 동일 모델이라던 기술은 폐기)
- MFDS 원본은 향후 `evidence_document/evidence_chunk`로 신규 적재, 기존 `rag_chunk`에는
  다시 적재하지 않음
- Knowledgedata / `IngredientKnowledgeFact`는 공식 Evidence corpus·citation source에서 제외
- Citation은 `chunk_id` 문자열 파싱이 아니라 `EvidenceDocument`/`EvidenceChunk`의 retrieved
  metadata로 Backend가 조립(LLM이 citation 텍스트를 생성하지 않음)
- Citation provenance 필수 후보 필드: `evidence_document_id`, `evidence_chunk_id`,
  `source_type`, `source_id`, `source_title`, `source_url`, `PMID`, `DOI`, `jurisdiction`,
  `section`, `page`/locator, `chunk_index`, 원문 text/span, `published_at`, `retrieved_at`,
  `content_hash`, `parser_version`

## Cross-session Decisions Needed

1. **`claim_chunk`와 `evidence_chunk`의 embedding 모델/차원** — 2026-09-15에는 둘 다
   `text-embedding-3-small`/1536차원으로 일치한다고 기록했으나, **2026-09-17 Evidence만
   `BAAI/bge-m3`(local)/1024차원으로 재확정**됐다. `claim_chunk`는 아직 실제 storage가
   없어(Session A dry-run 단계) 이 변경에 맞출지는 Session A가 `claim_chunk`를 실제로
   설계할 때 다시 결정한다 — 두 레이어가 이제 같은 모델일 필요는 없다(저장 구조가 이미
   분리돼 있으므로 같은 HNSW 인덱스로 묶는 안도 자연히 폐기).
2. **`ClaimPort`/`EvidencePort` 네이밍·시그니처 패턴 일관성** — agent 파트와의 최종
   합의 전에 최소 두 세션 간 스타일은 맞추는 게 좋음
3. **`ingredient_name_matcher.py` 등 공용 매칭 코드에 변경이 필요해지면** — 어느
   세션이 먼저 고치든 다른 세션의 회귀 테스트를 깨뜨릴 수 있어, 변경 전 이 Board에
   공지하고 상대의 관련 테스트(Session A: `test_nia_ingredient_matching_stage.py`,
   Session B: `test_product_taxonomy_normalizer.py` 등 product 매칭 테스트)가 여전히
   통과하는지 서로 확인 후 진행
4. **PM 결정 필요 — `ClaimHit`의 다중 `ingredient_refs` vs 단일 `ingredient_id` 호환** (2026-09-15
   접수): 기존 `ClaimHit`/`EvidenceQueryAnchor` contract가 단일 `ingredient_id`를 전제로
   설계됐다면, Claim 쪽 배열형 `ingredient_refs`(`IngredientRef{ingredient_id, raw_name,
   matching_status, role}`) 방향으로 변경할지 별도 단일 호환 필드를 유지할지 아직 미정.
   Evidence 쪽 `evidence_chunk_ingredient` 조인 테이블은 이미 다중 성분을 지원하므로
   구조적으로는 호환 가능해 보이나, `EvidenceQueryAnchor`가 다중 `ingredient_refs`를 받는
   시그니처로 확정됐는지는 Session B/Agent 파트 확인 필요. `role=unspecified`도 정상값으로
   처리해야 한다. Claim 세션은 `ingredient_refs`를 손실 없이 반환하는 데까지만 담당하고
   Agent contract는 직접 수정하지 않는다.

## 프로젝트 범위 참고 (PM 세션 추가, 2026-09-15)

Niacinamide `sebum_control` 케이스는 Evidence RAG의 첫 vertical slice이자 end-to-end 검증용
사례일 뿐, 서비스 전체 사용자 질문 범위를 대표하지 않는다. 현재 5개 POC 성분도 시작점일
뿐이며 최종 목표는 전체 `IngredientMaster`를 지원하는 범용 구조다. 서비스 기능/유스케이스의
최신 기준은 Notion, 구현 상태·세션 담당·충돌 관리 기준은 이 Board다. Notion 최신 유스케이스와
repository contract가 충돌하면 어느 세션도 임의로 한쪽을 선택하거나 범위를 확장하지 않고
PM/총괄 세션 결정 항목으로 여기에 기록한다(현재 접수된 충돌 없음).

## Merge Order

1. ✅ **완료** — Session B가 §13 목록 파일을 `feature/rag-pipeline`에 커밋(`086a969`)·
   푸시했다. `origin/feature/rag-pipeline`이 이제 Session A의 시작점이다.
2. Session A는 그 커밋을 포함한 `origin/feature/rag-pipeline`에서 `feature/claim-rag`를 분기한다
3. Session A는 `feature/claim-rag`에서 작업하며 주기적으로 `origin/feature/rag-pipeline`을
   merge(또는 rebase 대신 merge — 이 저장소 관례상 공유 브랜치에 force-push 금지)해 최신
   Session B 변경을 반영한다
4. 두 세션 다 **자기 소유 파일만** 건드리므로 실제 병합 충돌은 거의 없어야 한다 — 충돌이
   나면 CLAUDE.md 규칙 19의 "충돌이 나면 혼자 해결하지 않는다" 절차를 따른다(공용 파일
   충돌 시 특히)
5. `feature/claim-rag` → `feature/rag-pipeline` PR은 Session A의 Definition of Done
   충족 후, squash merge로 진행(저장소 관례)

## Git 작업 구조

```bash
# Session B 커밋·푸시 — 완료됨(086a969)

# Session A가 이어서 실행:
git worktree add ../skincare-claim-rag -b feature/claim-rag origin/feature/rag-pipeline
```

**Base branch는 `feature/rag-pipeline`을 추천한다** — `main`은 이 세션의 모든
Claim/Evidence 작업이 아직 반영 안 됐고(별도 PR 대기), `feature/data-pipeline`은
96커밋 뒤처진 오래된 브랜치라 base로 부적절하다.
