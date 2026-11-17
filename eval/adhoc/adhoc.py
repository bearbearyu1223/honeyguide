"""E1: are ad-hoc answers trustworthy? A Checker over the pilot's explore answers, with a control (T11d).

    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --dry-run      # both arms, units, estimate
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --only nc-why-05__explore__p2   # the trial
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 [--max-cost 15]                 # answers arm
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --source map                    # the control
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --repeat 3                      # finding 6
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --capture > outputs/adhoc_check.txt
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --spot-check  # writes spot_check.md (links)

Two arms, judged by one brief (eval/adhoc/brief.md, derived from agents/checker.md; differences in
BRIEF_NOTES.md), one schema (check_schema.json), the same isolation and the same parsing:
  answers  (--source answers, default) the source run's explore answers (an agent with Read/Grep/Glob and no
           map, what an engineer gets by asking ad hoc) for the flow and why/how questions (--types), split into
           units by eval/adhoc/adhoc_split.py; one check per answer.
  map      (--source map, the control) claims from the source run's eval map (maps/seed1/map.json, built at the
           same commit and never Checker-passed): a seeded sample (--map-n, default 100) stratified by evidence
           label, general_knowledge and searched_not_found left out, anchors stripped (the Checker sees the
           claim text only), in checks of about --batch-size (25) units, near an answer's size.
--repeat N re-checks N seeded answers of the answers arm into their own archive, for per-unit agreement.
--only <answer or batch id> runs that one check (the trial); the plan is the full one, so the later full run
skips it.

Each check is one isolated `claude -p` with the isolation of eval/run (runplan/isolate: a fresh scratch root, a
fresh `git archive` working dir of the pinned commit with the agent files removed, the allowlisted environment,
the token from the keychain into the child only, tools Read/Grep/Glob, no Bash, no --add-dir, --json-schema,
stream-json). The schema gives each unit a verdict (supported, not_supported, wrong, not_a_claim), a note and the
line ranges read.

Archives (never inside the source archive): <archive>/<run-id>-adhoc/ (answers), <run-id>-adhoc-map/ (map),
<run-id>-adhoc-repeat/ (repeat); --out-id overrides the one being run (with --capture/--dry-run: the answers').
  plan.json         the frozen plan: arm, source, scope, model, effort, caps, run order, every check's units
  log.jsonl         append-only events, as evalrun's
  runs/<id>/        prompt.txt, command.txt (token hidden), transcript.jsonl, stderr.txt, result.json, meta.json
                    (status, verdicts, problems, tokens, cost, model, wall), cost_so_far.json (see below)
  attempts/<id>/<n>/ earlier attempts (interrupted, usage limit, --retry-failed, a partial check's first part)
  spot_check.md     only with --spot-check
Statuses are evalrun's, plus `partial`: the check returned verdicts but left units without one. A partial check
is never final: the same command resumes it with a follow-up check of only the missing units (at most
MAX_FOLLOWUPS), merged into the earlier verdicts; after that its missing units stay "no verdict". Duplicate ids in
a check's output are flagged; when they disagree the unit gets no verdict.
Cost: a check's meta.json has the CLI's reported cost. While a check runs, cost_so_far.json holds the cost rebuilt
from the transcript's per-message tokens (config prices), so a check killed or timed out keeps what is known:
`spent` and the capture count it (a lower bound: a message in flight is not in the transcript).
Run order is the plan's seeded shuffle (config seed, as evalrun), so a cost stop leaves no kind of answer last.
Resuming, retries and stops are evalrun's (Runner's loop is reused). Stops at --max-cost (list price spent in
that archive, default $15), at --max-runs, or at the first usage limit. Model, effort, caps: eval/run/config.toml.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "eval" / "run", ROOT / "eval" / "pilot"):
    sys.path.insert(0, str(p))
import evalrun as ER  # noqa: E402  (puts src/ on the path when run outside uv)
import adhoc_split as S  # noqa: E402
import evalcfg as C  # noqa: E402
import isolate  # noqa: E402
import runplan as P  # noqa: E402
import runresult as RR  # noqa: E402
import workdirs as W  # noqa: E402
from honeyguide.anchors import check_path  # noqa: E402
from honeyguide.gitio import Repo  # noqa: E402

BRIEF = HERE / "brief.md"
SCHEMA = HERE / "check_schema.json"
DEFAULT_TYPES = ("flow", "whyhow")
VERDICTS = ("supported", "not_supported", "wrong", "not_a_claim")
DEFAULT_MAX_COST = 15.0
EST_FACTOR = (3, 6)          # a check reads more than the answer did: dry-run estimate only, before a trial
DEFAULT_MAP_N = 100
DEFAULT_BATCH = 25
MAP_EXCLUDE = ("general_knowledge", "searched_not_found")
MAP_FILE = Path("maps") / "seed1" / "map.json"
DEFAULT_REPEAT = 3
MAX_FOLLOWUPS = 2
OK_LIKE = ("ok", "partial")  # checks whose verdicts are read
SUFFIX = {"answers": "-adhoc", "map": "-adhoc-map", "repeat": "-adhoc-repeat"}

# The two arms' prompts differ only here: where the units come from (BRIEF_NOTES.md).
SOURCE_LINE = {
    "answers": "Its answer to the question below is split into numbered units: sentences and list items, in order.",
    "map": "They are separate statements from its description of the repository, numbered, in no particular order.",
}
CONTEXT = {
    "answers": "## The question\n\n{question}",
    "map": "## Where the units come from\n\nA description of the repository written by another agent; each unit is "
           "one of its statements, on its own. There is no question.",
}


@dataclass(frozen=True)
class CheckItem:
    id: str                  # the answer's run id or the batch id; also the folder under runs/
    qid: str
    qtype: str
    kind: str = "check"


# ------------------------------------------------------------------------------------------------------------
# Scope and plan (pure apart from reading the source archive)

def source_answers(src_root: Path, types: tuple[str, ...]) -> tuple[dict, list[dict], list[str]]:
    """(source plan, the explore answers in scope sorted by id, skipped ids with why). An answer is in scope when
    its question's type is in types and its run finished ok with a text."""
    plan = json.loads((src_root / "plan.json").read_text())
    qs = {q["id"]: q for q in plan["questions"]}
    out, skipped = [], []
    for it in sorted(plan["items"], key=lambda i: i["id"]):
        if it["kind"] != "answer" or it["condition"] != "explore" or qs[it["qid"]]["type"] not in types:
            continue
        mp = src_root / "runs" / it["id"] / "meta.json"
        m = json.loads(mp.read_text()) if mp.exists() else None
        text = ((m or {}).get("answer") or {}).get("text") or ""
        if not m or m.get("status") != "ok" or not text.strip():
            skipped.append(f"{it['id']}: {(m or {}).get('status', 'not run')}")
            continue
        q = qs[it["qid"]]
        out.append({"id": it["id"], "qid": q["id"], "qtype": q["type"], "question": q["text"], "text": text})
    return plan, out, skipped


