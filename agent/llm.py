"""대화 해석은 같은 방의 제한된 문맥만 받아 비동기로 실행한다."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.ports import LlmClient
from agent.rag.schemas import ChatModelConfig, LlmProvider, OpenAiChatConfig
from agent.schemas import ParsedRequest, UnderstandingRequest


class ChatModelLlmClient(LlmClient):
    """OpenAI 및 Ollama/Local OpenAI 호환 엔드포인트를 지원하는 비동기 대화 해석 클라이언트."""

    def __init__(self, config: ChatModelConfig) -> None:
        self._config = config
        self._client = self._build_client(config).with_structured_output(ParsedRequest)

    def _build_client(self, config: ChatModelConfig) -> ChatOpenAI:
        if config.provider is LlmProvider.OPENAI:
            if config.openai is None:
                raise ValueError("OpenAI 채팅 설정이 없습니다.")
            return ChatOpenAI(
                api_key=config.openai.api_key.get_secret_value(),
                model=config.openai.model.value,
                timeout=config.openai.timeout_seconds,
                max_retries=config.openai.max_retries,
            )
        # OLLAMA 및 LOCAL은 OpenAI 호환 API 서버(base_url)로 연결한다
        return ChatOpenAI(
            base_url=config.local.base_url,
            api_key=config.local.api_key.get_secret_value(),
            model=config.local.model,
            timeout=config.local.timeout_seconds,
            max_retries=config.local.max_retries,
        )

    async def understand(self, request: UnderstandingRequest) -> ParsedRequest:
        result = await self._client.ainvoke(
            [
                SystemMessage(content=request.system_prompt),
                HumanMessage(content=request.model_dump_json(exclude={"system_prompt"})),
            ]
        )
        if not isinstance(result, ParsedRequest):
            raise TypeError("요청 해석기가 ParsedRequest 형식의 응답을 반환하지 않았습니다.")
        return result


class OpenAiLlmClient(ChatModelLlmClient):
    """OpenAiChatConfig를 받는 기존 생성자 호환 래퍼."""

    def __init__(self, config: OpenAiChatConfig) -> None:
        super().__init__(ChatModelConfig(provider=LlmProvider.OPENAI, openai=config))


class LlmClientFactory:
    """설정에 따라 적절한 LlmClient 구현을 조립한다."""

    def create(self, config: ChatModelConfig) -> LlmClient:
        return ChatModelLlmClient(config)
