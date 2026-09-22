# E2E Evaluation — main sync 전/후 비교

## PRE_MAIN_E2E

- commit SHA: `dc0e06a` (`feat(data): Notion E2E 15개 시나리오를 실제 ChatService로 read-only 평가`)
- Pass/Fail: **2 / 13**
- 산출물(보존): `data/outputs/evidence_coverage/e2e_eval_results_pre_main_sync.csv`,
  `docs/data/E2E_EVAL_REPORT_pre_main_sync.md`

## MAIN_SYNC

| 항목 | 값 |
| --- | --- |
| origin/main SHA(당시) | `fd5f61d` (`Integration/nia case query planning (#64)`) |
| feature HEAD(merge 전) | `dc0e06a` |
| merge commit | `48f6761` (`Merge remote-tracking branch 'origin/main' into feature/data-evidence-coverage`, fast strategy `ort`) |
| conflicts | **없음** |
| 반영된 main 커밋 | `fd5f61d`, `4735080`, `fdeed93`, `107f0fa` (4건) |
| tests | 관련 유닛 테스트 15/15 통과(`test_retriever_eval.py`, `test_e2e_eval_runner.py`, `test_evidence_bundle_embedder.py`, `test_evidence_db_write_dry_run.py`). 병합으로 들어온 agent 테스트 22건 중 21건 통과, 1건 실패(`test_agent_assembly.py::test_local_embedding_settings_assemble_a_chat_service`) - `settings.database`(로컬 개발 DB)에 상품 taxonomy 시드 데이터가 없어서 나는 환경 의존 실패이며, `git blame` 확인 결과 이 merge로 새로 들어온 테스트(`fdeed93`)라 이번 merge 충돌·회귀와는 무관 |

merge로 들어온 주요 변경: `agent/query_planning.py`(신규, NIA case 질의 분해),
`backend/services/agent_assembly.py`(신규, 앱 기동 시 Agent 조립),
`agent/nodes.py`/`agent/prompts.py`/`agent/rag_workflow.py`/`agent/schemas.py` 수정.
`docs/agent/RAG_YK/2026-09-22_INGREDIENT_ALIAS_RESOLUTION_PLAN.md`(신규)도
포함됐는데, 이번 E2E가 발견한 "BHA" 성분 오추천 문제를 다루려는 **계획
문서**로 보인다(아직 구현 코드는 아님 - 실제로 #11 결과는 변화 없었다).

## POST_MAIN_E2E

- Pass/Fail: **2 / 13** (동일)
- Failure breakdown: DATA 3 / AGENT-RETRIEVAL 1 / AGENT-REASONING 9 / BACKEND-REPOSITORY 0 / PRODUCT-DATA 0 / UNKNOWN 0 (동일)
- 산출물: `data/outputs/evidence_coverage/e2e_eval_results_post_main_sync.csv`,
  `e2e_eval_results.csv`(최신본으로 교체 - 아래 "최종 상태" 참고)

### pre-main 대비 달라진 케이스

| # | 변화 | 해석 |
| --- | --- | --- |
| **#1** 피지 좁쌀 여드름 | citation 0건 -> **1건**(살리실릭애씨드 CIR Clinical Studies) 성공. 나이아신아마이드/병풀추출물은 여전히 반려 | 부분 개선. verdict는 여전히 FAIL(3성분 중 1성분만 성공) |
| **#4** 레티놀 주의사항 | citation 1건 -> **2건**(같은 CIR 문서의 Conclusion+Discussion) | PASS 유지, 더 완전해짐 |
| **#6** 3-O-Ethyl Ascorbic Acid 비교 | 이전: 두 target을 한 번에 묶어 검색해 5건 전부 Ascorbic Acid로 나옴. 이후: 유도체 단독으로 분리 검색돼 **0건** 반환 | DB 재확인 결과 이 유도체의 유일한 evidence link는 CIR/PubMed가 아니라 대만 MFDS `restricted_ingredient` 항목(효능 근거 아님)이다. `query_planning.py`(main에서 새로 들어온 NIA case 질의 분해 로직)가 성분별 검색을 분리하면서, efficacy 질의에 이 항목이 안 잡히는 게 **오히려 정확한 방향**으로 보인다 - verdict는 FAIL 유지(질문 의도인 "같은 효과인지 비교"에는 답 못함)이지만 분류를 AGENT-RETRIEVAL로 유지하고 근거를 갱신 |
| **#14** 레티놀 vs 바쿠치올 | 이전: Retinol 쪽 citation 1건 성공. 이후: **양쪽 다 반려**(citation 0) | 동일한 CIR chunk인데 이번엔 반려됨 - critical blocker 1(applicability 대량 반려)이 이 케이스에서는 오히려 더 심해짐 |
| 그 외 10개 케이스(#2,3,5,7,8,9,10,11,12,13,15) | 변화 없음 | critical blocker 1(applicability 반려), 2(BHA), 3(후속질문 맥락 단절) 전부 동일하게 재현됨 |

### Critical blocker 재현 확인(main sync 후에도 동일)

1. **Evidence applicability 대량 반려** — 여전히 재현(#14는 오히려 악화, #1은 부분 개선)
2. **"BHA" ingredient_master literal 항목** — 완전히 동일하게 재현(`e48d0911-...`,
   레티놀 세럼 5건 그대로 추천됨). merge에 포함된
   `INGREDIENT_ALIAS_RESOLUTION_PLAN.md`는 계획 문서일 뿐 아직 구현되지 않음
3. **후속 질문 맥락 단절** — 완전히 동일하게 재현(#12 직후 #15 실행해도
   동일한 무관 NIA case로 처리됨)

### READY_FOR_TEAM_HANDOFF

`NO` (main sync 전과 동일한 판정)

pass/fail 비율과 critical blocker 3건 모두 main sync 전후로 변하지 않았다.
#6에서 나타난 변화는 개선으로 해석되지만 verdict 자체는 그대로 FAIL이고,
#14는 오히려 악화됐다 - 전체적으로 이번 main sync가 E2E 결과를 유의미하게
바꾸지는 않았다.

## 최종 상태(파일 정리)

- `e2e_eval_results.csv` / `E2E_EVAL_REPORT.md` = **post-main-sync 결과**로 교체(가장 최신 코드 기준)
- `e2e_eval_results_pre_main_sync.csv` / `E2E_EVAL_REPORT_pre_main_sync.md` = main sync 전 결과(보존)
- `e2e_eval_results_post_main_sync.csv` = post-main 결과 사본(위 표의 근거, `e2e_eval_results.csv`와 동일 내용)
- `e2e_eval_raw.json` / `e2e_eval_raw_post_main_sync.json`은 각각 1.6MB로 500KB
  제한을 넘어 로컬에만 두고 git에는 커밋하지 않았다(이전과 동일 정책)