def explore_baseline(src_root: Path, plan: dict) -> dict:
    """Mean list cost and wall of the source's finished explore runs (every type): the assumed estimate's base."""
    costs, walls = [], []
    for it in plan["items"]:
        if it["kind"] == "answer" and it["condition"] == "explore":
            mp = src_root / "runs" / it["id"] / "meta.json"
            if mp.exists():
                m = json.loads(mp.read_text())
                if m.get("status") == "ok":
                    costs.append(float(m["usage"].get("cost_usd") or 0.0))
                    walls.append(float(m.get("wall_s") or 0.0))
    return {"runs": len(costs), "mean_usd": statistics.fmean(costs) if costs else 0.0,
            "mean_wall_s": statistics.fmean(walls) if walls else 0.0}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    """n split over the strata in proportion to counts (largest remainder; ties by stratum name). All of every
    stratum when n covers them."""
    total = sum(counts.values())
    if n >= total:
        return dict(counts)
    quota = {k: n * v / total for k, v in counts.items()}
    out = {k: int(q) for k, q in quota.items()}
    rest = sorted(counts, key=lambda k: (-(quota[k] - out[k]), k))
    for k in rest[: n - sum(out.values())]:
        out[k] += 1
    return out


def stratified_sample(claims: list[dict], n: int, rng: random.Random,
                      exclude: tuple[str, ...] = MAP_EXCLUDE) -> tuple[list[dict], dict]:
    """(the sample in a seeded shuffled order, a summary {in_map, eligible, sampled} by evidence label). Within a
    label, claims are sorted by key and then sampled, so the draw depends only on the map and the seed."""
    labels = sorted({c["evidence"] for c in claims} | set(exclude))
    in_map = {lb: sum(1 for c in claims if c["evidence"] == lb) for lb in labels}
    eligible = {lb: k for lb, k in in_map.items() if lb not in exclude and k}
    alloc = allocate(eligible, n)
    out: list[dict] = []
    for lb in sorted(alloc):
        pool = sorted((c for c in claims if c["evidence"] == lb), key=lambda c: (c["key"], c["text"]))
        out += rng.sample(pool, alloc[lb])
    rng.shuffle(out)
    return out, {"in_map": in_map, "eligible": eligible, "sampled": alloc}


def batch(xs: list, size: int) -> list[list]:
    """xs in order, cut into round(len / size) batches (at least one) whose sizes differ by at most one."""
    if not xs:
        return []
    nb = max(1, round(len(xs) / size))
    q, r = divmod(len(xs), nb)
    out, k = [], 0
    for i in range(nb):
        m = q + (1 if i < r else 0)
        out.append(xs[k:k + m])
        k += m
    return out


def run_order(ids: list[str], seed: int) -> list[str]:
    """The checks' run order: a seeded shuffle, as evalrun's (a stop part-way leaves no kind of check last)."""
    out = sorted(ids)
    random.Random(seed).shuffle(out)
    return out


def repeat_pick(ids: list[str], n: int, seed: int) -> list[str]:
    """The n answers the repeat re-checks: a seeded sample, sorted by id."""
    return sorted(random.Random(seed).sample(sorted(ids), min(n, len(ids))))


def _base_plan(cfg: dict, src_plan: dict, src_root: Path, out_id: str, arm: str) -> dict:
    return {"run_id": out_id, "arm": arm, "source_run_id": src_plan["run_id"], "source_archive": str(src_root),
            "repo": src_plan["repo"], "commit": src_plan["commit"], "url": src_plan["url"], "model": cfg["model"],
            "effort": cfg["effort"], "answer_cap_usd": cfg["caps"]["answer_usd"], "seed": int(cfg.get("seed", 0)),
            "config_sha256": cfg["_sha256"], "brief_sha256": sha(BRIEF), "schema_sha256": sha(SCHEMA)}


def build_plan(cfg: dict, src_plan: dict, src_root: Path, out_id: str, types: tuple[str, ...],
               answers: list[dict], skipped: list[str]) -> dict:
    """The answers arm: one check per answer, its units from the splitter."""
    items = []
    for a in answers:
        units = S.split_units(a["id"], a["text"])
        items.append({"id": a["id"], "qid": a["qid"], "qtype": a["qtype"], "question": a["question"],
                      "units": [asdict(u) for u in units]})
    plan = _base_plan(cfg, src_plan, src_root, out_id, "answers")
    plan.update({"types": list(types), "splitter_sha256": sha(HERE / "adhoc_split.py"), "items": items,
                 "skipped": skipped, "run_order": run_order([i["id"] for i in items], plan["seed"])})
    return plan


def build_repeat_plan(answers_plan: dict, out_id: str, n: int, of_id: str) -> dict:
    """The repeat: the answers arm's plan restricted to n seeded answers (same units, same brief)."""
    pick = repeat_pick([i["id"] for i in answers_plan["items"]], n, answers_plan["seed"])
    plan = {**answers_plan, "run_id": out_id, "arm": "repeat", "repeat_of": of_id, "repeat_n": n,
            "items": [i for i in answers_plan["items"] if i["id"] in pick]}
    plan["run_order"] = run_order(pick, plan["seed"])
    return plan


def map_claims(src_root: Path) -> tuple[Path, list[dict]]:
    p = src_root / MAP_FILE
    if not p.exists():
        raise SystemExit(f"{p}: no eval map in the source archive")
    return p, json.loads(p.read_text())["claims"]


