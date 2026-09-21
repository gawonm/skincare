"""Top-3 NIA Case에서 질문 관련 성분 Claim을 구조화 출력으로 추출한다."""

from httpx import HTTPError
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import ValidationError

from agent.prompts import PromptCatalog, PromptPurpose, PromptRequest
from agent.rag.case_claim_schemas import (
    CaseClaimExtractionRequest,
    CaseClaimExtractionResult,
    CaseClaimModelOutput,
)
from agent.rag.ports import CaseClaimExtractor
from agent.rag.schemas import ChatModelConfig, LlmProvider, LookupStatus


class ChatModelCaseClaimExtractor(CaseClaimExtractor):
    """OpenAI 또는 로컬 OpenAI 호환 모델로 Case Claim을 한 번만 추출한다."""

    def __init__(self, config: ChatModelConfig, prompt_catalog: PromptCatalog | None = None) -> None:
        self._config = config
        self._prompt_catalog = prompt_catalog or PromptCatalog()
        self._client = self._build_client(config).with_structured_output(CaseClaimModelOutput)

    async def extract(
        self,
        request: CaseClaimExtractionRequest,
    ) -> CaseClaimExtractionResult:
        prompt = self._prompt_catalog.get(
            PromptRequest(purpose=PromptPurpose.CASE_CLAIM_EXTRACTION)
        )
        try:
            result = await self._client.ainvoke(
                [
                    SystemMessage(content=prompt.system_message),
                    HumanMessage(content=request.model_dump_json()),
                ]
            )
            if not isinstance(result, CaseClaimModelOutput):
                raise TypeError("Case Claim 추출기가 계약된 구조화 응답을 반환하지 않았습니다.")
        except (
            HTTPError,
            OpenAIError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            # 외부·로컬 모델 오류를 빈 검색 결과로 숨기지 않고 그래프 상태로 전달한다.
            return CaseClaimExtractionResult(
                status=LookupStatus.ERROR,
                model=self._config.active_model(),
                error_message=f"NIA Case Claim 추출에 실패했습니다: {error}",
            )

        claims = result.claims[: request.limit]
        if not claims:
            return CaseClaimExtractionResult(
                status=LookupStatus.NO_RESULTS,
                model=self._config.active_model(),
            )
        return CaseClaimExtractionResult(
            status=LookupStatus.SUCCESS,
            claims=claims,
            model=self._config.active_model(),
        )

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
        return ChatOpenAI(
            base_url=config.local.base_url,
            api_key=config.local.api_key.get_secret_value(),
            model=config.local.model,
            timeout=config.local.timeout_seconds,
            max_retries=config.local.max_retries,
        )


class CaseClaimExtractorFactory:
    """채팅 모델 설정으로 런타임 Case Claim 추출기를 만든다."""

    def create(self, config: ChatModelConfig) -> CaseClaimExtractor:
        return ChatModelCaseClaimExtractor(config)
