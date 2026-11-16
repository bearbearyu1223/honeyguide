"""A sample store for the map page (T7.3): a small throwaway repo ("tinytrain") and a HONEYGUIDE_HOME filled through
the real contract functions (claims save, verdict set, question post, answer record, notes, activity, refresh).

    uv run python tests/t7_page_fixture.py OUT_DIR [--variant base|working|refreshed|empty]

builds OUT_DIR/<variant>/repo and OUT_DIR/<variant>/home and prints them as JSON. Serve one with
``HONEYGUIDE_HOME=<home> uv run honeyguide serve --repo <repo> --port 0``. Every variant is built from scratch.

Variants: ``base`` (a checked map, three discussions with branches, a not-supported claim, a general-knowledge claim,
a Tracer path answer, notes), ``working`` (base plus agents at work), ``refreshed`` (base, then a new commit and a
real refresh: claims moved, one re-checked, one still stale, one retired; last visit before the refresh), ``empty``
(an initialised store, no map).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_core_fixtures import GIT_CONFIG  # noqa: E402

import honeyguide.activity as activity  # noqa: E402
import honeyguide.claims as claims_mod  # noqa: E402
import honeyguide.inbox as inbox  # noqa: E402
import honeyguide.store as store_mod  # noqa: E402
from honeyguide.contract import load_side as load_session_side, update_side  # noqa: E402
from honeyguide.gitio import Repo  # noqa: E402
from honeyguide.mapdoc import plain_text  # noqa: E402
from honeyguide.refresh import apply_plan, plan_refresh  # noqa: E402
from honeyguide.repoid import identify  # noqa: E402
from honeyguide.store import Store, all_claims  # noqa: E402

VARIANTS = ("base", "working", "refreshed", "empty")

FILES = {
    "README.md": """# tinytrain

A small GPT pretraining repo.

## Results