def build_map_plan(cfg: dict, src_plan: dict, src_root: Path, out_id: str, n: int, size: int) -> dict:
    """The control: a stratified seeded sample of the eval map's claims, anchors stripped, in batches."""
    path, claims = map_claims(src_root)
    seed = int(cfg.get("seed", 0))
    sample, strata = stratified_sample(claims, n, random.Random(seed))
    items = []
    for k, part in enumerate(batch(sample, size), 1):
        bid = f"map-b{k:02d}"
        items.append({"id": bid, "qid": "", "qtype": "map", "question": "",
                      "units": [{"id": f"{bid}#s{j}", "text": c["text"], "kind": "claim", "level": 0,
                                 "key": c["key"], "label": c["evidence"]} for j, c in enumerate(part, 1)]})
    plan = _base_plan(cfg, src_plan, src_root, out_id, "map")
    plan.update({"map_path": str(path), "map_sha256": sha(path), "map_claims": len(claims), "map_n": n,
                 "batch_size": size, "exclude": list(MAP_EXCLUDE), "strata": strata, "items": items,
                 "skipped": [], "types": ["map"], "run_order": run_order([i["id"] for i in items], seed)})
    return plan


def short_id(uid: str) -> str:
    return uid.rsplit("#", 1)[1]


def check_prompt(commit: str, question: str, units: list[dict], arm: str = "answers") -> str:
    """The shared brief filled in: where the units come from, the question (answers) and the numbered units
    ([s<k>] and the text only, indented by list level). A map claim's key, label and anchors are never shown."""
    kind = "map" if arm == "map" else "answers"
    rows = []
    for u in units:
        text = u["text"].replace("\n", "\n      ")
        rows.append(f"[{short_id(u['id'])}] " + "  " * int(u["level"]) + text)
    return (BRIEF.read_text().replace("{source}", SOURCE_LINE[kind]).replace("{commit}", commit)
            .replace("{context}", CONTEXT[kind].replace("{question}", question))
            .replace("{units}", "\n".join(rows)))


def check_spec(cfg: dict, *, prompt: str, workdir: Path, config_dir: Path, home_dir: Path,
               claude_bin: str) -> isolate.RunSpec:
    """isolate's explore settings (fresh copy of the pin as the working dir, Read/Grep/Glob, no extra file), the
    check schema, the per-check cap."""
    return isolate.RunSpec(
        condition="explore", working_dir=workdir, tools=P.REPO_TOOLS, extra_file=None, model=cfg["model"],
        effort=cfg["effort"], budget_usd=min(float(cfg["caps"]["answer_usd"]), 5.0), config_dir=config_dir,
        home_dir=home_dir, prompt=prompt, output_format="stream-json", json_schema=P.compact_json(SCHEMA),
        claude_bin=claude_bin)


# ------------------------------------------------------------------------------------------------------------
# Reading a check's result (pure)

def _rel_path(path: str, workdirs: tuple[str, ...]) -> str:
    p = path.strip()
    for w in workdirs:
        if w and p.startswith(w.rstrip("/") + "/"):
            return p[len(w.rstrip("/")) + 1:]
    while p.startswith("./"):
        p = p[2:]
    return p


def norm_id(s: str) -> str:
    """A unit id as the check wrote it -> the short form: '[s1]', 'S1', ' s1 ', 'run#s1' -> 's1'."""
    t = s.strip()
    if "#" in t:
        t = t.rsplit("#", 1)[1]
    return t.strip().strip("[]").strip().lower()


def parse_verdicts(result: dict | None, units: list[dict], workdirs: tuple[str, ...] = ()) -> tuple[
        list[dict] | None, str, list[str]]:
    """(one row per unit in order: {unit, verdict, note, evidence}; verdict None when the check gave none), how it
    was read, problems. Ids are normalised (norm_id). A repeated id is always flagged: with the same verdict the
    first entry is kept; with different verdicts the unit gets none (never merged). None rows when the result is
    not the schema's object."""
    if not result:
        return None, "no result", []
    obj = result.get("structured_output")
    how = "structured_output"
    if not isinstance(obj, dict):
        try:
            obj = json.loads(str(result.get("result") or "").strip())
            how = "result text"
        except json.JSONDecodeError:
            return None, "result text is not JSON", []
    if not isinstance(obj, dict) or not isinstance(obj.get("units"), list):
        return None, "not {units: [...]}", []
    by_short = {short_id(u["id"]).lower(): u["id"] for u in units}
    got: dict[str, dict] = {}
    conflict: set[str] = set()
    problems: list[str] = []
    for k, e in enumerate(obj["units"]):
        if not isinstance(e, dict) or e.get("verdict") not in VERDICTS or not isinstance(e.get("id"), str):
            problems.append(f"entry {k}: malformed")
            continue
        uid = by_short.get(norm_id(e["id"]))
        if uid is None:
            problems.append(f"entry {k}: unknown id {e['id']!r}")
            continue
        sid = short_id(uid)
        if uid in got:
            first = got[uid]["verdict"]
            if first == e["verdict"]:
                problems.append(f"{sid}: repeated with the same verdict ({first}; first kept)")
            else:
                conflict.add(uid)
                problems.append(f"{sid}: repeated with different verdicts ({first}, {e['verdict']}): no verdict")
            continue
        ev = []
        for r in e.get("evidence") or []:
            if isinstance(r, dict) and isinstance(r.get("path"), str) and isinstance(r.get("start"), int) \
                    and isinstance(r.get("end"), int):
                ev.append({"path": _rel_path(r["path"], workdirs), "start": r["start"], "end": r["end"]})
            else:
                problems.append(f"{sid}: malformed evidence entry")
        got[uid] = {"unit": uid, "verdict": e["verdict"], "note": str(e.get("note") or ""), "evidence": ev}
    rows = []
    for u in units:
        if u["id"] in got and u["id"] not in conflict:
            rows.append(got[u["id"]])
        else:
            problems.append(f"{short_id(u['id'])}: no verdict")
            rows.append({"unit": u["id"], "verdict": None, "note": "", "evidence": []})
    return rows, how, problems


def counts_of(rows: list[dict]) -> dict:
    out = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    out["no verdict"] = sum(1 for r in rows if r["verdict"] is None)
    return out


