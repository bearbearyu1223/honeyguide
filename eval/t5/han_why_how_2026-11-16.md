# T5: Han's why/how questions and rubrics (verbatim, received 2026-11-16 in chat)

Written after both maps existed (the plan intended before); Han wrote them from the repos, not the maps.

## nanochat

1. Why does nanochat use transformer depth as its main model-scaling parameter?
Rubric: Explain how depth determines other architecture and training settings, why this simplifies scaling experiments, and what tradeoffs remain.
Files: nanochat/gpt.py; scripts/base_train.py

2. How does nanochat construct a GPT model from its configuration?
Rubric: Cover embedding dimensions, transformer blocks, attention, MLP, output prediction, and how configuration affects tensor shapes.
Files: nanochat/gpt.py

3. How does the distributed data loader partition training tokens across processes?
Rubric: Explain rank-dependent data assignment, batch and sequence boundaries, shard progression, and avoiding unintended overlap.
Files: nanochat/dataloader.py

4. Why does nanochat combine AdamW and Muon rather than use one optimizer for all parameters?
Rubric: Explain parameter-group differences, optimizer update behavior, and why different tensor types may benefit from different optimizers.
Files: nanochat/optim.py; scripts/base_train.py

5. How does the base-training loop coordinate forward passes, gradient updates, evaluation, and checkpointing?
Rubric: Trace data loading, loss calculation, backward pass, optimizer and scheduler updates, evaluation intervals, and checkpoint writes.
Files: scripts/base_train.py; nanochat/checkpoint_manager.py

6. Why does nanochat report bits per byte rather than relying only on token-level loss?
Rubric: Explain dependence of token loss on tokenization, byte normalization, and why this enables more meaningful comparisons.
Files: nanochat/loss_eval.py; nanochat/tokenizer.py

7. How does the inference engine reuse the KV cache during autoregressive generation?
Rubric: Explain prompt prefill, cached attention keys/values, incremental decoding, cache position management, and memory/speed tradeoffs.
Files: nanochat/engine.py; nanochat/gpt.py

8. How does supervised fine-tuning transform a pretrained model into a chat model?
Rubric: Describe chat formatting, supervised targets, loss masking where applicable, dataset mixtures, and checkpoint initialization.
Files: scripts/chat_sft.py; nanochat/tokenizer.py; tasks/common.py

9. How does the reinforcement-learning stage differ from supervised fine-tuning?
Rubric: Explain candidate generation, reward or scoring signals, policy updates, and the absence of a conventional next-token supervised target for every action.
Files: scripts/chat_rl.py; nanochat/engine.py

10. How are model checkpoints saved and restored across training and inference?
Rubric: Cover model state, optimizer/training metadata as applicable, reconstruction, device placement, and compatibility constraints.
Files: nanochat/checkpoint_manager.py; scripts/chat_cli.py

## waku-agent

1. Why does waku-agent separate gateway integrations from the core agent loop?
Rubric: Explain transport-specific input/output handling, shared agent behavior, reuse, and isolation of integration concerns.
Files: waku/; docs/

2. How does the agent loop decide whether to execute a tool or return a response?
Rubric: Cover model request, tool-call detection, dispatch, result messages, iteration, and termination conditions.
Files: waku/

3. Why does waku-agent maintain persistent memory in SQLite?
Rubric: Explain persistence across sessions, local ownership, structured queries, and tradeoffs against purely in-context memory.
Files: waku/; sql/

4. How does the memory gate decide whether an interaction should be remembered?
Rubric: Explain the gate's decision point, relevance/retention criteria, storage path, and why not every conversation should be saved.
Files: waku/

5. Why distinguish semantic, episodic, and procedural memory?
Rubric: Explain the information each represents, how it is used during agent execution, and the problems with treating all memory as one category.
Files: waku/; docs/

6. How does memory retrieval influence the next model request?
Rubric: Trace query/context preparation, retrieval, selected memories, prompt/context assembly, and model invocation.
Files: waku/

7. How does memory consolidation differ from simply appending new records?
Rubric: Explain deduplication or reconciliation where implemented, retention, updating knowledge, and handling conflicting information.
Files: waku/; sql/

8. How does the provider adapter let the same agent loop work with different LLM APIs?
Rubric: Explain normalization of messages, tool-call representation, model responses, provider-specific differences, and limitations.
Files: waku/

9. Why combine deterministic tests with LLM-as-judge evaluations?
Rubric: Explain reproducible assertions versus semantic judgments, where each is appropriate, and the risks of nondeterministic grading.
Files: evals/; docs/

10. How do tracing and release gates support debugging and regression prevention?
Rubric: Explain captured execution events, evaluation outcomes, thresholds or release decisions, and the limits of tracing alone.
Files: waku/; evals/