The default config reaches 3.3 validation loss in about 2 hours on one H100.
""",
    "model.py": '''"""GPT: attention blocks with rotary positions."""
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    n_layer: int = 12
    n_head: int = 12
    n_embd: int = 768
    vocab_size: int = 50304
    block_size: int = 1024


def apply_rotary(x, cos, sin):
    d = x.shape[-1] // 2
    x1, x2 = x[..., :d], x[..., d:]
    return torch.cat([x1 * cos + x2 * sin, x1 * (-sin) + x2 * cos], dim=-1)


class Attention(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.n_head = cfg.n_head
        self.qkv = nn.Linear(cfg.n_embd, 3 * cfg.n_embd, bias=False)
        self.proj = nn.Linear(cfg.n_embd, cfg.n_embd, bias=False)

    def forward(self, x, cos, sin, cache=None, layer=0):
        B, T, C = x.size()
        q, k, v = self.qkv(x).view(B, T, 3, self.n_head, C // self.n_head).unbind(2)
        q, k = apply_rotary(q, cos, sin), apply_rotary(k, cos, sin)
        q, k, v = (t.transpose(1, 2) for t in (q, k, v))
        if cache is not None:
            kv = cache.append(layer, k, v)
            k, v = kv[0], kv[1]
        y = F.scaled_dot_product_attention(q, k, v, is_causal=cache is None)
        return self.proj(y.transpose(1, 2).contiguous().view(B, T, C))


class GPT(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.wte = nn.Embedding(cfg.vocab_size, cfg.n_embd)
        self.blocks = nn.ModuleList([Attention(cfg) for _ in range(cfg.n_layer)])
        self.lm_head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.wte.weight  # tied

    def forward(self, idx, targets=None, cache=None):
        x = self.wte(idx)
        cos, sin = self.rotary(idx.size(1))
        for i, block in enumerate(self.blocks):
            x = x + block(x, cos, sin, cache, i)
        logits = self.lm_head(x)
        if targets is None:
            return logits
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss
''',
    "data.py": '''"""The sharded token loader."""
import glob
import random

import numpy as np
import torch


class ShardLoader:
    def __init__(self, data_dir, batch_size, seq_len, rank=0, world=1):
        self.files = sorted(glob.glob(f"{data_dir}/*.bin"))
        self.B, self.T = batch_size, seq_len
        self.rank, self.world = rank, world
        self.epoch, self.shard, self.pos = 0, 0, 0
        self._open(0)

    def _open(self, i):
        self.tokens = np.memmap(self.files[i], dtype=np.uint16, mode="r")

    def _next_shard(self):
        self.epoch += self.shard == len(self.files) - 1
        random.Random(self.epoch).shuffle(self.files)
        self.shard = (self.shard + 1) % len(self.files)
        self._open(self.shard)

    def next_batch(self):
        span = self.B * self.T + 1
        start = self.pos + self.rank * span
        buf = torch.from_numpy(self.tokens[start:start + span].astype(np.int64))
        self.pos += self.world * span
        return buf[:-1].view(self.B, self.T), buf[1:].view(self.B, self.T)
''',
    "engine.py": '''"""Sampling with a KV cache."""
import torch


class KVCache:
    def __init__(self, cfg, batch, max_len):
        hd = cfg.n_embd // cfg.n_head
        shape = (cfg.n_layer, 2, batch, cfg.n_head, max_len, hd)
        self.kv = torch.zeros(shape, dtype=torch.bfloat16)
        self.pos = 0

    def append(self, layer, k, v):
        t = k.size(2)
        self.kv[layer, 0, :, :, self.pos:self.pos + t] = k
        self.kv[layer, 1, :, :, self.pos:self.pos + t] = v
        return self.kv[layer, :, :, :, :self.pos + t]

    def advance(self, t):
        self.pos += t


class Engine:
    def __init__(self, model, tok):
        self.model, self.tok = model, tok
        self._cache = None

    def generate(self, prompt, max_tokens=256, temperature=0.8):
        cfg = self.model.cfg
        cache = self._cache or KVCache(cfg, batch=1, max_len=cfg.block_size)
        x = torch.tensor([self.tok.encode(prompt)])
        cache.pos = 0
        logits = self.model(x, cache=cache)  # prefill
        cache.advance(x.size(1))
        out = []
        for _ in range(max_tokens):
            nxt = sample(logits[:, -1], temperature)
            logits = self.model(nxt, cache=cache)
            cache.advance(1)
            out.append(nxt.item())
        # keep the buffer: the next call reuses it
        self._cache = cache
        return self.tok.decode(out)


def sample(logits, temperature):
    probs = torch.softmax(logits / temperature, dim=-1)
    return torch.multinomial(probs, 1)
''',
    "optim.py": '''"""AdamW and the learning-rate schedule."""
import torch


def build_optimizer(model, cfg):
    decay = [p for p in model.parameters() if p.ndim == 2]
    other = [p for p in model.parameters() if p.ndim != 2]
    groups = [{"params": decay, "weight_decay": 0.1}, {"params": other, "weight_decay": 0.0}]
    return torch.optim.AdamW(groups, lr=cfg.lr, betas=(0.9, 0.95))


def schedule(step, cfg):
    if step < cfg.warmup:
        return cfg.lr * (step + 1) / cfg.warmup
    frac = (step - cfg.warmup) / max(1, cfg.steps - cfg.warmup)
    return cfg.lr * (1.0 - frac)
''',
    "tokenizer.py": '''"""Encode and decode with tiktoken."""
import tiktoken

_enc = tiktoken.get_encoding("gpt2")


def encode(text):
    return _enc.encode(text)


def decode(ids):
    return _enc.decode(ids)
''',
    "train.py": '''"""The training loop."""
from contextlib import nullcontext

import torch

from data import ShardLoader
from model import GPT, ModelConfig
from optim import build_optimizer, schedule


def main(cfg):
    torch.manual_seed(cfg.seed)
    model = GPT(ModelConfig())
    loader = ShardLoader(cfg.data_dir, cfg.batch_size, cfg.seq_len)
    opt = build_optimizer(model, cfg)
    use_bf16 = torch.cuda.is_available()
    ctx = torch.autocast("cuda", dtype=torch.bfloat16) if use_bf16 else nullcontext()
    for step in range(cfg.steps):
        lr = schedule(step, cfg)
        for group in opt.param_groups:
            group["lr"] = lr
        for micro in range(cfg.grad_accum):
            x, y = loader.next_batch()
            with ctx:
                _, loss = model(x, y)
            loss = loss / cfg.grad_accum
            loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        if step % 10 == 0:
            print(step, loss.item() * cfg.grad_accum, lr)
        if step % 500 == 0:
            torch.save({"model": model.state_dict(), "step": step}, f"ckpt_{step}.pt")
''',
    "tests/test_model.py": '''from model import GPT, ModelConfig


def test_head_is_tied_to_embedding():
    m = GPT(ModelConfig(n_layer=2))
    assert m.lm_head.weight is m.wte.weight
''',
    "tests/test_optim.py": '''from types import SimpleNamespace

from optim import schedule


def test_warmup_then_linear_decay():
    cfg = SimpleNamespace(lr=1.0, warmup=200, steps=1000)
    assert schedule(199, cfg) == 1.0
    assert schedule(1000, cfg) == 0.0
''',
}

# the commit after the map was saved (refreshed variant): train.py's precision and accumulation lines change,
# tokenizer.py is deleted, data.py gains lines at the top (its claims move)
TRAIN_B = FILES["train.py"].replace(
    '''    use_bf16 = torch.cuda.is_available()
    ctx = torch.autocast("cuda", dtype=torch.bfloat16) if use_bf16 else nullcontext()''',
    '''    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if use_bf16 else torch.float16
    ctx = torch.autocast("cuda", dtype=dtype) if torch.cuda.is_available() else nullcontext()''').replace(
    '''            loss = loss / cfg.grad_accum
            loss.backward()''',
    '''            (loss / cfg.grad_accum).backward()''')
DATA_B = FILES["data.py"].replace('"""The sharded token loader."""\n',
                                  '"""The sharded token loader.\n\nShards are flat uint16 token files.\n"""\n')


def line_of(path: str, text: str) -> int:
    return FILES[path].splitlines().index(text) + 1


def A(path, anchor, block=False, end_anchor=None):
    out = {"path": path, "anchor": anchor}
    if end_anchor:
        out["end_anchor"] = end_anchor
    if block:
        out["extent"] = "block"
    return out


def C(key, text, evidence, *anchors, **extra):
    return {"key": key, "text": text, "evidence": evidence, "anchors": list(anchors), **extra}


def S(text, claim=None):
    return {"text": text, "claim": claim} if claim else {"text": text}


MAP_CLAIMS = [
    C("entry", "`train.py` is the only entry point", "read_in_source", A("train.py", "def main(cfg):")),
    C("loop", "It builds the model, the data loader and one AdamW optimizer, then runs a fixed number of steps",
      "read_in_source", A("train.py", "    model = GPT(ModelConfig())", ), A("train.py", "    for step in range(cfg.steps):")),
    C("layers", "The model is a 12-layer decoder-only transformer", "read_in_source", A("model.py", "    n_layer: int = 12")),
    C("rotary", "Positions are rotary, not learned", "read_in_source", A("model.py", "def apply_rotary(x, cos, sin):", True)),
    C("tied", "The token embedding and the output head share one weight matrix", "asserted_by_test",
      A("tests/test_model.py", "def test_head_is_tied_to_embedding():", True)),
    C("memmap", "Training data is pre-tokenized into `uint16` shards that the loader memory-maps, so no shard is ever loaded whole",
      "read_in_source", A("data.py", "        self.tokens = np.memmap(self.files[i], dtype=np.uint16, mode=\"r\")")),
    C("slice", "Each GPU reads its own interleaved slice of every shard, so multi-GPU runs need no sampler", "inferred",
      A("data.py", "        start = self.pos + self.rank * span", end_anchor="        self.pos += self.world * span")),
    C("bf16", "It trains in bf16 autocast on CUDA and in fp32 everywhere else", "seen_at_runtime",
      A("train.py", "    use_bf16 = torch.cuda.is_available()", end_anchor="    ctx = torch.autocast(\"cuda\", dtype=torch.bfloat16) if use_bf16 else nullcontext()")),
    C("noclip", "There is no gradient clipping", "searched_not_found", searched=["clip_grad", "clip_grad_norm_", "max_norm"]),
    C("readme", "The README reports 3.3 validation loss after about two hours on one H100", "docs",
      A("README.md", "The default config reaches 3.3 validation loss in about 2 hours on one H100.")),
    C("accum", "Gradients accumulate over `grad_accum` micro-batches before each optimizer step", "read_in_source",
      A("train.py", "        for micro in range(cfg.grad_accum):", end_anchor="        opt.step()")),
    C("ckpt", "Every 500 steps it saves the weights and the step, but not the optimizer state", "read_in_source",
      A("train.py", "        if step % 500 == 0:", end_anchor="            torch.save({\"model\": model.state_dict(), \"step\": step}, f\"ckpt_{step}.pt\")")),
    C("sdpa", "Attention is one call to `scaled_dot_product_attention`", "read_in_source",
      A("model.py", "        y = F.scaled_dot_product_attention(q, k, v, is_causal=cache is None)")),
    C("kernel", "Which kernel runs (flash, memory-efficient or plain) is picked by PyTorch at run time", "inferred",
      A("model.py", "        y = F.scaled_dot_product_attention(q, k, v, is_causal=cache is None)")),
    C("shuffle", "Shard order is reshuffled every epoch, seeded by the epoch number", "read_in_source",
      A("data.py", "        random.Random(self.epoch).shuffle(self.files)")),
    C("kv", "`Engine.generate` caches keys and values per layer and appends one position per new token", "read_in_source",
      A("engine.py", "    def generate(self, prompt, max_tokens=256, temperature=0.8):", True)),
    C("groups", "Every 2-D weight gets weight decay 0.1; biases and norms get none", "read_in_source",
      A("optim.py", "def build_optimizer(model, cfg):", True)),
    C("sched", "The learning rate warms up linearly, then decays linearly to zero", "asserted_by_test",
      A("tests/test_optim.py", "def test_warmup_then_linear_decay():", True)),
    C("tok", "Tokenizing is tiktoken's `gpt2` encoding", "read_in_source",
      A("tokenizer.py", "_enc = tiktoken.get_encoding(\"gpt2\")")),
    # hops of the two flows
    C("h1", "main pulls each micro-batch from the loader", "read_in_source", A("train.py", "            x, y = loader.next_batch()")),
    C("h2", "next_batch slices one span from the memory-mapped shard", "read_in_source", A("data.py", "    def next_batch(self):", True)),
    C("h3", "the forward pass runs under the autocast context", "seen_at_runtime", A("train.py", "                _, loss = model(x, y)")),
    C("h4", "backward runs once per micro-batch on the scaled loss", "seen_at_runtime", A("train.py", "            loss.backward()")),
    C("h5", "the optimizer steps once per outer step", "inferred", A("train.py", "        opt.step()")),
    C("g1", "generate encodes the prompt", "read_in_source", A("engine.py", "        x = torch.tensor([self.tok.encode(prompt)])")),
    C("g2", "the prefill runs every prompt position in one pass", "seen_at_runtime", A("engine.py", "        logits = self.model(x, cache=cache)  # prefill")),
    C("g3", "each new token is sampled from the last position's logits", "read_in_source", A("engine.py", "            nxt = sample(logits[:, -1], temperature)")),
    C("g4", "the ids are decoded back to text", "read_in_source", A("engine.py", "        return self.tok.decode(out)")),
    C("g5", "each new token runs one decode step through the model, reading the cache", "seen_at_runtime",
      A("engine.py", "            logits = self.model(nxt, cache=cache)")),
]

FLOWS = [
    {"id": "f-step", "title": "What happens in one training step?",
     "lanes": [{"id": "train", "label": "train.py · main", "path": "train.py"},
               {"id": "data", "label": "data.py · ShardLoader", "path": "data.py"},
               {"id": "model", "label": "model.py · GPT", "path": "model.py"},
               {"id": "optim", "label": "optim.py · AdamW", "path": "optim.py"}],
     "loops": [{"id": "acc", "label": "× grad_accum"}],
     "hops": [
         {"from": "train", "to": "data", "call": "loader.next_batch()", "returns": "x, y", "data": "(B, T) int64",
          "label": "one span of B × T + 1 tokens", "loop": "acc", "trace": "seen", "claim": "h2"},
         {"from": "train", "to": "model", "call": "model(x, y)", "data": "logits (B, T, 50304) → loss",
          "label": "under bf16 autocast on CUDA", "loop": "acc", "trace": "seen", "claim": "h3"},
         {"from": "train", "to": "model", "call": "loss.backward()", "label": "on loss / grad_accum", "loop": "acc",
          "trace": "blind_spot", "note": "autograd runs in C++, so the trace sees this call but not its walk back "
          "through model.py", "claim": "h4"},
         {"from": "train", "to": "optim", "call": "opt.step()", "label": "once per outer step", "trace": "unseen",
          "claim": "h5"}]},
    {"id": "f-gen", "title": "How does generate turn a prompt into text?",
     "lanes": [{"id": "engine", "label": "engine.py · Engine", "path": "engine.py"},
               {"id": "model", "label": "model.py · GPT", "path": "model.py"}],
     "loops": [{"id": "tok", "label": "per new token"}],
     "hops": [
         {"from": "engine", "to": "engine", "call": "tok.encode(prompt)", "data": "(1, P) int64", "trace": "seen", "claim": "g1"},
         {"from": "engine", "to": "model", "call": "model(x, cache=cache)", "data": "logits (1, P, 50304)",
          "label": "prefill: all prompt positions at once", "trace": "seen", "claim": "g2"},
         {"from": "engine", "to": "engine", "call": "sample(logits[:, -1])", "data": "(1, 1)", "loop": "tok",
          "trace": "seen", "claim": "g3"},
         {"from": "engine", "to": "model", "call": "model(nxt, cache=cache)", "data": "logits (1, 1, 50304)", "loop": "tok",
          "label": "decode: one new position, reading the cached keys and values", "trace": "seen", "claim": "g5"},
         {"from": "engine", "to": "engine", "call": "tok.decode(out)", "returns": "str", "trace": "seen", "claim": "g4"}]},
]

DOCUMENT = {
    "title": "tinytrain",
    "sections": [
        {"id": "overview", "kind": "overview", "title": "Overview", "blocks": [
            {"id": "b-entry", "type": "text", "spans": [S("`train.py` is the only entry point", "entry"), S(". "),
                                                       S(MAP_CLAIMS[1]["text"], "loop"), S(".")]},
            {"id": "b-model", "type": "text", "spans": [S(MAP_CLAIMS[2]["text"], "layers"), S(". "),
                                                       S("Positions are rotary, not learned", "rotary"), S(". "),
                                                       S(MAP_CLAIMS[4]["text"], "tied"), S(".")]},
            {"id": "b-data", "type": "text", "spans": [S(MAP_CLAIMS[5]["text"], "memmap"), S(". "),
                                                      S(MAP_CLAIMS[6]["text"], "slice"), S(".")]},
            {"id": "b-prec", "type": "text", "spans": [S(MAP_CLAIMS[7]["text"], "bf16"), S(". "),
                                                      S("There is no gradient clipping", "noclip"), S(".")]},
            {"id": "b-readme", "type": "text", "spans": [S(MAP_CLAIMS[9]["text"], "readme"), S(".")]},
        ]},
        {"id": "modules", "kind": "modules", "title": "Modules", "blocks": [
            {"id": "m-train", "type": "module", "path": "train.py", "role": "the training loop", "entry": True, "spans": [S(MAP_CLAIMS[10]["text"], "accum"), S(". "),
                                                                             S(MAP_CLAIMS[11]["text"], "ckpt"), S(".")]},
            {"id": "m-model", "type": "module", "path": "model.py", "role": "GPT, attention blocks", "spans": [S(MAP_CLAIMS[12]["text"], "sdpa"), S(". "),
                                                                             S(MAP_CLAIMS[13]["text"], "kernel"), S(".")]},
            {"id": "m-data", "type": "module", "path": "data.py", "role": "the sharded token loader", "spans": [S(MAP_CLAIMS[14]["text"], "shuffle"), S(".")]},
            {"id": "m-engine", "type": "module", "path": "engine.py", "role": "sampling with a KV cache", "spans": [S(MAP_CLAIMS[15]["text"], "kv"), S(".")]},
            {"id": "m-optim", "type": "module", "path": "optim.py", "role": "AdamW and the schedule", "spans": [S(MAP_CLAIMS[16]["text"], "groups"), S(". "),
                                                                             S(MAP_CLAIMS[17]["text"], "sched"), S(".")]},
            {"id": "m-tok", "type": "module", "path": "tokenizer.py", "role": "tiktoken's gpt2 encoding", "spans": [S(MAP_CLAIMS[18]["text"], "tok"), S(".")]},
        ]},
        {"id": "flows", "kind": "flows", "title": "Flows", "blocks": [
            {"id": "fl-step", "type": "flow", "flow": "f-step", "spans": [
                S("One step pulls `grad_accum` micro-batches, runs the model and backward on each, then steps the optimizer once.")]},
            {"id": "fl-gen", "type": "flow", "flow": "f-gen", "spans": [
                S("Generation runs the whole prompt once (the prefill), then one position per new token, reusing the cache.")]},
        ]},
    ],
    "flows": FLOWS,
}

# -- answers --------------------------------------------------------------------------------------------------------

ANSWER_CACHE = {
    "claims": [
        C("gk", "A KV cache trades memory for speed: each new token reuses the keys and values already computed for the prefix",
          "general_knowledge"),
        C("alloc", "Here it is allocated once, at full length: one bf16 tensor of shape (layers, 2, batch, heads, max_len, head_dim)",
          "read_in_source", A("engine.py", "class KVCache:", True)),
        C("pos", "Each new token writes one position and advances a shared `pos` counter", "read_in_source",
          A("engine.py", "    def append(self, layer, k, v):", end_anchor="        self.pos += t")),
        C("mb", "At the default size and batch 1 that is about 38 MB", "inferred",
          A("model.py", "class ModelConfig:", True)),
        C("freed", "It is freed when `generate` returns; nothing keeps it between calls", "read_in_source",
          A("engine.py", "        # keep the buffer: the next call reuses it", end_anchor="        self._cache = cache")),
    ],
}
ANSWER_POS = [
    C("p1", "Yes: `generate` sets `cache.pos = 0` before the prefill", "read_in_source", A("engine.py", "        cache.pos = 0")),
    C("p2", "The prefill writes every prompt position in one pass, then advances `pos` by the prompt length", "read_in_source",
      A("engine.py", "        logits = self.model(x, cache=cache)  # prefill", end_anchor="        cache.advance(x.size(1))")),
    C("p3", "Old entries past `pos` stay in the buffer, but `append` only returns positions up to `pos`, so they are never read",
      "inferred", A("engine.py", "        return self.kv[layer, :, :, :, :self.pos + t]")),
]
ANSWER_MB = [
    C("m1", "12 layers, 12 heads, head_dim 768 / 12 = 64, max_len 1024", "read_in_source", A("model.py", "class ModelConfig:", True)),
    C("m2", "bf16 stores each value in 2 bytes", "general_knowledge"),
    C("m3", "12 × 2 × 1 × 12 × 1024 × 64 values × 2 bytes ≈ 37.7 MB", "inferred",
      A("engine.py", "        shape = (cfg.n_layer, 2, batch, cfg.n_head, max_len, hd)")),
]
ANSWER_SECOND = {
    "claims": [
        C("t1", "the second call finds self._cache set and makes no new KVCache", "read_in_source",
          A("engine.py", "        cache = self._cache or KVCache(cfg, batch=1, max_len=cfg.block_size)")),
        C("t2", "pos is rewound to 0", "read_in_source", A("engine.py", "        cache.pos = 0")),
        C("t2b", "the prefill runs every prompt position through the model in one pass", "seen_at_runtime",
          A("engine.py", "        logits = self.model(x, cache=cache)  # prefill")),
        C("t3", "the prefill overwrites positions 0 … P−1 in every layer", "seen_at_runtime",
          A("engine.py", "        self.kv[layer, 0, :, :, self.pos:self.pos + t] = k", end_anchor="        self.kv[layer, 1, :, :, self.pos:self.pos + t] = v")),
        C("t4", "entries past pos are never read", "inferred", A("engine.py", "        return self.kv[layer, :, :, :, :self.pos + t]")),
        C("t5", "the buffer is kept again for the next call", "read_in_source", A("engine.py", "        self._cache = cache")),
    ],
    "path": {"id": "p-second", "title": "What happens when generate is called a second time?",
             "lanes": [{"id": "engine", "label": "engine.py · Engine", "path": "engine.py"},
                       {"id": "cache", "label": "engine.py · KVCache", "path": "engine.py"},
                       {"id": "model", "label": "model.py · GPT", "path": "model.py"}],
             "loops": [{"id": "layer", "label": "per layer, × 12"}],
             "hops": [
                 {"from": "engine", "to": "engine", "call": "Engine.generate(prompt)", "label": "self._cache is set: no new KVCache",
                  "returns": "the same KVCache object", "trace": "seen", "claim": "t1"},
                 {"from": "engine", "to": "cache", "call": "cache.pos = 0", "label": "rewinds the write position",
                  "trace": "seen", "claim": "t2"},
                 {"from": "engine", "to": "model", "call": "model(x, cache=cache)", "label": "prefill: all prompt positions at once",
                  "trace": "seen", "claim": "t2b"},
                 {"from": "model", "to": "cache", "call": "KVCache.append(layer, k, v)", "label": "overwrites positions 0 … P−1",
                  "data": "kv[:, :, :, :pos + t]", "loop": "layer", "trace": "seen", "claim": "t3"},
                 {"from": "model", "to": "model", "call": "attention over kv[: pos + t]", "label": "stale entries are never read",
                  "loop": "layer", "trace": "unseen", "claim": "t4"},
                 {"from": "engine", "to": "engine", "call": "self._cache = cache", "label": "keeps the buffer for the next call",
                  "trace": "seen", "claim": "t5"}]},
}
ANSWER_DATA = [
    C("d1", "Yes: each shard is opened with `np.memmap`, which maps the file without reading it", "read_in_source",
      A("data.py", "    def _open(self, i):", True)),
    C("d2", "Reshuffling reorders the file list only; it never touches the token arrays", "read_in_source",
      A("data.py", "        random.Random(self.epoch).shuffle(self.files)")),
    C("d3", "Each batch reads one span of B × T + 1 tokens per GPU, not the shard", "inferred",
      A("data.py", "        span = self.B * self.T + 1", end_anchor="        buf = torch.from_numpy(self.tokens[start:start + span].astype(np.int64))")),
]
ANSWER_LOSS = [
    C("l1", "The loss is divided by `grad_accum` before `backward()`, so the summed gradient is the gradient of the mean loss",
      "read_in_source", A("train.py", "            loss = loss / cfg.grad_accum", end_anchor="            loss.backward()")),
    C("l2", "The optimizer steps once per outer step, after all micro-batches", "read_in_source", A("train.py", "        opt.step()")),
    C("l3", "The logged loss is the average over all micro-batches", "read_in_source",
      A("train.py", "            print(step, loss.item() * cfg.grad_accum, lr)")),
]


def spans_of(drafts, joiner=".\n\n", end="."):
    """Answer spans: each claim's text as one claimed span, one paragraph each (as agents write them)."""
    out = []
    for i, c in enumerate(drafts):
        if i:
            out.append(S(joiner))
        out.append(S(c["text"], c["key"]))
    out.append(S(end))
    return out


