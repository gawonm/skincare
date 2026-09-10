"""성분명 매칭용 정규화.

의미가 다른 성분을 임의로 병합하지 않기 위해, 영문명은 대소문자·괄호·하이픈·공백
정도만 기계적으로 정규화한다. 국문명은 공백만 제거한다.
"""

import re

_EN_STRIP_CHARS_PATTERN = re.compile(r"[\s\-()]+")
_KO_WHITESPACE_PATTERN = re.compile(r"\s+")
_PARENTHETICAL_GROUP_PATTERN = re.compile(r"[(（][^)）]*[)）]")


class IngredientNameNormalizer:
    """`IngredientMaster.normalized_name_ko/en` 을 만들 때 쓰는 정규화 규칙."""

    def normalize_ko(self, name: str) -> str:
        return _KO_WHITESPACE_PATTERN.sub("", name).strip()

    def normalize_en(self, name: str | None) -> str | None:
        if name is None:
            return None
        normalized = _EN_STRIP_CHARS_PATTERN.sub("", name).lower().strip()
        return normalized or None

    def strip_common_name_annotation(self, name: str | None) -> str | None:
        """ "Niacinamide\\n(Vitamin B3)" 처럼 뒤에 덧붙은 상용명 표기를 제거한다.

        괄호 안 내용과, "/" 로 구분된 약칭(예: "Alpha Hydroxy Acid/AHA")의 뒷부분을
        제거해 본표기만 남긴다. 성분 자체를 바꾸는 게 아니라 매칭 전 표기만 통일하는
        것이므로, 이 결과로 정확히 하나의 표준 성분과 일치할 때만 매칭에 쓴다.
        """
        if name is None:
            return None
        without_parens = _PARENTHETICAL_GROUP_PATTERN.sub("", name)
        without_slash_suffix = without_parens.split("/")[0]
        collapsed = _KO_WHITESPACE_PATTERN.sub(" ", without_slash_suffix).strip()
        return collapsed or None
