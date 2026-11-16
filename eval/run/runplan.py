"""The run plan: every (repo, question, condition, pass) answering run plus the eval map builds, their order, their
prompts and their exact command lines.

Pure apart from reading the brief files. Command lines come from eval/pilot/isolate.py's build_run (the isolation
verified in T2: allowlisted env, fresh CLAUDE_CONFIG_DIR and HOME, --setting-sources "", --strict-mcp-config,
--no-session-persistence, --exclude-dynamic-system-prompt-sections, --restricted, --tools).

How the map or outline reaches a run: appended to the prompt, as a "Notes" block, with the same wording for both.
The explore, outline and map conditions therefore run the byte-identical command line apart from the prompt
(isolate's "explore" settings: working dir = a fresh copy, tools Read, Grep, Glob, no --add-dir); no-access runs
the same brief in an empty dir with no tools.

A map build whose map fails the check (maprender.validate_map) gets up to `map_fix_rounds` fix rounds: each is a
new isolated run with the build's settings (fresh repo copy, Read/Grep/Glob, same model, effort and map schema)
whose prompt holds the errors and the fix instructions; the previous map is a file outside the working dir, in its
own folder, reached through `--add-dir` (isolate's "map" settings: the only condition that allows an extra file
next to the repo tools). The fix round's `--max-budget-usd` is what is left of `caps.map_usd` after the build and
the earlier rounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import evalcfg as C

sys.path.insert(0, str(C.ROOT / "eval" / "pilot"))
import isolate  # noqa: E402

REPO_TOOLS = isolate.EXPLORE_TOOLS
BRIEF = C.HERE / "brief.md"
ANSWER_SCHEMA = C.HERE / "answer_schema.json"
MAP_SCHEMA = C.HERE / "map_schema.json"
CARTOGRAPHER = C.ROOT / "agents" / "cartographer.md"
NOTES_HEAD = ("Notes about this repository follow, between the two rules. They were prepared before this session "
              "and may be incomplete or wrong; the code is the authority.")
MAP_HEAD = ("MODE: explore\nREPO: {repo_dir}\n"
            "You have no Bash tool: this is an eval map build. Follow \"Eval mode (no Bash tool)\" at the end of "
            "this brief: explore the repository in REPO with Read, Grep and Glob, then return the full claims save "
            "input as one JSON object and nothing else.\n\n")


@dataclass(frozen=True)
class Item:
    id: str              # unique in the plan; also the folder name under runs/
    kind: str            # "map" (an eval map build) or "answer"
    repo: str
    qid: str = ""
    qtype: str = ""
    subset: str = ""
    condition: str = ""
    pass_no: int = 0     # answer pass (1-based); for map builds, the map seed
    map_seed: int = 0    # map condition: the map seed this pass reads


def build_items(cfg: dict, repo: str, size: str, questions: list[C.Question]) -> list[Item]:
    """Map builds (seed order) first, then the answering runs in a seeded shuffle (so a stop part-way through
    leaves every condition about equally done, and time-of-day effects spread over conditions)."""
    seeds = cfg["sizes"][size]["map_seeds"]
    maps = [Item(id=f"map-s{s}", kind="map", repo=repo, pass_no=s, map_seed=s) for s in range(1, seeds + 1)]
    answers = []
    for q in questions:
        for cond in C.CONDITIONS:
            for k in range(1, cfg["passes"][cond] + 1):
                answers.append(Item(id=f"{q.id}__{cond}__p{k}", kind="answer", repo=repo, qid=q.id, qtype=q.type,
                                    subset=q.subset, condition=cond, pass_no=k,
                                    map_seed=C.map_seed_for_pass(k, seeds) if cond == "map" else 0))
    random.Random(cfg.get("seed", 0)).shuffle(answers)
    return maps + answers


def counts(items: list[Item]) -> dict:
    out = {"map builds": sum(1 for i in items if i.kind == "map")}
    for c in C.CONDITIONS:
        out[c] = sum(1 for i in items if i.condition == c)
    out["answer runs"] = sum(1 for i in items if i.kind == "answer")
    out["total"] = len(items)
    return out


def plan_doc(cfg: dict, repo: str, size: str, run_id: str, questions: list[C.Question], items: list[Item],
             frozen: dict) -> dict:
    manifest = C.ROOT / "eval" / "questions" / "MANIFEST.txt"
    return {"run_id": run_id, "repo": repo, "size": size, "commit": frozen["commit"], "url": frozen["url"],
            "config_sha256": cfg["_sha256"], "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else "",
            "questions": [asdict(q) for q in questions], "items": [asdict(i) for i in items],
            "counts": counts(items)}


# ------------------------------------------------------------------------------------------------------------
# Prompts

def answer_prompt(frozen: dict, repo: str, question: str, notes: str | None) -> str:
    """The one answering brief, filled in. notes: the map or outline text (None for no-access and explore)."""
    block = f"\n{NOTES_HEAD}\n\n-----\n{notes.rstrip()}\n-----\n" if notes else ""
    text = BRIEF.read_text()
    for k, v in (("{repo}", repo), ("{url}", frozen["url"]), ("{commit}", frozen["commit"]),
                 ("{notes}", block), ("{question}", question)):
        text = text.replace(k, v)
    return text


def cartographer_body() -> str:
    """agents/cartographer.md without its front matter."""
    text = CARTOGRAPHER.read_text()
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    return text.lstrip("\n")


def map_prompt(repo_dir: Path) -> str:
    return MAP_HEAD.replace("{repo_dir}", str(repo_dir)) + cartographer_body()


MAP_FIX_HEAD = (
    "MODE: fix\nREPO: {repo_dir}\nPREVIOUS: {map_file}\n"
    "You have no Bash tool: this is an eval map build, fix round {round} of {rounds}. The map you returned (the full "
    "claims save input) is in PREVIOUS, {lines} lines of JSON: Read it in parts (offset and limit). It failed the "
    "eval runner's validation with the {n} error(s) listed below, one per line, exactly as the validator wrote them.\n"
    "Fix every one of them. Never get around an error by relabelling a claim you read in source as "
    "`general_knowledge`. Keep everything that was not wrong as it was; re-read the code in REPO with Read, Grep "
    "and Glob where an error needs it. `document.flows` is required: every `flow` block names a path record "
    "there. Then return the whole corrected object (target, mode, document with its title, coverage, sections and "
    "flows, and every claim) as your final answer, one JSON object and nothing else.\n"
    "The brief you built the map from follows the errors; its \"Fixing validation errors\" and \"Eval mode (no "
    "Bash tool)\" sections apply.\n\nErrors:\n")


def map_fix_prompt(repo_dir: Path, map_file: Path, map_lines: int, errors: list[str], round_no: int,
                   rounds: int) -> str:
    """A fix round's prompt: the head, the errors verbatim (one per line), then the Cartographer brief. Pure."""
    head = (MAP_FIX_HEAD.replace("{repo_dir}", str(repo_dir)).replace("{map_file}", str(map_file))
            .replace("{round}", str(round_no)).replace("{rounds}", str(rounds)).replace("{lines}", str(map_lines))
            .replace("{n}", str(len(errors))))
    return head + "".join(f"- {e}\n" for e in errors) + "\n-----\n\n" + cartographer_body()


