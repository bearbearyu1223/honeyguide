# waku-agent: flow hops to mark

Commit 2c7e7e6. For each question, tick one box per hop: **required** (an answer that misses it is incomplete) or **optional** (fine to mention, fine to skip). Hops are in first-call order; xN = times called; (fold) = counts as one step, inside is another question; (cached) = lru_cache, later calls may not show; [worker-1] = runs on a thread the code starts. [worker-1, wave-1] = runs on a thread the code starts, in a wave of tasks the real code runs at the same time: the trace ran them one after another, so hops on different threads of one wave have no order between them (the scorer does not penalise either order).

## wk-flo-01 (init)

Waku(settings, client=<scripted fake model client>) with a fresh home (empty SQLite state.db), no MCP servers or plugins, graph_workflows off, consolidate_every=3. Which repo functions does building the agent run, in order? (Count setting up memory, and building the tool registry, as one step each.)

- [ ] required [ ] optional: `Waku.__init__` waku/app.py:69
- [ ] required [ ] optional: `Settings.ensure_home` waku/config.py:314
- [ ] required [ ] optional: `connect` waku/db.py:111
- [ ] required [ ] optional: `_migrate` waku/db.py:83
- [ ] required [ ] optional: `Memory.__init__` waku/memory/__init__.py:60 (fold)
- [ ] required [ ] optional: `build_registry` waku/tools/__init__.py:14 (fold)
- [ ] required [ ] optional: `remember_via` waku/tools/waku_memory.py:101
- [ ] required [ ] optional: `_server` waku/tools/waku_memory.py:67 x4
- [ ] required [ ] optional: `consolidation_every` waku/tools/waku_memory.py:55
- [ ] required [ ] optional: `search_via` waku/tools/waku_memory.py:128
- [ ] required [ ] optional: `get_via` waku/tools/waku_memory.py:152
- [ ] required [ ] optional: `tool_name` waku/tools/waku_memory.py:188
- [ ] required [ ] optional: `ToolRegistry.get` waku/tools/registry.py:44
- [ ] required [ ] optional: `Session.__init__` waku/runtime/session.py:86
- [ ] required [ ] optional: `enabled` waku/plugins/store.py:75
- [ ] required [ ] optional: `read` waku/plugins/store.py:57
- [ ] required [ ] optional: `folder` waku/plugins/store.py:38

## wk-flo-02 (turn_tool)

That agent's first turn: waku.respond(<a request to remember an agenda for Alex>), where the model saves it with one save_note call and then replies. Which repo functions does respond call, in order? (Count running the turn, the consolidation check and the receipt as one step each.)

- [ ] required [ ] optional: `Waku.respond` waku/app.py:136
- [ ] required [ ] optional: `compose` waku/ops/tracing.py:217
- [ ] required [ ] optional: `Waku._before_turn` waku/app.py:281
- [ ] required [ ] optional: `Waku._run_full_turn` waku/app.py:392 (fold)
- [ ] required [ ] optional: `kept_body` waku/memory/reports.py:176
- [ ] required [ ] optional: `saved_by_model` waku/memory/reports.py:156 x2
- [ ] required [ ] optional: `find` waku/memory/reports.py:88 x2
- [ ] required [ ] optional: `save` waku/memory/reports.py:260
- [ ] required [ ] optional: `Waku.respond.<locals>._status` waku/app.py:211
- [ ] required [ ] optional: `Session.add_exchange` waku/runtime/session.py:140
- [ ] required [ ] optional: `note` waku/memory/tool_note.py:46
- [ ] required [ ] optional: `_short` waku/memory/tool_note.py:38 x2
- [ ] required [ ] optional: `Memory.log_chat` waku/memory/__init__.py:144
- [ ] required [ ] optional: `Waku._recalled` waku/app.py:358
- [ ] required [ ] optional: `tool_name` waku/tools/waku_memory.py:188 x4
- [ ] required [ ] optional: `_server` waku/tools/waku_memory.py:67 x4
- [ ] required [ ] optional: `Memory.maybe_consolidate` waku/memory/__init__.py:271 (fold)
- [ ] required [ ] optional: `Memory.export_markdown` waku/memory/__init__.py:213
- [ ] required [ ] optional: `Memory.export_fact_files` waku/memory/__init__.py:240
- [ ] required [ ] optional: `_fact_file_text` waku/memory/__init__.py:46
- [ ] required [ ] optional: `_fact_file_text.<locals>.one_line` waku/memory/__init__.py:52 x3
- [ ] required [ ] optional: `Waku._receipt` waku/app.py:379 (fold)
- [ ] required [ ] optional: `Waku._after_turn` waku/app.py:341

