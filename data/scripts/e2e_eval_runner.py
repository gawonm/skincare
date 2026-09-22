"""Notion "E2E 품질 평가 시나리오 — NIA → Evidence → Product" 15개를 실제
ChatService(LangGraph)로 실행해 원시 결과를 JSON으로 남기는 진입점.

`tests/agent/interactive_two_layer_rag_cli.py::InteractiveTwoLayerRagCli`를
그대로 재사용한다 - Agent/Backend 코드를 한 줄도 고치지 않는다. DB는 읽기
전용 쿼리만 발생한다(대화 히스토리·체크포인터는 개발용 in-memory 구현이라
DB에 쓰지 않는다). 판정(PASS/FAIL, 실패 분류)은 여기서 자동으로 매기지
않는다 - Notion 템플릿 자체가 사람이 답변 텍스트를 읽고 채우는 항목을
포함하므로, 이 스크립트는 원시 데이터 수집까지만 하고 최종 CSV/리포트는
그 데이터를 사람이 검토해 작성한다.

사용법:
    uv run python -m data.scripts.e2e_eval_runner --dsn postgresql+asyncpg://app:app@localhost:5432/evidence_e2e_eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from core.config import AgentSettings, RagRetrievalSettings, settings
from core.database import Database, DatabaseConfig
from tests.agent.interactive_two_layer_rag_cli import (
    CliDisplayMode,
    InteractiveTwoLayerRagCli,
    TwoLayerProductTaxonomyProvider,
)

_DEFAULT_RAW_OUTPUT = Path("data/outputs/evidence_coverage/e2e_eval_raw.json")

# config.yaml에 agent.retrieval 블록이 없어 free_text_min_vector_similarity가 None이고,
# InteractiveTwoLayerRagCli가 그대로 RuntimeError를 던진다(retriever_eval.py에서 이미 겪은
# 문제와 동일 - 이 프로젝트에 정해진 production 값 자체가 없다). config.yaml 파일은 고치지
# 않고, 이 프로세스의 메모리 상 settings 객체만 retriever_eval.py와 같은 값(0.3)으로
# 덮어써 실행한다 - 다른 프로세스/개발 환경에는 영향 없다.
settings.agent = AgentSettings(
    chat=settings.agent.chat,
    embedding=settings.agent.embedding,
    reranker=settings.agent.reranker,
    retrieval=RagRetrievalSettings(
        free_text_min_vector_similarity=0.3,
        rrf_k=settings.agent.retrieval.rrf_k,
        rerank_candidate_limit=settings.agent.retrieval.rerank_candidate_limit,
    ),
)

# Notion "E2E 품질 평가 시나리오 — NIA → Evidence → Product" 15개(2026-09-22 확인).
# 13번은 원문이 "이 성분은..."으로 일반화돼 있어 실제 실행을 위해 구체 성분(감마-터피넨,
# evidence 2건뿐인 sparse 사례)을 대입했다 - 임의 창작이 아니라 Notion "예상 성분/개념"란의
# "Evidence sparse ingredient"에 맞춰 DB에서 실제로 근거가 희소한 성분을 골랐다.
_QUERIES: list[tuple[int, str, str]] = [
    (1, "피지 좁쌀 여드름", "피지가 많고 좁쌀 여드름이 나는데 뭘 써야 해?"),
    (2, "나이아신아마이드 피지", "나이아신아마이드는 피지 조절에 실제로 효과 있어?"),
    (3, "레티놀 주름 이유", "레티놀은 주름에 왜 좋은 거야?"),
    (4, "레티놀 주의사항", "레티놀 처음 쓰는데 주의할 점 알려줘"),
    (5, "비타민C 미백", "비타민C는 미백에 효과 있어?"),
    (6, "3-O-Ethyl Ascorbic Acid 비교", "3-O-Ethyl Ascorbic Acid도 비타민C랑 같은 효과야?"),
    (
        7,
        "트라넥사믹 vs 나이아신아마이드",
        "트라넥사믹애씨드랑 나이아신아마이드 중 미백에는 뭐가 달라?",
    ),
    (8, "판테놀 진정", "판테놀은 민감한 피부 진정에 도움 돼?"),
    (9, "병풀 성분 동일 여부", "병풀 성분은 다 같은 거야?"),
    (10, "히알루론산 제품 추천", "히알루론산 들어간 제품 추천해줘"),
    (11, "BHA 제품 추천", "BHA 제품 추천해줘"),
    (12, "살리실산 여드름 제품 추천", "살리실산 들어간 여드름 제품 추천해줘"),
    (13, "sparse evidence 성분", "감마-터피넨 성분은 피부 효능 논문 근거가 얼마나 있어?"),
    (14, "레티놀 vs 바쿠치올", "레티놀과 바쿠치올 중 뭐가 더 나아?"),
    # 15번은 12번 바로 다음 턴으로 같은 대화방에서 실행해 "직전 추천 제품"을 참조한다.
    (15, "추천 이유 재질문", "이 제품을 추천한 이유가 뭐야?"),
]


def _flow_snapshot_dict(snapshot) -> dict:
    return json.loads(snapshot.model_dump_json())


async def _run_single_case(
    database: Database, product_taxonomy, number: int, case_id: str, query: str
) -> dict:
    cli = InteractiveTwoLayerRagCli(
        display_mode=CliDisplayMode.COMPACT,
        database=database,
        product_taxonomy=product_taxonomy,
    )
    try:
        result = await cli.handle_message(query)
        return {
            "number": number,
            "case_id": case_id,
            "query": query,
            "turn_output": json.loads(result.turn_output.model_dump_json()),
            "flow_trace": _flow_snapshot_dict(cli._flow_trace.snapshot()),
        }
    finally:
        await cli.close()


async def _run_case_pair_15_follows_12(
    database: Database, product_taxonomy, case12: tuple[int, str, str], case15: tuple[int, str, str]
) -> tuple[dict, dict]:
    """12번 제품 추천 -> 같은 방에서 15번 '추천 이유' 후속 질문."""
    cli = InteractiveTwoLayerRagCli(
        display_mode=CliDisplayMode.COMPACT,
        database=database,
        product_taxonomy=product_taxonomy,
    )
    try:
        n12, id12, q12 = case12
        result12 = await cli.handle_message(q12)
        record12 = {
            "number": n12,
            "case_id": id12,
            "query": q12,
            "turn_output": json.loads(result12.turn_output.model_dump_json()),
            "flow_trace": _flow_snapshot_dict(cli._flow_trace.snapshot()),
        }
        n15, id15, q15 = case15
        result15 = await cli.handle_message(q15)
        record15 = {
            "number": n15,
            "case_id": id15,
            "query": q15,
            "turn_output": json.loads(result15.turn_output.model_dump_json()),
            "flow_trace": _flow_snapshot_dict(cli._flow_trace.snapshot()),
            "preceding_case": id12,
        }
        return record12, record15
    finally:
        await cli.close()


async def _run(dsn: str) -> list[dict]:
    database = Database(DatabaseConfig(url=dsn))
    try:
        product_taxonomy = await TwoLayerProductTaxonomyProvider(database.session_factory).load()
        records: list[dict] = []
        case12 = next(c for c in _QUERIES if c[0] == 12)
        case15 = next(c for c in _QUERIES if c[0] == 15)
        for number, case_id, query in _QUERIES:
            if number == 12:
                record12, record15 = await _run_case_pair_15_follows_12(
                    database, product_taxonomy, case12, case15
                )
                records.append(record12)
                records.append(record15)
            elif number == 15:
                continue  # case 12 처리 시 함께 실행됨
            else:
                records.append(
                    await _run_single_case(database, product_taxonomy, number, case_id, query)
                )
        return records
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--raw-output", type=Path, default=_DEFAULT_RAW_OUTPUT)
    args = parser.parse_args()

    records = asyncio.run(_run(args.dsn))
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    with args.raw_output.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(records)} records to {args.raw_output}")


if __name__ == "__main__":
    main()
