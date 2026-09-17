"""`core.config`의 공용 `LlmChatSettings`(provider: openai/ollama/local)를 그대로
읽어 `ChatOpenAI`를 조립한다. `config.yaml`의 `agent.chat.provider`를 바꾸면
agent 런타임과 이 NIA labeling pipeline이 동시에 provider를 바꿔 쓴다.

`agent/llm.py`의 `ChatModelLlmClient`/`ChatModelClaimGenerator`를 직접 import하지
않는다 — 두 클래스 모두 `__init__`에서 `.with_structured_output(고정 스키마)`를 바로
호출해 다른 구조화 출력 스키마(`LlmNiaLabelingOutput`)에 재사용할 수 없고, provider별
연결 분기 로직도 별도 함수로 분리돼 있지 않아 import만으로 가져올 수 없다(각 파일
안에 인라인으로 중복돼 있음). 그 분기 로직 자체(공개된 재사용 단위가 없는 5줄 내외의
if/else)만 여기서도 그대로 반복한다 — `data/`가 `agent/`를 import하는 새 방향을
만들지 않기 위한 판단이다(`docs/data/POC_DATASET_HANDOFF.md` 등 data 파트 관례상
backend는 읽기 전용으로 import해도 agent는 전례가 없다).
"""

from langchain_openai import ChatOpenAI

from core.config import LlmChatSettings, LlmProvider, OpenAiConfig


class NiaChatModelClientFactory:
    def create(
        self, chat_settings: LlmChatSettings, openai_config: OpenAiConfig | None
    ) -> ChatOpenAI:
        if chat_settings.provider is LlmProvider.OPENAI:
            if openai_config is None:
                raise ValueError("provider=openai인데 config.yaml에 openai 블록이 없습니다.")
            return ChatOpenAI(
                api_key=openai_config.api_key,
                model=openai_config.chat_model.value,
                timeout=openai_config.timeout_seconds,
                max_retries=openai_config.max_retries,
            )
        # OLLAMA/LOCAL 둘 다 OpenAI 호환 API(base_url)로 붙는다.
        local = chat_settings.local
        return ChatOpenAI(
            base_url=local.base_url,
            api_key=local.api_key,
            model=local.model,
            timeout=local.timeout_seconds,
            max_retries=local.max_retries,
        )
