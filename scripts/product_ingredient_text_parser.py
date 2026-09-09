"""전성분(INCI) 원문(`ProductCandidateRow.raw_ingredients_text`)을 구간·성분 단위로 나눈다.

콤마를 무조건 구분자로 쓰지 않는다. 실제 원문에 이런 패턴이 있다:

- `1,2-Hexanediol`: 콤마가 구분자가 아니라 성분명 일부다. 순진하게 콤마로 나누면
  "1"과 "2-Hexanediol"로 깨진다.
- `Ammonium Acryloyldimethyltaurate/VP Copolymer`: 슬래시가 성분명 일부다. 이 파서는
  슬래시를 구분자로 취급하지 않으므로 원문을 그대로 안 건드리면 자동으로 보존된다.
- `(2,000 ppm)`, `(0.45%)`: 괄호 안 함량 표기에도 콤마가 들어간다. 괄호 안 콤마는
  구분자로 안 본다.
- `Citrus Aurantium Dulcis (Orange) Peel Oil`: 식물 일반명이 괄호 안에 있다. 함량
  표기(숫자+%/ppm/ppb/mg)가 아닌 괄호는 성분명 일부라 제거하지 않는다.

원문에 구분자가 아예 빠진 것으로 의심되는 경우(예: 스크래핑 과정에서 콤마가 유실돼
"Glycereth-261,2-Hexanediol" 처럼 두 성분명이 붙어버린 경우)는 임의로 나누지 않고
`IngredientTokenParseStatus.NEEDS_REVIEW` 로 남긴다.

일부 상품(관찰된 사례 94개 중 2개)은 원문 구분자가 콤마가 아니라 "@"다 — 콤마는
"1,2-Hexanediol" 같은 성분명 내부에만 어쩌다 나오고, "@"가 훨씬 많이 나온다. 이 파서는
구분자별 등장 횟수를 세서 어느 쪽을 실제 구분자로 쓸지 상품마다(정확히는 구간마다)
판정한다 — 전체 데이터셋에 고정된 구분자를 가정하지 않는다.
"""

import re

from scripts.product_candidate_schemas import DataSource

# 파서 로직이 바뀔 때마다 올린다(예: "@" 구분자 지원 추가로 1.0.0 → 1.1.0). 저장 쪽
# (`models.product_ingredient.ProductIngredientSnapshot.parser_version`)이 이 값을 그대로
# 저장해, 파서가 나중에 개선되면 어떤 스냅샷을 재파싱해야 할지 가려낸다.
PARSER_VERSION = "1.1.0"
from scripts.product_ingredient_parse_schemas import (
    IngredientSectionLinkStatus,
    IngredientSectionParse,
    IngredientTokenParseStatus,
    ParsedIngredientToken,
    ProductIngredientParseResult,
)

_COMMA_DELIMITER = ","
_AT_DELIMITER = "@"

# "[옵션명]" 처럼 그 줄 전체가 대괄호 하나로만 이루어진 줄. 성분 목록 중간에 섞여 나오는
# "Ascorbic Acid [Vitamin C]" 같은 인라인 이명 표기와는 다르다(그건 줄 전체가 아니라
# 성분명 뒤에 붙어 나온다). 줄 단위로만 판정해서 이 둘을 구분한다.
_SECTION_HEADER_LINE = re.compile(r"^\[(?P<label>[^\[\]]+)\]$")

# 콤마 분리 후 남는, "1,2-Hexanediol" 류(숫자,숫자-단어) 성분명의 앞부분만 떨어져 나온
# 토큰. 이 뒤에 "숫자-단어..."로 시작하는 다음 토큰이 바로 오면 원래 하나였던 성분명을
# 다시 합친다. 이 계열(1,2-헥산다이올, 1,2-펜탄다이올 등)은 국내 화장품에 방부보조제로
# 흔히 쓰여 실제 원문에서 자주 나온다.
_LEADING_DIGIT_TOKEN = re.compile(r"^\d{1,2}$")
_DIOL_CONTINUATION_TOKEN = re.compile(r"^\d{1,2}-[A-Za-z]")

