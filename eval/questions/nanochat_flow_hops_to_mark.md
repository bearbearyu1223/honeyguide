# nanochat: flow hops to mark

Commit 92d63d4. For each question, tick one box per hop: **required** (an answer that misses it is incomplete) or **optional** (fine to mention, fine to skip). Hops are in first-call order; xN = times called; (fold) = counts as one step, inside is another question; (cached) = lru_cache, later calls may not show; [worker-1] = runs on a thread the code starts.

## nc-flo-01 (build)

With config GPTConfig(sequence_len=32, n_layer=2, n_head=2, n_kv_head=2, n_embd=32, window_pattern='SSSL'), the model is built with GPT(config) on the meta device, moved with to_empty(device='cpu'), then model.init_weights() is called. Which repo functions run, in order?

- [ ] required [ ] optional: `GPT.__init__` nanochat/gpt.py:157
- [ ] required [ ] optional: `GPT._compute_window_sizes` nanochat/gpt.py:287
- [ ] required [ ] optional: `Block.__init__` nanochat/gpt.py:145 x2
- [ ] required [ ] optional: `CausalSelfAttention.__init__` nanochat/gpt.py:68 x2
- [ ] required [ ] optional: `MLP.__init__` nanochat/gpt.py:132 x2
- [ ] required [ ] optional: `GPT._precompute_rotary_embeddings` nanochat/gpt.py:270 x2
- [ ] required [ ] optional: `GPT.init_weights` nanochat/gpt.py:203

## nc-flo-02 (forward_loss)

Same toy GPTConfig on CPU (n_layer=2, n_embd=32, float32, torch.compile off): loss = model(x, y) with x and y random token ids of shape (2, 16). Which repo functions run, in order, from GPT.forward until the loss is returned?

- [ ] required [ ] optional: `GPT.forward` nanochat/gpt.py:459
- [ ] required [ ] optional: `norm` nanochat/gpt.py:42 x10
- [ ] required [ ] optional: `Linear.forward` nanochat/gpt.py:49 x15
- [ ] required [ ] optional: `Block.forward` nanochat/gpt.py:150 x2
- [ ] required [ ] optional: `CausalSelfAttention.forward` nanochat/gpt.py:84 x2
- [ ] required [ ] optional: `apply_rotary_emb` nanochat/gpt.py:57 x4
- [ ] required [ ] optional: `flash_attn_func` nanochat/flash_attention.py:115 x2
- [ ] required [ ] optional: `_sdpa_attention` nanochat/flash_attention.py:77 x2
- [ ] required [ ] optional: `MLP.forward` nanochat/gpt.py:137 x2

## nc-flo-03 (optimizer_step)

Same toy model on CPU, one process (world size 1), after loss.backward(): optimizer.step() on the optimizer returned by model.setup_optimizer() with default arguments, with torch.compile disabled. Which repo functions run, in order?

- [ ] required [ ] optional: `MuonAdamW.step` nanochat/optim.py:428
- [ ] required [ ] optional: `MuonAdamW._reduce_adamw` nanochat/optim.py:274 x6
- [ ] required [ ] optional: `MuonAdamW._reduce_muon` nanochat/optim.py:295 x4
- [ ] required [ ] optional: `MuonAdamW._compute_adamw` nanochat/optim.py:320 x6
- [ ] required [ ] optional: `adamw_step_fused` nanochat/optim.py:23 x8
- [ ] required [ ] optional: `MuonAdamW._compute_muon` nanochat/optim.py:362 x4
- [ ] required [ ] optional: `muon_step_fused` nanochat/optim.py:111 x4
- [ ] required [ ] optional: `MuonAdamW._finish_gathers` nanochat/optim.py:419

## nc-flo-04 (engine_generate)

Same toy model and its trained toy tokenizer on CPU: Engine(model, tokenizer).generate(prompt_ids, num_samples=1, max_tokens=4, temperature=0.6, top_k=50, seed=42), consumed to the end. Which repo functions does Engine.generate call, in order? (Count each pass through the model as one step; what happens inside it is another question.)

- [ ] required [ ] optional: `Engine.__init__` nanochat/engine.py:171
- [ ] required [ ] optional: `Engine.generate` nanochat/engine.py:175
- [ ] required [ ] optional: `RustBPETokenizer.encode_special` nanochat/tokenizer.py:89 x5 (cached)
- [ ] required [ ] optional: `KVCache.__init__` nanochat/engine.py:92 x2
- [ ] required [ ] optional: `GPT.forward` nanochat/gpt.py:459 x5 (fold)
- [ ] required [ ] optional: `KVCache.prefill` nanochat/engine.py:123
- [ ] required [ ] optional: `RowState.__init__` nanochat/engine.py:162
- [ ] required [ ] optional: `sample_next_token` nanochat/engine.py:140 x4

## nc-flo-05 (engine_generate)

In that generate call, the first model forward pass: GPT.forward on the 9-token prompt (batch 1) with a fresh KV cache (kv_cache passed, no targets). Which repo functions run, in order, until the logits are returned?

- [ ] required [ ] optional: `GPT.forward` nanochat/gpt.py:459
- [ ] required [ ] optional: `norm` nanochat/gpt.py:42 x10
- [ ] required [ ] optional: `Linear.forward` nanochat/gpt.py:49 x15
- [ ] required [ ] optional: `Block.forward` nanochat/gpt.py:150 x2
- [ ] required [ ] optional: `CausalSelfAttention.forward` nanochat/gpt.py:84 x2
- [ ] required [ ] optional: `apply_rotary_emb` nanochat/gpt.py:57 x4
- [ ] required [ ] optional: `flash_attn_with_kvcache` nanochat/flash_attention.py:139 x2
- [ ] required [ ] optional: `_sdpa_attention` nanochat/flash_attention.py:77 x2
- [ ] required [ ] optional: `MLP.forward` nanochat/gpt.py:137 x2
- [ ] required [ ] optional: `KVCache.advance` nanochat/engine.py:119

