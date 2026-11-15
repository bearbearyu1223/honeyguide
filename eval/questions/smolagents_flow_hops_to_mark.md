# smolagents: flow hops to mark

Commit e1249d3. For each question, tick one box per hop: **required** (an answer that misses it is incomplete) or **optional** (fine to mention, fine to skip). Hops are in first-call order; xN = times called; (fold) = counts as one step, inside is another question; (cached) = lru_cache, later calls may not show; [worker-1] = runs on a thread the code starts.

## sa-flo-01 (model_init)

OpenAIModel(model_id='canned-model', client=<fake OpenAI client>) with all other arguments at their defaults. Which repo functions run, in order?

- [ ] required [ ] optional: `OpenAIModel.__init__` src/smolagents/models.py:1671
- [ ] required [ ] optional: `ApiModel.__init__` src/smolagents/models.py:1161
- [ ] required [ ] optional: `Model.__init__` src/smolagents/models.py:484
- [ ] required [ ] optional: `RateLimiter.__init__` src/smolagents/utils.py:512
- [ ] required [ ] optional: `Retrying.__init__` src/smolagents/utils.py:531

## sa-flo-02 (code_agent_init)

CodeAgent(tools=[add], model=model) where add is a @tool-decorated function add(a: int, b: int) -> int and model is that OpenAIModel; every other argument at its default (local executor). Which repo functions run, in order? (Count setting up the tools, and the step callbacks, as one step each.)

- [ ] required [ ] optional: `CodeAgent.__init__` src/smolagents/agents.py:1527
- [ ] required [ ] optional: `MultiStepAgent.__init__` src/smolagents/agents.py:294
- [ ] required [ ] optional: `MultiStepAgent._validate_name` src/smolagents/agents.py:364
- [ ] required [ ] optional: `MultiStepAgent._setup_managed_agents` src/smolagents/agents.py:369
- [ ] required [ ] optional: `MultiStepAgent._setup_tools` src/smolagents/agents.py:389 (fold)
- [ ] required [ ] optional: `MultiStepAgent._validate_tools_and_managed_agents` src/smolagents/agents.py:404
- [ ] required [ ] optional: `CodeAgent.initialize_system_prompt` src/smolagents/agents.py:1620
- [ ] required [ ] optional: `populate_template` src/smolagents/agents.py:102
- [ ] required [ ] optional: `Tool.to_code_prompt` src/smolagents/tools.py:258 x2
- [ ] required [ ] optional: `AgentMemory.__init__` src/smolagents/memory.py:228
- [ ] required [ ] optional: `MultiStepAgent._setup_step_callbacks` src/smolagents/agents.py:416 (fold)
- [ ] required [ ] optional: `CodeAgent.create_python_executor` src/smolagents/agents.py:1598
- [ ] required [ ] optional: `LocalPythonExecutor.__init__` src/smolagents/local_python_executor.py:1708
- [ ] required [ ] optional: `LocalPythonExecutor._check_authorized_imports_are_installed` src/smolagents/local_python_executor.py:1727

## sa-flo-03 (code_agent_run)

That CodeAgent: agent.run('What is 2 + 3?') where the model's one reply is a thought plus code calling add(2, 3) and final_answer(result). Which repo functions does run call, in order? (Count each agent step as one step; what happens inside a step is another question.)

- [ ] required [ ] optional: `MultiStepAgent.run` src/smolagents/agents.py:436
- [ ] required [ ] optional: `CodeAgent.initialize_system_prompt` src/smolagents/agents.py:1620 (fold)
- [ ] required [ ] optional: `AgentMemory.reset` src/smolagents/memory.py:232
- [ ] required [ ] optional: `LocalPythonExecutor.send_variables` src/smolagents/local_python_executor.py:1760
- [ ] required [ ] optional: `LocalPythonExecutor.send_tools` src/smolagents/local_python_executor.py:1763
- [ ] required [ ] optional: `MultiStepAgent._run_stream` src/smolagents/agents.py:540
- [ ] required [ ] optional: `CodeAgent._step_stream` src/smolagents/agents.py:1638 (fold)
- [ ] required [ ] optional: `MultiStepAgent._finalize_step` src/smolagents/agents.py:620 x2
- [ ] required [ ] optional: `CallbackRegistry.callback` src/smolagents/memory.py:300 x2
- [ ] required [ ] optional: `handle_agent_output_types` src/smolagents/agent_types.py:263

## sa-flo-04 (code_agent_run)

In that CodeAgent run, the single step: CodeAgent._step_stream for step 1. Which repo functions run, in order, from building the messages to the code's output? (Count the model call and the code execution as one step each.)

- [ ] required [ ] optional: `CodeAgent._step_stream` src/smolagents/agents.py:1638
- [ ] required [ ] optional: `MultiStepAgent.write_memory_to_messages` src/smolagents/agents.py:758
- [ ] required [ ] optional: `SystemPromptStep.to_messages` src/smolagents/memory.py:203
- [ ] required [ ] optional: `TaskStep.to_messages` src/smolagents/memory.py:191
- [ ] required [ ] optional: `OpenAIModel.generate` src/smolagents/models.py:1761 (fold)
- [ ] required [ ] optional: `parse_code_blobs` src/smolagents/utils.py:198
- [ ] required [ ] optional: `extract_code_from_text` src/smolagents/utils.py:189
- [ ] required [ ] optional: `fix_final_answer_code` src/smolagents/local_python_executor.py:332
- [ ] required [ ] optional: `LocalPythonExecutor.__call__` src/smolagents/local_python_executor.py:1747 (fold)
- [ ] required [ ] optional: `truncate_content` src/smolagents/utils.py:257

## sa-flo-05 (code_agent_run)