# -- a fixed clock, so "since your last visit" and re-check times are deterministic ----------------------------------

CLOCKED = (store_mod, activity, inbox, claims_mod)


@contextlib.contextmanager
def clock(when: datetime):
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    old = [m.now_iso for m in CLOCKED]
    for m in CLOCKED:
        m.now_iso = lambda: stamp
    try:
        yield
    finally:
        for m, f in zip(CLOCKED, old, strict=True):
            m.now_iso = f


def iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *GIT_CONFIG, "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout


def make_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for path, text in FILES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "tinytrain")
    git(root, "remote", "add", "origin", "https://github.com/example/tinytrain.git")
    sha = git(root, "rev-parse", "HEAD").strip()
    git(root, "update-ref", "refs/remotes/origin/main", sha)  # "pushed": GitHub permalinks are offered
    return sha


def map_anchor(document: dict, revision: str, quote: str) -> dict:
    text = plain_text(document)
    start = text.index(quote)
    assert text.find(quote, start + 1) == -1, quote
    return {"doc": "map", "revision": revision, "quote": quote, "start": start, "end": start + len(quote)}


def answer_anchor(response: dict, quote: str) -> dict:
    start = response["text"].index(quote)
    return {"doc": f"answer:{response['id']}", "revision": response["revision"], "quote": quote, "start": start,
            "end": start + len(quote)}


