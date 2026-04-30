import os
from langchain_mcp_adapters.client import MultiServerMCPClient


def _server_config() -> dict:
    url = os.getenv("MCP_SERVER_URL")
    if not url:
        raise RuntimeError("MCP_SERVER_URL is not set in environment")
    return {
        "meridian": {
            "url": url,
            "transport": "streamable_http",
        }
    }


def make_client() -> MultiServerMCPClient:
    """Create a MultiServerMCPClient instance (v0.1+ API — no context manager)."""
    return MultiServerMCPClient(_server_config())


async def load_tools(client: MultiServerMCPClient) -> list:
    """Fetch and return LangChain-compatible tools from the MCP server."""
    return await client.get_tools()