## wk-flo-03 (turn_tool)

In that first turn, building the system prompt: Session.build_system on the message, where the small model's gate replies retrieve=true with query 'alex' and memory is still empty. Which repo functions run, in order?

- [ ] required [ ] optional: `Session.build_system` waku/runtime/session.py:100
- [ ] required [ ] optional: `load_soul` waku/runtime/session.py:73
- [ ] required [ ] optional: `unavailable` waku/tools/treg.py:95
- [ ] required [ ] optional: `own_key` waku/tools/treg.py:70
- [ ] required [ ] optional: `Memory.gated_retrieve` waku/memory/__init__.py:118
- [ ] required [ ] optional: `metered.__init__` waku/ops/tracing.py:249
- [ ] required [ ] optional: `_MeteredMessages.__init__` waku/ops/tracing.py:227
- [ ] required [ ] optional: `should_retrieve` waku/memory/retrieval_gate.py:36
- [ ] required [ ] optional: `_MeteredMessages.create` waku/ops/tracing.py:230
- [ ] required [ ] optional: `SqliteFactStore.search` waku/memory/semantic/store.py:100
- [ ] required [ ] optional: `_fts_query` waku/memory/semantic/store.py:31 x2
- [ ] required [ ] optional: `select` waku/memory/slot_gate.py:66
- [ ] required [ ] optional: `SqliteEpisodeStore.search` waku/memory/episodic/store.py:27
- [ ] required [ ] optional: `Memory.matching_skills` waku/memory/__init__.py:139
- [ ] required [ ] optional: `SkillLoader.match` waku/memory/procedural/loader.py:77
- [ ] required [ ] optional: `SkillLoader._scan_sig` waku/memory/procedural/loader.py:58

## wk-flo-04 (turn_tool)

In that first turn, the loop: run_loop where the model's first reply asks for save_note(subject='alex', content=<the agenda>) and its second reply is plain text. Which repo functions are called, in order, until the reply is returned?

- [ ] required [ ] optional: `run_loop` waku/loop/agent.py:91
- [ ] required [ ] optional: `ToolRegistry.schemas` waku/tools/registry.py:47 x2
- [ ] required [ ] optional: `ToolRegistry.execute` waku/tools/registry.py:50
- [ ] required [ ] optional: `make_tool.<locals>.save_note` waku/tools/notes.py:35
- [ ] required [ ] optional: `chain.<locals>.run` waku/loop/trim.py:60
- [ ] required [ ] optional: `shrink_read` waku/memory/reports.py:186
- [ ] required [ ] optional: `shrink_seen` waku/loop/trim.py:40

## wk-flo-05 (turn_limit)

