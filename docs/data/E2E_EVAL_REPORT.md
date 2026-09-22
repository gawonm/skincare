# E2E 품질 평가 리포트 — NIA → Evidence → Product

> **이 문서는 `feature/data-evidence-coverage`에 `origin/main`을 merge(commit
> `48f6761`)한 뒤 재실행한 결과다.** merge 전 결과는
> `E2E_EVAL_REPORT_pre_main_sync.md` / `e2e_eval_results_pre_main_sync.csv`에
> 보존돼 있고, 두 결과의 차이는 [E2E_EVAL_MAIN_SYNC_COMPARISON.md](E2E_EVAL_MAIN_SYNC_COMPARISON.md)에
> 정리했다. **pass/fail 비율과 3개 critical blocker는 main sync 전후로
> 동일하다** - 아래 표는 merge 후 재실행 기준으로 갱신됐다.

## 범위와 방법

canonical `skincare_reference_2026-09-22_v5.dump`를 별도 read-only 평가
DB(`evidence_e2e_eval`)에 복원해, [Notion "E2E 품질 평가 시나리오 — NIA →
Evidence → Product"](https://app.notion.com/p/E2E-NIA-Evidence-Product-3e2f7cbca87081ac8198df51633c4345)의
15개 시나리오를 **실제 ChatService(LangGraph) 전체 경로**로 실행했다.
`tests/agent/interactive_two_layer_rag_cli.py::InteractiveTwoLayerRagCli`를
그대로 재사용했다(이미 NIA case 검색·성분 해석·Evidence 검색·상품 검색·
claim 추출 각 단계를 기록하는 `TwoLayerFlowTraceCollector`가 구현돼 있어
새로 만들지 않았다). Agent/Backend/schema 코드는 한 줄도 고치지 않았고,
추가 Evidence 수집도 하지 않았다. 실제 OpenAI API 호출이 발생했다(사용자
설정 키, 비용 발생).

13번 시나리오는 Notion 원문이 "이 성분은..."으로 일반화돼 있어, 실제 실행을
위해 Notion이 명시한 "Evidence sparse ingredient" 조건에 맞는 구체
성분(감마-터피넨, evidence 2건)을 대입했다. 15번은 Notion 지시대로 12번
바로 다음 턴으로 같은 대화방에서 실행해 "직전 추천 제품" 참조를 검증했다.

DB는 읽기 전용 쿼리만 발생했다(대화 히스토리/체크포인터는 개발용 in-memory
구현). 평가 종료 후 `evidence_e2e_eval`은 drop했다.

## 결과 요약

**15 cases / 2 pass / 13 fail**

| # | 시나리오 | 판정 | 분류 |
| --- | --- | --- | --- |
| 1 | 피지 좁쌀 여드름 | FAIL | AGENT-REASONING |
| 2 | 나이아신아마이드 피지 | FAIL | AGENT-REASONING |
| 3 | 레티놀 주름 이유 | FAIL | AGENT-REASONING |
| 4 | 레티놀 주의사항 | **PASS** | - |
| 5 | 비타민C 미백 | FAIL | AGENT-REASONING |
| 6 | 3-O-Ethyl Ascorbic Acid 비교 | FAIL | AGENT-RETRIEVAL |
| 7 | 트라넥사믹 vs 나이아신아마이드 | FAIL | AGENT-REASONING |
| 8 | 판테놀 진정 | FAIL | AGENT-REASONING |
| 9 | 병풀 성분 동일 여부 | FAIL | AGENT-REASONING |
| 10 | 히알루론산 제품 추천 | FAIL | DATA |
| 11 | BHA 제품 추천 | FAIL | **DATA(critical)** |
| 12 | 살리실산 여드름 제품 추천 | **PASS** | - |
| 13 | sparse evidence 성분 | FAIL | DATA |
| 14 | 레티놀 vs 바쿠치올 | FAIL | AGENT-REASONING |
| 15 | 추천 이유 재질문 | FAIL | **AGENT-REASONING(critical)** |

**Failure breakdown**: DATA 3 / AGENT-RETRIEVAL 1 / AGENT-REASONING 9 /
BACKEND-REPOSITORY 0 / PRODUCT-DATA 0 / UNKNOWN 0

## 🔴 Critical blocker 1 — Evidence Applicability 단계가 유효 근거를 대량 반려

9개 시나리오(#1 일부, 2, 3, 5, 7, 8, 9 일부, 14)에서 공통 패턴이 나타났다:

1. NIA case 검색(해당되는 경우) — 정상
2. 성분 선택 및 `ingredient_id` canonical resolution — 정상
3. Evidence 검색 — **정상**(target_ids 정확히 매칭된 chunk 5~8건 반환,
   예: 시나리오 2는 정확히 sebum_control 주제인 `PMID:16766489`까지 검색됨)
4. 최종 답변 생성 직전 단계에서 검색된 evidence 전체가
   `"검색 자료의 인용문과 적용 조건을 확인하지 못해 답변에서 제외했습니다"`로
   **전부 반려**되어 `citations=0`, `UnresolvedKind.NO_EVIDENCE`로 끝남

즉 검색(retrieval)은 정확한데, 그 뒤 인용문·적용조건을 검증하는
`EvidenceApplicabilityEvaluator`(또는 answer generator의 citation 검증 로직)
단계에서 대부분의 유효 evidence가 탈락한다. 성공한 케이스(#1의 살리실릭애씨드,
#4)는 공통적으로 CIR "Conclusion"/"Clinical Studies" 성격의 짧고 명확한
문장을 인용했다 — PubMed abstract 근거는 이 세션에서 단 한 번도 citation에
성공하지 못했다. PubMed abstract 형식(초록 전문)과 CIR Conclusion 형식(요약
결론 문장)의 차이가 이 단계의 통과 여부와 상관관계가 있어 보인다. main sync
전에는 #14의 Retinol 쪽도 성공했었지만, main sync 후 재실행에서는 동일
chunk임에도 반려로 바뀌었다(재현성이 완벽하지 않다는 뜻이기도 하다) - 자세한
전/후 비교는 [E2E_EVAL_MAIN_SYNC_COMPARISON.md](E2E_EVAL_MAIN_SYNC_COMPARISON.md)
참고.

**코드는 고치지 않았다.** 이 단계(`EvidenceApplicabilityEvaluator` 등)를
Agent 파트가 직접 확인해야 한다.

## 🔴 Critical blocker 2 — "BHA"가 ingredient_master에 별도 실체로 존재

시나리오 11에서 "BHA"가 `CommonIngredientAliasMapper`가 정의한 모호
성분군(살리실릭애씨드/베타인살리실레이트)으로 처리되지 않고, **`ingredient_master`에
`BHA`/`비에이치에이`라는 별도의 실제 row(ingredient_code 718, id
`e48d0911-3e9a-4aa4-b013-8b10c3931548`)로 존재**해 exact match로 즉시
확정됐다. 이 literal `BHA` ingredient에는 실제로 `product_ingredient`
confirmed 링크가 8건 있고(제품 성분표의 원문 토큰이 구체 화학명으로 분해되지
않고 "BHA" 그대로 남은 것으로 추정), 그중 하나가 추천 1순위로 나온 "썸바이미
레티놀 인텐스 리액티베이팅 세럼"이다 — DB로 직접 재확인한 결과 이 제품은
Salicylic Acid/Betaine Salicylate가 전혀 없고 literal `BHA` 링크 1건만 갖고
있었다. **사용자에게는 완전히 무관한 레티놀 세럼이 "BHA 제품"으로
추천된다.**

분류는 DATA(ingredient_master 시드 데이터에 "BHA"라는 미분해 항목이 존재)로
했지만, 근본적으로는 ingredient 해석 파이프라인이 `CommonIngredientAliasMapper`의
모호 판정보다 DB exact match를 먼저/대신 적용하는 구조 문제와도 맞닿아 있다
- 어느 쪽이 진짜 근본 원인인지는 Agent 파트 확인이 필요하다.

## 🔴 Critical blocker 3 — 후속 질문이 직전 턴을 전혀 참조하지 못함

시나리오 15("이 제품을 추천한 이유가 뭐야?")를 시나리오 12(살리실산 제품
추천) 바로 다음 턴으로, 같은 대화방·같은 `InteractiveTwoLayerRagCli`
인스턴스에서 실행했다. 정상이라면 "이 제품"이 12번에서 추천한 살리실릭애씨드
제품을 가리켜야 한다. 실제로는:

- NIA case 검색이 **새로** 실행돼 완전히 무관한 사례(`COT_WHT_F_O30_01132`,
  37세 색소침착 상담)가 매칭됐다.
- 그 사례에서 언급된 무관한 성분(쑥추출물, 1,10-데칸다이올 등)을 기준으로
  다시 검색해, 12번과 전혀 다른 제품 13건을 새로 제시했다.

대화 맥락(직전 턴의 추천 결과)을 후속 질문 처리에 전혀 연결하지 못하는
것으로 보인다 — 이 시나리오가 원래 검증하려던 "추천 이유 설명" 기능 자체가
동작하지 않는다.

## 통과한 2개 시나리오

- **#4 레티놀 주의사항**: precaution 질의에 CIR Conclusion 청크를 정확히
  인용했고, efficacy 전용 논문으로 안전성을 과장하지 않았다.
- **#12 살리실산 여드름 제품 추천**: `ingredient_id`가 정확히 resolve됐고,
  1위 추천 제품("스킨푸드 Pantothenic 워터 Parsley 토너")이 실제로 Salicylic
  Acid를 confirmed 링크로 갖고 있음을 DB에서 직접 재확인했다(나머지 4건은
  개별 검증하지 않음).

## 안전장치가 지켜진 부분(실패했지만 위험하지 않은 경우)

- **#6, #14**: 원형-유도체(Ascorbic Acid ↔ 3-O-Ethyl Ascorbic Acid), 성분 간
  비교(Retinol vs Bakuchiol)에서 **허위로 근거를 귀속시키거나 임의의
  "승자"를 지어내지 않았다.** 근거가 불완전하면 그 항목만 조용히 "확인 불가"
  처리했다 — 과장된 답변보다는 안전한 실패 방식이다.
- **#13**: sparse-evidence 성분에 대해 확신 있는 답을 지어내지 않았다.
- **#9, #10**: family 용어("병풀", "히알루론산")를 임의로 하나의
  `ingredient_id`로 확정하지 않고 보수적으로 처리했다(다만 #10은 그 결과
  요청 자체가 중단됨 - 완료 기준은 못 채웠다).

## 산출물

- `data/outputs/evidence_coverage/e2e_eval_results.csv` (15 rows, Notion
  기록 템플릿 필드 기준)
- `data/outputs/evidence_coverage/e2e_eval_raw_post_main_sync.json` (각
  케이스의 전체 `ChatTurnOutput` + 단계별 trace 원본 - 재검토용. 1.6MB로
  pre-commit의 500KB 제한을 넘어 로컬에만 남기고 git에는 커밋하지 않았다.
  위 critical blocker 3건의 구체적 근거(PMID, ingredient_id, product_id,
  NIA case_id 등)는 전부 이 문서에 직접 옮겨 적었으므로 원본 없이도
  재현·검증 가능하다)
- `docs/data/E2E_EVAL_REPORT.md` (이 문서, main sync 후 최신 기준)
- `docs/data/E2E_EVAL_MAIN_SYNC_COMPARISON.md` (main sync 전/후 비교, commit
  SHA·conflict 여부·달라진 케이스 정리)
- `data/outputs/evidence_coverage/e2e_eval_results_pre_main_sync.csv` /
  `docs/data/E2E_EVAL_REPORT_pre_main_sync.md` (main sync **전** 결과, 보존)

## 판정

`READY_FOR_TEAM_HANDOFF: NO`

15개 중 13개가 실패했고, 그중 3건은 critical(evidence applicability 대량
반려, BHA 오추천, 후속 질문 맥락 단절)로 분류된다. Evidence
DB(document/chunk/link)와 canonical 성분 resolution 자체는 정확했다는 점은
확인됐으므로(이전 단계 retriever 평가와 이번 flow trace 모두 일관됨),
**문제는 거의 전부 Evidence 검색 이후 단계(applicability 평가, 후속 질문
맥락 처리)와 ingredient_master 시드 데이터(BHA 항목)에 있다.** 코드 수정은
하지 않았고, Agent 파트의 확인이 필요하다.