def fix_budget(cap: float, spent: float) -> float:
    """What is left of the map cap for the next fix round, rounded down to the cent (0.0 when none is left)."""
    return max(0.0, math.floor(round((cap - spent) * 100, 6)) / 100)


def compact_json(path: Path) -> str:
    return json.dumps(json.loads(path.read_text()), separators=(",", ":"))


# ------------------------------------------------------------------------------------------------------------
# Command lines

def run_spec(cfg: dict, item: Item, *, prompt: str, workdir: Path, config_dir: Path, home_dir: Path,
             claude_bin: str) -> isolate.RunSpec:
    no_access = item.kind == "answer" and item.condition == "no-access"
    budget = cfg["caps"]["map_usd"] if item.kind == "map" else cfg["caps"]["answer_usd"]
    return isolate.RunSpec(
        condition="no-access" if no_access else "explore", working_dir=workdir,
        tools=() if no_access else REPO_TOOLS, extra_file=None, model=cfg["model"], effort=cfg["effort"],
        budget_usd=min(budget, 5.0), config_dir=config_dir, home_dir=home_dir, prompt=prompt,
        output_format="stream-json",
        json_schema=compact_json(MAP_SCHEMA if item.kind == "map" else ANSWER_SCHEMA), claude_bin=claude_bin)


