import logging
import os
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.mcp_client import load_tools, make_client
from agent.nodes import build_worker_node, tool_router
from agent.state import AgentState, initial_state

log = logging.getLogger(__name__)


def _build_llm():
    provider = os.getenv("LLM_PROVIDER", "openrouter")
    model = os.getenv("LLM_MODEL", "anthropic/claude-haiku-4-5")
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model)
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'openrouter', 'anthropic', or 'google'.")


class MeridianAgent:
    def __init__(self):
        self.graph = None
        self.tools: list = []
        self.memory = MemorySaver()
        self.session_id = str(uuid.uuid4())
        self._state: AgentState = initial_state()

    async def setup(self):
        log.info("MeridianAgent setup — session=%s", self.session_id[:8])
        client = make_client()
        self.tools = await load_tools(client)
        log.info("MCP tools loaded (%d): %s", len(self.tools), [t.name for t in self.tools])

        llm = _build_llm()
        provider = os.getenv("LLM_PROVIDER", "openrouter")
        model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        log.info("LLM: %s / %s", provider, model)
        llm_with_tools = llm.bind_tools(self.tools)

        g = StateGraph(AgentState)
        g.add_node("worker", build_worker_node(llm_with_tools))
        g.add_node("tools", ToolNode(self.tools))
        g.add_edge(START, "worker")
        g.add_conditional_edges("worker", tool_router, {"tools": "tools", "end": END})
        g.add_edge("tools", "worker")
        self.graph = g.compile(checkpointer=self.memory)
        log.info("Graph compiled OK")

    async def chat(self, user_message: str, history: list) -> tuple[str, list]:
        log.info("→ user: %s", user_message[:120])
        config = {"configurable": {"thread_id": self.session_id}}
        input_state = {"messages": [HumanMessage(content=user_message)]}

        if log.isEnabledFor(logging.DEBUG):
            reply = await self._chat_streamed(input_state, config)
        else:
            result = await self.graph.ainvoke(input_state, config=config)
            reply = result["messages"][-1].content

        log.info("← bot: %s", reply[:120])
        updated_history = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return reply, updated_history

    async def _chat_streamed(self, input_state: dict, config: dict) -> str:
        """Run the graph with astream_events so every node and tool call is logged."""
        reply = ""
        async for event in self.graph.astream_events(input_state, config=config, version="v2"):
            kind = event["event"]
            name = event.get("name", "")

            if kind == "on_chain_start" and name in ("worker", "tools"):
                log.debug("[node start] %s", name)

            elif kind == "on_chain_end" and name in ("worker", "tools"):
                log.debug("[node end]   %s", name)

            elif kind == "on_chat_model_start":
                messages = event["data"].get("messages", [[]])
                n_msgs = sum(len(b) for b in messages)
                log.debug("[llm]  sending %d message(s) to model", n_msgs)

            elif kind == "on_chat_model_end":
                output = event["data"].get("output")
                if output:
                    tool_calls = getattr(output, "tool_calls", [])
                    if tool_calls:
                        for tc in tool_calls:
                            log.debug("[llm]  tool_call → %s(%s)", tc["name"], tc.get("args", {}))
                    else:
                        content = getattr(output, "content", "")
                        log.debug("[llm]  text response: %s", str(content)[:200])
                        reply = str(content)

            elif kind == "on_tool_start":
                log.debug("[tool] calling %s  args=%s", name, event["data"].get("input", {}))

            elif kind == "on_tool_end":
                output = str(event["data"].get("output", ""))[:200]
                log.debug("[tool] %s → %s", name, output)

        return reply

    async def close(self):
        pass  # MultiServerMCPClient v0.1+ manages its own connection lifecycle
