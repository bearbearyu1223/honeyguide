"""waku-agent toy entry point, run under the tracer by runner.py.

One real Waku (waku/app.py) built with a scripted fake model client: the
client argument is the repo's own seam ("evals swap in a scripted model"),
so Waku.respond, the retrieval gate, the loop, the tools, consolidation,
the receipt and the triage graph all run, and the only thing faked is the
model's HTTP call. Every reply is scripted in order and labelled with the
call it must answer (gate, loop, final, consolidation, triage, quick); a call
that doesn't match the script, or a script not used up, fails the run.

State lives in a throwaway HOME and WAKU_HOME (SQLite state.db, MEMORY.md,
the outbox, the JSONL trace), made fresh per process and removed at exit.
Before waku is imported: every WAKU_* variable and every API key or token is
removed from the environment, TZ is UTC, and the working directory is the
capture's temp dir, so no .env is found. No network: the client never
leaves the process, and the search, calendar-sync, MCP and plugin paths are
switched off.

The triage graph runs its first wave (classify, check_calendar) on a thread
pool. Which thread reaches repo code first is a race, so the entry swaps the
engine's ThreadPoolExecutor for one that runs each submitted node to the end
on its own pool thread before the next is submitted (submit order). The
nodes still run on pool threads, one at a time instead of overlapping.
"""

import atexit
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS

# ---- environment, before waku is imported (config.py reads it at import)
for _k in list(os.environ):
    if (_k.startswith("WAKU_") or _k.endswith(("_API_KEY", "_TOKEN", "_SECRET"))
            or _k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "ANTHROPIC_BASE_URL",
                      "OPENAI_BASE_URL")):
        del os.environ[_k]
HOME = tempfile.mkdtemp(prefix="honeyguide-waku-")
atexit.register(shutil.rmtree, HOME, True)
os.environ["HOME"] = HOME
os.environ["WAKU_HOME"] = os.path.join(HOME, ".waku")
os.environ["TZ"] = "UTC"
time.tzset()

import waku  # noqa: E402
import waku.graph.engine as graph_engine  # noqa: E402
from waku.app import Waku  # noqa: E402
from waku.config import Settings  # noqa: E402

MODEL, SMALL = "scripted-model", "scripted-small-model"
CONSOLIDATE_EVERY = 3
LIMIT_ITERATIONS = 2

# A long note, so the turn that reads it back has a tool result over
# waku/loop/trim.py's LONG_CHARS (4000) to cut before a later call.
AGENDA = " ".join("Item %d: review the Acme demo plan with Alex, owners and dates."
                  % i for i in range(1, 76))

TURNS = {
    "turn_tool": "Remember this agenda for my meetings with Alex: " + AGENDA[:60] + "...",
    "turn_limit": "What did I save about Alex? Then draft him a message about it.",
    "turn_consolidate": "Thanks. For the record, I prefer meetings before 10am.",
    "graph_quick": "thanks!",
    "graph_full": "What do you know about Alex?",
}

CONFIG = {
    "app": "Waku(settings, client=ScriptedClient) from waku/app.py",
    "fake client": "messages.create returns scripted replies in order; "
                   "each is checked against the call it answers",
    "settings": "model %r, small_model %r, consolidate_every %d, "
                "max_iterations 15 (2 in turn_limit), history_turns 12, "
                "graph_workflows off (on in graph_*), apple/google calendar, "
                "apple tools, gh, experimental off"
                % (MODEL, SMALL, CONSOLIDATE_EVERY),
    "home": "throwaway HOME and WAKU_HOME (state.db, MEMORY.md, outbox, "
            "traces), TZ=UTC, WAKU_* and API keys unset",
    "turn_tool": "gate retrieve 'alex' (empty memory); save_note(subject "
                 "'alex', content: a %d-character agenda); reply"
                 % len(AGENDA),
    "turn_limit": "max_iterations 2: gate retrieve 'alex' (finds the note); "
                  "manage_memory search 'alex'; send_message to Alex; "
                  "limit hit, one tools-off final call",
    "turn_consolidate": "gate skip; plain reply; consolidation due (6 "
                        "unconsolidated rows): 2 facts proposed, 1 an ops "
                        "fact that is dropped; 1 episode",
    "graph_quick": "graph_workflows on: triage says quick; quick reply",
    "graph_full": "graph_workflows on: triage says full; gate retrieve "
                  "'alex'; plain reply",
    "graph pool": "first wave run one node at a time on pool threads, "
                  "in submit order (see SKIPS)",
}

