"""
MCP client + agent loop for the Bounded Response Agent.

This is the 'host' for the assignment: it starts server.py over stdio, discovers its
tools via MCP, hands their schemas to Gemini, and executes whichever tool calls Gemini
requests -- looping until Gemini gives a final text answer. Requires GEMINI_API_KEY
in the environment.

Usage:
    export GEMINI_API_KEY=...
    python client.py "Which source IP has been hitting db01 with denied connections, and can you quarantine it?"
"""
import asyncio
import json
import os
import sys

from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "gemini-3.8-flash"
SERVER_CMD = sys.executable
SERVER_ARGS = ["server.py"]


def mcp_tools_to_gemini(tools) -> types.Tool:
    """Convert MCP tool definitions into Gemini function declarations."""
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=t.name,
                description=t.description or "",
                parameters_json_schema=t.input_schema,
            )
            for t in tools
        ]
    )


async def run_agent(goal: str) -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")
    client = genai.Client(api_key=api_key)
    params = StdioServerParameters(command=SERVER_CMD, args=SERVER_ARGS)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            discovered = await session.list_tools()
            tools = mcp_tools_to_gemini(discovered.tools)
            print(f"[client] discovered tools: {[t.name for t in discovered.tools]}\n")

            contents = [types.Content(role="user", parts=[types.Part.from_text(text=goal)])]

            for turn in range(8):  # safety cap on agent loop length
                response = client.models.generate_content(
                    model=MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        max_output_tokens=1024,
                        tools=[tools],
                    ),
                )

                content = response.candidates[0].content
                function_calls = []
                for part in content.parts:
                    if part.text and part.text.strip():
                        print(f"[gemini] {part.text.strip()}\n")
                    if part.function_call:
                        function_calls.append(part.function_call)

                if not function_calls:
                    print("[client] final answer above.")
                    return

                contents.append(content)

                tool_results = []
                for call in function_calls:
                    arguments = dict(call.args or {})
                    print(f"[tool_call] {call.name}({json.dumps(arguments)})")
                    result = await session.call_tool(call.name, arguments)
                    text = " ".join(c.text for c in result.content if hasattr(c, "text"))
                    status = "ERROR" if result.is_error else "ok"
                    print(f"[tool_result:{status}] {text}\n")
                    tool_results.append(
                        types.Part.from_function_response(
                            name=call.name,
                            response={"result": text, "is_error": result.is_error},
                        )
                    )
                contents.append(types.Content(role="user", parts=tool_results))

            print("[client] stopped after max turns without a final answer.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python client.py \"<goal for the agent>\"")
        sys.exit(1)
    asyncio.run(run_agent(sys.argv[1]))