def ask(st: Store, text: str, anchor: dict, parent: str | None = None) -> dict:
    body = {"text": text, "anchor": anchor}
    if parent:
        body["parent_response"] = parent
    return inbox.post_question(st, body)


def answer(st: Store, repo: Repo, q: dict, agent: str, drafts: list, path: dict | None = None, spans=None) -> dict:
    data = {"question": q["id"], "agent": agent, "claims": drafts, "spans": spans or spans_of(drafts),
            "generation": {"model": "fixture"}}
    if path:
        data["path"] = path
    return inbox.record_answer(st, repo, data)["response"]


def check_all(st: Store, response: dict | None = None, flags: dict | None = None) -> None:
    """The Checker's verdicts: supported, except ``flags`` (key -> note) not supported; general knowledge skipped."""
    flags = flags or {}
    claims = response["claims"] if response else st.load("map")["claims"]
    verdicts = []
    for c in claims:
        if c["evidence"] == "general_knowledge":
            verdicts.append({"claim": c["id"], "verdict": "skipped"})
        elif c.get("key") in flags:
            verdicts.append({"claim": c["id"], "verdict": "not_supported", "note": flags[c["key"]]})
        else:
            verdicts.append({"claim": c["id"], "verdict": "supported"})
    claims_mod.set_verdicts(st, {"verdicts": verdicts})


