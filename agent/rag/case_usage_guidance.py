"""NIA Case 원문에서 성분과 연결 가능한 사용법 구간만 규칙으로 추출한다."""

import re
from typing import ClassVar

from agent.rag.case_claim_schemas import (
    CaseClaimIngredientResolutionStatus,
    ResolvedCaseClaim,
)
from agent.rag.case_schemas import CaseSearchHit
from agent.rag.schemas import CaseUsageGuidance


class CaseUsageGuidanceExtractor:
    """번호가 붙은 Case 추론 단계 중 사용법 구간을 결정적으로 선택한다."""

    _STEP_HEADING_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?m)^(?P<step>\d+)\.\s*(?P<title>[^\r\n]+?)\s*$"
    )
    _USAGE_TITLE_TERMS: ClassVar[tuple[str, str]] = ("사용법", "관리방안")
    _SOURCE_PREFIX: ClassVar[str] = "nia-case-usage"

    def extract(
        self,
        cases: list[CaseSearchHit],
        resolved_claims: list[ResolvedCaseClaim],
    ) -> list[CaseUsageGuidance]:
        cases_by_id = {case.case_id: case for case in cases}
        ingredient_ids_by_case: dict[str, list[str]] = {}
        sections_by_case: dict[str, str] = {}

        for claim in resolved_claims:
            case = cases_by_id.get(claim.claim.case_id)
            if case is None:
                continue
            section = sections_by_case.get(case.case_id)
            if section is None:
                section = self._usage_section(case.page_content)
                if section:
                    sections_by_case[case.case_id] = section
            if not section:
                continue
            for ingredient in claim.ingredients:
                if (
                    ingredient.status is not CaseClaimIngredientResolutionStatus.MATCHED
                    or ingredient.ingredient_id is None
                    or ingredient.raw_name not in section
                ):
                    continue
                ingredient_ids_by_case.setdefault(case.case_id, []).append(
                    ingredient.ingredient_id
                )

        return [
            CaseUsageGuidance(
                source_id=f"{self._SOURCE_PREFIX}:{case_id}",
                case_id=case_id,
                text=sections_by_case[case_id],
                ingredient_ids=list(dict.fromkeys(ingredient_ids)),
            )
            for case_id, ingredient_ids in ingredient_ids_by_case.items()
        ]

    def _usage_section(self, page_content: str) -> str:
        headings = list(self._STEP_HEADING_PATTERN.finditer(page_content))
        for index, heading in enumerate(headings):
            title = heading.group("title").strip()
            if not all(term in title for term in self._USAGE_TITLE_TERMS):
                continue
            end = headings[index + 1].start() if index + 1 < len(headings) else len(page_content)
            # 원문 일부 문자열 검증을 유지해야 하므로 재조립하지 않고 원래 구간을 그대로 자른다.
            return page_content[heading.start():end].strip()
        return ""
