# nanochat: callers disputes

Commit 92d63d4. Each callers key is the AST call graph united with the T3 runtime trace. Below are the call sites the AST could not resolve and the trace did not confirm. For each, tick **caller** (add it to the key) or **not** (leave it out).

Kinds:
- attr: obj.m() on an object whose type the AST cannot see; m matches the target by name only
- getattr: getattr(obj, 'm') with the target's name as a string
- reference: the target passed or stored without being called (callback, registry, decorator)

## nc-cal-01: GPT.estimate_decode_flops (0 callers in the key, 1 to decide)

- [ ] caller [ ] not: `main` scripts/infer_bench.py line 173, 221 (attr: `estimate_decode_flops`; only repo def named so)

## nc-cal-02: get_peak_bandwidth (1 callers in the key, 0 to decide)

- in key (ast): `main` scripts/infer_bench.py

## nc-cal-03: load_hub_dataset (5 callers in the key, 0 to decide)

- in key (ast): `ARC.__init__` tasks/arc.py
- in key (ast): `GSM8K.__init__` tasks/gsm8k.py
- in key (ast): `HumanEval.__init__` tasks/humaneval.py
- in key (ast): `MMLU.__init__` tasks/mmlu.py
- in key (ast): `SmolTalk.__init__` tasks/smoltalk.py

## nc-cal-04: KVCache.prefill (1 callers in the key, 0 to decide)

- in key (trace): `Engine.generate` nanochat/engine.py

## nc-cal-05: sample_next_token (1 callers in the key, 0 to decide)

- in key (both): `Engine.generate` nanochat/engine.py

## nc-cal-06: norm (3 callers in the key, 1 to decide)

- in key (both): `Block.forward` nanochat/gpt.py
- in key (both): `CausalSelfAttention.forward` nanochat/gpt.py
- in key (both): `GPT.forward` nanochat/gpt.py
- [ ] caller [ ] not: `muon_step_fused` nanochat/optim.py line 139, 140, 144, 160 (attr: `norm`; only repo def named so)

## nc-cal-07: flash_attn_with_kvcache (1 callers in the key, 2 to decide)

- in key (trace): `CausalSelfAttention.forward` nanochat/gpt.py
- [ ] caller [ ] not: `<module>` nanochat/flash_attention.py line 194 (reference: `flash_attn_with_kvcache`; only repo def named so)
- [ ] caller [ ] not: `flash_attn_with_kvcache` nanochat/flash_attention.py line 158 (attr: `flash_attn_with_kvcache`; only repo def named so)

## nc-cal-08: GPT._precompute_rotary_embeddings (2 callers in the key, 0 to decide)

- in key (both): `GPT.__init__` nanochat/gpt.py
- in key (both): `GPT.init_weights` nanochat/gpt.py

## nc-cal-09: compute_init (8 callers in the key, 0 to decide)

- in key (ast): `<module>` nanochat/engine.py
- in key (ast): `main` scripts/base_eval.py
- in key (ast): `<module>` scripts/base_train.py
- in key (ast): `<module>` scripts/chat_cli.py
- in key (ast): `<module>` scripts/chat_eval.py
- in key (ast): `<module>` scripts/chat_rl.py
- in key (ast): `<module>` scripts/chat_sft.py
- in key (ast): `main` scripts/infer_bench.py

## nc-cal-10: use_calculator (1 callers in the key, 0 to decide)

- in key (ast): `Engine.generate` nanochat/engine.py

