"""사람이 확보한 CIR report PDF 텍스트에서 "이 report 의 범위(scope)에 해당 성분이 실제로 들어 있는가"를 확인한다.

제목 유사성만으로 성분을 연결하지 않기 위한 검증 단계다. 네트워크 호출·스크래핑 없음(이미 확보한 PDF 페이지 텍스트만 읽는다).
성분명이 REFERENCES 이전 본문에 정확한 단어 경계로 나타날 때만 근거로 인정하고, 위치(페이지)와 문맥을 함께 남겨 사람이 확인한다.
"""

import re

from pydantic import BaseModel

_REFERENCES_HEADING = re.compile(r"^\s*REFERENCES\s*$", re.MULTILINE)
_SNIPPET_RADIUS = 80
_MAX_SNIPPETS = 3


class ScopeEvidence(BaseModel):
    page: int
    snippet: str


class IngredientScope(BaseModel):
    ingredient: str
    in_scope: bool
    evidence: list[ScopeEvidence]


class CirScopeChecker:
    def check(self, pages: list[str], ingredient_names: list[str]) -> list[IngredientScope]:
        body = self._body_pages(pages)
        results: list[IngredientScope] = []
        for name in ingredient_names:
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.IGNORECASE
            )
            evidence: list[ScopeEvidence] = []
            for page_number, text in body:
                for match in pattern.finditer(text):
                    start = max(0, match.start() - _SNIPPET_RADIUS)
                    snippet = " ".join(text[start : match.end() + _SNIPPET_RADIUS].split())
                    evidence.append(ScopeEvidence(page=page_number, snippet=snippet))
                    if len(evidence) >= _MAX_SNIPPETS:
                        break
                if len(evidence) >= _MAX_SNIPPETS:
                    break
            results.append(
                IngredientScope(ingredient=name, in_scope=bool(evidence), evidence=evidence)
            )
        return results

    def _body_pages(self, pages: list[str]) -> list[tuple[int, str]]:
        """REFERENCES 이후는 다른 논문 제목에 성분명이 섞이므로 근거에서 뺀다."""
        body: list[tuple[int, str]] = []
        for index, text in enumerate(pages, start=1):
            heading = _REFERENCES_HEADING.search(text)
            if heading:
                body.append((index, text[: heading.start()]))
                break
            body.append((index, text))
        return body
