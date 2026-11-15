"""smolagents toy entry point, run under the tracer by runner.py.

The model is the repo's real OpenAIModel class with a fake client object in
place of openai.OpenAI (ApiModel accepts `client=`), so OpenAIModel.generate,
_prepare_completion_kwargs, the rate limiter and the retryer all run, and
the only thing faked is the HTTP call: the fake returns canned replies. No
network, no API key, the openai package is never imported.
"""

import json
from types import SimpleNamespace

from smolagents import CodeAgent, ToolCallingAgent, tool
from smolagents.models import OpenAIModel

MODEL_ID = "canned-model"
TASK = "What is 2 + 3?"

# A real OpenAI-compatible server stops at the "</code>" stop sequence, so the
# canned code reply ends before it (CodeAgent appends it itself).
CODE_REPLY = ("Thought: I will add the numbers with the tool.\n"
              "<code>\nresult = add(2, 3)\nfinal_answer(result)\n")
TOOL_REPLIES = [
    ("I will add the numbers.", "add", {"a": 2, "b": 3}),
    ("I can answer now.", "final_answer", {"answer": 5}),
]

CONFIG = {
    "model": "OpenAIModel(model_id=%r, client=FakeOpenAIClient)" % MODEL_ID,
    "fake client": "chat.completions.create returns canned replies in order",
    "tool": "@tool add(a: int, b: int) -> int",
    "task": TASK,
    "CodeAgent": "CodeAgent(tools=[add], model=...) defaults: local "
                 "executor, verbosity INFO, max_steps 20; 1 step",
    "CodeAgent reply": "Thought + <code> result = add(2, 3); "
                       "final_answer(result) (no closing tag)",
    "ToolCallingAgent": "ToolCallingAgent(tools=[add], model=...) defaults; "
                        "2 steps (add, then final_answer)",
}

SKIPS = [
    ("the HTTP request: openai.OpenAI is replaced by a fake client",
     "src/smolagents/models.py", "return openai.OpenAI(**self.client_kwargs)"),
    ("streaming output (stream_outputs=False is the default)",
     "src/smolagents/agents.py", "output_stream = self.model.generate_stream("),
    ("planning steps (planning_interval=None)", "src/smolagents/agents.py",
     "for element in self._generate_planning_step("),
    ("remote executors (e2b, docker, modal, blaxel); local executor only",
     "src/smolagents/agents.py", "remote_executors = {"),
    ("errors and retries: the fake never fails, so no retry, no error step",
     "src/smolagents/agents.py", "action_step.error = e"),
    ("max-steps fallback (each run ends with a final answer)",
     "src/smolagents/agents.py", "final_answer = self._handle_max_steps_reached(task)"),
    ("parallel tool calls in a thread pool (one call per reply here)",
     "src/smolagents/agents.py",
     "with ThreadPoolExecutor(self.max_tool_threads) as executor:"),
    ("managed agents, images, structured outputs, step callbacks",
     "src/smolagents/agents.py", "self._setup_managed_agents(managed_agents)"),
]


@tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: The first integer.
        b: The second integer.
    """
    return a + b


class _ToolCall:
    """Like the openai SDK's tool-call object: has model_dump()."""

    def __init__(self, i, name, arguments):
        self._d = {"id": "call_%d" % i, "type": "function",
                   "function": {"name": name, "arguments": json.dumps(arguments)}}

    def model_dump(self):
        return json.loads(json.dumps(self._d))


class FakeOpenAIClient:
    """Stands in for openai.OpenAI. Records the request keys it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.request_keys = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.request_keys.append(sorted(kwargs))
        content, tool_calls = self.replies.pop(0)
        message = SimpleNamespace(role="assistant", content=content,
                                  tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


def versions():
    import smolagents
    return {"smolagents": smolagents.__version__}


def setup():
    code_client = FakeOpenAIClient([(CODE_REPLY, None)])
    tool_client = FakeOpenAIClient(
        [(text, [_ToolCall(i, name, args)])
         for i, (text, name, args) in enumerate(TOOL_REPLIES)])
    return {"code_client": code_client, "tool_client": tool_client,
            "results": {}}


def code_model_init(ctx):
    ctx["code_model"] = OpenAIModel(model_id=MODEL_ID, client=ctx["code_client"])


def code_agent_init(ctx):
    ctx["code_agent"] = CodeAgent(tools=[add], model=ctx["code_model"])


def code_agent_run(ctx):
    answer = ctx["code_agent"].run(TASK)
    ctx["results"]["CodeAgent answer"] = answer
    ctx["results"]["CodeAgent steps in memory"] = len(ctx["code_agent"].memory.steps)
    ctx["results"]["CodeAgent model calls"] = len(ctx["code_client"].request_keys)


def tool_agent_init(ctx):
    model = OpenAIModel(model_id=MODEL_ID, client=ctx["tool_client"])
    ctx["tool_agent"] = ToolCallingAgent(tools=[add], model=model)


def tool_agent_run(ctx):
    answer = ctx["tool_agent"].run(TASK)
    ctx["results"]["ToolCallingAgent answer"] = answer
    ctx["results"]["ToolCallingAgent model calls"] = len(ctx["tool_client"].request_keys)


PHASES = [
    ("model_init", "OpenAIModel(model_id, client=fake)", code_model_init),
    ("code_agent_init", "CodeAgent(tools=[add], model=model)", code_agent_init),
    ("code_agent_run", "code_agent.run(TASK)", code_agent_run),
    ("tool_agent_init", "OpenAIModel(...) + ToolCallingAgent(...)",
     tool_agent_init),
    ("tool_agent_run", "tool_agent.run(TASK)", tool_agent_run),
]
