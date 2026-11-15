# smolagents: callers disputes

Commit e1249d3. Each callers key is the AST call graph united with the T3 runtime trace. Below are the call sites the AST could not resolve and the trace did not confirm. For each, tick **caller** (add it to the key) or **not** (leave it out).

Kinds:
- attr: obj.m() on an object whose type the AST cannot see; m matches the target by name only
- getattr: getattr(obj, 'm') with the target's name as a string
- reference: the target passed or stored without being called (callback, registry, decorator)

## sa-cal-01: sanitize_for_rich (2 callers in the key, 0 to decide)

- in key (ast): `AgentLogger.log_error` src/smolagents/monitoring.py
- in key (both): `AgentLogger.log_task` src/smolagents/monitoring.py

## sa-cal-02: timeout (1 callers in the key, 1 to decide)

- in key (both): `evaluate_python_code` src/smolagents/local_python_executor.py
- [ ] caller [ ] not: `WebSearchTool.search_exa` src/smolagents/default_tools.py line 477 (getattr: `timeout`; only repo def named so)

## sa-cal-03: SafeSerializer.dumps (1 callers in the key, 0 to decide)

- in key (ast): `RemotePythonExecutor.send_variables` src/smolagents/remote_executors.py

## sa-cal-04: SafeSerializer.from_json_safe (3 callers in the key, 2 to decide)

- in key (ast): `RemotePythonExecutor._deserialize_final_answer` src/smolagents/remote_executors.py
- in key (ast): `SafeSerializer.from_json_safe` src/smolagents/serialization.py
- in key (ast): `SafeSerializer.loads` src/smolagents/serialization.py
- [ ] caller [ ] not: `SafeSerializer.get_deserializer_code` src/smolagents/serialization.py line 468 (reference: `from_json_safe`; only repo def named so)
- [ ] caller [ ] not: `SafeSerializer.get_safe_serializer_code` src/smolagents/serialization.py line 392 (reference: `from_json_safe`; only repo def named so)

## sa-cal-05: CodeAgent._step_stream (2 callers in the key, 0 to decide)

- in key (both): `MultiStepAgent._run_stream` src/smolagents/agents.py
- in key (ast): `MultiStepAgent.step` src/smolagents/agents.py

## sa-cal-06: OpenAIModel.generate (3 callers in the key, 6 to decide)

- in key (trace): `CodeAgent._step_stream` src/smolagents/agents.py
- in key (trace): `ToolCallingAgent._step_stream` src/smolagents/agents.py
- in key (ast): `Model.__call__` src/smolagents/models.py
- [ ] caller [ ] not: `MultiStepAgent._generate_planning_step` src/smolagents/agents.py line 672, 730 (attr: `generate`)
- [ ] caller [ ] not: `MultiStepAgent.provide_final_answer` src/smolagents/agents.py line 847 (attr: `generate`)
- [ ] caller [ ] not: `SpeechToTextTool.forward` src/smolagents/default_tools.py line 672 (attr: `generate`)
- [ ] caller [ ] not: `TransformersModel.generate` src/smolagents/models.py line 1069 (attr: `generate`)
- [ ] caller [ ] not: `TransformersModel.generate_stream` src/smolagents/models.py line 1115 (reference: `generate`)
- [ ] caller [ ] not: `VLLMModel.generate` src/smolagents/models.py line 731 (attr: `generate`)

## sa-cal-07: Monitor.update_metrics (1 callers in the key, 1 to decide)

- in key (trace): `CallbackRegistry.callback` src/smolagents/memory.py
- [ ] caller [ ] not: `MultiStepAgent._setup_step_callbacks` src/smolagents/agents.py line 434 (reference: `update_metrics`; only repo def named so)

## sa-cal-08: populate_template (5 callers in the key, 0 to decide)

- in key (both): `CodeAgent.initialize_system_prompt` src/smolagents/agents.py
- in key (ast): `MultiStepAgent.__call__` src/smolagents/agents.py
- in key (ast): `MultiStepAgent._generate_planning_step` src/smolagents/agents.py
- in key (ast): `MultiStepAgent.provide_final_answer` src/smolagents/agents.py
- in key (both): `ToolCallingAgent.initialize_system_prompt` src/smolagents/agents.py

## sa-cal-09: truncate_content (3 callers in the key, 0 to decide)

- in key (both): `CodeAgent._step_stream` src/smolagents/agents.py
- in key (ast): `MultiStepAgent.__call__` src/smolagents/agents.py
- in key (both): `evaluate_python_code.<locals>._execute_code` src/smolagents/local_python_executor.py

## sa-cal-10: ToolCallingAgent.execute_tool_call (1 callers in the key, 0 to decide)

- in key (both): `ToolCallingAgent.process_tool_calls.<locals>.process_single_tool_call` src/smolagents/agents.py

