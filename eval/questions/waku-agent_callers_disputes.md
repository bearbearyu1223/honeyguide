# waku-agent: callers disputes

Commit 2c7e7e6. Each callers key is the AST call graph united with the T3 runtime trace. Below are the call sites the AST could not resolve and the trace did not confirm. For each, tick **caller** (add it to the key) or **not** (leave it out).

Kinds:
- attr: obj.m() on an object whose type the AST cannot see; m matches the target by name only
- getattr: getattr(obj, 'm') with the target's name as a string
- reference: the target passed or stored without being called (callback, registry, decorator)

## wk-cal-01: Memory.gated_retrieve (1 callers in the key, 0 to decide)

- in key (trace): `Session.build_system` waku/runtime/session.py

## wk-cal-02: run_loop (2 callers in the key, 0 to decide)

- in key (both): `Waku._run_full_turn` waku/app.py
- in key (ast): `agent_node.<locals>.run` waku/graph/nodes.py

## wk-cal-03: Waku.respond (0 callers in the key, 10 to decide)

- [ ] caller [ ] not: `main` waku/gateway/cli.py line 91 (attr: `respond`)
- [ ] caller [ ] not: `GatewayAgentRunner._respond` waku/gateway/runner.py line 71 (attr: `respond`)
- [ ] caller [ ] not: `run_gateway_turn` waku/gateway/runner.py line 120 (attr: `respond`)
- [ ] caller [ ] not: `main` waku/gateway/voice.py line 353 (attr: `respond`)
- [ ] caller [ ] not: `wake_loop` waku/gateway/voice.py line 298 (attr: `respond`)
- [ ] caller [ ] not: `_build_handler.<locals>.Handler.do_POST` waku/gateway/whatsapp.py line 225 (attr: `respond`)
- [ ] caller [ ] not: `compare_stream.<locals>.run` waku/ops/arena.py line 117 (attr: `respond`)
- [ ] caller [ ] not: `main` waku/ops/brief.py line 27 (attr: `respond`)
- [ ] caller [ ] not: `chat_stream` waku/ops/dashboard.py line 117 (attr: `respond`)
- [ ] caller [ ] not: `run_arena.<locals>.one` waku/ops/memory_arena.py line 484, 554 (attr: `respond`)

## wk-cal-04: shrink_seen (1 callers in the key, 1 to decide)

- in key (trace): `chain.<locals>.run` waku/loop/trim.py
- [ ] caller [ ] not: `Waku._run_full_turn` waku/app.py line 429 (reference: `shrink_seen`; only repo def named so)

## wk-cal-05: kept_if_due (2 callers in the key, 0 to decide)

- in key (both): `Memory.maybe_consolidate` waku/memory/__init__.py
- in key (ast): `consolidate_if_due` waku/memory/consolidation.py

## wk-cal-06: ToolRegistry.schemas (2 callers in the key, 0 to decide)

- in key (trace): `_final_answer` waku/loop/agent.py
- in key (trace): `run_loop` waku/loop/agent.py

## wk-cal-07: run_graph (2 callers in the key, 0 to decide)

- in key (both): `Waku._respond_via_graph` waku/app.py
- in key (ast): `run_gather` waku/ops/gather.py

## wk-cal-08: clip (2 callers in the key, 0 to decide)

- in key (both): `kept_if_due` waku/memory/consolidation.py
- in key (ast): `Session.switch` waku/runtime/session.py

## wk-cal-09: resolve_home (7 callers in the key, 0 to decide)

- in key (ast): `<module>` waku/config.py
- in key (ast): `_load_home_env` waku/config.py
- in key (ast): `env_write_target` waku/config.py
- in key (ast): `home_notice` waku/config.py
- in key (ast): `cli_main` waku/integrations.py
- in key (ast): `model_key_locations` waku/key_locations.py
- in key (ast): `_no_key_message` waku/loop/models.py

## wk-cal-10: Memory.maybe_consolidate (1 callers in the key, 0 to decide)

- in key (trace): `Waku.respond` waku/app.py

