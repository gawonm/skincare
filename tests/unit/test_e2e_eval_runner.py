"""`e2e_eval_runner._QUERIES` 구성 자체에 대한 최소 점검.

실제 실행 검증(ChatService/LLM/DB 호출)은 이 테스트의 범위 밖이다 - 결과는
docs/data/E2E_EVAL_REPORT.md가 담당한다.
"""

from data.scripts.e2e_eval_runner import _QUERIES


def test_fifteen_scenarios_with_unique_numbers() -> None:
    numbers = [number for number, _, _ in _QUERIES]
    assert numbers == list(range(1, 16))


def test_every_query_is_non_empty() -> None:
    assert all(query.strip() for _, _, query in _QUERIES)


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
