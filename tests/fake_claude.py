"""A stand-in for `claude -p --output-format stream-json` in the eval tests: no model, no network.

The tests copy this file to <dir>/claude (with a shebang for the test's Python) and write <dir>/claude.json, the
control file:
  {"rules": [{"match": "<substring of the prompt>", "cond": "map" (optional), "behavior": "...",
              "answer": {"items": [...], "text": "..."}}, ...],
   "map_output": {...claims save input...}, "map_behavior": "ok",
   "fix_outputs": [{...}, ...], "fix_behaviors": ["ok", ...]}
A map fix round (prompt starts "MODE: fix") returns fix_outputs[n-1] for the n-th fix call (the last one repeats;
default map_output) with fix_behaviors[n-1] (default ok); it records the --add-dir folder's files and whether the
PREVIOUS file in the prompt was there.
behaviors: ok, error, capped, usage_limit, usage_limit_once (first call usage limit, later ok), bad_json,
echo_token (prints the token it was given, to test that the runner withholds it).
Each call is appended to <dir>/calls.jsonl: the argv without the prompt, a prompt hash, the condition it saw, the
working dir's files, the environment's variable names and whether a token was present (never the token itself).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROL = json.loads((HERE / "claude.json").read_text())
TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"


def condition(argv, prompt):
    tools = argv[argv.index("--tools") + 1] if "--tools" in argv else None
    if tools == "":
        return "no-access"
    if prompt.startswith("MODE: fix\n"):
        return "mapfix"
    if "MODE: explore" in prompt and "Eval mode" in prompt:
        return "mapbuild"
    if "Notes about this repository" in prompt:
        return "outline" if "# Outline of" in prompt else "map"
    return "explore"


def listing(cwd):
    root = Path(cwd)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def emit(model, cwd, result, tool_use=True):
    print(json.dumps({"type": "system", "subtype": "init", "model": model, "cwd": cwd, "tools": []}))
    if tool_use:
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "x"}}]}}))
    print(json.dumps(result))


def main():
    argv = sys.argv[1:]
    prompt = argv[argv.index("-p") + 1]
    model = argv[argv.index("--model") + 1]
    cwd = os.getcwd()
    cond = condition(argv, prompt)
    calls = HERE / "calls.jsonl"
    shown = [a for i, a in enumerate(argv) if i != argv.index("-p") + 1]
    extra = {}
    if "--add-dir" in argv:
        add = argv[argv.index("--add-dir") + 1]
        extra["add_dir"] = add
        extra["add_dir_files"] = listing(add)
    if cond == "mapfix":
        prev = next(ln.split(": ", 1)[1] for ln in prompt.splitlines() if ln.startswith("PREVIOUS: "))
        extra["previous"] = prev
        extra["previous_map"] = json.loads(Path(prev).read_text()) if Path(prev).exists() else None
        extra["prompt"] = prompt.split("\n-----\n")[0]       # the head and the errors, not the brief
    n_fix = 0
    if calls.exists():
        n_fix = sum(1 for ln in calls.read_text().splitlines() if json.loads(ln)["cond"] == "mapfix")
    with calls.open("a") as f:
        f.write(json.dumps({"argv": shown, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
                            "cond": cond, "cwd": cwd, "files": listing(cwd), "env": sorted(os.environ),
                            "home": os.environ.get("HOME"), "token_present": bool(os.environ.get(TOKEN_VAR)),
                            "path": os.environ.get("PATH"), **extra}) + "\n")
    if cond == "mapbuild":
        behavior, answer = CONTROL.get("map_behavior", "ok"), CONTROL["map_output"]
    elif cond == "mapfix":
        outs = CONTROL.get("fix_outputs") or [CONTROL["map_output"]]
        behs = CONTROL.get("fix_behaviors") or ["ok"]
        answer, behavior = outs[min(n_fix, len(outs) - 1)], behs[min(n_fix, len(behs) - 1)]
    else:
        behavior, answer = "ok", {"items": [], "text": "I could not tell."}
        for r in CONTROL["rules"]:
            if r["match"] in prompt and r.get("cond", cond) == cond:
                behavior, answer = r.get("behavior", "ok"), r.get("answer", answer)
                break
    if behavior == "usage_limit_once":
        state = HERE / ("once-" + hashlib.sha256(prompt.encode()).hexdigest()[:12])
        if state.exists():
            behavior = "ok"
        else:
            state.write_text("1")
            behavior = "usage_limit"
    usage = {"input_tokens": 10, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 500,
             "output_tokens": 100, "cache_creation": {"ephemeral_1h_input_tokens": 500, "ephemeral_5m_input_tokens": 0}}
    cost = (10 * 4 + 1000 * 0.2 + 500 * 8 + 100 * 20) / 1e6
    base = {"type": "result", "num_turns": 3, "duration_ms": 1200, "total_cost_usd": cost, "usage": usage,
            "modelUsage": {model: {"inputTokens": 10, "costUSD": cost, "costBasis": "list"}}}
    if behavior == "usage_limit":
        emit(model, cwd, {**base, "subtype": "success", "is_error": True, "total_cost_usd": 0,
                          "result": "Claude AI usage limit reached|1794777040"}, tool_use=False)
        return 1
    if behavior == "error":
        emit(model, cwd, {**base, "subtype": "error_during_execution", "is_error": True, "result": ""})
        return 1
    if behavior == "capped":
        emit(model, cwd, {**base, "subtype": "error_max_budget_usd", "is_error": True})
        return 1
    if behavior == "bad_json":
        emit(model, cwd, {**base, "subtype": "success", "is_error": False, "result": "Here is my answer: train.py"})
        return 0
    if behavior == "echo_token":
        print("leaking " + os.environ.get(TOKEN_VAR, ""))
    emit(model, cwd, {**base, "subtype": "success", "is_error": False, "result": json.dumps(answer),
                      "structured_output": answer})
    return 0


if __name__ == "__main__":
    sys.exit(main())
