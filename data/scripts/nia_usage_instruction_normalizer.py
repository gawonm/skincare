"""`usage_instruction`의 quote 원문에서 `time_of_day`/`frequency`를 deterministic하게
보강한다. LLM 출력이 이미 채운 값은 절대 덮어쓰지 않고, 비어 있을 때만 원문에서
regex로 찾은 값을 채운다 — LLM 판단을 대체하는 게 아니라 원문 정보 유실을 막는 것이 목적.

`NiaFrequencyPeriod`는 day/week/month/every_other_day만 있고 스키마를 바꾸지 않기로
했으므로, 이 enum으로 표현 안 되는 패턴(예: "한 달에 한 번" 이상 드문 주기)은 채우지 않고
그대로 None으로 남긴다 — 억지로 끼워맞추지 않는다.
"""

import re

_MORNING_EVENING_RE = re.compile(r"아침\s*[,·\-와과]*\s*저녁|저녁\s*[,·\-와과]*\s*아침")
_MORNING_RE = re.compile(r"아침")
_EVENING_RE = re.compile(r"저녁")
_DAYTIME_RE = re.compile(r"낮\s*(에|동안)?|주간")
_NIGHT_RE = re.compile(r"밤\s*(에|동안)?|취침\s*전|자기\s*전")

_EVERY_OTHER_DAY_RE = re.compile(r"격일|이틀에\s*한\s*번")
_DAILY_RE = re.compile(r"매일|하루도\s*빠짐없이")
_WEEKLY_RANGE_RE = re.compile(r"주\s*(\d+)\s*[~\-]\s*(\d+)\s*회")
_WEEKLY_SINGLE_RE = re.compile(r"주\s*(\d+)\s*회")
_DAILY_COUNT_RE = re.compile(r"하루\s*(\d+)\s*[~\-]?\s*(\d+)?\s*회")


class NiaUsageInstructionNormalizer:
    def normalize(
        self, quote_text: str, time_of_day: list[str], frequency: dict | None
    ) -> tuple[list[str], dict | None]:
        normalized_time_of_day = list(time_of_day)
        if not normalized_time_of_day:
            normalized_time_of_day = self._extract_time_of_day(quote_text)

        normalized_frequency = frequency
        if normalized_frequency is None:
            normalized_frequency = self._extract_frequency(quote_text)

        normalized_frequency = self._reconcile(normalized_time_of_day, normalized_frequency)
        return normalized_time_of_day, normalized_frequency

    def _reconcile(self, time_of_day: list[str], frequency: dict | None) -> dict | None:
        """period=day인데 서로 다른 time_of_day 개수가 frequency.max보다 많으면(예:
        '매일 아침저녁'이 time_of_day 2개 + frequency 1회로 따로 뽑히는 경우) parser의
        frequency/time_of_day 정합성 invariant를 깨므로, 하루 횟수를 time_of_day 개수에
        맞춰 올린다. LLM이 준 값이든 이 클래스가 추출한 값이든 최종 조합이 모순이면 안
        되므로 출처를 가리지 않고 적용한다."""
        if frequency is None or frequency.get("period") != "day":
            return frequency
        distinct_tod = len(set(time_of_day))
        if distinct_tod > frequency["max"]:
            return {"min": distinct_tod, "max": distinct_tod, "period": "day"}
        return frequency

    def _extract_time_of_day(self, text: str) -> list[str]:
        if _MORNING_EVENING_RE.search(text):
            return ["morning", "evening"]
        result = []
        if _MORNING_RE.search(text):
            result.append("morning")
        if _EVENING_RE.search(text):
            result.append("evening")
        if _DAYTIME_RE.search(text):
            result.append("daytime")
        if _NIGHT_RE.search(text):
            result.append("night")
        return result

    def _extract_frequency(self, text: str) -> dict | None:
        m = _WEEKLY_RANGE_RE.search(text)
        if m:
            return {"min": int(m.group(1)), "max": int(m.group(2)), "period": "week"}
        m = _WEEKLY_SINGLE_RE.search(text)
        if m:
            n = int(m.group(1))
            return {"min": n, "max": n, "period": "week"}
        m = _DAILY_COUNT_RE.search(text)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            return {"min": lo, "max": hi, "period": "day"}
        if _EVERY_OTHER_DAY_RE.search(text):
            return {"min": 1, "max": 1, "period": "every_other_day"}
        if _DAILY_RE.search(text):
            return {"min": 1, "max": 1, "period": "day"}
        return None
