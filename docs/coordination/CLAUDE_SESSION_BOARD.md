# Claude Session Coordination Board

> 두 세션이 직접 대화할 수 없으므로 이 문서가 communication channel이다. 규칙:
> 1) 작업 시작 전 이 문서를 읽는다 2) 본인 섹션의 Status/Changed files를 갱신한다
> 3) 상대 소유 파일을 수정하지 않는다 4) 상대 결정이 필요하면 "Needs from Session X"에
> 적는다 5) shared contract는 직접 고치지 않고 "Shared Decisions"에 먼저 제안한다
> 6) merge 전에 상대 섹션의 Changed files를 확인한다.

---

## Session A — Claim RAG

**Branch**: `feature/claim-rag` (worktree, `feature/rag-pipeline`의 `ea54117`에서 분기 — 아래 "Git 작업 구조" 참고)

**Owner**: (새 세션 배정 시 기록)

**Allowed files**: [CLAIM_RAG_SESSION_HANDOFF.md](CLAIM_RAG_SESSION_HANDOFF.md) §13

**Do not edit**: [CLAIM_RAG_SESSION_HANDOFF.md](CLAIM_RAG_SESSION_HANDOFF.md) §14

**Current task**: (아직 시작 전)

**Status**: `NOT_STARTED`

**Last update**: —

**Changed files**: (없음)

**Needs from Session B**:
- (없음 — 시작 시 `claim_chunk` 컬럼 초안을 여기 공유하면 Session B가 Evidence 쪽
  임베딩 모델/차원과 맞출지 검토 가능)

---

## Session B — Evidence / Existing Session

**Branch**: `feature/rag-pipeline` (현재 실제 branch, origin과 동기화됨, 최신 커밋 `ea54117`)

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

**Current task**: Claim RAG 세션 handoff 작성 완료. 다음은 §5(아래 "Session B 재정의된
작업 범위") 진행.

**Status**: `IN_PROGRESS`

**Last update**: 2026-09-15 (이 문서 작성 시점)

**Changed files** (이번 handoff 작업에서):
```
docs/coordination/CLAIM_RAG_SESSION_HANDOFF.md  (신규)
docs/coordination/CLAUDE_SESSION_BOARD.md        (신규)
```

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

## Cross-session Decisions Needed

1. **`claim_chunk`와 향후 `evidence_chunk`(Session B가 별도로 결정 예정)의 embedding
   모델/차원 통일 여부** — 다르면 두 벡터를 같은 HNSW 인덱스로 못 묶는다
2. **`ClaimPort`/`EvidencePort` 네이밍·시그니처 패턴 일관성** — agent 파트와의 최종
   합의 전에 최소 두 세션 간 스타일은 맞추는 게 좋음
3. **`ingredient_name_matcher.py` 등 공용 매칭 코드에 변경이 필요해지면** — 어느
   세션이 먼저 고치든 다른 세션의 회귀 테스트를 깨뜨릴 수 있어, 변경 전 이 Board에
   공지하고 상대의 관련 테스트(Session A: `test_nia_ingredient_matching_stage.py`,
   Session B: `test_product_taxonomy_normalizer.py` 등 product 매칭 테스트)가 여전히
   통과하는지 서로 확인 후 진행

## Merge Order

1. Session B가 현재 로컬에 쌓인 미커밋 Claim RAG 관련 파일(§13 목록과 동일)을
   `feature/rag-pipeline`에 먼저 커밋·푸시한다(Session A의 시작점을 만들기 위함 —
   아래 "Git 작업 구조" 참고). **이 handoff 문서만으로는 그 파일들이 아직 Session A의
   worktree에 없다.**
2. Session A는 그 커밋을 포함한 `origin/feature/rag-pipeline`에서 `feature/claim-rag`를 분기한다
3. Session A는 `feature/claim-rag`에서 작업하며 주기적으로 `origin/feature/rag-pipeline`을
   merge(또는 rebase 대신 merge — 이 저장소 관례상 공유 브랜치에 force-push 금지)해 최신
   Session B 변경을 반영한다
4. 두 세션 다 **자기 소유 파일만** 건드리므로 실제 병합 충돌은 거의 없어야 한다 — 충돌이
   나면 CLAUDE.md 규칙 19의 "충돌이 나면 혼자 해결하지 않는다" 절차를 따른다(공용 파일
   충돌 시 특히)
5. `feature/claim-rag` → `feature/rag-pipeline` PR은 Session A의 Definition of Done
   충족 후, squash merge로 진행(저장소 관례)

## Git 작업 구조 (제안, 아직 실행 안 함)

```bash
# Session B가 먼저(이 handoff 이후 별도 승인 시):
git add <§13에 나열된 미커밋 파일들>
git commit -m "feat(data): NIA claim pipeline 1차 완료 (Session A 인계 지점)"
git push origin feature/rag-pipeline

# 그 다음 Session A가:
git worktree add ../skincare-claim-rag -b feature/claim-rag origin/feature/rag-pipeline
```

**Base branch는 `feature/rag-pipeline`을 추천한다** — `main`은 이 세션의 모든
Claim/Evidence 작업이 아직 반영 안 됐고(별도 PR 대기), `feature/data-pipeline`은
96커밋 뒤처진 오래된 브랜치라 base로 부적절하다.