# 트레일링 괄호가 함량/각주 표기인지 판정한다. %, ppm, ppb, mg, µg 뒤에 오는 숫자(콤마·
# 소수점 포함)만 함량으로 본다. "(Orange)", "(Vitamin C)" 처럼 숫자가 없는 괄호는 이
# 패턴에 안 걸려서 matching_name 에 그대로 남는다 — 식물 일반명·이명은 성분 식별에
# 필요한 정보라 제거하면 안 된다.
_CONCENTRATION_INNER_PATTERN = re.compile(
    r"^\d[\d,.\s]*\s*(%|ppm|ppb|mg|µg|㎍)$", re.IGNORECASE
)
_TRAILING_PAREN_PATTERN = re.compile(r"\(([^()]*)\)\s*$")

# "단어+숫자" 로 끝나는 토큰 바로 뒤에, 콤마로 이미 나뉘었지만 "숫자-디올류" 로
# 시작하는 토큰이 오면 원문에서 콤마가 하나 유실됐다고 의심한다. 예:
# "Glycereth-261,2-Hexanediol" 은 콤마 하나로 나누면 "Glycereth-261" / "2-Hexanediol"
# 두 토큰이 되는데, 실제로는 "Glycereth-26" + "1,2-Hexanediol" 사이의 콤마가 빠진
# 것이다. 두 토큰 다 억지로 고치지 않고(어디서 잘려야 할지 파서가 확신할 수 없다)
# 검토 대상으로 남긴다. "digit-word" 전부를 의심하면 "PEG-40" 다음에 우연히 다른
# 숫자로 시작하는 성분(예: "2-Bromo-2-Nitropropane-1,3-Diol")이 오는 정상 케이스까지
# 오탐하므로, 실제로 자주 콤마 없이 붙는 걸로 관찰된 디올류 성분명으로 범위를 좁힌다.
_TRAILING_DIGIT_SUFFIX = re.compile(r"^(?=.*[A-Za-z]).+\d+$")
_KNOWN_MERGED_DIOL_CONTINUATION = re.compile(
    r"^\d{1,2}-(hexanediol|pentanediol|butanediol|propanediol|octanediol)",
    re.IGNORECASE,
)


