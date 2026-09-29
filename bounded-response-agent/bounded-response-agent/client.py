"""
MCP client + agent loop for the Bounded Response Agent.

This is the 'host' for the assignment: it starts server.py over stdio, discovers its
tools via MCP, hands their schemas to Claude, and executes whichever tool calls Claude
requests -- looping until Claude gives a final text answer. Requires ANTHROPIC_API_KEY
in the environment.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python client.py "Which source IP has been hitting db01 with denied connections, and can you quarantine it?"
"""
import asyncio
import json
import sys

from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "claude-sonnet-4-6"
SERVER_CMD = sys.executable
SERVER_ARGS = ["server.py"]


def mcp_tools_to_anthropic(tools) -> list[dict]:
    """Convert MCP tool definitions into Anthropic's tool-use schema."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


async def run_agent(goal: str) -> None:
    client = Anthropic()
    params = StdioServerParameters(command=SERVER_CMD, args=SERVER_ARGS)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            discovered = await session.list_tools()
            tools = mcp_tools_to_anthropic(discovered.tools)
            print(f"[client] discovered tools: {[t['name'] for t in tools]}\n")

            messages = [{"role": "user", "content": goal}]

            for turn in range(8):  # safety cap on agent loop length
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    tools=tools,
                    messages=messages,
                )

                # Print any reasoning/text Claude produced this turn.
                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        print(f"[claude] {block.text.strip()}\n")

                if response.stop_reason != "tool_use":
                    print("[client] final answer above.")
                    return

                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    print(f"[tool_call] {block.name}({json.dumps(block.input)})")
                    result = await session.call_tool(block.name, block.input)
                    text = " ".join(c.text for c in result.content if hasattr(c, "text"))
                    status = "ERROR" if result.is_error else "ok"
                    print(f"[tool_result:{status}] {text}\n")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": text,
                            "is_error": result.is_error,
                        }
                    )
                messages.append({"role": "user", "content": tool_results})

            print("[client] stopped after max turns without a final answer.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python client.py \"<goal for the agent>\"")
        sys.exit(1)
    asyncio.run(run_agent(sys.argv[1]))
