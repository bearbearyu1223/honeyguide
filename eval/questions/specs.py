"""The hand-chosen part of each question set.

Locate questions are phrased by hand from reading each function at the
pinned commit, by behaviour, never by symbol or file name; generate.py
derives every key from the code and the T3 trace, and checks the phrasing
for leaks. Callers questions name their target. Flow questions name their
entry point and the T3 configuration, and say which calls they fold
(collapse into one hop because another question covers what's inside).

Han's why/how questions are written separately (T5) and slot in under
"why_how" in the frozen JSON.
"""

from keys import FlowRules

SPECS = {}

# ==========================================================================
# nanochat @ 92d63d4 (2026-07-03)

SPECS["nanochat"] = {
    "prefix": "nc",
    "flow_rules": FlowRules(drop_classes=(), drop_funcs=("print0",)),
    "locate": [
        # code last changed after 2026-06-30 (inference cost accounting, the
        # datasets-library replacement, the FA3 loader)
        ("nanochat/common.py", "get_peak_bandwidth",
         "Where does the code look up a GPU's peak memory bandwidth from its "
         "device name, the ceiling that decode speed is compared against?"),
        ("nanochat/gpt.py", "GPT.estimate_decode_flops",
         "Where is the forward compute needed to produce one new token at a "
         "given context length estimated, with each layer's attention "
         "capped at its window?"),
        ("nanochat/gpt.py", "GPT.kv_read_bytes",
         "Where is the amount of cached key/value memory that one decoding "
         "step has to load computed, given that sliding-window layers only "
         "look back over their window?"),
        ("scripts/infer_bench.py", "bench_generate",
         "Where is a single timed generation run measured: time to first "
         "token, the time of every later step, and peak GPU memory?"),
        ("tasks/common.py", "load_hub_dataset",
         "Where are a hub dataset's parquet shards listed through the web "
         "API, downloaded once under a file lock and read into one Arrow "
         "table, as a stand-in for the datasets library?"),
        ("nanochat/flash_attention.py", "_load_flash_attention_3",
         "Where does the code decide which downloadable attention kernel to "
         "fetch depending on the GPU's compute capability, returning nothing "
         "when no GPU is available?"),
        # code last changed before 2026-06-30
        ("scripts/base_train.py", "get_lr_multiplier",
         "During base-model pretraining, where is the per-step learning-rate "
         "multiplier computed: linear warmup over a number of steps, flat, "
         "then a linear decay to a final fraction?"),
        ("nanochat/engine.py", "use_calculator",
         "Where is an expression the model writes during generation checked "
         "against allowed characters and banned words, and evaluated only if "
         "it is plain arithmetic or a string .count() call?"),
        ("nanochat/core_eval.py", "find_common_length",
         "In the in-context-learning evaluation, where is the length of the "
         "prefix or suffix shared by several token sequences found?"),
        ("nanochat/gpt.py", "GPT._compute_window_sizes",
         "Where is each layer's attention window chosen by tiling a pattern "
         "of short and long letters across the layers, with the final layer "
         "forced to full context?"),
        ("nanochat/engine.py", "sample_next_token",
         "Where is a token drawn from the logits with a temperature and an "
         "optional top-k cut, using argmax when the temperature is zero?"),
        ("nanochat/tokenizer.py", "RustBPETokenizer.render_conversation",
         "Where is a multi-turn chat turned into token ids plus a mask that "
         "marks which tokens the assistant is trained to produce?"),
    ],
    "callers": [
        ("nanochat/gpt.py", "GPT.estimate_decode_flops"),
        ("nanochat/common.py", "get_peak_bandwidth"),
        ("tasks/common.py", "load_hub_dataset"),
        ("nanochat/engine.py", "KVCache.prefill"),
        ("nanochat/engine.py", "sample_next_token"),
        ("nanochat/gpt.py", "norm"),
        ("nanochat/flash_attention.py", "flash_attn_with_kvcache"),
        ("nanochat/gpt.py", "GPT._precompute_rotary_embeddings"),
        ("nanochat/common.py", "compute_init"),
        ("nanochat/engine.py", "use_calculator"),
    ],
    "flow": [
        {
            "phase": "build",
            "entries": [("GPT.__init__", 0), ("GPT.init_weights", 0)],
            "fold": [],
            "text": "With config GPTConfig(sequence_len=32, n_layer=2, n_head=2, "
                    "n_kv_head=2, n_embd=32, window_pattern='SSSL'), the model is "
                    "built with GPT(config) on the meta device, moved with "
                    "to_empty(device='cpu'), then model.init_weights() is called. "
                    "Which repo functions run, in order?",
        },
        {
            "phase": "forward_loss",
            "entries": [("GPT.forward", 0)],
            "fold": [],
            "text": "Same toy GPTConfig on CPU (n_layer=2, n_embd=32, float32, "
                    "torch.compile off): loss = model(x, y) with x and y random "
                    "token ids of shape (2, 16). Which repo functions run, in "
                    "order, from GPT.forward until the loss is returned?",
        },
        {
            "phase": "optimizer_step",
            "entries": [("MuonAdamW.step", 0)],
            "fold": [],
            "text": "Same toy model on CPU, one process (world size 1), after "
                    "loss.backward(): optimizer.step() on the optimizer returned "
                    "by model.setup_optimizer() with default arguments, with "
                    "torch.compile disabled. Which repo functions run, in order?",
        },
        {
            "phase": "engine_generate",
            "entries": [("Engine.__init__", 0), ("Engine.generate", 0)],
            "fold": ["GPT.forward"],
            "text": "Same toy model and its trained toy tokenizer on CPU: "
                    "Engine(model, tokenizer).generate(prompt_ids, num_samples=1, "
                    "max_tokens=4, temperature=0.6, top_k=50, seed=42), consumed "
                    "to the end. Which repo functions does Engine.generate call, "
                    "in order? (Count each pass through the model as one step; "
                    "what happens inside it is another question.)",
        },
        {
            "phase": "engine_generate",
            "entries": [("GPT.forward", 0)],
            "fold": [],
            "text": "In that generate call, the first model forward pass: "
                    "GPT.forward on the 9-token prompt (batch 1) with a fresh "
                    "KV cache (kv_cache passed, no targets). Which repo "
                    "functions run, in order, until the logits are returned?",
        },
    ],
}