def build(out: Path, variant: str) -> dict:
    if variant not in VARIANTS:
        raise SystemExit(f"variant must be one of {', '.join(VARIANTS)}")
    base = out / variant
    root, home = base / "repo", base / "home"
    sha = make_repo(root)
    repo = Repo.open(root)
    identity = identify(repo).to_dict()
    st = Store(identity["id"], root=home)
    st.init(identity)
    info = {"variant": variant, "repo": str(root), "home": str(home), "store": str(st.dir), "commit": sha, "ids": {}}
    if variant == "empty":
        return info
    now = datetime.now(timezone.utc).replace(microsecond=0)
    t0 = now - timedelta(hours=3)
    ids = info["ids"]
    with clock(t0):
        saved = claims_mod.save_claims(st, repo, {"target": "map", "mode": "replace", "claims": MAP_CLAIMS,
                                                  "document": DOCUMENT})
        check_all(st)
        doc = st.load("map")["document"]
        rev = doc["revision"]
        # 1. the KV cache: an answer with a general-knowledge claim and a not-supported claim, three follow-ups
        q1 = ask(st, "How big does the cache get, and when is it freed?",
                 map_anchor(doc, rev, "caches keys and values per layer"))
        r1 = answer(st, repo, q1, "investigator", ANSWER_CACHE["claims"])
        check_all(st, r1, {"freed": f"Line {line_of('engine.py', '        self._cache = cache')} keeps the cache on "
                                     "self._cache, so the next call reuses it."})
        q1a = ask(st, "Is pos reset between prompts?", answer_anchor(r1, "advances a shared `pos` counter"), r1["id"])
        r1a = answer(st, repo, q1a, "investigator", ANSWER_POS)
        check_all(st, r1a)
        q1b = ask(st, "How is 38 MB computed?", answer_anchor(r1, "about 38 MB"), r1["id"])
        r1b = answer(st, repo, q1b, "investigator", ANSWER_MB)
        check_all(st, r1b)
        q1c = ask(st, "What happens when generate is called a second time?",
                  answer_anchor(r1, "nothing keeps it between calls"), r1["id"])
        r1c = answer(st, repo, q1c, "tracer", ANSWER_SECOND["claims"], path=ANSWER_SECOND["path"],
                     spans=[S("So the cache is not freed: the second call reuses the same buffer and rewinds it.")])
        check_all(st, r1c)
        # 2. the data loader
        q2 = ask(st, "Does this still hold when shards are reshuffled?",
                 map_anchor(doc, rev, "no shard is ever loaded whole"))
        r2 = answer(st, repo, q2, "investigator", ANSWER_DATA)
        check_all(st, r2)
        # 3. the training loop: one claim the Checker flags
        q3 = ask(st, "What does this mean for the logged loss?", map_anchor(doc, rev, "before each optimizer step"))
        r3 = answer(st, repo, q3, "investigator", ANSWER_LOSS)
        check_all(st, r3, {"l3": f"Line {line_of('train.py', '            print(step, loss.item() * cfg.grad_accum, lr)')} logs "
                                 "the last micro-batch's loss, rescaled; it is not an average."})
        # a follow-up routed to the Tracer whose path is the map's training-step flow
        r3_whole = {"doc": f"answer:{r3['id']}", "revision": r3["revision"], "quote": r3["text"], "start": 0,
                    "end": len(r3["text"])}
        q3a = ask(st, "What happens in one training step?", r3_whole, r3["id"])
        step_claims = [dict(c) for c in MAP_CLAIMS if c["key"] in ("h2", "h3", "h4", "h5")]
        r3a = answer(st, repo, q3a, "tracer", step_claims, path=json.loads(json.dumps(FLOWS[0])),
                     spans=[S("One step pulls grad_accum micro-batches, runs the model and backward on each, "
                              "then steps the optimizer once.")])
        check_all(st, r3a)
        # notes: one on the map, one saved answer
        inbox.post_note(st, {"text": "Compare with nanochat: is rotary applied before or after the QK norm?",
                             "anchor": map_anchor(doc, rev, "Positions are rotary, not learned")})
        inbox.post_note(st, {"text": r2["text"], "from_response": r2["id"]})
        inbox.post_note(st, {"text": "Inferred, not read: worth a runtime check with 2 GPUs.", "share_with_agents": True,
                             "anchor": map_anchor(doc, rev, "Each GPU reads its own interleaved slice of every shard")})
    ids.update(q1=q1["id"], r1=r1["id"], q1a=q1a["id"], q1b=q1b["id"], q1c=q1c["id"], q2=q2["id"], q3=q3["id"],
               r3=r3["id"], q3a=q3a["id"], r3a=r3a["id"], r1c=r1c["id"], saved=len(saved["saved"]))
    info["visits"] = {"previous": iso(t0 + timedelta(hours=1)), "last": iso(t0 + timedelta(hours=2))}
    set_visits(st, **info["visits"])

    if variant == "working":
        with clock(now - timedelta(seconds=40)):
            # an answered follow-up whose claims the Checker hasn't reached yet
            q4 = ask(st, "Does the cache grow past block_size?", answer_anchor(r1, "allocated once, at full length"), r1["id"])
            r4 = answer(st, repo, q4, "investigator", [
                C("w1", "No: it is allocated with `max_len=cfg.block_size` and never resized", "read_in_source",
                  A("engine.py", "        cache = self._cache or KVCache(cfg, batch=1, max_len=cfg.block_size)")),
                C("w2", "Writing past `max_len` would fail with a shape error rather than grow it", "inferred",
                  A("engine.py", "        self.kv[layer, 0, :, :, self.pos:self.pos + t] = k")),
                C("w3", "So `max_tokens` plus the prompt must fit in `block_size`", "inferred",
                  A("engine.py", "    def generate(self, prompt, max_tokens=256, temperature=0.8):"))])
            first = r4["claims"][0]["id"]
            claims_mod.set_verdicts(st, {"claim": first, "verdict": "supported"})
            # a follow-up being investigated, and a new question on the map routed to the Tracer
            q5 = ask(st, "Is the cache shared between two Engine objects?", answer_anchor(r1, "advances a shared `pos` counter"), r1["id"])
            inbox.claim(st, {"id": q5["id"], "agent": "investigator"})
            q6 = ask(st, "What happens when a run resumes from a checkpoint?", map_anchor(doc, rev, "saves the weights and the step"))
            inbox.claim(st, {"id": q6["id"], "agent": "tracer"})
        activity.start(st, {"agent": "checker", "question": q4["id"], "status": "checking claim 2 of 3 against `engine.py` 39"})
        activity.start(st, {"agent": "investigator", "question": q5["id"], "status": "reading `engine.py` 4–21 …"})
        activity.start(st, {"agent": "tracer", "question": q6["id"], "status": "following `torch.save` into `train.py` 31"})
        activity.start(st, {"agent": "cartographer", "question": None, "status": "mapping `optim.py` (5 of 7 files)"})
        ids.update(q4=q4["id"], q5=q5["id"], q6=q6["id"])

    if variant == "refreshed":
        (root / "train.py").write_text(TRAIN_B)
        (root / "data.py").write_text(DATA_B)
        (root / "tokenizer.py").unlink()
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "mixed precision on GPUs without bf16; drop tokenizer.py")
        head = git(root, "rev-parse", "HEAD").strip()   # local only: not on origin, so no GitHub link
        t_refresh = now - timedelta(minutes=30)
        note = "`tokenizer.py` was deleted; `train.py` precision and accumulation changed."
        with clock(t_refresh):
            try:   # T7.5's one-call refresh, when present
                from honeyguide.memory import refresh_apply
                refresh_apply(repo, st, {"note": note})
            except ImportError:
                m, a = st.load("map"), st.load("answers")
                plan = plan_refresh(repo, all_claims(m, a))
                apply_plan(st, plan)
                counts: dict[str, int] = {}
                for r in plan.claims:
                    counts[r.state] = counts.get(r.state, 0) + 1
                activity.add_refresh(st, {"base": sha, "target": head, "counts": counts, "note": note})
        by_key = {c.get("key"): c for c in st.load("map")["claims"]}
        with clock(now - timedelta(minutes=20)):
            # the Checker has re-read one stale map claim (it still holds at the new lines); the rest wait
            verdict = (lambda d: claims_mod.set_verdicts(st, d, repo)) if "repo" in \
                claims_mod.set_verdicts.__code__.co_varnames else (lambda d: claims_mod.set_verdicts(st, d))
            verdict({"verdicts": [
                {"claim": by_key["accum"]["id"], "verdict": "supported", "note": "re-read at the new lines",
                 "anchors": [A("train.py", "        for micro in range(cfg.grad_accum):", end_anchor="        opt.step()")]}]})
        waiting = [c for _, c in all_claims(st.load("map"), st.load("answers"))
                   if c["freshness"] == "stale" and c["check"] == "unchecked"]
        activity.start(st, {"agent": "checker", "question": None,
                            "status": f"re-checking {len(waiting)} stale claims in `train.py`"})
        info["counts"] = (load_session(st)["refresh_log"] or [{}])[-1].get("counts")
        # last visited after the map was built, before the refresh: one claim re-checked since
        info["visits"] = {"previous": iso(t_refresh - timedelta(hours=1)), "last": iso(t_refresh - timedelta(minutes=50))}
        set_visits(st, **info["visits"])
        info["head"] = head
    return info


