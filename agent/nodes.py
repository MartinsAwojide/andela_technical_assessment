from typing import Any, Callable
from langchain_core.messages import SystemMessage
from agent.state import AgentState
from agent.prompts import SYSTEM_PROMPT


def build_worker_node(llm_with_tools) -> Callable[[AgentState], dict[str, Any]]:
    """Factory that closes over the bound LLM and returns a LangGraph node callable."""

    def worker(state: AgentState) -> dict[str, Any]:
        messages = list(state["messages"])

        # Inject system message at the front if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages

        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    return worker


def tool_router(state: AgentState) -> str:
    """Route to the tool executor if the LLM emitted tool calls, otherwise end."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "end"