SKIPS = [
    ("the HTTP request: the model client is a scripted fake (get_client "
     "is never called)", "waku/app.py",
     "self.client = client or get_client(self.settings)"),
    ("streaming replies (stream=False, the CLI default)",
     "waku/loop/agent.py", "with client.messages.stream("),
    ("MCP servers, Waku Memory and plugins: no mcp.json, no plugin, so no "
     "bridge, no remember, no hooks", "waku/tools/__init__.py",
     "if mcp_config.exists() or plugin_servers:"),
    ("plugin hooks (SessionStart, UserPromptSubmit, PreToolUse deny, Stop "
     "thread)", "waku/app.py",
     "if self.hooks is None or source not in GATEWAY_SOURCES:"),
    ("research turns that read Waku Memory first (needs the bridge)",
     "waku/app.py",
     "known = brain.read_first(user_message, self.brain_search, self.brain_get)"),
    ("sending a research report to Waku Memory (no remember)",
     "waku/memory/reports.py",
     "memory_id = remember(report.body, scope, kind=KIND)"),
    ("other memory stores (supabase, mem0, zep, langmem, notion); SQLite "
     "only", "waku/memory/__init__.py",
     'if settings.semantic_store == "supabase":'),
    ("the Jev slot gate (off without WAKU_SLOT_GATE=jev)",
     "waku/memory/slot_gate.py", 'os.environ.get("WAKU_SLOT_GATE", "")'),
    ("OpenTelemetry export (JSONL trace only)", "waku/ops/tracing.py",
     "if not settings.otel_endpoint:"),
    ("opt-in tools: experimental, Apple, GitHub; web search is offered but "
     "never called", "waku/tools/__init__.py", "if settings.apple_tools:"),
    ("failures: the fake never fails, so no gate or triage fail-open, no "
     "tool error text, no failed final answer", "waku/loop/agent.py",
     'log.warning("the final answer after the iteration limit failed'),
    ("the triage graph's overlapping first wave: its two nodes run one "
     "after the other here", "waku/graph/engine.py",
     "with ThreadPoolExecutor(max_workers=len(wave)) as pool:"),
    ("gateways (Telegram, Discord, WhatsApp, voice), the dashboard, and "
     "everything under hosted/ (never imported)", "waku/gateway/runner.py",
     "class GatewayAgentRunner"),
]


# --------------------------------------------------------------------------
# The scripted client

def _usage():
    return NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
              cache_creation_input_tokens=0)


def text_reply(text):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn",
              usage=_usage())


def tool_reply(text, call_id, name, args):
    return NS(content=[NS(type="text", text=text),
                       NS(type="tool_use", id=call_id, name=name, input=args)],
              stop_reason="tool_use", usage=_usage())


PROMPT_KINDS = (
    ("You are a retrieval gate", "gate"),
    ("You are a triage gate", "triage"),
    ("You distill", "consolidation"),
    ("You are Waku, a warm", "quick"),
)


def call_kind(kwargs):
    """Which of waku's model calls this is, from the request alone."""
    if "tool_choice" in kwargs:
        return "final"
    if "system" in kwargs:
        return "loop"
    content = kwargs["messages"][0]["content"]
    for prefix, kind in PROMPT_KINDS:
        if isinstance(content, str) and content.startswith(prefix):
            return kind
    return "other"


class ScriptedMessages:
    def __init__(self):
        self.script, self.calls, self.last = [], [], {}

    def load(self, script):
        if self.script:
            raise AssertionError("previous script not used up: %r" % self.script)
        self.script = list(script)

    def create(self, **kwargs):
        kind = call_kind(kwargs)
        self.calls.append(kind)
        self.last[kind] = kwargs
        if not self.script:
            raise AssertionError("unscripted model call: %s" % kind)
        want, reply = self.script.pop(0)
        if want != kind:
            raise AssertionError("script expected %s, got %s" % (want, kind))
        return reply


class ScriptedClient:
    def __init__(self):
        self.messages = ScriptedMessages()


class InOrderPool:
    """Stands in for ThreadPoolExecutor in waku.graph.engine: each submit runs
    its node to the end on a pool thread of its own, before returning. The
    threads stay alive until the pool closes, so each is a distinct thread."""

    def __init__(self, max_workers=None):
        self._pools = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for pool in self._pools:
            pool.shutdown(wait=True)
        return False

    def submit(self, fn, *args, **kwargs):
        pool = ThreadPoolExecutor(max_workers=1)
        self._pools.append(pool)
        future = pool.submit(fn, *args, **kwargs)
        future.exception()          # wait for it to finish
        return future


# --------------------------------------------------------------------------

def versions():
    import anthropic
    return {"waku-agent": waku.__version__, "anthropic": anthropic.__version__}


def setup():
    graph_engine.ThreadPoolExecutor = InOrderPool
    settings = Settings(
        provider="anthropic", api_key="", base_url=None, model=MODEL,
        small_model=SMALL, home=Path(os.environ["WAKU_HOME"]),
        max_iterations=15, max_tokens=8192, history_turns=12,
        unavailable_tools=(), consolidate_every=CONSOLIDATE_EVERY,
        memory_mode="", retrieval_top_k=4, semantic_store="sqlite",
        episodic_store="sqlite", apple_calendar=False, google_calendar=False,
        apple_tools=False, gh_tool=False, experimental=False,
        graph_workflows=False, otel_endpoint="")
    return {"settings": settings, "client": ScriptedClient(), "results": {}}


