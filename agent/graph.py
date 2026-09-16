"""LangGraph 상태 그래프 조립과 실행 경계."""

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes import AgentNodes
from agent.rag_workflow import RagWorkflowNodes
from agent.schemas import (
    AgentInvocation,
    AgentState,
    GraphInvocationRequest,
    GraphInvocationResult,
    GraphNode,
    InformationRoute,
    Intent,
    RagRoute,
    TaskRoute,
    ValidationRoute,
)


class AgentGraphRouter:
    """조건 분기를 Enum으로 제한해 노드 이름 오타를 막는다."""

    def after_information(self, state: AgentState) -> InformationRoute:
        if state.follow_up_question:
            return InformationRoute.ASK_USER
        return InformationRoute.ROUTE_TASK

    def after_task_routing(self, state: AgentState) -> TaskRoute:
        if state.current_intent is Intent.EVIDENCE_QA:
            return TaskRoute.ROUTE_RAG
        if state.current_intent is not None:
            return TaskRoute.PROCESS_TASK
        return TaskRoute.VALIDATE_RESULT

    def after_validation(self, state: AgentState) -> ValidationRoute:
        if state.needs_revision and state.revision_count < state.execution_limits.max_revisions:
            return ValidationRoute.REVISE_RESULT
        return ValidationRoute.FINALIZE_RESPONSE


class RagWorkflowRouter:
    """선택된 2-Layer RAG 경로를 첫 검색 노드로 연결한다."""

    def after_rag_routing(self, state: AgentState) -> RagRoute:
        if state.rag_route is None:
            raise RuntimeError("RAG 경로가 선택되지 않았습니다.")
        return state.rag_route


class AgentGraph:
    """LangGraph의 dict 기반 설정을 Pydantic 요청 뒤에 격리한다."""

    def __init__(self, compiled: CompiledStateGraph) -> None:
        self._compiled = compiled

    async def ainvoke(self, request: GraphInvocationRequest) -> GraphInvocationResult:
        # LangGraph가 RunnableConfig 매핑만 받으므로 이 경계에서만 dict를 만든다.
        config = RunnableConfig(
            configurable={"thread_id": request.invocation.thread_id},
            recursion_limit=request.recursion_limit,
        )
        # 노드 사이의 경과 시간 검사만으로는 응답하지 않는 외부 호출을 중단할 수 없다.
        async with asyncio.timeout(request.invocation.execution_limits.timeout_seconds):
            result: Any = await self._compiled.ainvoke(request.invocation, config=config)
        return GraphInvocationResult(state=AgentState.model_validate(result))


