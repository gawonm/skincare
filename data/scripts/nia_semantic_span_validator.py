"""복원된 source_spans의 quote가 '원문의 literal substring'이라는 것과 '그 statement의
실제 근거'라는 것은 다른 문제다. `NiaSourceSpanBuilder`는 전자만 보장한다. 이 클래스는
LLM 호출 없이(비용 0, 완전 재현 가능) statement의 의미 내용(성분명 + predicate 둘 다)이
최종 quote 안에 실제로 등장하는지를 substring 기준으로 확인한다.

과학적 근거 검증이 아니다 — "이 quote가 이 statement가 말하는 대상/내용과 관련이
있어 보이는가"만 본다. LLM semantic validator를 별도로 쓰는 방안도 검토했지만, pilot
규모에서도 39건 × statement당 추가 호출이 필요해 비용·지연이 배로 늘고 재현성이
떨어진다 — deterministic 신호로 먼저 걸러내고, 남는 애매한 것만 review_queue로 보내는
쪽이 이번 단계에는 더 현실적이라고 판단했다.

중요: 성분명이 quote에 있다는 것만으로 통과시키지 않는다. `_semantic_content`가 성분명과
predicate(효과/주의/사용법/맥락)를 함께 담은 텍스트를 만들고, 그 안의 각 의미 토큰이
quote 안에 substring으로 등장하는 "비율"을 점수로 쓴다 — 성분명만 맞고 predicate가
다르면 점수가 낮게 나온다. 정확 일치(Jaccard) 대신 substring 포함 여부를 쓰는 이유는
한국어 조사가 명사 뒤에 바로 붙기 때문이다("미백" 주장이 원문에 "미백에"로 나오면
정확 토큰 일치로는 놓친다) — 그렇다고 `difflib` 문자열 유사도를 쓰면 조사·어미 같은
공통 문법 요소만으로도 무관한 문장이 점수를 받아버리는 문제가 실측으로 확인돼 빼냈다.
"""

import re

_HANGUL_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# 이 미만이면 statement와 quote가 사실상 무관하다고 본다(semantic mismatch).
_STRONG_MISMATCH_THRESHOLD = 0.2
# 이 미만이면(그러나 mismatch보다는 크면) 애매하다고 보고 review로만 보낸다.
_ACCEPT_THRESHOLD = 0.5


class NiaSemanticSpanCheckResult:
    def __init__(self, score: float, verdict: str) -> None:
        self.score = score
        self.verdict = verdict  # "ok" | "low_confidence" | "mismatch"


class NiaSemanticSpanValidator:
    def check(self, statement: dict) -> NiaSemanticSpanCheckResult:
        quote_text = " ".join(span["quote"] for span in statement["source_spans"])
        semantic_text = self._semantic_content(statement)
        if not semantic_text.strip():
            return NiaSemanticSpanCheckResult(1.0, "ok")

        score = self._substring_coverage(semantic_text, quote_text)
        if score < _STRONG_MISMATCH_THRESHOLD:
            return NiaSemanticSpanCheckResult(score, "mismatch")
        if score < _ACCEPT_THRESHOLD:
            return NiaSemanticSpanCheckResult(score, "low_confidence")
        return NiaSemanticSpanCheckResult(score, "ok")

    def _semantic_content(self, statement: dict) -> str:
        stype = statement["statement_type"]
        if stype == "case_observation":
            return statement["subject"]
        if stype == "cause_claim":
            return " ".join(
                [statement["subject"], *statement["objects"], statement.get("scope_text") or ""]
            )
        if stype == "ingredient_effect_claim":
            subj = statement["subject"]
            return " ".join([subj["raw_name"], subj.get("raw_name_ko") or "", statement["object"]])
        if stype == "precaution":
            return statement["subject"]
        if stype == "usage_instruction":
            return statement["action"]
        if stype == "combination_claim":
            names = " ".join(s["raw_name"] for s in statement["subjects"])
            return f"{names} {statement['object']}"
        if stype == "contextual_factor":
            return f"{statement['factor_raw']} {statement['details_raw']}"
        return ""

    def _substring_coverage(self, semantic_text: str, quote_text: str) -> float:
        """semantic_text의 의미 토큰(2글자 이상) 중 quote_text에 substring으로 등장하는
        비율. 성분명 토큰과 predicate 토큰이 섞여 있으므로, 성분명만 맞고 predicate가
        빠지면 자동으로 점수가 낮아진다(토큰 하나가 아니라 여러 개 중 일부만 매칭)."""
        tokens = {t.lower() for t in _HANGUL_TOKEN_RE.findall(semantic_text) if len(t) >= 2}
        if not tokens:
            return 1.0
        quote_lower = quote_text.lower()
        matched = sum(1 for t in tokens if t in quote_lower)
        return matched / len(tokens)
