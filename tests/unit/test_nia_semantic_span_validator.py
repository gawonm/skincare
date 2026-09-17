"""LLM/DB 호출 없이 `NiaSemanticSpanValidator`의 판정만 검증한다.

statement dict는 `nia_pilot_runner.NiaPilotRecordProcessor._build_statements`가 만드는
형태(스키마 필드명과 동일)를 그대로 흉내 낸다.
"""

from data.scripts.nia_semantic_span_validator import NiaSemanticSpanValidator


def _span(quote: str) -> dict:
    return {
        "json_path": "$.chain_of_thought[0].content",
        "quote": quote,
        "start": 0,
        "end": len(quote),
    }


def _ingredient_effect_claim(raw_name: str, raw_name_ko: str, object_: str, quote: str) -> dict:
    return {
        "statement_id": "T-S001",
        "statement_type": "ingredient_effect_claim",
        "source_spans": [_span(quote)],
        "subject": {
            "raw_name": raw_name,
            "raw_name_ko": raw_name_ko,
            "ingredient_id": None,
            "matching_status": "unresolved",
        },
        "object": object_,
        "concentration_raw": None,
    }


class TestNiaSemanticSpanValidator:
    def test_same_ingredient_same_meaning_passes(self) -> None:
        stmt = _ingredient_effect_claim(
            "NIACINAMIDE",
            "나이아신아마이드",
            "미백",
            "나이아신아마이드는 멜라닌 생성을 억제해 미백에 도움을 줍니다.",
        )
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict == "ok"

    def test_same_ingredient_different_predicate_should_not_pass(self) -> None:
        """사용자가 지적한 핵심 결함 재현: 성분명만 같고 주장 내용(효과 vs 자극)은 다름.

        ingredient name overlap을 'ok'의 충분조건으로 쓰지 않는지 확인하는 회귀 테스트.
        """
        stmt = _ingredient_effect_claim(
            "NIACINAMIDE",
            "나이아신아마이드",
            "미백",
            "나이아신아마이드는 일부 피부에서 자극을 유발할 수 있다.",
        )
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict != "ok", (
            "성분명만 일치하고 claim의 predicate(미백 vs 자극)는 다른데 'ok'로 통과됨 — "
            "ingredient name overlap이 semantic validation의 충분조건으로 쓰이고 있음"
        )

    def test_different_ingredient_similar_wording_should_not_pass(self) -> None:
        """다른 성분 + 서술 문형이 비슷하면 predicate token overlap만으로 통과할 위험."""
        stmt = _ingredient_effect_claim(
            "RETINOL",
            "레티놀",
            "미백",
            "나이아신아마이드는 미백에 도움을 줍니다.",
        )
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict != "ok", (
            "quote가 언급하는 성분(나이아신아마이드)과 statement의 subject(레티놀)가 다른데 "
            "predicate 단어(미백)가 겹친다는 이유로 통과됨 — 성분 identity를 확인하지 않음"
        )

    def test_usage_statement_matching_quote_passes(self) -> None:
        stmt = {
            "statement_id": "T-S002",
            "statement_type": "usage_instruction",
            "source_spans": [_span("아침저녁으로 순한 약산성 클렌저를 사용해 세안합니다.")],
            "action_id": "A001",
            "action": "세안/클렌징(약산성)",
            "time_of_day": ["morning", "evening"],
            "frequency": None,
            "ingredient_ids": [],
        }
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict == "ok"

    def test_precaution_with_unrelated_quote_is_rejected_by_subject_alone(self) -> None:
        """precaution의 semantic_content는 `subject`만 쓰고 `relation`은 포함하지
        않는다. `relation`(avoid/possible_irritation)은 영문 enum 값이라 한국어 quote에
        substring으로 나타나지 않으므로, 토큰으로 추가하면 모든 precaution 점수를
        일괄적으로 낮춰 false reject를 늘릴 위험이 있다(경험적으로 확인). 실측 결과
        subject만으로도 이미 무관한 quote를 정확히 걸러내므로 relation을 추가하지
        않았다 — 이 테스트가 그 근거다.
        """
        stmt = {
            "statement_id": "T-S004",
            "statement_type": "precaution",
            "source_spans": [_span("레티놀은 피부 탄력에 도움을 줍니다.")],
            "subject": "자외선 주의",
            "relation": "avoid",
        }
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict == "mismatch"

    def test_contextual_factor_wrong_span_is_rejected(self) -> None:
        """실제 pilot에서 관찰된 오복원 사례: factor/details와 무관한 문장이 quote로 복원됨."""
        stmt = {
            "statement_id": "T-S003",
            "statement_type": "contextual_factor",
            "source_spans": [_span("토너로 피부결을 정돈한 뒤 세럼을 이마에 도포합니다.")],
            "factor_raw": "헤어 제품",
            "details_raw": "헤어 제품 주의",
            "priority_raw": 1,
            "causal_link_status": "not_established",
        }
        result = NiaSemanticSpanValidator().check(stmt)
        assert result.verdict in ("mismatch", "low_confidence")
