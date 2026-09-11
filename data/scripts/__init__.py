"""일회성 데이터 적재/ETL 스크립트.

원본 파일(PDF, 엑셀 등)을 파싱해 `models/` 테이블에 적재하는 코드가 여기 들어간다.
웹 요청 경로(`backend`)나 LLM이 호출하는 도구(`agent/tools`)와는 역할이 다르므로 분리한다.

규칙
- `core`, `models` 만 import 한다. `backend`, `agent` 는 import 하지 않는다.
- DB 세션은 스크립트의 진입점(entrypoint)에서 만들어 각 클래스에 주입한다.
- 각 단계는 클래스로 만들고, 입력과 출력은 Enum/Pydantic 으로 정의한다.
"""
