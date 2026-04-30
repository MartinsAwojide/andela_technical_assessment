# Meridian Electronics — Customer Support Chatbot

AI-powered customer support agent for Meridian Electronics. Handles product availability lookups, customer authentication, order history, and order placement via a live MCP server backend.

---

## Overview

| Component | Detail |
| --- | --- |
| **LLM** | OpenRouter (default: `openai/gpt-4o-mini`) — swappable to Anthropic or Google via env var |
| **Agent framework** | LangGraph — explicit state machine with tool-call routing |
| **Tools** | 8 MCP tools over Streamable HTTP (no direct DB access) |
| **UI** | Gradio `gr.Blocks` chat interface |
| **Auth** | Per-session email + PIN via `verify_customer_pin` MCP tool |
| **Memory** | In-memory per session (`MemorySaver` + `thread_id`) |

---

## Architecture

```text
Browser
  │
  ▼
Gradio UI (app.py)
  │  gr.State holds MeridianAgent instance for the session
  ▼
MeridianAgent (agent/graph.py)
  │  LangGraph StateGraph compiled with MemorySaver checkpointer
  │
  ├─► worker node (agent/nodes.py)
  │     LLM with all MCP tools bound
  │     Injects SYSTEM_PROMPT on first turn
  │
  ├─► tools node (LangGraph ToolNode)
  │     Executes MCP tool calls returned by the LLM
  │
  └─► conditional router
        tool_calls present → tools node → worker node
        no tool_calls      → END (reply sent to UI)
  │
  ▼
MultiServerMCPClient (agent/mcp_client.py)
  │  langchain-mcp-adapters over Streamable HTTP
  ▼
MCP Server — GCP Cloud Run
  order-mcp: 8 tools (list_products, search_products, get_product,
             verify_customer_pin, get_customer, list_orders,
             get_order, create_order)
```

### Agent state

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # full conversation history
    authenticated: bool
    customer_email: Optional[str]
    session_token: Optional[str]
    auth_attempts: int
```

### File layout

```text
andela_technical_assessment/
├── app.py                  # Gradio UI entry point
├── agent/
│   ├── graph.py            # MeridianAgent class + LLM factory
│   ├── nodes.py            # worker node + tool_router
│   ├── mcp_client.py       # MultiServerMCPClient wrapper
│   ├── state.py            # AgentState TypedDict
│   └── prompts.py          # SYSTEM_PROMPT
├── test_mcp_tools.py       # MCP tool test suite (46 tests)
├── pyproject.toml          # uv project
├── .env.example            # env var template (no secrets)
└── BUILD_PLAN.md           # original design document
```

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
- An [OpenRouter](https://openrouter.ai) API key (or Anthropic / Google key)

### Install

```bash
git clone https://github.com/MartinsAwojide/andela_technical_assessment
cd andela_technical_assessment
uv sync
```

### Configure

```bash
cp .env.example .env
```

Edit `.env` and fill in your key:

```dotenv
# MCP Server (pre-configured, no changes needed)
MCP_SERVER_URL=https://order-mcp-74afyau24q-uc.a.run.app/mcp

# LLM — openrouter | anthropic | google
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4o-mini

OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

To switch providers, change `LLM_PROVIDER` and `LLM_MODEL`:

| Provider | `LLM_PROVIDER` | Example `LLM_MODEL` | Key var |
| --- | --- | --- | --- |
| OpenRouter | `openrouter` | `openai/gpt-4o-mini` | `OPENROUTER_API_KEY` |
| Anthropic | `anthropic` | `claude-haiku-4-5-20251001` | `ANTHROPIC_API_KEY` |
| Google | `google` | `gemini-2.0-flash` | `GOOGLE_API_KEY` |

---

## Run

```bash
uv run python app.py
```

Opens the Gradio chat UI at `http://localhost:7860`.

### Example conversations

#### Product lookup (no login required)

```text
You:  Do you have any 27-inch monitors in stock?
Bot:  Yes — here are the available 27-inch monitors: ...
```

#### Authenticated flow

```text
You:  I'd like to check my order history.
Bot:  I'll need to verify your identity. Please share your email and PIN.
You:  donaldgarcia@example.net / 7912
Bot:  Identity confirmed. Here are your 14 orders: ...
```

#### Place an order

```text
You:  I'd like to order one MON-0054.
Bot:  Order placed — Order ID: 39632648, Total: $166.85 USD.
```

---

## Test

The test suite covers all 8 MCP tools across two modes.

### Full suite — structured pass/fail (46 tests)

Uses `langchain-mcp-adapters` — the same path as the chatbot.

```bash
uv run python test_mcp_tools.py
```

Expected output: `Results: 46/46 passed`

### Demo mode — narrative JSON-RPC walkthrough

Uses `httpx` directly (no adapter) to show raw server responses at each step.

```bash
uv run python test_mcp_tools.py --demo
```

Walks through the full customer journey: browse → search → product detail → authenticate → order history → place order → confirm.

### What is tested

| Section | Tests |
| --- | --- |
| `list_products` | All products, 5 category filters, active/inactive flags |
| `search_products` | 5 keyword searches including a no-match case |
| `get_product` | 2 known SKUs, 1 invalid SKU |
| `verify_customer_pin` | All 10 test customers, wrong PIN, unknown email |
| `get_customer` | 3 verified customers, invalid UUID |
| `list_orders` | Unfiltered, by customer, all 5 status filters |
| `get_order` | Known order ID, invalid UUID |
| `create_order` | Valid order, over-inventory, invalid customer, invalid SKU |
