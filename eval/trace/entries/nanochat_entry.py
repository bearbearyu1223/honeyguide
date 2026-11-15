"""nanochat toy entry point, run under the tracer by runner.py.

Mirrors the order of scripts/base_train.py (build on the meta device, move to
real storage, init weights, set up the optimizer, forward with targets,
backward, one optimizer step) and scripts/chat_cli.py (Engine.generate with
its default sampling settings), at a toy size on the CPU.
"""

import os

# Dynamo will not compile while a profile hook is active ("Attempt to trace
# generator"), so the @torch.compile fused optimizer kernels run eagerly.
# Must be set before torch is imported.
os.environ["TORCH_COMPILE_DISABLE"] = "1"

import torch  # noqa: E402

from nanochat.engine import Engine  # noqa: E402
from nanochat.gpt import GPT, GPTConfig  # noqa: E402
from nanochat.tokenizer import SPECIAL_TOKENS, RustBPETokenizer  # noqa: E402

# Tiny throwaway tokenizer, trained the way tests/test_tokenizer.py does it
# (same method and size, ASCII-only corpus)
CORPUS = [
    "The quick brown fox jumps over the lazy dog.",
    "hello world, hello tokenizer, hello hello hello",
    "Numbers like 12345 and unicode like naive cafe should survive.",
    "def f(x):\n    return x + 1\n",
] * 8
EXTRA_MERGES = 35

CONFIG = {
    "device": "cpu",
    "torch.compile": "disabled (TORCH_COMPILE_DISABLE=1)",
    "model": "GPTConfig(sequence_len=32, n_layer=2, n_head=2, "
             "n_kv_head=2, n_embd=32, window_pattern='SSSL')",
    "tokenizer": "RustBPETokenizer trained on a 4-line corpus x8, "
                 "vocab 256 + %d specials + %d merges" % (len(SPECIAL_TOKENS), EXTRA_MERGES),
    "train batch": "random token ids, B=2, T=16, torch.manual_seed(0)",
    "optimizer": "model.setup_optimizer() defaults (MuonAdamW)",
    "generate": "Engine.generate(prompt, num_samples=1, max_tokens=4, "
                "temperature=0.6, top_k=50, seed=42) (chat_cli defaults "
                "except max_tokens)",
    "prompt": "<|bos|><|user_start|>hello world<|user_end|><|assistant_start|>",
}
BATCH, SEQ = 2, 16

# What a real run does that this toy run does not, from reading the code at
# the pinned commit. (text, repo-relative file, a string that must occur in
# that file; the capture resolves it to a line number.)
SKIPS = [
    ("torch.compile of the fused AdamW/Muon steps: disabled for tracing "
     "(TORCH_COMPILE_DISABLE=1); same Python calls, eager kernels",
     "nanochat/optim.py", "@torch.compile(dynamic=False, fullgraph=True)"),
    ("Flash Attention 3 kernels (CUDA sm80/89/90 only); CPU takes the "
     "SDPA fallback", "nanochat/flash_attention.py",
     "if not torch.cuda.is_available():"),
    ("bf16 compute dtype (CUDA SM80+); CPU/MPS default to float32",
     "nanochat/common.py", "if capability >= (8, 0):"),
    ("sliding-window mask: the short window (128) is longer than T, so "
     "every layer takes the plain causal branch",
     "nanochat/flash_attention.py",
     "mask = mask & ((row_idx - col_idx) <= window)"),
    ("multi-GPU reduce/gather in the optimizer (world_size == 1 here)",
     "nanochat/optim.py",
     "future = dist.all_reduce(grad, op=dist.ReduceOp.AVG, async_op=True)"),
    ("torch.compile of the whole model (outside the package filter)",
     "scripts/base_train.py", "model = torch.compile(model, dynamic=False)"),
    ("FP8 training (H100+, --fp8)", "scripts/base_train.py",
     "# FP8 training initialization"),
    ("fp16 GradScaler path", "scripts/base_train.py",
     "scaler.scale(loss).backward()"),
    ("real data loader and grad accumulation; batch here is random ids",
     "scripts/base_train.py", "for micro_step in range(grad_accum_steps):"),
    ("checkpoint loading (load_model); weights here are fresh init",
     "nanochat/checkpoint_manager.py", "def load_model("),
    ("calculator tool use: an untrained model never emits "
     "<|python_start|>", "nanochat/engine.py",
     "result = use_calculator(expr)"),
]


def versions():
    return {"torch": torch.__version__}


def setup():
    vocab = 256 + len(SPECIAL_TOKENS) + EXTRA_MERGES
    tok = RustBPETokenizer.train_from_iterator(iter(CORPUS), vocab)
    ids = [tok.get_bos_token_id(), tok.encode_special("<|user_start|>")]
    ids += tok.encode("hello world")
    ids += [tok.encode_special("<|user_end|>"),
            tok.encode_special("<|assistant_start|>")]
    torch.manual_seed(0)
    v = tok.get_vocab_size()
    x = torch.randint(0, v, (BATCH, SEQ))
    y = torch.randint(0, v, (BATCH, SEQ))
    cfg = GPTConfig(sequence_len=32, vocab_size=v, n_layer=2, n_head=2,
                    n_kv_head=2, n_embd=32, window_pattern="SSSL")
    return {"tok": tok, "prompt": ids, "x": x, "y": y, "cfg": cfg,
            "results": {"tokenizer vocab": v, "prompt tokens": len(ids)}}


def build(ctx):
    torch.manual_seed(0)
    with torch.device("meta"):
        model = GPT(ctx["cfg"])
    model.to_empty(device="cpu")
    model.init_weights()
    ctx["model"] = model


def optimizer_setup(ctx):
    ctx["opt"] = ctx["model"].setup_optimizer()


def forward_loss(ctx):
    ctx["loss"] = ctx["model"](ctx["x"], ctx["y"])
    ctx["results"]["loss after init"] = round(ctx["loss"].item(), 4)


def backward(ctx):
    ctx["loss"].backward()


def optimizer_step(ctx):
    ctx["opt"].step()
    ctx["model"].zero_grad(set_to_none=True)


def engine_generate(ctx):
    engine = Engine(ctx["model"], ctx["tok"])
    out = []
    for column, _masks in engine.generate(ctx["prompt"], num_samples=1,
                                          max_tokens=4, temperature=0.6,
                                          top_k=50, seed=42):
        out.append(column[0])
    ctx["results"]["generated ids"] = out


PHASES = [
    ("build", "GPT(config) on meta -> to_empty(cpu) -> init_weights()", build),
    ("optimizer_setup", "model.setup_optimizer()", optimizer_setup),
    ("forward_loss", "loss = model(x, y)", forward_loss),
    ("backward", "loss.backward()", backward),
    ("optimizer_step", "optimizer.step(); model.zero_grad()", optimizer_step),
    ("engine_generate", "Engine(model, tok).generate(...), 4 tokens",
     engine_generate),
]
