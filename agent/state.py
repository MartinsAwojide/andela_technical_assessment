from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # add_messages reducer accumulates history across turns — never replaces
    messages: Annotated[list[Any], add_messages]
    authenticated: bool
    customer_email: Optional[str]
    session_token: Optional[str]
    auth_attempts: int


def initial_state() -> AgentState:
    return {
        "messages": [],
        "authenticated": False,
        "customer_email": None,
        "session_token": None,
        "auth_attempts": 0,
    }