def merge_rows(units: list[dict], earlier: list[dict], new: list[dict]) -> list[dict]:
    """A follow-up's rows merged into the earlier check's: a unit keeps its earlier verdict when it had one."""
    old = {r["unit"]: r for r in earlier if r.get("verdict") is not None}
    fresh = {r["unit"]: r for r in new}
    return [old.get(u["id"]) or fresh.get(u["id"]) or {"unit": u["id"], "verdict": None, "note": "", "evidence": []}
            for u in units]


def check_evidence(rows: list[dict], lines_of) -> list[dict]:
    """The deterministic evidence pass: every cited range against the pinned commit. lines_of(path) gives the
    file's lines at the commit, or None when it is not there. One record per row: {unit, verdict, ranges,
    bad: [{path, start, end, why}]}; why is 'bad path', 'no such file' or 'lines out of range (file has N)'."""
    out = []
    for r in rows:
        bad = []
        for e in r.get("evidence") or []:
            why = ""
            try:
                check_path(e["path"])
            except ValueError:
                why = "bad path"
            if not why:
                lines = lines_of(e["path"])
                if lines is None:
                    why = "no such file"
                elif not 1 <= e["start"] <= e["end"] <= len(lines):
                    why = f"lines out of range (file has {len(lines)})"
            if why:
                bad.append({**e, "why": why})
        out.append({"unit": r["unit"], "verdict": r.get("verdict"), "ranges": len(r.get("evidence") or []),
                    "bad": bad})
    return out


def repo_lines(clone: Path, commit: str):
    repo = Repo.open(clone)
    return lambda path: repo.lines_at(commit, path)


# ------------------------------------------------------------------------------------------------------------
# Cost while a check runs (pure): the transcript's per-message usage, priced

class UsageTracker:
    """Adds up stream-json assistant messages' usage (one count per message id, the largest seen: a message's
    content blocks arrive as several events) into a usage_summary-shaped dict priced at config prices."""

    def __init__(self, prices: dict):
        self.prices = prices
        self.by_msg: dict[str, dict] = {}
        self.models: set[str] = set()

    def add(self, line: str) -> bool:
        """True when the line changed the totals."""
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return False
        msg = obj.get("message") if isinstance(obj, dict) and obj.get("type") == "assistant" else None
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            return False
        key = str(msg.get("id") or f"anon-{len(self.by_msg)}")
        cc = u.get("cache_creation") or {}
        row = {k: int(u.get(k) or 0) for k in RR.TOKEN_FIELDS}
        row["cache_write_1h"] = int(cc.get("ephemeral_1h_input_tokens") or 0)
        row["cache_write_5m"] = int(cc.get("ephemeral_5m_input_tokens") or 0)
        old = self.by_msg.get(key, {})
        self.by_msg[key] = {k: max(v, old.get(k, 0)) for k, v in row.items()}
        if msg.get("model"):
            self.models.add(str(msg["model"]))
        return True

    def summary(self) -> dict:
        out = RR.usage_summary(None)
        for row in self.by_msg.values():
            for k in RR.TOKEN_FIELDS:
                out["tokens"][k] += row[k]
            out["cache_write_1h"] += row["cache_write_1h"]
            out["cache_write_5m"] += row["cache_write_5m"]
        out["cost_usd"] = RR.notional_cost(out, self.prices)["rebuilt_with_cache"]
        out["models"] = sorted(self.models)
        out["messages"] = len(self.by_msg)
        out["cost_source"] = "rebuilt from the transcript's per-message tokens at config prices (a lower bound)"
        return out


# ------------------------------------------------------------------------------------------------------------
# The runner: evalrun's loop, stops and resume, with a check instead of an answering run

