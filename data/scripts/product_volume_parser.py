"""상품명(`raw_title`)에서 단품 용량(ml/g)을 뽑아낸다.

세트·리필·옵션선택형 상품은 제목만 봐서는 "한 병당 용량"과 "구성 전체 용량"을
구분할 수 없다(예: "30ml*2ea"가 30ml짜리 2개인지, 총 60ml 한 병인지 텍스트만으로는
불명확). 이런 경우 억지로 하나를 골라 반환하면 나중에 단위가격(원/ml) 계산에 잘못
쓰일 위험이 있으므로, 모호하면 `None` 을 돌려주고 값을 만들어내지 않는다.
"""

import re

_VOLUME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G)\b")
_UNIT_NORMALIZATION = {"ml": "ml", "mL": "ml", "ML": "ml", "g": "g", "G": "g"}

# 용량 뒤에 붙는 배수 표기(예: "30ml*2ea", "40ml x2"). 이게 있으면 총 용량인지
# 단품 용량인지 제목만으로 확정할 수 없다.
_MULTIPLIER_PATTERN = re.compile(r"[*x×]\s*\d+", re.IGNORECASE)

# 구성이 여러 개거나(세트/리필/더블팩) 용량이 옵션마다 다를 수 있는(옵션선택형) 상품임을
# 나타내는 표현들. 하나라도 나오면 대표 용량을 확정하지 않는다.
_AMBIGUOUS_KEYWORD_PATTERN = re.compile(
    r"\b(set|pack|refill|double|duo|triple|option|options|type|types)\b|1\+1|2\+1",
    re.IGNORECASE,
)


class ProductVolumeParser:
    def parse(self, raw_title: str) -> tuple[float | None, str | None]:
        matches = _VOLUME_PATTERN.findall(raw_title)
        if len(matches) != 1:
            return None, None
        if _MULTIPLIER_PATTERN.search(raw_title) or _AMBIGUOUS_KEYWORD_PATTERN.search(raw_title):
            return None, None

        value_text, unit_text = matches[0]
        return float(value_text), _UNIT_NORMALIZATION[unit_text]
