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
# smolagents @ e1249d3 (2026-11-15)

SMOL_RULES = FlowRules(
    drop_classes=("AgentLogger", "Monitor", "Timing", "TokenUsage"),
    drop_funcs=(),
)

SPECS["smolagents"] = {
    "prefix": "sa",
    "flow_rules": SMOL_RULES,
    "locate": [
        # newest code in the package (last changed 2026-01 to 2026-05)
        ("src/smolagents/default_tools.py", "WebSearchTool.search_exa",
         "Where is a query sent to the Exa API, with each result's title, "
         "URL and highlights turned into a result entry?"),
        ("src/smolagents/utils.py", "sanitize_for_rich",
         "Where are arbitrary values, bytes included, turned into a string "
         "that is safe to print to the console, with ASCII control "
         "characters replaced by visible escape codes?"),
        ("src/smolagents/local_python_executor.py", "timeout",
         "Where is the limit on how long model-written code may run "
         "enforced, by running it in a one-worker thread pool and raising an "
         "error if it hasn't finished in time?"),
        ("src/smolagents/remote_executors.py",
         "RemotePythonExecutor._deserialize_final_answer",
         "When code runs in a remote sandbox, where is the encoded answer it "
         "sends back decoded, choosing JSON or pickle by a prefix and "
         "rejecting pickle unless it was allowed?"),
        ("src/smolagents/serialization.py", "SafeSerializer.to_json_safe",
         "Where are Python values such as tuples, sets, bytes, dates, numpy "
         "arrays and images converted into plain JSON structures tagged with "
         "type markers?"),
        ("src/smolagents/serialization.py", "SafeSerializer.dumps",
         "Where is a value encoded into a prefixed string for the remote "
         "executor, JSON-only by default, falling back to pickle with a "
         "warning only when that is allowed?"),
        # older code
        ("src/smolagents/local_python_executor.py", "fix_final_answer_code",
         "Where is model-written code rewritten so that assigning to a "
         "variable with the same name as the answer-returning tool does not "
         "shadow that tool?"),
        ("src/smolagents/models.py", "remove_content_after_stop_sequences",
         "After a model has returned its full reply, where is that text "
         "trimmed at the stop strings (shared helper, and a reply with no "
         "content is passed through unchanged)?"),
        ("src/smolagents/utils.py", "truncate_content",
         "Where is long output shortened to a maximum length by keeping its "
         "first and last halves with a notice in between?"),
        ("src/smolagents/agents.py", "ToolCallingAgent._substitute_state_variables",
         "Before a tool runs, where are string arguments that match the name "
         "of a stored value swapped for that value?"),
        ("src/smolagents/models.py", "agglomerate_stream_deltas",
         "Where are streamed chunks of a model reply merged into one message, "
         "concatenating partial tool-call arguments by index and adding up "
         "token counts?"),
        ("src/smolagents/utils.py", "RateLimiter.throttle",
         "Where does a model client sleep so that its requests stay under a "
         "requests-per-minute limit?"),
    ],
    "callers": [
        ("src/smolagents/utils.py", "sanitize_for_rich"),
        ("src/smolagents/local_python_executor.py", "timeout"),
        ("src/smolagents/serialization.py", "SafeSerializer.dumps"),
        ("src/smolagents/serialization.py", "SafeSerializer.from_json_safe"),
        ("src/smolagents/agents.py", "CodeAgent._step_stream"),
        ("src/smolagents/models.py", "OpenAIModel.generate"),
        ("src/smolagents/monitoring.py", "Monitor.update_metrics"),
        ("src/smolagents/agents.py", "populate_template"),
        ("src/smolagents/utils.py", "truncate_content"),
        ("src/smolagents/agents.py", "ToolCallingAgent.execute_tool_call"),
    ],
    "flow": [
        {
            "phase": "model_init",
            "entries": [("OpenAIModel.__init__", 0)],
            "fold": [],
            "text": "OpenAIModel(model_id='canned-model', client=<fake OpenAI "
                    "client>) with all other arguments at their defaults. Which "
                    "repo functions run, in order?",
        },
        {
            "phase": "code_agent_init",
            "entries": [("CodeAgent.__init__", 0)],
            "fold": ["MultiStepAgent._setup_tools", "MultiStepAgent._setup_step_callbacks"],
            "text": "CodeAgent(tools=[add], model=model) where add is a "
                    "@tool-decorated function add(a: int, b: int) -> int and model "
                    "is that OpenAIModel; every other argument at its default "
                    "(local executor). Which repo functions run, in order? "
                    "(Count setting up the tools, and the step callbacks, as "
                    "one step each.)",
        },
        {
            "phase": "code_agent_run",
            "entries": [("MultiStepAgent.run", 0)],
            "fold": ["CodeAgent._step_stream", "CodeAgent.initialize_system_prompt"],
            "text": "That CodeAgent: agent.run('What is 2 + 3?') where the "
                    "model's one reply is a thought plus code calling add(2, 3) "
                    "and final_answer(result). Which repo functions does run "
                    "call, in order? (Count each agent step as one step; what "
                    "happens inside a step is another question.)",
        },
        {
            "phase": "code_agent_run",
            "entries": [("CodeAgent._step_stream", 0)],
            "fold": ["OpenAIModel.generate", "LocalPythonExecutor.__call__"],
            "text": "In that CodeAgent run, the single step: "
                    "CodeAgent._step_stream for step 1. Which repo functions "
                    "run, in order, from building the messages to the code's "
                    "output? (Count the model call and the code execution as one "
                    "step each.)",
        },
        {
            "phase": "code_agent_run",
            "entries": [("OpenAIModel.generate", 0)],
            "fold": [],
            "text": "In that CodeAgent step, the model call: OpenAIModel.generate "
                    "with the system and task messages and stop sequences, "
                    "against the fake client. Which repo functions run, in order?",
        },
        {
            "phase": "code_agent_run",
            "entries": [("LocalPythonExecutor.__call__", 0)],
            "fold": ["Tool.__call__"],
            "text": "In that CodeAgent step, the code execution: the default "
                    "LocalPythonExecutor called on 'result = add(2, 3)\\n"
                    "final_answer(result)'. Which repo functions run, in order? "
                    "(Count each tool call as one step.)",
        },
        {
            "phase": "tool_agent_run",
            "entries": [("ToolCallingAgent._step_stream", 0)],
            "fold": ["OpenAIModel.generate", "ToolCallingAgent.execute_tool_call"],
            "text": "ToolCallingAgent(tools=[add], model=<the same fake "
                    "OpenAIModel>) running 'What is 2 + 3?': its first step, "
                    "ToolCallingAgent._step_stream, where the model replies with "
                    "one tool call add(a=2, b=3). Which repo functions run, in "
                    "order? (Count the model call and the tool execution as one "
                    "step each.)",
        },
        {
            "phase": "tool_agent_run",
            "entries": [("ToolCallingAgent.execute_tool_call", 0)],
            "fold": [],
            "text": "In that first step, the tool execution: "
                    "ToolCallingAgent.execute_tool_call('add', {'a': 2, 'b': 3}). "
                    "Which repo functions run, in order, until the result "
                    "returns?",
        },
    ],
}