In that CodeAgent step, the model call: OpenAIModel.generate with the system and task messages and stop sequences, against the fake client. Which repo functions run, in order?

- [ ] required [ ] optional: `OpenAIModel.generate` src/smolagents/models.py:1761
- [ ] required [ ] optional: `Model._prepare_completion_kwargs` src/smolagents/models.py:502
- [ ] required [ ] optional: `get_clean_message_list` src/smolagents/models.py:332
- [ ] required [ ] optional: `supports_stop_parameter` src/smolagents/models.py:418 x2
- [ ] required [ ] optional: `ApiModel._apply_rate_limit` src/smolagents/models.py:1189
- [ ] required [ ] optional: `RateLimiter.throttle` src/smolagents/utils.py:517
- [ ] required [ ] optional: `Retrying.__call__` src/smolagents/utils.py:551

## sa-flo-06 (code_agent_run)

In that CodeAgent step, the code execution: the default LocalPythonExecutor called on 'result = add(2, 3)\nfinal_answer(result)'. Which repo functions run, in order? (Count each tool call as one step.)

- [ ] required [ ] optional: `LocalPythonExecutor.__call__` src/smolagents/local_python_executor.py:1747
- [ ] required [ ] optional: `evaluate_python_code` src/smolagents/local_python_executor.py:1583
- [ ] required [ ] optional: `PrintContainer.__init__` src/smolagents/local_python_executor.py:241
- [ ] required [ ] optional: `timeout` src/smolagents/local_python_executor.py:285
- [ ] required [ ] optional: `timeout.<locals>.decorator` src/smolagents/local_python_executor.py:304
- [ ] required [ ] optional: `timeout.<locals>.decorator.<locals>.wrapper` src/smolagents/local_python_executor.py:305
- [ ] required [ ] optional: `evaluate_python_code.<locals>._execute_code` src/smolagents/local_python_executor.py:1639 [worker-1]
- [ ] required [ ] optional: `safer_eval.<locals>._check_return` src/smolagents/local_python_executor.py:196 x7 [worker-1]
- [ ] required [ ] optional: `evaluate_ast` src/smolagents/local_python_executor.py:1416 x7 [worker-1]
- [ ] required [ ] optional: `evaluate_assign` src/smolagents/local_python_executor.py:770 [worker-1]
- [ ] required [ ] optional: `evaluate_call` src/smolagents/local_python_executor.py:825 x2 [worker-1]
- [ ] required [ ] optional: `check_safer_result` src/smolagents/local_python_executor.py:156 x5 [worker-1]
- [ ] required [ ] optional: `Tool.__call__` src/smolagents/tools.py:231 x2 (fold) [worker-1]
- [ ] required [ ] optional: `set_value` src/smolagents/local_python_executor.py:794 [worker-1]
- [ ] required [ ] optional: `evaluate_name` src/smolagents/local_python_executor.py:941 [worker-1]
- [ ] required [ ] optional: `evaluate_python_code.<locals>.final_answer` src/smolagents/local_python_executor.py:1633 [worker-1]
- [ ] required [ ] optional: `FinalAnswerException.__init__` src/smolagents/local_python_executor.py:1579 [worker-1]
- [ ] required [ ] optional: `truncate_content` src/smolagents/utils.py:257 [worker-1]

## sa-flo-07 (tool_agent_run)

ToolCallingAgent(tools=[add], model=<the same fake OpenAIModel>) running 'What is 2 + 3?': its first step, ToolCallingAgent._step_stream, where the model replies with one tool call add(a=2, b=3). Which repo functions run, in order? (Count the model call and the tool execution as one step each.)

- [ ] required [ ] optional: `ToolCallingAgent._step_stream` src/smolagents/agents.py:1276
- [ ] required [ ] optional: `MultiStepAgent.write_memory_to_messages` src/smolagents/agents.py:758
- [ ] required [ ] optional: `SystemPromptStep.to_messages` src/smolagents/memory.py:203
- [ ] required [ ] optional: `TaskStep.to_messages` src/smolagents/memory.py:191
- [ ] required [ ] optional: `OpenAIModel.generate` src/smolagents/models.py:1761 (fold)
- [ ] required [ ] optional: `parse_json_if_needed` src/smolagents/models.py:193
- [ ] required [ ] optional: `ToolCallingAgent.process_tool_calls` src/smolagents/agents.py:1361
- [ ] required [ ] optional: `ToolCallingAgent.process_tool_calls.<locals>.process_single_tool_call` src/smolagents/agents.py:1383
- [ ] required [ ] optional: `ToolCallingAgent.execute_tool_call` src/smolagents/agents.py:1453 (fold)

## sa-flo-08 (tool_agent_run)

In that first step, the tool execution: ToolCallingAgent.execute_tool_call('add', {'a': 2, 'b': 3}). Which repo functions run, in order, until the result returns?

- [ ] required [ ] optional: `ToolCallingAgent.execute_tool_call` src/smolagents/agents.py:1453
- [ ] required [ ] optional: `ToolCallingAgent._substitute_state_variables` src/smolagents/agents.py:1444
- [ ] required [ ] optional: `validate_tool_arguments` src/smolagents/tools.py:1361
- [ ] required [ ] optional: `_get_json_schema_type` src/smolagents/_function_type_hints_utils.py:415 x2
- [ ] required [ ] optional: `Tool.__call__` src/smolagents/tools.py:231
- [ ] required [ ] optional: `handle_agent_input_types` src/smolagents/agent_types.py:257
- [ ] required [ ] optional: `tool.<locals>.wrapped_function` src/smolagents/tools.py:1096
- [ ] required [ ] optional: `handle_agent_output_types` src/smolagents/agent_types.py:263

