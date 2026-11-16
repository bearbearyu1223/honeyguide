"""The eval's settings (eval/run/config.toml) and the questions a run size selects.

Standard library only. Pure apart from reading files: the frozen question sets (eval/questions/<repo>.json) and
Han's why/how questions (eval/human/answers/whyhow_<repo>.json) are read, never written.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.toml"
CONDITIONS = ("no-access", "explore", "outline", "map")
TYPES = ("locate", "callers", "flow", "whyhow")


def expand(path: str | Path, base: Path = ROOT) -> Path:
    """~ expanded; a relative path is taken from the honeyguide repo root."""
    p = Path(str(path)).expanduser()
    return p if p.is_absolute() else base / p


def load_config(path: Path = CONFIG) -> dict:
    cfg = tomllib.loads(path.read_text())
    cfg["_path"] = str(path)
    cfg["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    if not str(cfg.get("model", "")).startswith("claude-"):
        raise ValueError("config: model must be a full model id (claude-...)")
    for c in CONDITIONS:
        n = cfg["passes"].get(c)
        if not isinstance(n, int) or n < 0:
            raise ValueError(f"config: passes.{c} must be a count (0 skips the condition, e.g. a smoke test)")
    for name, size in cfg["sizes"].items():
        need = 1 if (cfg["passes"].get("map", 0) or cfg["passes"].get("outline", 0)) else 0
        if not isinstance(size.get("map_seeds"), int) or size["map_seeds"] < need:
            raise ValueError(f"config: sizes.{name}.map_seeds must be at least {need} (the map and outline "
                             "conditions need a map)")
        for t in TYPES:
            v = size.get(t)
            if v != "all" and not (isinstance(v, int) and v >= 0):
                raise ValueError(f"config: sizes.{name}.{t} must be 'all' or a count")
    n = cfg.get("map_fix_rounds")
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 5:
        raise ValueError("config: map_fix_rounds must be a count from 0 to 5 (fix rounds after a map build whose map "
                         "fails the check)")
    for k in ("timeout_answer_s", "timeout_map_s"):
        if not isinstance(cfg.get(k), int) or cfg[k] <= 0:
            raise ValueError(f"config: {k} must be a positive number of seconds")
    if cfg["model"] not in cfg.get("prices", {}):
        raise ValueError(f"config: no [prices.{cfg['model']}] table")


@dataclass(frozen=True)
class Question:
    id: str
    type: str          # locate / callers / flow / whyhow
    text: str
    subset: str        # before / after / none (why/how carry no cutoff tag)


def load_questions(cfg: dict, repo: str) -> tuple[dict, list[dict], list[dict]]:
    """(frozen set, its generated questions in presentation order, Han's why/how questions in his order)."""
    rc = cfg["repos"][repo]
    frozen = json.loads(expand(rc["questions"]).read_text())
    by_id = {q["id"]: q for q in frozen["questions"]}
    ordered = [by_id[i] for i in frozen["presentation_order"]]
    wh_path = expand(cfg.get("answers_dir", "eval/human/answers")) / f"whyhow_{repo}.json"
    whyhow = json.loads(wh_path.read_text())["questions"] if wh_path.exists() else []
    return frozen, ordered, whyhow


def select_questions(cfg: dict, repo: str, size: str) -> list[Question]:
    """The size's questions: per type the first N in presentation order (why/how in Han's order), then listed
    in that same overall order (generated questions first, why/how after)."""
    sz = cfg["sizes"][size]
    _, ordered, whyhow = load_questions(cfg, repo)
    taken: dict[str, int] = {t: 0 for t in TYPES}
    out: list[Question] = []

    def want(t: str) -> bool:
        n = sz[t]
        return n == "all" or taken[t] < n

    for q in ordered:
        if want(q["type"]):
            taken[q["type"]] += 1
            out.append(Question(q["id"], q["type"], q["text"], q["cutoff"]["subset"]))
    for q in whyhow:
        if want("whyhow"):
            taken["whyhow"] += 1
            out.append(Question(q["id"], "whyhow", q["text"], "none"))
    for t in TYPES:
        if sz[t] != "all" and taken[t] < sz[t]:
            raise ValueError(f"size {size}: wants {sz[t]} {t} questions, {repo} has {taken[t]}")
    return out


def map_seed_for_pass(k: int, seeds: int) -> int:
    """Map pass k (1-based) reads map seed ((k - 1) mod seeds) + 1."""
    return (k - 1) % seeds + 1