class AgentGraphFactory:
    """프로세스 수명 동안 재사용할 체크포인터를 그래프에 주입한다."""

    def __init__(
        self,
        nodes: AgentNodes,
        rag_nodes: RagWorkflowNodes,
        router: AgentGraphRouter,
        rag_router: RagWorkflowRouter,
        checkpointer: BaseCheckpointSaver[str],
    ) -> None:
        self._nodes = nodes
        self._rag_nodes = rag_nodes
        self._router = router
        self._rag_router = rag_router
        self._checkpointer = checkpointer

    def create(self) -> AgentGraph:
        builder = StateGraph(
            AgentState,
            input_schema=AgentInvocation,
            output_schema=AgentState,
        )
        builder.add_node(GraphNode.PREPARE_TURN.value, self._nodes.prepare_turn)
        builder.add_node(GraphNode.UNDERSTAND_REQUEST.value, self._nodes.understand_request)
        builder.add_node(GraphNode.RESOLVE_ENTITIES.value, self._nodes.resolve_entities)
        builder.add_node(GraphNode.ASSESS_INFORMATION.value, self._nodes.assess_information)
        builder.add_node(GraphNode.ASK_USER.value, self._nodes.ask_user)
        builder.add_node(GraphNode.ROUTE_TASK.value, self._nodes.route_task)
        builder.add_node(GraphNode.ROUTE_RAG.value, self._rag_nodes.route_rag)
        builder.add_node(GraphNode.SEARCH_CLAIMS.value, self._rag_nodes.search_claims)
        builder.add_node(
            GraphNode.RESOLVE_CLAIM_INGREDIENTS.value,
            self._rag_nodes.resolve_claim_ingredients,
        )
        builder.add_node(GraphNode.SEARCH_EVIDENCE.value, self._rag_nodes.search_evidence)
        builder.add_node(
            GraphNode.ASSEMBLE_RAG_RESPONSE.value,
            self._rag_nodes.assemble_rag_response,
        )
        builder.add_node(GraphNode.PROCESS_TASK.value, self._nodes.process_task)
        builder.add_node(GraphNode.VALIDATE_RESULT.value, self._nodes.validate_result)
        builder.add_node(GraphNode.REVISE_RESULT.value, self._nodes.revise_result)
        builder.add_node(GraphNode.FINALIZE_RESPONSE.value, self._nodes.finalize_response)

        builder.add_edge(START, GraphNode.PREPARE_TURN.value)
        builder.add_edge(GraphNode.PREPARE_TURN.value, GraphNode.UNDERSTAND_REQUEST.value)
        builder.add_edge(GraphNode.UNDERSTAND_REQUEST.value, GraphNode.RESOLVE_ENTITIES.value)
        builder.add_edge(GraphNode.RESOLVE_ENTITIES.value, GraphNode.ASSESS_INFORMATION.value)
        builder.add_conditional_edges(
            GraphNode.ASSESS_INFORMATION.value,
            self._router.after_information,
            {
                InformationRoute.ASK_USER: GraphNode.ASK_USER.value,
                InformationRoute.ROUTE_TASK: GraphNode.ROUTE_TASK.value,
            },
        )
        builder.add_edge(GraphNode.ASK_USER.value, GraphNode.FINALIZE_RESPONSE.value)
        builder.add_conditional_edges(
            GraphNode.ROUTE_TASK.value,
            self._router.after_task_routing,
            {
                TaskRoute.ROUTE_RAG: GraphNode.ROUTE_RAG.value,
                TaskRoute.PROCESS_TASK: GraphNode.PROCESS_TASK.value,
                TaskRoute.VALIDATE_RESULT: GraphNode.VALIDATE_RESULT.value,
            },
        )
        builder.add_conditional_edges(
            GraphNode.ROUTE_RAG.value,
            self._rag_router.after_rag_routing,
            {
                RagRoute.CLAIM_THEN_EVIDENCE: GraphNode.SEARCH_CLAIMS.value,
                RagRoute.EVIDENCE_ONLY: GraphNode.SEARCH_EVIDENCE.value,
            },
        )
        builder.add_edge(
            GraphNode.SEARCH_CLAIMS.value,
            GraphNode.RESOLVE_CLAIM_INGREDIENTS.value,
        )
        builder.add_edge(
            GraphNode.RESOLVE_CLAIM_INGREDIENTS.value,
            GraphNode.SEARCH_EVIDENCE.value,
        )
        builder.add_edge(
            GraphNode.SEARCH_EVIDENCE.value,
            GraphNode.ASSEMBLE_RAG_RESPONSE.value,
        )
        builder.add_edge(GraphNode.ASSEMBLE_RAG_RESPONSE.value, GraphNode.ROUTE_TASK.value)
        builder.add_edge(GraphNode.PROCESS_TASK.value, GraphNode.ROUTE_TASK.value)
        builder.add_conditional_edges(
            GraphNode.VALIDATE_RESULT.value,
            self._router.after_validation,
            {
                ValidationRoute.REVISE_RESULT: GraphNode.REVISE_RESULT.value,
                ValidationRoute.FINALIZE_RESPONSE: GraphNode.FINALIZE_RESPONSE.value,
            },
        )
        builder.add_edge(GraphNode.REVISE_RESULT.value, GraphNode.VALIDATE_RESULT.value)
        builder.add_edge(GraphNode.FINALIZE_RESPONSE.value, END)
        return AgentGraph(builder.compile(checkpointer=self._checkpointer))
