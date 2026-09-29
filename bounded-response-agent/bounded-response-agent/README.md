# Bounded Response Agent

## Project description
A small SOC (security operations center) assistant for a junior analyst. It can freely
investigate the network — look up devices and read firewall logs — but it is *bounded*
when it comes to taking action: it will only quarantine a host if that host is inside its
authorized response scope (`in_scope=true` in the inventory). Core infrastructure and
firewalls are outside that scope; the agent must refuse and say to escalate instead of
acting. This models the access-control idea that read authority and act authority can be
different boundaries, even for the same agent.

Data: `data/devices.csv` (a small inventory with an `in_scope` flag per device) and
`data/events.csv` (a firewall log). `data/actions_log.csv` starts empty and records any
quarantine actions taken during a session.

A task that needs multiple tools: "investigate this IP's denied traffic, find out which
host it is, and quarantine it if you're allowed to" — one tool's output (the denied
source IP, or the resolved hostname) feeds the next tool's input.

## Tools
| Tool | Purpose | Bounded? | Validation |
|---|---|---|---|
| `lookup_device(hostname)` | Hostname -> IP, role, VLAN, in_scope | No (read) | Unknown host -> error |
| `get_events_for_ip(ip, action?, limit=20)` | Firewall events for an IP | No (read) | Valid IP, action in {allow, deny}, 1<=limit<=100 |
| `summarize_denied_by_source(min_count=1)` | Denied-connection counts per source IP | No (read) | min_count >= 1 |
| `quarantine_host(hostname, reason)` | The one response action: quarantine a device | **Yes** | Unknown host -> error; out-of-scope host -> refused with escalation message; empty reason -> error; repeat call -> idempotent, returns the original record instead of double-acting |

Errors are raised as `ToolError` (not plain `ValueError`) so the message reaches the
calling model — in SDK 2.x a plain `ValueError` is otherwise masked as a generic
"Error executing tool".

## Setup
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # mcp==2.2.0, Python 3.10+
python verify_tools.py                 # protocol-level check of all 4 tools, no LLM needed
```
Before each fresh demo run, reset the action log so quarantine behaves the same way twice:
```
echo "hostname,quarantined_at,reason" > data/actions_log.csv
```

**Option A — your own client (`client.py`, included).** This is the MCP client/host for
this assignment: it starts `server.py` over stdio, discovers tools via MCP, converts
their schemas for the Gemini API, sends your goal to Gemini, executes whatever tool
calls Gemini requests, feeds the results back, and loops until Gemini gives a final
answer. Requires a Gemini API key:
```
export GEMINI_API_KEY=...
python client.py "Which source IP has been hitting db01 with denied connections, and can you quarantine it?"
```
It prints every tool call, its arguments, the raw result, and Gemini's final answer — that
output *is* the demonstration trace, paste it straight into the sections below. Model:
`gemini-3.8-flash` (change `MODEL` in `client.py` if you use a different one).

**Option B — an existing host (e.g. Claude Desktop).** Copy
`claude_desktop_config.example.json` into the host's MCP config, replace the placeholder
paths with absolute paths on your machine, restart the host, and run the same three
prompts there instead.

## Demonstration traces (fresh conversation each, same config)
For each run, paste the host's actual tool-call view: tool name, arguments, returned
result, and the assistant's final answer.

**A. Successful task, dependent tool calls.**
Prompt: "Which source IP has been hitting db01 with denied connections, and can you
quarantine it?"
Expected shape: `get_events_for_ip(ip=<db01's IP>, action=deny)` or
`summarize_denied_by_source` to find the source -> `lookup_device` to resolve that IP to
a hostname -> `quarantine_host(hostname, reason)` using the hostname found in the
previous step.
<PASTE TRACE>

**B. Different request, different tool combination.**
Prompt: "Is core-sw1 seeing any denied traffic, and would you be able to quarantine it if
needed?"
Expected shape: `lookup_device(core-sw1)` -> `get_events_for_ip` -> an attempted
`quarantine_host(core-sw1, ...)` that is refused for being out of scope, with the
assistant relaying the escalation message rather than claiming success.
<PASTE TRACE>

**C. Invalid input / failed call, handled without inventing success.**
Prompt: "Quarantine the host printer07, it looks suspicious."
Expected shape: `quarantine_host(printer07, ...)` (or a `lookup_device` first) returns a
"no device named" error; the assistant reports that printer07 isn't in the inventory and
does not claim it was quarantined.
<PASTE TRACE>

## Architecture (150-250 words)
<WRITE IN YOUR OWN WORDS>
Cover: what the MCP server owns (tool implementations, data, the scope/validation rules),
what the MCP client does (the host app: discovers tools via MCP, sends the schema to the
model, executes whichever calls the model requests, returns results to the model), and
what the LLM does (reads the user's goal, decides which tools to call and in what order,
reads each result before deciding the next call, composes the final answer). Note that
tool authority (like the in_scope boundary) is enforced by the server, not by asking the
model nicely — the model can request `quarantine_host` on anything, but only the server
decides whether it happens.

## Limitation observed
<FILL IN from your actual runs, e.g.: the model sometimes calls quarantine_host directly
on a hostname mentioned in the prompt without first calling lookup_device to confirm it
exists, relying on the tool's own error instead of checking first; or: scope is a boolean
per device, so it can't express a device that's readable-but-partially-actionable.>