# ==========================================================================
# waku-agent @ 2c7e7e6 (2026-11-14). Questions stay in waku/ (never hosted/).

# waku's own telemetry: the JSONL/OTel Tracer, the observer fan-out that
# feeds it (and the turn's meta capture), and the graph engine's locked
# wrapper around that observer. Each only records what happened.
WAKU_RULES = FlowRules(
    drop_classes=("Tracer",),
    drop_funcs=("compose.<locals>.fanout", "run_graph.<locals>.notify"),
)

WAKU_SETUP = ("Waku(settings, client=<scripted fake model client>) with a fresh "
              "home (empty SQLite state.db), no MCP servers or plugins, "
              "graph_workflows off, consolidate_every=3")

SPECS["waku-agent"] = {
    "prefix": "wk",
    "flow_rules": WAKU_RULES,
    "locate": [
        ("waku/loop/trim.py", "shrink_seen",
         "Before each later model call in a turn, where are long tool results "
         "the model has already read cut to their opening, with a note saying "
         "how long they were?"),
        ("waku/loop/agent.py", "_final_answer",
         "When a turn runs out of steps, where is the one last model call made "
         "with tool use switched off, so the reply comes from what was already "
         "gathered?"),
        ("waku/memory/retrieval_gate.py", "should_retrieve",
         "Where does a small model decide whether a message needs the user's "
         "stored memories at all, returning search keywords, and falling back "
         "to searching when its reply can't be read?"),
        ("waku/memory/consolidation.py", "is_ops_state",
         "When chats are distilled into long-term facts, where is a proposed "
         "fact thrown out because it is about the assistant's own running "
         "condition, such as an account balance, a rate limit or a token "
         "count?"),
        ("waku/memory/consolidation.py", "restates",
         "Where is a proposed fact dropped because it has a number or a date "
         "and every name, number and date in it already appears in the memory "
         "the turn read?"),
        ("waku/config.py", "resolve_home",
         "Where is the folder that holds the assistant's database and files "
         "chosen: an environment variable first, then an older per-folder "
         "location kept until the person copies it, otherwise one under the "
         "user's home directory?"),
        ("waku/graph/engine.py", "run_graph",
         "Where does a workflow of steps run in waves, running the ready steps "
         "of a wave on a thread pool, merging what they return into one shared "
         "dictionary and raising if two write the same key?"),
        ("waku/memory/semantic/store.py", "_fts_query",
         "Where is a user's free text reduced to lowercase word tokens joined "
         "by OR, so it can be used safely as a full-text search over the "
         "SQLite index?"),
        ("waku/memory/procedural/loader.py", "SkillLoader.match",
         "Where are the stored how-to instructions picked for a message, by "
         "counting words it shares with each one's name and description, "
         "re-reading the folder first when a file changed?"),
        ("waku/tools/registry.py", "ToolRegistry.execute",
         "Where is one action the model asked for run so that an unknown name "
         "or an exception comes back to the model as text instead of stopping "
         "the turn?"),
        ("waku/gateway/runner.py", "safe_exception",
         "Where are the values of configured secrets (keys, tokens, "
         "passwords) removed from an error message before it is shown to the "
         "person in a chat app?"),
        ("waku/plugins/hooks.py", "read_output",
         "Where is a plugin hook's JSON answer read for extra context, a "
         "refusal of the action about to run, and a message to show the "
         "person?"),
    ],
    "callers": [
        ("waku/memory/__init__.py", "Memory.gated_retrieve"),
        ("waku/loop/agent.py", "run_loop"),
        ("waku/app.py", "Waku.respond"),
        ("waku/loop/trim.py", "shrink_seen"),
        ("waku/memory/consolidation.py", "kept_if_due"),
        ("waku/tools/registry.py", "ToolRegistry.schemas"),
        ("waku/graph/engine.py", "run_graph"),
        ("waku/memory/tool_note.py", "clip"),
        ("waku/config.py", "resolve_home"),
        ("waku/memory/__init__.py", "Memory.maybe_consolidate"),
    ],
    "flow": [
        {
            "phase": "init",
            "entries": [("Waku.__init__", 0)],
            "fold": ["Memory.__init__", "build_registry"],
            "text": WAKU_SETUP + ". Which repo functions does building the "
                    "agent run, in order? (Count setting up memory, and "
                    "building the tool registry, as one step each.)",
        },
        {
            "phase": "turn_tool",
            "entries": [("Waku.respond", 0)],
            "fold": ["Waku._run_full_turn", "Memory.maybe_consolidate",
                     "Waku._receipt"],
            "text": "That agent's first turn: waku.respond(<a request to "
                    "remember an agenda for Alex>), where the model saves it "
                    "with one save_note call and then replies. Which repo "
                    "functions does respond call, in order? (Count running "
                    "the turn, the consolidation check and the receipt as one "
                    "step each.)",
        },
        {
            "phase": "turn_tool",
            "entries": [("Session.build_system", 0)],
            "fold": [],
            "text": "In that first turn, building the system prompt: "
                    "Session.build_system on the message, where the small "
                    "model's gate replies retrieve=true with query 'alex' and "
                    "memory is still empty. Which repo functions run, in "
                    "order?",
        },
        {
            "phase": "turn_tool",
            "entries": [("run_loop", 0)],
            "fold": [],
            "text": "In that first turn, the loop: run_loop where the model's "
                    "first reply asks for save_note(subject='alex', "
                    "content=<the agenda>) and its second reply is plain "
                    "text. Which repo functions are called, in order, until "
                    "the reply is returned?",
        },
        {
            "phase": "turn_limit",
            "entries": [("run_loop", 0)],
            "fold": ["ToolRegistry.execute"],
            "text": "The second turn, with settings.max_iterations=2: "
                    "run_loop where the model asks for manage_memory "
                    "(search 'alex', a 4,800-character result) and then "
                    "send_message, so the limit is reached. Which repo "
                    "functions are called, in order, until the reply is "
                    "returned? "
                    "(Count each tool's execution as one step.)",
        },
        {
            "phase": "turn_consolidate",
            "entries": [("Memory.maybe_consolidate", 0)],
            "fold": [],
            "text": "The third turn ends with six unconsolidated chat rows "
                    "(consolidate_every=3): Memory.maybe_consolidate, where "
                    "the small model proposes two facts (one about the "
                    "user's meeting times, one an account balance) and one "
                    "episode. Which repo functions run, in order?",
        },
        {
            "phase": "graph_quick",
            "entries": [("Waku._respond_via_graph", 0)],
            "fold": [],
            "text": "The fourth turn, with settings.graph_workflows=True: "
                    "waku.respond('thanks!'), where the triage model answers "
                    "'quick'. Which repo functions does "
                    "Waku._respond_via_graph run, in order, until the quick "
                    "reply is returned?",
        },
        {
            "phase": "graph_full",
            "entries": [("Waku._respond_via_graph", 0)],
            "fold": ["build_triage_graph", "Waku._run_full_turn"],
            "text": "The fifth turn, graph_workflows still on: a question "
                    "about Alex, where the triage model answers 'full'. "
                    "Which repo functions does "
                    "Waku._respond_via_graph run, in order? (Count building "
                    "the graph, and the full turn it hands over to, as one "
                    "step each.)",
        },
    ],
}