The second turn, with settings.max_iterations=2: run_loop where the model asks for manage_memory (search 'alex', a 4,800-character result) and then send_message, so the limit is reached. Which repo functions are called, in order, until the reply is returned? (Count each tool's execution as one step.)

- [ ] required [ ] optional: `run_loop` waku/loop/agent.py:91
- [ ] required [ ] optional: `ToolRegistry.schemas` waku/tools/registry.py:47 x3
- [ ] required [ ] optional: `ToolRegistry.execute` waku/tools/registry.py:50 x2 (fold)
- [ ] required [ ] optional: `chain.<locals>.run` waku/loop/trim.py:60 x2
- [ ] required [ ] optional: `shrink_read` waku/memory/reports.py:186 x2
- [ ] required [ ] optional: `shrink_seen` waku/loop/trim.py:40 x2
- [ ] required [ ] optional: `_final_answer` waku/loop/agent.py:203

## wk-flo-06 (turn_consolidate)

The third turn ends with six unconsolidated chat rows (consolidate_every=3): Memory.maybe_consolidate, where the small model proposes two facts (one about the user's meeting times, one an account balance) and one episode. Which repo functions run, in order?

- [ ] required [ ] optional: `Memory.maybe_consolidate` waku/memory/__init__.py:271
- [ ] required [ ] optional: `metered.__init__` waku/ops/tracing.py:249
- [ ] required [ ] optional: `_MeteredMessages.__init__` waku/ops/tracing.py:227
- [ ] required [ ] optional: `kept_if_due` waku/memory/consolidation.py:161
- [ ] required [ ] optional: `clip` waku/memory/tool_note.py:62 x6
- [ ] required [ ] optional: `_saved_reports` waku/memory/consolidation.py:297
- [ ] required [ ] optional: `_MeteredMessages.create` waku/ops/tracing.py:230
- [ ] required [ ] optional: `is_ops_state` waku/memory/consolidation.py:375 x2
- [ ] required [ ] optional: `is_memory_state` waku/memory/consolidation.py:401
- [ ] required [ ] optional: `keep` waku/memory/slot_gate.py:83
- [ ] required [ ] optional: `enabled` waku/memory/slot_gate.py:44
- [ ] required [ ] optional: `SqliteFactStore.add` waku/memory/semantic/store.py:71
- [ ] required [ ] optional: `SqliteEpisodeStore.add` waku/memory/episodic/store.py:20

## wk-flo-07 (graph_quick)

The fourth turn, with settings.graph_workflows=True: waku.respond('thanks!'), where the triage model answers 'quick'. Which repo functions does Waku._respond_via_graph run, in order, until the quick reply is returned?

- [ ] required [ ] optional: `Waku._respond_via_graph` waku/app.py:436
- [ ] required [ ] optional: `build_triage_graph` waku/graph/workflows/triage.py:89
- [ ] required [ ] optional: `Graph.add_node` waku/graph/engine.py:71 x5
- [ ] required [ ] optional: `Graph.add_edge` waku/graph/engine.py:76 x6
- [ ] required [ ] optional: `key_router` waku/graph/nodes.py:65
- [ ] required [ ] optional: `Graph.add_router` waku/graph/engine.py:84
- [ ] required [ ] optional: `run_graph` waku/graph/engine.py:106
- [ ] required [ ] optional: `run_graph.<locals>.next_wave` waku/graph/engine.py:128 x4
- [ ] required [ ] optional: `run_graph.<locals>.run_one` waku/graph/engine.py:141 x4 [worker-1, wave-1]
- [ ] required [ ] optional: `build_triage_graph.<locals>.classify` waku/graph/workflows/triage.py:97 [worker-1, wave-1]
- [ ] required [ ] optional: `metered.__init__` waku/ops/tracing.py:249 x2 [worker-1, wave-1]
- [ ] required [ ] optional: `_MeteredMessages.__init__` waku/ops/tracing.py:227 x2 [worker-1, wave-1]
- [ ] required [ ] optional: `classify_message` waku/graph/workflows/triage.py:52 [worker-1, wave-1]
- [ ] required [ ] optional: `_MeteredMessages.create` waku/ops/tracing.py:230 x2 [worker-1, wave-1]
- [ ] required [ ] optional: `todays_events` waku/graph/workflows/triage.py:73 [worker-2, wave-1]
- [ ] required [ ] optional: `key_router.<locals>.route` waku/graph/nodes.py:69
- [ ] required [ ] optional: `Waku._respond_via_graph.<locals>.quick_reply` waku/app.py:448
- [ ] required [ ] optional: `with_context` waku/app.py:50

## wk-flo-08 (graph_full)

The fifth turn, graph_workflows still on: a question about Alex, where the triage model answers 'full'. Which repo functions does Waku._respond_via_graph run, in order? (Count building the graph, and the full turn it hands over to, as one step each.)

- [ ] required [ ] optional: `Waku._respond_via_graph` waku/app.py:436
- [ ] required [ ] optional: `build_triage_graph` waku/graph/workflows/triage.py:89 (fold)
- [ ] required [ ] optional: `run_graph` waku/graph/engine.py:106
- [ ] required [ ] optional: `run_graph.<locals>.next_wave` waku/graph/engine.py:128 x4
- [ ] required [ ] optional: `run_graph.<locals>.run_one` waku/graph/engine.py:141 x4 [worker-3, wave-1]
- [ ] required [ ] optional: `build_triage_graph.<locals>.classify` waku/graph/workflows/triage.py:97 [worker-3, wave-1]
- [ ] required [ ] optional: `metered.__init__` waku/ops/tracing.py:249 [worker-3, wave-1]
- [ ] required [ ] optional: `_MeteredMessages.__init__` waku/ops/tracing.py:227 [worker-3, wave-1]
- [ ] required [ ] optional: `classify_message` waku/graph/workflows/triage.py:52 [worker-3, wave-1]
- [ ] required [ ] optional: `_MeteredMessages.create` waku/ops/tracing.py:230 [worker-3, wave-1]
- [ ] required [ ] optional: `todays_events` waku/graph/workflows/triage.py:73 [worker-4, wave-1]
- [ ] required [ ] optional: `key_router.<locals>.route` waku/graph/nodes.py:69
- [ ] required [ ] optional: `Waku._run_full_turn` waku/app.py:392 (fold)

