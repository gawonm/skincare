"""LLM 호출 없이 `NiaLlmLabeler`가 provider에 무관하게 조립되고, 구조화 출력을 받았을
때의 처리(record 직렬화 → 메시지 구성 → 타입 확인)가 그대로 동작하는지 확인한다.
실제 네트워크 호출은 fake client로 대체한다.
"""

import pytest

from core.config import (
    LlmChatSettings,
    LlmProvider,
    LocalChatSettings,
    OpenAiChatModel,
    OpenAiConfig,
)
from data.scripts.nia_llm_label_schemas import LlmNiaLabelingOutput
from data.scripts.nia_llm_labeler import NiaLlmLabeler


class _FakeStructuredClient:
    def __init__(self, response: object) -> None:
        self._response = response
        self.last_messages = None

    async def ainvoke(self, messages):
        self.last_messages = messages
        return self._response


class TestNiaLlmLabeler:
    def test_openai_provider_assembles(self) -> None:
        labeler = NiaLlmLabeler(
            LlmChatSettings(provider=LlmProvider.OPENAI),
            OpenAiConfig(api_key="sk-test", chat_model=OpenAiChatModel.GPT_4O_MINI),
        )
        assert labeler.provider == "openai"
        assert labeler.model == "gpt-4o-mini"
        assert labeler.base_url is None

    def test_ollama_provider_assembles_without_openai_config(self) -> None:
        labeler = NiaLlmLabeler(
            LlmChatSettings(
                provider=LlmProvider.OLLAMA,
                local=LocalChatSettings(base_url="http://localhost:11434/v1", model="qwen3.5:9b"),
            ),
            None,
        )
        assert labeler.provider == "ollama"
        assert labeler.model == "qwen3.5:9b"
        assert labeler.base_url == "http://localhost:11434/v1"

    @pytest.mark.asyncio
    async def test_label_returns_mocked_structured_output(self) -> None:
        """구조화 출력 클라이언트를 fake로 바꿔서, record 직렬화 → 응답 타입 확인까지
        기존 파이프라인(NIA structured output parsing)이 그대로 동작하는지 본다."""
        labeler = NiaLlmLabeler(
            LlmChatSettings(provider=LlmProvider.OPENAI),
            OpenAiConfig(api_key="sk-test", chat_model=OpenAiChatModel.GPT_4O_MINI),
        )
        mock_output = LlmNiaLabelingOutput(statements=[])
        fake_client = _FakeStructuredClient(mock_output)
        labeler._client = fake_client  # 네트워크 호출을 대신할 fake로 교체

        record = {
            "info": {"question": "테스트"},
            "meta": {},
            "external": [],
            "chain_of_thought": [],
        }
        result = await labeler.label(record)

        assert result is mock_output
        assert isinstance(result, LlmNiaLabelingOutput)
        assert fake_client.last_messages is not None
        assert "테스트" in fake_client.last_messages[1].content

    @pytest.mark.asyncio
    async def test_label_rejects_wrong_response_type(self) -> None:
        labeler = NiaLlmLabeler(
            LlmChatSettings(provider=LlmProvider.OPENAI),
            OpenAiConfig(api_key="sk-test", chat_model=OpenAiChatModel.GPT_4O_MINI),
        )
        labeler._client = _FakeStructuredClient("not-the-right-type")

        with pytest.raises(TypeError):
            await labeler.label({"info": {}, "meta": {}, "external": [], "chain_of_thought": []})
