"""LLM 호출 없이(객체 생성만) `NiaChatModelClientFactory`가 provider별로 올바른
`ChatOpenAI`를 조립하는지 확인한다. `ChatOpenAI(...)` 생성 자체는 네트워크 호출을
하지 않는다 — 실제 요청은 `.ainvoke()`를 부를 때만 발생한다.
"""

import pytest

from core.config import (
    LlmChatSettings,
    LlmProvider,
    LocalChatSettings,
    OpenAiChatModel,
    OpenAiConfig,
)
from data.scripts.nia_chat_model_client import NiaChatModelClientFactory


class TestNiaChatModelClientFactory:
    def test_openai_provider_assembles_client(self) -> None:
        chat_settings = LlmChatSettings(provider=LlmProvider.OPENAI)
        openai_config = OpenAiConfig(api_key="sk-test", chat_model=OpenAiChatModel.GPT_4O_MINI)

        client = NiaChatModelClientFactory().create(chat_settings, openai_config)

        assert client.model_name == "gpt-4o-mini"
        assert client.openai_api_base is None  # 기본 OpenAI 엔드포인트

    def test_openai_provider_without_config_raises(self) -> None:
        chat_settings = LlmChatSettings(provider=LlmProvider.OPENAI)

        with pytest.raises(ValueError):
            NiaChatModelClientFactory().create(chat_settings, None)

    def test_ollama_provider_assembles_client_without_api_key(self) -> None:
        chat_settings = LlmChatSettings(
            provider=LlmProvider.OLLAMA,
            local=LocalChatSettings(base_url="http://localhost:11434/v1", model="qwen3.5:9b"),
        )

        # openai_config=None 이어도 ollama는 조립돼야 한다(API 키 불필요).
        client = NiaChatModelClientFactory().create(chat_settings, None)

        assert client.model_name == "qwen3.5:9b"
        assert client.openai_api_base == "http://localhost:11434/v1"

    def test_local_provider_assembles_client(self) -> None:
        chat_settings = LlmChatSettings(
            provider=LlmProvider.LOCAL,
            local=LocalChatSettings(base_url="http://localhost:8000/v1", model="custom-model"),
        )

        client = NiaChatModelClientFactory().create(chat_settings, None)

        assert client.model_name == "custom-model"
        assert client.openai_api_base == "http://localhost:8000/v1"
