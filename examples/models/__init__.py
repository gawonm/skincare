"""모델 패키지 예시.

`config.yaml` 의 `model_modules` 가 가리키는 곳이 여기다. Alembic 은 이 패키지를
import 할 뿐이므로, **아래 import 문이 없는 모델은 `Base.metadata` 에 올라오지 않고
autogenerate 에도 나오지 않는다.** 새 모델 파일을 만들면 여기에 한 줄 추가한다.

`__all__` 은 그 import 들이 재export 라는 표시다. 이게 없으면 ruff/flake8 이
"쓰지 않는 import"(F401)로 잡는다. Alembic 동작에는 영향이 없다.
"""

from examples.models.exchange_rate import ExchangeRate
from examples.models.instrument import Instrument, Market
from examples.models.quote import Quote

__all__ = ["ExchangeRate", "Instrument", "Market", "Quote"]