class ProductIngredientTextParser:
    """전성분 원문 하나를 `ProductIngredientParseResult` 로 바꾼다."""

    def parse(
        self, source: DataSource, source_product_id: str, raw_ingredients_text: str
    ) -> ProductIngredientParseResult:
        raw_sections = self._split_sections(raw_ingredients_text)
        sections = tuple(
            self._parse_section(label, section_text) for label, section_text in raw_sections
        )
        return ProductIngredientParseResult(
            source=source,
            source_product_id=source_product_id,
            raw_ingredients_text=raw_ingredients_text,
            sections=sections,
        )

    def _parse_section(self, label: str | None, section_text: str) -> IngredientSectionParse:
        tokens = self._parse_tokens(section_text)
        link_status = (
            IngredientSectionLinkStatus.NO_OPTION_SECTIONS
            if label is None
            else IngredientSectionLinkStatus.AMBIGUOUS
        )
        return IngredientSectionParse(
            section_label=label,
            section_raw_text=section_text,
            link_status=link_status,
            tokens=tokens,
        )

    def _split_sections(self, raw_text: str) -> list[tuple[str | None, str]]:
        lines = raw_text.splitlines()
        sections: list[tuple[str | None, list[str]]] = []
        current_label: str | None = None
        current_lines: list[str] = []
        found_header = False

        for line in lines:
            header_match = _SECTION_HEADER_LINE.match(line.strip())
            if header_match is not None:
                if found_header or current_lines:
                    sections.append((current_label, current_lines))
                current_label = header_match.group("label")
                current_lines = []
                found_header = True
            else:
                current_lines.append(line)
        sections.append((current_label, current_lines))

        if not found_header:
            return [(None, raw_text.strip())]

        return [
            (label, "\n".join(lines_).strip())
            for label, lines_ in sections
            if "\n".join(lines_).strip()
        ]

    def _parse_tokens(self, section_text: str) -> tuple[ParsedIngredientToken, ...]:
        delimiter = self._detect_delimiter(section_text)
        raw_tokens = self._split_top_level(section_text, delimiter)
        if delimiter == _COMMA_DELIMITER:
            # "@" 구분자를 쓰는 상품은 "1,2-Hexanediol" 안 콤마가 애초에 안 쪼개져서
            # 이 재결합이 필요 없다 — 오히려 잘못 합칠 위험만 생긴다.
            raw_tokens = self._rejoin_known_diol_splits(raw_tokens)
        suspected_indices = self._find_suspected_missing_separator_pairs(raw_tokens)
        return tuple(
            self._build_token(order, raw_token, order in suspected_indices)
            for order, raw_token in enumerate(raw_tokens)
        )

    def _detect_delimiter(self, text: str) -> str:
        # 대부분은 콤마로 구분하지만, 일부 상품은 원문 자체가 "@"로 구분돼 있다(관찰된
        # 사례: 콤마는 "1,2-Hexanediol" 같은 성분명 내부에만 한두 번 나오고, "@"가
        # 훨씬 많이 나온다). 어느 쪽이 실제 구분자인지 등장 횟수로 판정한다.
        if text.count(_AT_DELIMITER) > text.count(_COMMA_DELIMITER):
            return _AT_DELIMITER
        return _COMMA_DELIMITER

    def _find_suspected_missing_separator_pairs(self, tokens: list[str]) -> set[int]:
        suspected: set[int] = set()
        for index in range(len(tokens) - 1):
            if _TRAILING_DIGIT_SUFFIX.match(tokens[index]) and _KNOWN_MERGED_DIOL_CONTINUATION.match(
                tokens[index + 1]
            ):
                suspected.add(index)
                suspected.add(index + 1)
        return suspected

    def _split_top_level(self, text: str, delimiter: str) -> list[str]:
        # 괄호 안 구분자는 구분자로 안 본다 — 함량 표기 "(2,000 ppm)" 이 안 쪼개지게 한다.
        tokens: list[str] = []
        depth = 0
        current: list[str] = []
        for char in text:
            if char in "([":
                depth += 1
                current.append(char)
            elif char in ")]":
                depth = max(0, depth - 1)
                current.append(char)
            elif char == delimiter and depth == 0:
                tokens.append("".join(current))
                current = []
            else:
                current.append(char)
        tokens.append("".join(current))
        return [token.strip() for token in tokens if token.strip()]

    def _rejoin_known_diol_splits(self, tokens: list[str]) -> list[str]:
        result: list[str] = []
        index = 0
        while index < len(tokens):
            has_next = index + 1 < len(tokens)
            if (
                has_next
                and _LEADING_DIGIT_TOKEN.match(tokens[index])
                and _DIOL_CONTINUATION_TOKEN.match(tokens[index + 1])
            ):
                result.append(f"{tokens[index]},{tokens[index + 1]}")
                index += 2
            else:
                result.append(tokens[index])
                index += 1
        return result

    def _build_token(
        self, order: int, raw_token: str, is_suspected_missing_separator: bool
    ) -> ParsedIngredientToken:
        if is_suspected_missing_separator:
            return ParsedIngredientToken(
                order=order,
                raw_token=raw_token,
                matching_name=raw_token,
                concentration_text=None,
                parse_status=IngredientTokenParseStatus.NEEDS_REVIEW,
                review_reason="구분자(콤마) 누락 의심 — 두 성분명이 이어붙은 것으로 보임",
            )

        matching_name, concentration_text = self._split_trailing_concentration(raw_token)
        return ParsedIngredientToken(
            order=order,
            raw_token=raw_token,
            matching_name=matching_name,
            concentration_text=concentration_text,
            parse_status=IngredientTokenParseStatus.PARSED,
        )

    def _split_trailing_concentration(self, raw_token: str) -> tuple[str, str | None]:
        match = _TRAILING_PAREN_PATTERN.search(raw_token)
        if match is None:
            return raw_token, None

        inner = match.group(1).strip()
        if not _CONCENTRATION_INNER_PATTERN.match(inner):
            return raw_token, None

        matching_name = raw_token[: match.start()].strip()
        return matching_name, f"({inner})"
