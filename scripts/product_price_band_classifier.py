"""`lowest_price` 를 `PriceBand` 로 분류한다.

경계값은 `docs/data/data.md` 의 가격대 표와 동일하게 유지한다. 여기서 바꾸면 문서도 같이 고친다.
"""

from scripts.product_candidate_schemas import PriceBand


class PriceBandClassifier:
    _UNDER_10K = 10_000
    _UNDER_20K = 20_000
    _UNDER_30K = 30_000
    _UNDER_50K = 50_000

    def classify(self, lowest_price: int) -> PriceBand:
        if lowest_price < self._UNDER_10K:
            return PriceBand.UNDER_10K
        if lowest_price < self._UNDER_20K:
            return PriceBand.BAND_10K
        if lowest_price < self._UNDER_30K:
            return PriceBand.BAND_20K
        if lowest_price < self._UNDER_50K:
            return PriceBand.BAND_30K_40K
        return PriceBand.OVER_50K
