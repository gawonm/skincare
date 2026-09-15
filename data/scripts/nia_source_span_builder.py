"""LLM이 반환한 (json_path, quote)에서 실제 원문 offset을 deterministic하게 계산한다.

LLM에게 "원문을 글자 단위로 그대로 복붙해라"를 계속 요구하는 대신, LLM은 의미상 어떤
문장이 근거인지만 판단하고, 실제 quote/start/end는 이 클래스가 원문에서
deterministic하게 복원한다. LLM이 준 `json_path`는 힌트로만 쓴다 — 실제 확인 결과
LLM이 `chain_of_thought[i]`의 배열 인덱스와 원본 `step`(1부터 시작)을 혼동하거나,
아예 다른 필드(`info.answer` 등)를 잘못 지목하는 경우가 있어, 항상 record 전체의
텍스트 후보 전부를 대상으로 찾는다.

1) quote가 record 어딘가에 정확히(그리고 유일하게) 존재하면 그대로 쓴다.
2) 없으면 각 텍스트 후보를 문장 단위로 쪼갠 뒤 `difflib`로 가장 비슷한 문장(들)을
   찾아 그 문장의 실제 원문 substring과 offset을 쓴다 — quote는 항상 원문의 리터럴
   substring이므로 내용을 지어내지 않는다.

각 결과에는 `confidence`(exact/fuzzy)를 함께 반환해, 낮은 신뢰도로 복원된 span은
review queue로 보낼 수 있게 한다.
"""

import difflib
import re

_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+")
# 문장 단위 fuzzy 매칭에서 이 이상이면 채택. 이 미만이면 실패로 남겨 review 대상으로 만든다.
_ACCEPT_RATIO = 0.45
# 이 이상이면 "높은 신뢰도"로 보고, 미만이면 review queue로 플래그만 남기고 채택한다.
_HIGH_CONFIDENCE_RATIO = 0.75
_MAX_SENTENCE_EXTENSION = 2


class NiaSourceSpanBuildError(ValueError):
    """어떤 방법으로도 원문에서 span을 복원하지 못했을 때 발생한다."""


class NiaSourceSpanBuilder:
    def build(self, record: dict, json_path: str, quote: str) -> tuple[dict, str]:
        """(span dict, confidence) 를 반환한다. confidence는 exact/fuzzy."""
        candidates = self._text_candidates(record)
        # 힌트로 준 경로를 먼저 시도해 흔한 경우 빠르게 끝낸다.
        candidates.sort(key=lambda c: c[0] != json_path)

        for path, text in candidates:
            span = self._find_exact(path, text, quote)
            if span is not None:
                return span, "exact"

        best = None
        best_ratio = -1.0
        for path, text in candidates:
            span, ratio = self._best_fuzzy_span(path, text, quote)
            if span is not None and ratio > best_ratio:
                best, best_ratio = span, ratio

        if best is None or best_ratio < _ACCEPT_RATIO:
            raise NiaSourceSpanBuildError(
                f"quote를 원문에서 복원하지 못함(exact/fuzzy 전부 실패, best_ratio={best_ratio:.2f}): "
                f"path={json_path} quote={quote!r}"
            )
        confidence = "exact" if best_ratio >= _HIGH_CONFIDENCE_RATIO else "fuzzy"
        return best, confidence

    def _text_candidates(self, record: dict) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        for idx, item in enumerate(record.get("chain_of_thought", [])):
            content = item.get("content")
            if isinstance(content, str):
                candidates.append((f"$.chain_of_thought[{idx}].content", content))
        for idx, item in enumerate(record.get("external", [])):
            details = item.get("details")
            if isinstance(details, str):
                candidates.append((f"$.external[{idx}].details", details))
        info = record.get("info", {})
        for field in ("question", "answer", "target_concern"):
            value = info.get(field)
            if isinstance(value, str):
                candidates.append((f"$.info.{field}", value))
        return candidates

    def _find_exact(self, path: str, text: str, quote: str) -> dict | None:
        start = text.find(quote)
        if start < 0:
            return None
        second = text.find(quote, start + 1)
        if second >= 0:
            return None  # 중복 등장 - offset이 모호하므로 exact로 인정하지 않는다.
        return {"json_path": path, "quote": quote, "start": start, "end": start + len(quote)}

    def _best_fuzzy_span(self, path: str, text: str, quote: str) -> tuple[dict | None, float]:
        sentences = self._sentence_spans(text)
        if not sentences:
            return None, -1.0

        best_ratio = -1.0
        best_span = None
        for i in range(len(sentences)):
            start = sentences[i][0]
            for j in range(i, min(i + _MAX_SENTENCE_EXTENSION, len(sentences))):
                end = sentences[j][1]
                candidate = text[start:end]
                ratio = difflib.SequenceMatcher(None, quote, candidate).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_span = (start, end)

        if best_span is None:
            return None, -1.0
        start, end = best_span
        return {"json_path": path, "quote": text[start:end], "start": start, "end": end}, best_ratio

    def _sentence_spans(self, text: str) -> list[tuple[int, int]]:
        spans = []
        for m in _SENTENCE_RE.finditer(text):
            s, e = m.span()
            if text[s:e].strip():
                spans.append((s, e))
        return spans