def waiting_and_failed(info: dict) -> dict:
    """Two more questions on a built variant (T7.12): one open that nobody has picked up (the page shows it waiting
    for the Guide) and one that failed. Adds their ids to ``info["ids"]`` as ``qwait`` and ``qfail``."""
    st = Store(Path(info["store"]).name, root=Path(info["home"]))
    doc = st.load("map")["document"]
    rev = doc["revision"]
    q = ask(st, "Why is the learning rate warmed up?", map_anchor(doc, rev, "Positions are rotary, not learned"))
    f = ask(st, "Where are the checkpoints written?", map_anchor(doc, rev, "saves the weights and the step"))
    inbox.claim(st, {"id": f["id"], "agent": "investigator"})
    inbox.fail(st, {"id": f["id"], "reason": "the session ended before the answer was saved"})
    info["ids"].update(qwait=q["id"], qfail=f["id"])
    return info


def load_session(st: Store) -> dict:
    return load_session_side(st, "session")


def set_visits(st: Store, previous: str | None, last: str | None) -> None:
    """The page posts a visit on load; screenshots of "since your last visit" reset it first."""
    def apply(d: dict) -> None:
        d["previous_visit"], d["last_visit"] = previous, last
    update_side(st, "session", apply)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out")
    p.add_argument("--variant", default="base", choices=VARIANTS)
    args = p.parse_args(argv)
    print(json.dumps(build(Path(args.out), args.variant), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
