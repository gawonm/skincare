"""LangGraph 상태 그래프 조립과 실행 경계."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes import AgentNodes
from agent.schemas import (
    AgentInvocation,
    AgentState,
    GraphInvocationRequest,
    GraphInvocationResult,
    GraphNode,
    InformationRoute,
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
        if state.current_intent is not None:
            return TaskRoute.PROCESS_TASK
        return TaskRoute.VALIDATE_RESULT

    def after_validation(self, state: AgentState) -> ValidationRoute:
        if state.needs_revision and state.revision_count < state.execution_limits.max_revisions:
            return ValidationRoute.REVISE_RESULT
        return ValidationRoute.FINALIZE_RESPONSE


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
        result: Any = await self._compiled.ainvoke(request.invocation, config=config)
        return GraphInvocationResult(state=AgentState.model_validate(result))


class AgentGraphFactory:
    """프로세스 수명 동안 재사용할 체크포인터를 그래프에 주입한다."""

    def __init__(
        self,
        nodes: AgentNodes,
        router: AgentGraphRouter,
        checkpointer: BaseCheckpointSaver[str],
    ) -> None:
        self._nodes = nodes
        self._router = router
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
                TaskRoute.PROCESS_TASK: GraphNode.PROCESS_TASK.value,
                TaskRoute.VALIDATE_RESULT: GraphNode.VALIDATE_RESULT.value,
            },
        )
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