class AdhocRunner(ER.Runner):
    def __init__(self, cfg: dict, plan: dict, archive: ER.Archive, *, claude_bin: str, token: str,
                 max_cost: float, max_runs: int | None, retry_failed: bool, concurrency: int, resume_cmd: str,
                 only: str | None = None):
        self.cfg, self.plan, self.archive = cfg, plan, archive
        self.repo = plan["repo"]
        rc = cfg["repos"][self.repo]
        self.clone = C.expand(rc["clone"])
        self.remove = list(rc.get("remove", []))
        self.commit = plan["commit"]
        self.claude_bin = claude_bin
        self.token = token
        self.max_cost = max_cost
        self.max_runs = max_runs
        self.retry_failed = retry_failed
        self.concurrency = max(1, concurrency)
        self.resume_cmd = resume_cmd
        self.only = only
        self.by_id = {i["id"]: i for i in plan["items"]}
        order = plan.get("run_order") or sorted(self.by_id)
        self.items = [CheckItem(id=self.by_id[k]["id"], qid=self.by_id[k]["qid"], qtype=self.by_id[k]["qtype"])
                      for k in order]
        self.prices = cfg["prices"][cfg["model"]]
        self.stop_reason = ""
        self.started_now = 0
        self.spent = archive.spent()
        self.parent_env = {k: os.environ[k] for k in ("LANG", "TERM") if k in os.environ}

    # -- partial checks ------------------------------------------------------------------------------------
    def attempt_metas(self, item_id: str) -> list[tuple[int, dict]]:
        base = self.archive.root / "attempts" / item_id
        out = []
        for p in base.glob("*/meta.json") if base.exists() else []:
            out.append((int(p.parent.name), json.loads(p.read_text())))
        return sorted(out, key=lambda x: x[0])

    def prior_partial(self, item_id: str) -> tuple[int, dict] | None:
        """The latest attempt that ended partial: a new check of this item is its follow-up."""
        parts = [(n, m) for n, m in self.attempt_metas(item_id) if m.get("status") == "partial"]
        return parts[-1] if parts else None

    def followups_used(self, item_id: str) -> int:
        return sum(1 for _, m in self.attempt_metas(item_id) if m.get("status") == "partial")

    def needs_run(self, item: CheckItem) -> bool:
        meta = self.archive.meta(item.id)
        if meta and meta.get("status") == "partial":
            if self.followups_used(item.id) >= MAX_FOLLOWUPS:
                return False
            missing = meta.get("counts", {}).get("no verdict", 0)
            n = self.archive.to_attempts(item.id)
            self.archive.log("followup_missing_units", id=item.id, attempt_kept=n, missing=missing)
            ER.status(f"  {item.id}: {missing} units without a verdict; a follow-up checks only those "
                      f"(kept as attempt {n})")
            return True
        return super().needs_run(item)

    # -- one check -----------------------------------------------------------------------------------------
    def _call(self, d: Path, run, prompt: str, timeout: int) -> dict:
        """evalrun's _call, streaming: stdout is read as it comes, and every assistant message's usage updates
        cost_so_far.json (numbers only), so a check killed or timed out keeps its known cost."""
        (d / "prompt.txt").write_text(prompt)
        shown = list(run.argv)
        shown[2] = f"<prompt.txt: {len(prompt)} chars>"
        (d / "command.txt").write_text("\n".join(P.isolate.describe(P.isolate.Run(
            argv=shown, env=run.env, cwd=run.cwd, redact=run.redact))) + f"\ncwd:  {run.cwd}\n")
        tracker = UsageTracker(self.prices)
        out_lines: list[str] = []
        err_parts: list[str] = []
        t0 = time.monotonic()
        proc = subprocess.Popen(run.argv, env=run.env, cwd=run.cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

        def read_out() -> None:
            for line in proc.stdout:
                out_lines.append(line)
                if tracker.add(line):
                    rec = {"usage": tracker.summary(), "updated": ER.now()}
                    (d / ER.COST_SO_FAR).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")

        def read_err() -> None:
            err_parts.append(proc.stderr.read())
        threads = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
        for t in threads:
            t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
        for t in threads:
            t.join(timeout=10)
        wall = time.monotonic() - t0
        out, err = "".join(out_lines), "".join(err_parts)
        code = None if timed_out else proc.returncode
        token_seen = bool(self.token) and (self.token in out or self.token in err)
        if token_seen:
            out, err = "", "[withheld: the token appeared in this run's output]\n"
        parsed = RR.parse_stream(out)
        (d / "transcript.jsonl").write_text(out)
        (d / "stderr.txt").write_text(err)
        if parsed["result"] is not None:
            (d / "result.json").write_text(json.dumps(parsed["result"], indent=1, sort_keys=True) + "\n")
        return {"out": out, "err": err, "code": code, "timed_out": timed_out, "wall": wall,
                "token_seen": token_seen, "parsed": parsed, "result": parsed["result"],
                "rebuilt": tracker.summary() if tracker.by_msg else None}

    def _execute(self, item: CheckItem) -> dict:
        spec_item = self.by_id[item.id]
        units = spec_item["units"]
        prev = self.prior_partial(item.id)
        if prev:
            have = {r["unit"] for r in prev[1]["verdicts"] if r.get("verdict") is not None}
            todo = [u for u in units if u["id"] not in have] or units
        else:
            todo = units
        d = self.archive.run_dir(item.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "started").write_text(ER.now() + "\n")
        root, cfg_dir, home, work = self._new_root()
        try:
            wd = W.make_repo_workdir(self.clone, self.commit, self.remove, work)
            prompt = check_prompt(self.commit, spec_item["question"], todo, self.plan.get("arm", "answers"))
            spec = check_spec(self.cfg, prompt=prompt, workdir=work, config_dir=cfg_dir, home_dir=home,
                              claude_bin=self.claude_bin)
            run = isolate.build_run(spec, P.child_env_source(self.token, self.parent_env))
            c = self._call(d, run, prompt, self.cfg["timeout_answer_s"])
            wds = tuple(dict.fromkeys((str(work), str(work.resolve()), str(work).removeprefix("/private"))))
            rows, how, problems = parse_verdicts(c["result"], todo, wds)
            st, reason = self._classify(c, rows is not None)
            if prev and rows is not None:
                rows = merge_rows(units, prev[1]["verdicts"], rows)
            if st == "ok" and any(r["verdict"] is None for r in rows):
                st, reason = "partial", f"{sum(r['verdict'] is None for r in rows)} units without a verdict"
            usage = RR.usage_summary(c["result"])
            if c["result"] is None and c["rebuilt"]:
                usage = c["rebuilt"]
            init = c["parsed"]["init"] or {}
            meta = {"id": item.id, "item": asdict(item), "status": st, "reason": reason, "exit": c["code"],
                    "wall_s": round(c["wall"], 1), "started": (d / "started").read_text().strip(),
                    "ended": ER.now(), "model_requested": self.cfg["model"], "model_init": init.get("model"),
                    "models_used": usage["models"], "usage": usage, "tool_calls": c["parsed"]["tool_calls"],
                    "tool_names": c["parsed"]["tool_names"], "verdicts": rows, "read_from": how,
                    "problems": problems, "counts": counts_of(rows or []), "units": len(units),
                    "units_asked": len(todo), "workdir": str(work), "workdir_files": wd["files"],
                    "agent_files_removed": wd["removed"], "prompt_chars": len(prompt),
                    "leak_scan": P.isolate.leak_scan(c["out"] + c["err"])}
            if prev:
                meta["followup_of"] = prev[0]
        finally:
            shutil.rmtree(root, ignore_errors=True)
        (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
        return meta

    def run(self) -> int:
        pool = [i for i in self.items if self.only is None or i.id == self.only]
        todo = [i for i in pool if self.needs_run(i)]
        ER.status(f"{len(self.items)} checks in the plan" + (f" (--only {self.only})" if self.only else "")
                  + f", {len(todo)} to run, ${self.spent:.2f} already spent")
        self._run_all(todo)
        return self.report([])

    def report(self, blocked: list[str]) -> int:
        by: dict[str, int] = {}
        stuck = 0
        for i in self.items:
            st = (self.archive.meta(i.id) or {}).get("status", "not run")
            by[st] = by.get(st, 0) + 1
            if st == "partial" and self.followups_used(i.id) >= MAX_FOLLOWUPS:
                stuck += 1
        finished = sum(v for k, v in by.items() if k in RR.FINAL)
        noun = "batches" if self.plan.get("arm") == "map" else "answers"
        print(f"adhoc check {self.plan['run_id']}: {finished} of {len(self.items)} {noun} checked; "
              + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + f"; spent ${self.spent:.2f} (list price)")
        if self.stop_reason:
            self.archive.log("stop", reason=self.stop_reason)
            print(f"stopped: {self.stop_reason}")
        if by.get("error"):
            print(f"{by['error']} failed checks stay failed; --retry-failed runs them again")
        if by.get("partial"):
            parts = []
            if by["partial"] > stuck:
                parts.append(f"{by['partial'] - stuck} get a follow-up for their missing units on resume")
            if stuck:
                parts.append(f"{stuck} used their {MAX_FOLLOWUPS} follow-ups; their missing units stay no verdict")
            print(f"{by['partial']} partial checks (units without a verdict): " + "; ".join(parts))
        if finished + stuck < len(self.items):
            print(f"resume with: {self.resume_cmd}")
            return 3
        return 0


# ------------------------------------------------------------------------------------------------------------
# The estimate (dry run): measured cost per unit when an archive has checks, the assumed range otherwise

def measured(archive: ER.Archive) -> dict | None:
    """Cost and wall per unit over the archive's checks that returned verdicts (ok or partial), every attempt of
    those items included (a follow-up, an interrupted try). None when there are none."""
    pf = archive.root / "plan.json"
    if not pf.exists():
        return None
    plan = json.loads(pf.read_text())
    cost = wall = 0.0
    units = 0
    ids = []
    for it in plan["items"]:
        m = archive.meta(it["id"])
        if not m or m.get("status") not in OK_LIKE:
            continue
        ids.append(it["id"])
        units += len(it["units"])
        dirs = [archive.run_dir(it["id"])] + sorted((archive.root / "attempts" / it["id"]).glob("*"))
        for dd in dirs:
            p = dd / "meta.json" if (dd / "meta.json").exists() else dd / ER.COST_SO_FAR
            if p.exists():
                x = json.loads(p.read_text())
                cost += float((x.get("usage") or {}).get("cost_usd") or 0.0)
                wall += float(x.get("wall_s") or 0.0)
    if not units:
        return None
    return {"checks": ids, "units": units, "usd": cost, "wall_s": wall, "usd_per_unit": cost / units,
            "wall_per_unit": wall / units}


def done_units(archive: ER.Archive, plan: dict) -> int:
    """Units in this plan's checks that are final already."""
    return sum(len(it["units"]) for it in plan["items"]
               if (archive.meta(it["id"]) or {}).get("status") in RR.FINAL)


def dry_run(cfg: dict, arms: dict, src_root: Path, src_plan: dict, claude_bin: str, max_cost: float,
            source: str) -> None:
    """arms: {"answers": (plan, archive), "map": (plan, archive) or why it is not available,
    "repeat": (plan, archive)}."""
    ans, ans_ar = arms["answers"]
    items = ans["items"]
    print("E1 ad-hoc answer check (dry run: nothing is run, no token is read)")
    print(f"source     {ans['source_run_id']} ({src_root}), read only")
    print(f"repo       {ans['repo']} at {ans['commit'][:12]}")
    print(f"model      {cfg['model']}, effort {cfg['effort']}; cap ${cfg['caps']['answer_usd']:g} per check; "
          f"stop at ${max_cost:g} per archive (--max-cost)")
    print(f"brief      eval/adhoc/brief.md, one brief for both arms (sha256 {ans['brief_sha256'][:12]}); "
          "differences from agents/checker.md: BRIEF_NOTES.md")
    print(f"order      each arm's checks run in a seeded shuffle (seed {ans['seed']})")
    # --- answers arm
    print(f"ARM 1      ad-hoc answers: archive {ans_ar.root}")
    all_types = {q["type"] for q in src_plan["questions"]}
    by_type = {t: sum(1 for i in items if i["qtype"] == t) for t in ans["types"]}
    print(f"scope      explore answers of types {', '.join(ans['types'])}: {len(items)} answers ("
          + ", ".join(f"{t} {k}" for t, k in by_type.items()) + "); left out: "
          + (", ".join(sorted(all_types - set(ans["types"]))) or "none"))
    for s in ans["skipped"]:
        print(f"           skipped (not ok in the source): {s}")
    n_ans = sum(len(i["units"]) for i in items)
    print(f"units      {n_ans} in {len(items)} answers (adhoc_split.py: sentences, list items)")
    for i in items:
        kinds: dict[str, int] = {}
        for u in i["units"]:
            kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
        print(f"  {i['id']:<26} {len(i['units']):>3} units  ("
              + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + ")")
    # --- map arm
    mp = arms["map"]
    n_map = 0
    if isinstance(mp, str):
        print(f"ARM 2      map claims (the control): not available: {mp}")
    else:
        mplan, m_ar = mp
        st = mplan["strata"]
        n_map = sum(len(i["units"]) for i in mplan["items"])
        print(f"ARM 2      map claims (the control): archive {m_ar.root}")
        print(f"map        {mplan['map_path']} ({mplan['map_claims']} claims), read only; never Checker-passed")
        left = ", ".join(f"{lb} {st['in_map'].get(lb, 0)}" for lb in mplan["exclude"])
        print(f"sample     {n_map} of {sum(st['eligible'].values())} eligible claims (seed {mplan['seed']}), "
              f"stratified by evidence label; left out: {left}")
        print(f"  {'label':<20} {'in map':>7} {'eligible':>9} {'sampled':>8}")
        for lb in sorted(st["in_map"]):
            print(f"  {lb:<20} {st['in_map'][lb]:>7} {st['eligible'].get(lb, 0):>9} {st['sampled'].get(lb, 0):>8}")
        print(f"units      {n_map} claims in {len(mplan['items'])} checks of about {mplan['batch_size']}, anchors "
              "stripped (claim text only): " + ", ".join(f"{i['id']} {len(i['units'])}" for i in mplan["items"]))
    # --- repeat
    rplan, r_ar = arms["repeat"]
    n_rep = sum(len(i["units"]) for i in rplan["items"])
    print(f"REPEAT     {len(rplan['items'])} answers re-checked (seed {rplan['seed']}), {n_rep} units: "
          + ", ".join(i["id"] for i in rplan["items"]))
    print(f"           archive {r_ar.root}")
    # --- estimate
    scopes = [("answers", ans, ans_ar, n_ans)]
    if not isinstance(mp, str):
        scopes.append(("map", mp[0], mp[1], n_map))
    scopes.append(("repeat", rplan, r_ar, n_rep))
    meas = {k: measured(ar) for k, _, ar, _ in scopes}
    pooled = [m for m in meas.values() if m]
    conc = max(1, int(cfg.get("concurrency", 1)))
    if pooled:
        tot_u = sum(m["units"] for m in pooled)
        rate = sum(m["usd"] for m in pooled) / tot_u
        wrate = sum(m["wall_s"] for m in pooled) / tot_u
        print("ESTIMATE   measured-based, from the checks already in the archives:")
        for k, m in meas.items():
            if m:
                print(f"           {k}: {len(m['checks'])} check(s), {m['units']} units, ${m['usd']:.2f}, "
                      f"{m['wall_s'] / 60:.1f} min")
        print(f"           pooled ${rate:.4f} and {wrate:.1f} s per unit; an arm with checks of its own uses its "
              "own rate")
        tot = tmin = 0.0
        for k, plan_k, ar, n in scopes:
            m = meas[k]
            r, w = (m["usd_per_unit"], m["wall_per_unit"]) if m else (rate, wrate)
            left = n - (done_units(ar, plan_k) if (ar.root / "plan.json").exists() else 0)
            tot += r * left
            tmin += w * left / 60 / conc
            print(f"  {k:<8} {n:>4} units, {left:>4} left: ${r * n:.2f} in all, ${r * left:.2f} left, "
                  f"{w * left / 60 / conc:.0f} min left ({'own' if m else 'pooled'} rate)")
        print(f"  all three: ${tot:.2f} list and {tmin:.0f} min left at concurrency {conc} (a projection from "
              "measured checks, not a result)")
    else:
        bl = explore_baseline(src_root, src_plan)
        lo, hi = EST_FACTOR
        per = (bl["mean_usd"] * lo, bl["mean_usd"] * hi)
        mins = (bl["mean_wall_s"] * lo * len(items) / 60 / conc, bl["mean_wall_s"] * hi * len(items) / 60 / conc)
        print(f"ESTIMATE   source explore runs: {bl['runs']}, mean ${bl['mean_usd']:.3f} and "
              f"{bl['mean_wall_s']:.0f} s each; a check reads more,")
        print(f"           assumed {lo}-{hi}x: ${per[0]:.2f}-${per[1]:.2f} per answer, "
              f"${per[0] * len(items):.2f}-${per[1] * len(items):.2f} for {len(items)} answers, "
              f"{mins[0]:.0f}-{mins[1]:.0f} min at concurrency {conc}")
        if n_ans:
            pu = (per[0] * len(items) / n_ans, per[1] * len(items) / n_ans)
            other = n_map + n_rep
            print(f"           per unit ${pu[0]:.4f}-${pu[1]:.4f}: map arm and repeat ({other} units) "
                  f"${pu[0] * other:.2f}-${pu[1] * other:.2f}")
        print("           (an estimate, not measured; after the trial (--only) the dry run projects from it)")
    if (ans_ar.root / "plan.json").exists():
        done = sum(1 for i in items if (ans_ar.meta(i["id"]) or {}).get("status") in RR.FINAL)
        print(f"resume     the answers archive exists: {done} answers checked, they would be skipped")
    # --- the command and an example prompt, for --source
    plan = mp[0] if source == "map" and not isinstance(mp, str) else ans
    if not plan["items"]:
        return
    root = Path(str(C.expand(cfg["scratch"]))) / "hg-eval-RUN_ROOT"
    first = plan["items"][0]
    prompt = check_prompt(plan["commit"], first["question"], first["units"], plan["arm"])
    spec = check_spec(cfg, prompt=prompt, workdir=root / "work", config_dir=root / "cfg", home_dir=root / "home",
                      claude_bin=claude_bin)
    env_src = P.child_env_source(ER.PLACEHOLDER_TOKEN, {k: os.environ[k] for k in ("LANG", "TERM")
                                                           if k in os.environ})
    run = isolate.build_run(spec, env_src)
    run.argv[2] = f"<prompt: {len(prompt)} chars, sha256 {hashlib.sha256(prompt.encode()).hexdigest()[:12]}>"
    run.argv[run.argv.index("--json-schema") + 1] = f"<check_schema.json, sha256 {plan['schema_sha256'][:12]}>"
    lines = isolate.describe(run)
    print("command    one per check; token hidden; RUN_ROOT is a fresh scratch folder, removed after the run")
    print("  " + lines[0])
    print("  " + lines[1])
    print(f"  cwd:  {root / 'work'} (git archive of the pin, agent files removed: "
          f"{', '.join(cfg['repos'][plan['repo']].get('remove', [])) or 'none'})")
    print(f"--- example prompt ({first['id']}, the {plan['arm']} arm; --source picks the arm shown) ---")
    print(prompt.rstrip())


# ------------------------------------------------------------------------------------------------------------

PLAN_KEYS = ("arm", "items", "commit", "model", "effort", "config_sha256", "brief_sha256", "schema_sha256",
             "splitter_sha256", "types", "map_sha256", "map_n", "batch_size", "run_order", "repeat_of")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E1: check ad-hoc answers' claims, with map claims as the control.")
    ap.add_argument("--run-id", required=True, help="the source eval run (e.g. pilot-nanochat-2)")
    ap.add_argument("--source", choices=("answers", "map"), default="answers",
                    help="answers (the ad-hoc arm, default) or map (the control: the eval map's claims)")
    ap.add_argument("--out-id", help="the archive of what this command runs (default <run-id>-adhoc, -adhoc-map "
                                     "with --source map, -adhoc-repeat with --repeat); with --capture or "
                                     "--dry-run, the answers arm's")
    ap.add_argument("--map-id", help="capture, dry run: the map arm's archive (default <run-id>-adhoc-map)")
    ap.add_argument("--repeat-id", help="capture, dry run: the repeat's archive (default <run-id>-adhoc-repeat)")
    ap.add_argument("--types", default=",".join(DEFAULT_TYPES), help="question types (default flow,whyhow)")
    ap.add_argument("--map-n", type=int, default=DEFAULT_MAP_N, help="map claims sampled (default 100)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH, help="map claims per check (default 25)")
    ap.add_argument("--repeat", type=int, nargs="?", const=DEFAULT_REPEAT,
                    help=f"re-check N seeded answers (default {DEFAULT_REPEAT}) into the repeat archive")
    ap.add_argument("--only", help="run only this check (an answer id or a batch id): the trial")
    ap.add_argument("--config", type=Path, default=C.CONFIG)
    ap.add_argument("--archive", type=Path, help="default: config archive")
    ap.add_argument("--claude-bin", help="default: config claude_bin on PATH")
    ap.add_argument("--dry-run", action="store_true", help="print both arms, units, the estimate; run nothing")
    ap.add_argument("--capture", action="store_true", help="print the capture (outputs/adhoc_check.txt)")
    ap.add_argument("--spot-check", action="store_true", help="write spot_check.md (the sample, full links)")
    ap.add_argument("--runs-txt", type=Path, default=ROOT / "outputs" / "runs.txt",
                    help="the map Checker numbers, for comparison in the capture")
    ap.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST, help="USD list price (default 15)")
    ap.add_argument("--max-runs", type=int, help="start at most this many checks in this invocation")
    ap.add_argument("--retry-failed", action="store_true", help="run failed (status error) checks again")
    ap.add_argument("--concurrency", type=int, help="default config concurrency")
    a = ap.parse_args(argv)
    if a.repeat is not None and (a.source != "answers" or a.repeat < 1):
        raise SystemExit("--repeat N (N >= 1) re-checks answers; it takes no --source map")
    cfg = C.load_config(a.config)
    types = tuple(t for t in a.types.split(",") if t)
    bad = [t for t in types if t not in C.TYPES]
    if bad or not types:
        raise SystemExit(f"--types: unknown {bad}; choose from {', '.join(C.TYPES)}")
    base = a.archive or C.expand(cfg["archive"])
    src_root = base / a.run_id
    reading = a.capture or a.spot_check or a.dry_run
    arm = "repeat" if a.repeat is not None else a.source
    ids = {k: f"{a.run_id}{SUFFIX[k]}" for k in SUFFIX}
    if a.out_id:
        ids["answers" if reading else arm] = a.out_id
    if a.map_id:
        ids["map"] = a.map_id
    if a.repeat_id:
        ids["repeat"] = a.repeat_id
    for k, v in ids.items():
        r = (base / v).resolve()
        if r == src_root.resolve() or src_root.resolve() in r.parents:
            raise SystemExit(f"the check's archive ({k}) must be a new folder, not the source archive or inside it")
    archives = {k: ER.Archive(base / v) for k, v in ids.items()}
    if a.capture or a.spot_check:
        import adhoc_report as R
        return R.main_report(cfg, archives["answers"], a.runs_txt, spot_check=a.spot_check,
                             map_archive=archives["map"], repeat_archive=archives["repeat"])
    src_plan, answers, skipped = source_answers(src_root, types)
    if src_plan["repo"] not in cfg["repos"]:
        raise SystemExit(f"the source's repo {src_plan['repo']!r} is not in the config")
    ans_plan = build_plan(cfg, src_plan, src_root, ids["answers"], types, answers, skipped)
    claude_bin = a.claude_bin or shutil.which(cfg["claude_bin"]) or cfg["claude_bin"]
    if a.dry_run:
        try:
            mp: tuple | str = (build_map_plan(cfg, src_plan, src_root, ids["map"], a.map_n, a.batch_size),
                               archives["map"])
        except SystemExit as exc:
            mp = str(exc)
        rep = build_repeat_plan(ans_plan, ids["repeat"], a.repeat or DEFAULT_REPEAT, ids["answers"])
        dry_run(cfg, {"answers": (ans_plan, archives["answers"]), "map": mp, "repeat": (rep, archives["repeat"])},
                src_root, src_plan, claude_bin, a.max_cost, a.source)
        return 0
    if arm == "answers":
        plan = ans_plan
    elif arm == "map":
        plan = build_map_plan(cfg, src_plan, src_root, ids["map"], a.map_n, a.batch_size)
    else:
        plan = build_repeat_plan(ans_plan, ids["repeat"], a.repeat, ids["answers"])
    archive = archives[arm]
    if a.only and a.only not in {i["id"] for i in plan["items"]}:
        raise SystemExit(f"--only {a.only}: not a check of the {arm} arm's plan")
    pf = archive.root / "plan.json"
    if pf.exists():
        old = json.loads(pf.read_text())
        for k in PLAN_KEYS:
            if old.get(k) != plan.get(k):
                raise SystemExit(f"{pf}: the saved plan's {k} differs from this one; resume needs the same "
                                 "source, scope, config, brief, schema, splitter and sample (start a new --out-id "
                                 "instead)")
    else:
        archive.root.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
        archive.log("plan", arm=arm, checks=len(plan["items"]), units=sum(len(i["units"]) for i in plan["items"]))
    resume = (f"uv run python eval/adhoc/adhoc.py --run-id {a.run_id}"
              + (" --source map" if arm == "map" else "")
              + (f" --repeat {a.repeat}" if arm == "repeat" else "")
              + (f" --out-id {a.out_id}" if a.out_id else "")
              + (f" --types {a.types}" if types != DEFAULT_TYPES else "")
              + (f" --map-n {a.map_n}" if arm == "map" and a.map_n != DEFAULT_MAP_N else "")
              + (f" --batch-size {a.batch_size}" if arm == "map" and a.batch_size != DEFAULT_BATCH else "")
              + (f" --config {a.config}" if a.config != C.CONFIG else "")
              + (f" --archive {a.archive}" if a.archive else "")
              + (f" --claude-bin {a.claude_bin}" if a.claude_bin else "")
              + (f" --max-cost {a.max_cost:g}" if a.max_cost != DEFAULT_MAX_COST else ""))
    token = ER.read_token(cfg["token_command"])
    t0 = time.monotonic()
    runner = AdhocRunner(cfg, plan, archive, claude_bin=claude_bin, token=token, max_cost=a.max_cost,
                         max_runs=a.max_runs, retry_failed=a.retry_failed,
                         concurrency=a.concurrency or cfg.get("concurrency", 1), resume_cmd=resume, only=a.only)
    rc = runner.run()
    ER.status(f"wall {time.monotonic() - t0:.0f} s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