def _turn(ctx, phase, script):
    client = ctx["client"]
    client.messages.load(script)
    before = len(client.messages.calls)
    result = ctx["waku"].respond(TURNS[phase])
    client.messages.load([])          # raises if the script was not used up
    calls = client.messages.calls[before:]
    ctx["results"]["%s model calls" % phase] = " ".join(calls)
    return result


def init(ctx):
    ctx["waku"] = Waku(settings=ctx["settings"], client=ctx["client"])
    ctx["results"]["tools offered"] = len(ctx["waku"].tools.schemas())


def turn_tool(ctx):
    r = _turn(ctx, "turn_tool", [
        ("gate", text_reply('{"retrieve": true, "query": "alex", '
                            '"reason": "about a person"}')),
        ("loop", tool_reply("I'll save that.", "tu_1", "save_note",
                            {"subject": "alex", "content": AGENDA})),
        ("loop", text_reply("Saved your agenda for Alex.")),
    ])
    ctx["results"]["turn_tool reply"] = r.reply


def turn_limit(ctx):
    settings = ctx["waku"].settings
    settings.max_iterations = LIMIT_ITERATIONS
    try:
        r = _turn(ctx, "turn_limit", [
            ("gate", text_reply('{"retrieve": true, "query": "alex", '
                                '"reason": "asks about memory"}')),
            ("loop", tool_reply("Let me look.", "tu_2", "manage_memory",
                                {"action": "search", "query": "alex"})),
            ("loop", tool_reply("Drafting it.", "tu_3", "send_message",
                                {"to": "Alex", "body": "Here is the agenda."})),
            ("final", text_reply("You saved an agenda; a draft to Alex is in "
                                 "your outbox.")),
        ])
    finally:
        settings.max_iterations = 15
    out = r.tool_calls[0]["output"]
    ctx["results"]["turn_limit limit reached"] = r.limit_reached
    ctx["results"]["turn_limit iterations"] = r.iterations
    ctx["results"]["manage_memory output chars"] = len(out)
    # the messages list the final call was sent (the loop mutates it in
    # place, so this is what it held after trimming)
    sent = [len(b["content"]) for m in ctx["client"].messages.last["final"]["messages"]
            if isinstance(m.get("content"), list)
            for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    ctx["results"]["tool results in final call"] = " ".join(
        "%d chars" % n for n in sent)


def turn_consolidate(ctx):
    r = _turn(ctx, "turn_consolidate", [
        ("gate", text_reply('{"retrieve": false, "query": "", '
                            '"reason": "states a preference"}')),
        ("loop", text_reply("Noted: mornings before 10am.")),
        ("consolidation", text_reply(
            '{"facts": [{"subject": "user", "content": "The user prefers '
            'meetings before 10am."}, {"subject": "treg", "content": "The '
            'treg balance is $0.75 USD."}], "episode": "Planned meetings '
            'with Alex.", "company_research": false}')),
    ])
    conn = ctx["waku"].conn
    ctx["results"]["turn_consolidate reply"] = r.reply
    ctx["results"]["facts after consolidation"] = conn.execute(
        "SELECT COUNT(*) FROM facts").fetchone()[0]
    ctx["results"]["episodes after consolidation"] = conn.execute(
        "SELECT COUNT(*) FROM episodes").fetchone()[0]


def graph_quick(ctx):
    ctx["waku"].settings.graph_workflows = True
    r = _turn(ctx, "graph_quick", [
        ("triage", text_reply('{"route": "quick", "reason": "just thanks"}')),
        ("quick", text_reply("You're welcome!")),
    ])
    ctx["results"]["graph_quick reply"] = r.reply


def graph_full(ctx):
    try:
        r = _turn(ctx, "graph_full", [
            ("triage", text_reply('{"route": "full", "reason": "asks memory"}')),
            ("gate", text_reply('{"retrieve": true, "query": "alex", '
                                '"reason": "about a person"}')),
            ("loop", text_reply("You saved an agenda for Alex.")),
        ])
    finally:
        ctx["waku"].settings.graph_workflows = False
    ctx["results"]["graph_full reply"] = r.reply


PHASES = [
    ("init", "Waku(settings, client=ScriptedClient())", init),
    ("turn_tool", "waku.respond(...): gate, save_note, reply", turn_tool),
    ("turn_limit", "waku.respond(...) with max_iterations=2: two tool "
                   "calls, then the tools-off final call", turn_limit),
    ("turn_consolidate", "waku.respond(...): reply, then consolidation",
     turn_consolidate),
    ("graph_quick", "waku.respond('thanks!') with graph_workflows on: "
                    "quick route", graph_quick),
    ("graph_full", "waku.respond(...) with graph_workflows on: full route",
     graph_full),
]

if __name__ == "__main__":
    sys.exit("run through eval/trace/capture.py")
