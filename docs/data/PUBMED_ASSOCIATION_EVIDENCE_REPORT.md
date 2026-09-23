# Chitin–Beta-Glucan Association Evidence 반영 보고서

## 목적

NIA Case가 제안한 키틴의 Evidence 검색 결과를 점검한 결과, 자동 선별 후보 두 건은 키틴 단독
연구가 아니라 Chitin–Beta-Glucan 복합물 연구였다. 이를 키틴 단독 근거로 연결하지 않고 복수 성분
association으로 보존한다.

## 반영 자료

| PMID | 범위 | 표준 성분 연결 |
| --- | --- | --- |
| [19743936](https://pubmed.ncbi.nlm.nih.gov/19743936/) | 2.5% chitin-glucan 제형의 발 건조증 연구 | Chitin + Beta-Glucan |
| [19099547](https://pubmed.ncbi.nlm.nih.gov/19099547/) | 0.5~2% 및 1.5% chitin-glucan 제형의 피부 보습·장벽 연구 | Chitin + Beta-Glucan |

- Chitin: `c4399298-58ae-4df1-8f6b-eeaae7a98ce3`
- Beta-Glucan: `94c4bad8-5f3b-47c9-8044-543ec8f971a7`
- Chitosan은 별도 성분이므로 연결하지 않았다.
- 두 청크 모두 `formulation_type=combination_formulation`이며 Agent에서는 `ASSOCIATION`으로 전달된다.
- 따라서 키틴 또는 베타글루칸의 단독 효능 Claim을 검증하는 Citation으로 사용하지 않는다.

## 구현 및 재현

검수 입력은 `data/manual_review/pubmed_association_reviews.json`, 생성기는
`data/scripts/pubmed_association_bundle.py`다. 두 파일은 `data/*` ignore 정책 때문에 전달 시
명시적으로 포함해야 한다.

```powershell
uv run python -m data.scripts.pubmed_association_bundle --dry-run
uv run python -m data.scripts.pubmed_association_bundle
uv run python -m data.scripts.compact_evidence_loader `
  --bundles data/outputs/evidence_coverage/pubmed_association_bundle.jsonl `
  --dsn postgresql+asyncpg://app:app@localhost:5432/skincare_reference_20260923_v5_2
uv run python -m data.scripts.compact_evidence_loader `
  --bundles data/outputs/evidence_coverage/pubmed_association_bundle.jsonl `
  --dsn postgresql+asyncpg://app:app@localhost:5432/skincare_reference_20260923_v5_2 `
  --execute
```

## 검증 결과

- association bundle: 문서 2, 청크 2, 성분 링크 4
- v5_2: `evidence_document=128`, `evidence_chunk=8487`,
  `evidence_chunk_ingredient=8508`
- BGE-M3 1,024차원 embedding NULL/비정상: 0
- 중복 `chunk_id`: 0
- Evidence link orphan: 0
- v5_2 dump를 별도 빈 DB에 복원해 같은 수치와 Alembic revision `9f4c2a7d8e61`을 확인했다.

## Evidence가 없는 나머지 Case 성분

알로에베라잎즙가루, 안디로바씨오일, 고추냉이뿌리추출물, 미네랄솔트는 현재 정확한 표준 성분 ID에
연결할 직접 Evidence를 확보하지 못했다. 이름이 비슷한 유도체나 계열 자료를 대신 연결하지 않으며,
해당 추천은 `Claim 기반`으로만 표시하고 Evidence 제한을 별도로 유지한다.
