import asyncio
import logging
import os
import sys
import gradio as gr
from dotenv import load_dotenv

from agent.graph import MeridianAgent

load_dotenv(override=True)


def _setup_logging() -> None:
    debug = "--debug" in sys.argv
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # silence noisy libraries at INFO level
    for noisy in ("httpx", "httpcore", "gradio", "urllib3", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not debug else logging.DEBUG)
    if debug:
        from langchain_core.globals import set_debug
        set_debug(True)  # prints full LLM prompts + responses to stdout


_setup_logging()


async def setup_agent() -> MeridianAgent:
    agent = MeridianAgent()
    await agent.setup()
    return agent


async def process_message(
    agent: MeridianAgent,
    message: str,
    history: list,
) -> tuple[list, MeridianAgent]:
    if not message.strip():
        return history, agent
    _, new_history = await agent.chat(message, history)
    return new_history, agent


async def reset_session() -> tuple[list, str, MeridianAgent]:
    new_agent = MeridianAgent()
    await new_agent.setup()
    return [], "", new_agent


def free_resources(agent: MeridianAgent):
    if not agent:
        return
    try:
        asyncio.run(agent.close())
    except RuntimeError:
        pass  # e.g. already inside a running event loop
    except Exception:
        pass


with gr.Blocks(title="Meridian Support") as ui:
    gr.Markdown("## Meridian Electronics — Customer Support")
    gr.Markdown(
        "Ask about product availability, check your orders, or place a new order. "
        "Account features require your email and PIN."
    )

    agent_state = gr.State(delete_callback=free_resources)

    chatbot = gr.Chatbot(
        label="Support Chat",
        height=450,
        buttons=["copy"],
    )

    with gr.Row():
        message_box = gr.Textbox(
            label="Your message",
            placeholder="e.g. Is the MX500 keyboard in stock?",
            scale=8,
        )
        send_btn = gr.Button("Send", variant="primary", scale=1)

    reset_btn = gr.Button("New conversation", variant="stop")

    ui.load(setup_agent, inputs=[], outputs=[agent_state])

    message_box.submit(
        process_message,
        inputs=[agent_state, message_box, chatbot],
        outputs=[chatbot, agent_state],
    ).then(lambda: "", outputs=[message_box])

    send_btn.click(
        process_message,
        inputs=[agent_state, message_box, chatbot],
        outputs=[chatbot, agent_state],
    ).then(lambda: "", outputs=[message_box])

    reset_btn.click(
        reset_session,
        inputs=[],
        outputs=[chatbot, message_box, agent_state],
    )


if __name__ == "__main__":
    # Hugging Face Spaces / Docker: bind all interfaces; respect PORT when set.
    _port = int(os.environ.get("PORT", os.environ.get("GRADIO_SERVER_PORT", "7860")))
    ui.launch(
        server_name="0.0.0.0",
        server_port=_port,
        inbrowser=os.getenv("SPACE_ID") is None and "--no-browser" not in sys.argv,
        theme=gr.themes.Default(primary_hue="blue"),
    )
