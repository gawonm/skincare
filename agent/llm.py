"""대화 해석은 같은 방의 제한된 문맥만 받아 비동기로 실행한다."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.ports import LlmClient
from agent.rag.schemas import OpenAiChatConfig
from agent.schemas import ParsedRequest, UnderstandingRequest


class OpenAiLlmClient(LlmClient):
    def __init__(self, config: OpenAiChatConfig) -> None:
        self._client = ChatOpenAI(
            api_key=config.api_key.get_secret_value(),
            model=config.model,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        ).with_structured_output(ParsedRequest)

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
