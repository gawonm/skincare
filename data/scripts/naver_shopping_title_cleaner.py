"""검색 결과 상품명(`title`)에서 HTML 태그를 제거한다."""

import html
import re

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


class ShoppingTitleCleaner:
    def clean(self, raw_title: str) -> str:
        return _HTML_TAG_PATTERN.sub("", html.unescape(raw_title)).strip()