def fix_run_spec(cfg: dict, *, prompt: str, workdir: Path, map_file: Path, budget: float, config_dir: Path,
                 home_dir: Path, claude_bin: str) -> isolate.RunSpec:
    """A map fix round: the build's settings plus the previous map as an extra file (isolate's "map" condition,
    which validates that the file lives outside the working dir)."""
    return isolate.RunSpec(
        condition="map", working_dir=workdir, tools=REPO_TOOLS, extra_file=map_file, model=cfg["model"],
        effort=cfg["effort"], budget_usd=min(budget, 5.0), config_dir=config_dir, home_dir=home_dir, prompt=prompt,
        output_format="stream-json", json_schema=compact_json(MAP_SCHEMA), claude_bin=claude_bin)


def build_command(cfg: dict, item: Item, spec: isolate.RunSpec, parent_env: dict,
                  budget: float | None = None) -> isolate.Run:
    """isolate.build_run, with the map build's budget set above isolate's $5 one-shot ceiling when configured.
    budget: a fix round's own cap (what is left of caps.map_usd)."""
    run = isolate.build_run(spec, parent_env)
    cap = cfg["caps"]["map_usd"] if item.kind == "map" else cfg["caps"]["answer_usd"]
    if budget is not None:
        cap = budget
    i = run.argv.index("--max-budget-usd")
    run.argv[i + 1] = f"{cap:g}"
    return run


def child_env_source(token: str | None, parent: dict) -> dict:
    """What build_run may copy from: the token (from the keychain, never from our own environment) plus LANG and
    TERM. Nothing else of the caller's environment is offered."""
    env = {k: parent[k] for k in ("LANG", "TERM") if k in parent}
    if token:
        env[isolate.TOKEN_VAR] = token
    return env


# ------------------------------------------------------------------------------------------------------------
# Estimates (dry run only)

def estimate(cfg: dict, items: list[Item]) -> dict:
    """Low/high cost and wall minutes from config [estimate]: labelled estimates, not measurements.

    A map build's low end is the build alone (the map passes the check); its high end allows every fix round:
    cost up to caps.map_usd (which covers the build and its fixes), time up to (1 + map_fix_rounds) builds."""
    est = cfg["estimate"]
    rounds = int(cfg.get("map_fix_rounds", 0))
    lo_usd = hi_usd = lo_min = hi_min = 0.0
    map_hi_usd = min(cfg["caps"]["map_usd"], est["map_build_usd"][1] * (1 + rounds))
    map_hi_min = est["map_build_min"][1] * (1 + rounds)
    for it in items:
        key = "map_build" if it.kind == "map" else it.condition
        lo_usd += est[f"{key}_usd"][0]
        lo_min += est[f"{key}_min"][0]
        hi_usd += map_hi_usd if it.kind == "map" else est[f"{key}_usd"][1]
        hi_min += map_hi_min if it.kind == "map" else est[f"{key}_min"][1]
    conc = max(1, int(cfg.get("concurrency", 1)))
    return {"usd": (lo_usd, hi_usd), "minutes_sequential": (lo_min, hi_min),
            "minutes_wall": (lo_min / conc, hi_min / conc), "concurrency": conc,
            "map_build": {"fix_rounds": rounds, "usd": (est["map_build_usd"][0], map_hi_usd),
                          "min": (est["map_build_min"][0], map_hi_min)}}
