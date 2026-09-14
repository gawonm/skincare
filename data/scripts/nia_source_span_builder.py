"""LLM이 반환한 (json_path, quote)에서 실제 원문 offset을 deterministic하게 계산한다.

`data/manual_review/nia/nia_pilot_annotate.py`의 `make_span`/`get_by_path` 로직을 그대로
클래스화했다 — 로직 변경 없음.
"""


class NiaSourceSpanBuildError(ValueError):
    """quote가 원문에 없거나 중복으로 등장해 offset을 확정할 수 없을 때 발생한다."""


class NiaSourceSpanBuilder:
    """LLM이 `chain_of_thought[i].content`의 `i`를 `step`(1부터 시작)과 혼동해 잘못된
    배열 인덱스를 자주 준다(실제 확인된 systematic 오류). 지정한 경로에서 quote를 못
    찾으면, 같은 배열(`chain_of_thought`/`external`) 안의 다른 인덱스로 재시도한다 —
    quote 문자열 자체는 여전히 원문과 완전히 일치해야 하므로 내용을 지어내지 않는다.
    """

    def build(self, record: dict, json_path: str, quote: str) -> dict:
        try:
            return self._build_at(record, json_path, quote)
        except NiaSourceSpanBuildError:
            fallback_path = self._retry_sibling_index(record, json_path, quote)
            if fallback_path is None:
                raise
            return self._build_at(record, fallback_path, quote)

    def _build_at(self, record: dict, json_path: str, quote: str) -> dict:
        text = self._resolve_path(record, json_path)
        start = text.find(quote)
        if start < 0:
            raise NiaSourceSpanBuildError(f"quote가 원문에 없음: path={json_path} quote={quote!r}")
        second = text.find(quote, start + 1)
        if second >= 0:
            raise NiaSourceSpanBuildError(
                f"quote가 원문에 중복 등장(오프셋 모호): path={json_path} quote={quote!r}"
            )
        end = start + len(quote)
        return {"json_path": json_path, "quote": quote, "start": start, "end": end}

    def _retry_sibling_index(self, record: dict, json_path: str, quote: str) -> str | None:
        for array_name in ("chain_of_thought", "external"):
            prefix = f"$.{array_name}["
            if not json_path.startswith(prefix):
                continue
            array = record.get(array_name, [])
            field = json_path.split("].", 1)[1] if "]." in json_path else None
            if field is None:
                return None
            for idx, item in enumerate(array):
                text = item.get(field)
                if isinstance(text, str) and quote in text:
                    return f"$.{array_name}[{idx}].{field}"
        return None

    def _resolve_path(self, record: dict, json_path: str) -> str:
        assert json_path.startswith("$."), f"지원하지 않는 json_path 형식: {json_path}"
        current = record
        for part in json_path[2:].split("."):
            if "[" in part:
                key, idx = part[:-1].split("[")
                current = current[key][int(idx)]
            else:
                current = current[part]
        return current
