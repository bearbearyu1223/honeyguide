"""Reading one `claude -p --output-format stream-json` run: the result event, the model, tokens, tool calls, the
run's status. Pure (text in, dicts out).

Statuses (final unless noted):
  ok              a result with is_error false and a parseable answer
  capped          the result's subtype is error_max_* (budget or turns): counts as wrong, never re-run
  invalid_answer  the run finished but its answer is not the schema's JSON: counts as wrong, never re-run
  error           no result, a non-zero exit, a timeout, or is_error: counts as wrong; re-run only with
                  --retry-failed, and the earlier attempt is kept
  usage_limit     the subscription's usage limit stopped the run (not final: the runner stops and the run is
                  resumed later; logged)
"""

from __future__ import annotations

import json
import re

USAGE_LIMIT = re.compile(r"usage limit|limit reached|limit will reset|resets at|rate[_ ]limit", re.I)
FINAL = ("ok", "capped", "invalid_answer", "error")
TOKEN_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


def parse_stream(stdout: str) -> dict:
    """{init, result, tool_calls, tool_names} from stream-json lines; result is the last result event."""
    init = result = None
    tools: dict[str, int] = {}
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            init = obj
        elif obj.get("type") == "result":
            result = obj
        elif obj.get("type") == "assistant":
            for block in (obj.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name"))
                    tools[name] = tools.get(name, 0) + 1
    return {"init": init, "result": result, "tool_calls": sum(tools.values()), "tool_names": dict(sorted(tools.items()))}


def is_usage_limit(result: dict | None, stderr: str) -> bool:
    if result and result.get("api_error_status") == 429:
        return True
    if result and not result.get("is_error"):
        return False   # a finished run is never a usage-limit stop, whatever stderr mentions
    texts = [stderr or ""]
    if result and result.get("is_error"):
        texts.append(str(result.get("result") or ""))
        texts += [str(e) for e in result.get("errors") or []]
    return any(USAGE_LIMIT.search(t) for t in texts)


def classify(exit_code: int | None, result: dict | None, stderr: str, answer_ok: bool,
             timed_out: bool = False) -> tuple[str, str]:
    """(status, reason)."""
    if timed_out:
        return "error", "timeout"
    if is_usage_limit(result, stderr):
        return "usage_limit", "usage limit"
    if result is None:
        return "error", f"no result event (exit {exit_code})"
    sub = str(result.get("subtype") or "")
    if sub.startswith("error_max"):
        return "capped", sub
    if result.get("is_error") or sub.startswith("error"):
        return "error", sub or "is_error"
    if exit_code not in (0, None):
        return "error", f"exit {exit_code}"
    if not answer_ok:
        return "invalid_answer", "answer is not the schema's JSON"
    return "ok", ""


def usage_summary(result: dict | None) -> dict:
    """Tokens by type, cache writes split by TTL, reported cost, models used."""
    if not result:
        return {"tokens": {k: 0 for k in TOKEN_FIELDS}, "cache_write_1h": 0, "cache_write_5m": 0,
                "cost_usd": 0.0, "models": [], "num_turns": 0, "duration_ms": 0}
    u = result.get("usage") or {}
    cc = u.get("cache_creation") or {}
    return {"tokens": {k: int(u.get(k) or 0) for k in TOKEN_FIELDS},
            "cache_write_1h": int(cc.get("ephemeral_1h_input_tokens") or 0),
            "cache_write_5m": int(cc.get("ephemeral_5m_input_tokens") or 0),
            "cost_usd": float(result.get("total_cost_usd") or 0.0),
            "models": sorted((result.get("modelUsage") or {}).keys()),
            "num_turns": int(result.get("num_turns") or 0), "duration_ms": int(result.get("duration_ms") or 0)}


def parse_answer(result: dict | None) -> tuple[dict | None, str]:
    """The answer object ({items, text}) and how it was read, or (None, why not)."""
    if not result:
        return None, "no result"
    obj = result.get("structured_output")
    how = "structured_output"
    if not isinstance(obj, dict):
        text = str(result.get("result") or "").strip()
        m = re.match(r"^```(?:json)?\s*\n(.*)\n```$", text, re.S)
        if m:
            text = m.group(1)
        try:
            obj = json.loads(text)
            how = "result text"
        except json.JSONDecodeError:
            return None, "result text is not JSON"
    if not isinstance(obj, dict) or not isinstance(obj.get("items"), list) or not isinstance(obj.get("text"), str):
        return None, "not {items, text}"
    items = []
    for it in obj["items"]:
        if isinstance(it, dict) and isinstance(it.get("file"), str) and isinstance(it.get("symbol"), str):
            row = {"file": it["file"], "symbol": it["symbol"]}
            if isinstance(it.get("line"), int):
                row["line"] = it["line"]
            items.append(row)
    return {"items": items, "text": obj["text"]}, how


def notional_cost(summary: dict, prices: dict) -> dict:
    """List-price cost rebuilt from tokens (with cache, to check the price table) and without cache (every input
    token at the input price)."""
    t = summary["tokens"]
    m = 1e-6
    w1h, w5m = summary["cache_write_1h"], summary["cache_write_5m"]
    other_w = max(0, t["cache_creation_input_tokens"] - w1h - w5m)   # TTL not reported: priced as 5-minute
    with_cache = m * (t["input_tokens"] * prices["input"] + t["cache_read_input_tokens"] * prices["cache_read"]
                      + w1h * prices["cache_write_1h"] + (w5m + other_w) * prices["cache_write_5m"]
                      + t["output_tokens"] * prices["output"])
    all_in = t["input_tokens"] + t["cache_read_input_tokens"] + t["cache_creation_input_tokens"]
    without = m * (all_in * prices["input"] + t["output_tokens"] * prices["output"])
    return {"rebuilt_with_cache": with_cache, "without_cache": without}
