"""E1: are ad-hoc answers trustworthy? A Checker over the pilot's explore answers (T11d).

    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --dry-run      # scope, units, a prompt, estimate
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 [--max-cost 15]
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --capture > outputs/adhoc_check.txt
    uv run python eval/adhoc/adhoc.py --run-id pilot-nanochat-2 --spot-check  # writes spot_check.md (links)

The source is an eval run archive (eval/run/evalrun.py), read and never written. Its explore answers (an agent
with Read/Grep/Glob and no map, what an engineer gets by asking ad hoc) for the flow and why/how questions
(--types) are split into units by eval/adhoc/adhoc_split.py, and each answer gets one isolated `claude -p`
check, with the isolation of eval/run (runplan/isolate: a fresh scratch root, a fresh `git archive` working dir of
the pinned commit with the agent files removed, the allowlisted environment, the token from the keychain into the
child only, tools Read/Grep/Glob, no Bash, no --add-dir, --json-schema, stream-json). The prompt is
eval/adhoc/brief.md (the Checker's rules adapted for units that cite no lines) with the question and the
numbered units; the schema (check_schema.json) gives each unit a verdict (supported, not_supported, wrong,
not_a_claim), a note and the line ranges read.

Everything kept goes to <archive>/<run-id>-adhoc/ (never inside the source archive):
  plan.json         the frozen plan: source, scope, model, effort, caps, every answer with its units
  log.jsonl         append-only events, as evalrun's
  runs/<answer id>/ prompt.txt, command.txt (token hidden), transcript.jsonl, stderr.txt, result.json,
                    meta.json (status, verdicts, problems, tokens, cost, model, wall)
  attempts/<id>/<n>/ earlier attempts (interrupted, usage limit, --retry-failed)
  spot_check.md     only with --spot-check: the capture's spot-check sample with full GitHub links
Resuming, retries and stops are evalrun's (Runner's loop is reused): the same command resumes; an interrupted run
or one stopped by the usage limit runs again; a failed one only with --retry-failed. Stops at --max-cost (list
price spent in this archive, default $15), at --max-runs, or at the first usage limit. Per answer
--max-budget-usd is config caps.answer_usd. Model and effort: eval/run/config.toml.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import sys
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
EST_FACTOR = (3, 6)          # a check reads more than the answer did: dry-run estimate only


@dataclass(frozen=True)
class CheckItem:
    id: str                  # the source answer's run id; also the folder under runs/
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
    """Mean list cost and wall of the source's finished explore runs (every type): the dry run's estimate base."""
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


def build_plan(cfg: dict, src_plan: dict, src_root: Path, out_id: str, types: tuple[str, ...],
               answers: list[dict], skipped: list[str]) -> dict:
    items = []
    for a in answers:
        units = S.split_units(a["id"], a["text"])
        items.append({"id": a["id"], "qid": a["qid"], "qtype": a["qtype"], "question": a["question"],
                      "units": [asdict(u) for u in units]})
    return {"run_id": out_id, "source_run_id": src_plan["run_id"], "source_archive": str(src_root),
            "repo": src_plan["repo"], "commit": src_plan["commit"], "url": src_plan["url"],
            "types": list(types), "model": cfg["model"], "effort": cfg["effort"],
            "answer_cap_usd": cfg["caps"]["answer_usd"], "seed": int(cfg.get("seed", 0)),
            "config_sha256": cfg["_sha256"], "brief_sha256": sha(BRIEF), "schema_sha256": sha(SCHEMA),
            "splitter_sha256": sha(HERE / "adhoc_split.py"), "items": items, "skipped": skipped}


def short_id(uid: str) -> str:
    return uid.rsplit("#", 1)[1]


def check_prompt(commit: str, question: str, units: list[dict]) -> str:
    """The brief filled in: the question and the numbered units ([s<k>], indented by list level)."""
    rows = []
    for u in units:
        text = u["text"].replace("\n", "\n      ")
        rows.append(f"[{short_id(u['id'])}] " + "  " * int(u["level"]) + text)
    return (BRIEF.read_text().replace("{commit}", commit).replace("{question}", question)
            .replace("{units}", "\n".join(rows)))


def check_spec(cfg: dict, *, prompt: str, workdir: Path, config_dir: Path, home_dir: Path,
               claude_bin: str) -> isolate.RunSpec:
    """isolate's explore settings (fresh copy of the pin as the working dir, Read/Grep/Glob, no extra file), the
    check schema, the per-answer cap."""
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


def parse_verdicts(result: dict | None, units: list[dict], workdirs: tuple[str, ...] = ()) -> tuple[
        list[dict] | None, str, list[str]]:
    """(one row per unit in order: {unit, verdict, note, evidence}; verdict None when the check gave none), how it
    was read, problems (unknown, repeated or missing ids, malformed entries). None rows when the result is not
    the schema's object."""
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
    by_short = {short_id(u["id"]): u["id"] for u in units}
    got: dict[str, dict] = {}
    problems: list[str] = []
    for k, e in enumerate(obj["units"]):
        if not isinstance(e, dict) or e.get("verdict") not in VERDICTS or not isinstance(e.get("id"), str):
            problems.append(f"entry {k}: malformed")
            continue
        uid = by_short.get(e["id"].strip()) or (e["id"] if e["id"] in by_short.values() else None)
        if uid is None:
            problems.append(f"entry {k}: unknown id {e['id']!r}")
            continue
        if uid in got:
            problems.append(f"{short_id(uid)}: repeated (first kept)")
            continue
        ev = []
        for r in e.get("evidence") or []:
            if isinstance(r, dict) and isinstance(r.get("path"), str) and isinstance(r.get("start"), int) \
                    and isinstance(r.get("end"), int):
                ev.append({"path": _rel_path(r["path"], workdirs), "start": r["start"], "end": r["end"]})
            else:
                problems.append(f"{short_id(uid)}: malformed evidence entry")
        got[uid] = {"unit": uid, "verdict": e["verdict"], "note": str(e.get("note") or ""), "evidence": ev}
    rows = []
    for u in units:
        if u["id"] in got:
            rows.append(got[u["id"]])
        else:
            problems.append(f"{short_id(u['id'])}: no verdict")
            rows.append({"unit": u["id"], "verdict": None, "note": "", "evidence": []})
    return rows, how, problems


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
# The runner: evalrun's loop, stops and resume, with a check instead of an answering run

class AdhocRunner(ER.Runner):
    def __init__(self, cfg: dict, plan: dict, archive: ER.Archive, *, claude_bin: str, token: str,
                 max_cost: float, max_runs: int | None, retry_failed: bool, concurrency: int, resume_cmd: str):
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
        self.items = [CheckItem(id=i["id"], qid=i["qid"], qtype=i["qtype"]) for i in plan["items"]]
        self.by_id = {i["id"]: i for i in plan["items"]}
        self.stop_reason = ""
        self.started_now = 0
        self.spent = archive.spent()
        self.parent_env = {k: os.environ[k] for k in ("LANG", "TERM") if k in os.environ}

    def _execute(self, item: CheckItem) -> dict:
        spec_item = self.by_id[item.id]
        d = self.archive.run_dir(item.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "started").write_text(ER.now() + "\n")
        root, cfg_dir, home, work = self._new_root()
        try:
            wd = W.make_repo_workdir(self.clone, self.commit, self.remove, work)
            prompt = check_prompt(self.commit, spec_item["question"], spec_item["units"])
            spec = check_spec(self.cfg, prompt=prompt, workdir=work, config_dir=cfg_dir, home_dir=home,
                              claude_bin=self.claude_bin)
            run = isolate.build_run(spec, P.child_env_source(self.token, self.parent_env))
            c = self._call(d, run, prompt, self.cfg["timeout_answer_s"])
            wds = tuple(dict.fromkeys((str(work), str(work.resolve()), str(work).removeprefix("/private"))))
            rows, how, problems = parse_verdicts(c["result"], spec_item["units"], wds)
            st, reason = self._classify(c, rows is not None)
            usage = RR.usage_summary(c["result"])
            init = c["parsed"]["init"] or {}
            counts = {v: sum(1 for r in rows or [] if r["verdict"] == v) for v in VERDICTS}
            counts["no verdict"] = sum(1 for r in rows or [] if r["verdict"] is None)
            meta = {"id": item.id, "item": asdict(item), "status": st, "reason": reason, "exit": c["code"],
                    "wall_s": round(c["wall"], 1), "started": (d / "started").read_text().strip(),
                    "ended": ER.now(), "model_requested": self.cfg["model"], "model_init": init.get("model"),
                    "models_used": usage["models"], "usage": usage, "tool_calls": c["parsed"]["tool_calls"],
                    "tool_names": c["parsed"]["tool_names"], "verdicts": rows, "read_from": how,
                    "problems": problems, "counts": counts, "units": len(spec_item["units"]),
                    "workdir": str(work), "workdir_files": wd["files"], "agent_files_removed": wd["removed"],
                    "prompt_chars": len(prompt), "leak_scan": P.isolate.leak_scan(c["out"] + c["err"])}
        finally:
            shutil.rmtree(root, ignore_errors=True)
        (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
        return meta

    def run(self) -> int:
        todo = [i for i in self.items if self.needs_run(i)]
        ER.status(f"{len(self.items)} answers to check, {len(todo)} to run, ${self.spent:.2f} already spent")
        self._run_all(todo)
        return self.report([])

    def report(self, blocked: list[str]) -> int:
        by: dict[str, int] = {}
        for i in self.items:
            st = (self.archive.meta(i.id) or {}).get("status", "not run")
            by[st] = by.get(st, 0) + 1
        finished = sum(v for k, v in by.items() if k in RR.FINAL)
        print(f"adhoc check {self.plan['run_id']}: {finished} of {len(self.items)} answers checked; "
              + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + f"; spent ${self.spent:.2f} (list price)")
        if self.stop_reason:
            self.archive.log("stop", reason=self.stop_reason)
            print(f"stopped: {self.stop_reason}")
        if by.get("error"):
            print(f"{by['error']} failed checks stay failed; --retry-failed runs them again")
        if finished < len(self.items):
            print(f"resume with: {self.resume_cmd}")
            return 3
        return 0


# ------------------------------------------------------------------------------------------------------------

def dry_run(cfg: dict, plan: dict, archive: ER.Archive, src_root: Path, src_plan: dict, claude_bin: str,
            max_cost: float) -> None:
    items = plan["items"]
    n_units = sum(len(i["units"]) for i in items)
    print("E1 ad-hoc answer check (dry run: nothing is run, no token is read)")
    print(f"source     {plan['source_run_id']} ({src_root}), read only")
    print(f"archive    {archive.root}")
    print(f"repo       {plan['repo']} at {plan['commit'][:12]}")
    print(f"model      {cfg['model']}, effort {cfg['effort']}; cap ${cfg['caps']['answer_usd']:g} per answer; "
          f"stop at ${max_cost:g} (--max-cost)")
    all_types = {q["type"] for q in src_plan["questions"]}
    by_type = {t: sum(1 for i in items if i["qtype"] == t) for t in plan["types"]}
    print(f"scope      explore answers of types {', '.join(plan['types'])}: {len(items)} answers ("
          + ", ".join(f"{t} {k}" for t, k in by_type.items()) + "); left out: "
          + (", ".join(sorted(all_types - set(plan["types"]))) or "none"))
    for s in plan["skipped"]:
        print(f"           skipped (not ok in the source): {s}")
    print(f"units      {n_units} in {len(items)} answers (adhoc_split.py: sentences, list items)")
    for i in items:
        kinds: dict[str, int] = {}
        for u in i["units"]:
            kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
        print(f"  {i['id']:<26} {len(i['units']):>3} units  ("
              + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + ")")
    base = explore_baseline(src_root, src_plan)
    lo, hi = EST_FACTOR
    per = (base["mean_usd"] * lo, base["mean_usd"] * hi)
    conc = max(1, int(cfg.get("concurrency", 1)))
    mins = (base["mean_wall_s"] * lo * len(items) / 60 / conc, base["mean_wall_s"] * hi * len(items) / 60 / conc)
    print(f"ESTIMATE   source explore runs: {base['runs']}, mean ${base['mean_usd']:.3f} and "
          f"{base['mean_wall_s']:.0f} s each; a check reads more,")
    print(f"           assumed {lo}-{hi}x: ${per[0]:.2f}-${per[1]:.2f} per answer, "
          f"${per[0] * len(items):.2f}-${per[1] * len(items):.2f} for {len(items)} answers, "
          f"{mins[0]:.0f}-{mins[1]:.0f} min at concurrency {conc}")
    print("           (an estimate, not measured)")
    if (archive.root / "plan.json").exists():
        done = sum(1 for i in items if (archive.meta(i["id"]) or {}).get("status") in RR.FINAL)
        print(f"resume     the archive exists: {done} answers checked, they would be skipped")
    if not items:
        return
    root = Path(str(C.expand(cfg["scratch"]))) / "hg-eval-RUN_ROOT"
    first = items[0]
    prompt = check_prompt(plan["commit"], first["question"], first["units"])
    spec = check_spec(cfg, prompt=prompt, workdir=root / "work", config_dir=root / "cfg", home_dir=root / "home",
                      claude_bin=claude_bin)
    env_src = P.child_env_source(ER.PLACEHOLDER_TOKEN, {k: os.environ[k] for k in ("LANG", "TERM")
                                                           if k in os.environ})
    run = isolate.build_run(spec, env_src)
    run.argv[2] = f"<prompt: {len(prompt)} chars, sha256 {hashlib.sha256(prompt.encode()).hexdigest()[:12]}>"
    run.argv[run.argv.index("--json-schema") + 1] = f"<check_schema.json, sha256 {plan['schema_sha256'][:12]}>"
    lines = isolate.describe(run)
    print("command    one per answer; token hidden; RUN_ROOT is a fresh scratch folder, removed after the run")
    print("  " + lines[0])
    print("  " + lines[1])
    print(f"  cwd:  {root / 'work'} (git archive of the pin, agent files removed: "
          f"{', '.join(cfg['repos'][plan['repo']].get('remove', [])) or 'none'})")
    print(f"--- example prompt ({first['id']}) ---")
    print(prompt.rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E1: check the claims in a run's explore answers (T11d).")
    ap.add_argument("--run-id", required=True, help="the source eval run (e.g. pilot-nanochat-2)")
    ap.add_argument("--out-id", help="the check's archive folder (default <run-id>-adhoc)")
    ap.add_argument("--types", default=",".join(DEFAULT_TYPES), help="question types (default flow,whyhow)")
    ap.add_argument("--config", type=Path, default=C.CONFIG)
    ap.add_argument("--archive", type=Path, help="default: config archive")
    ap.add_argument("--claude-bin", help="default: config claude_bin on PATH")
    ap.add_argument("--dry-run", action="store_true", help="print scope, units, a prompt, the command; run nothing")
    ap.add_argument("--capture", action="store_true", help="print the capture (outputs/adhoc_check.txt)")
    ap.add_argument("--spot-check", action="store_true", help="write spot_check.md (the sample, full links)")
    ap.add_argument("--runs-txt", type=Path, default=ROOT / "outputs" / "runs.txt",
                    help="the map Checker numbers, for comparison in the capture")
    ap.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST, help="USD list price (default 15)")
    ap.add_argument("--max-runs", type=int, help="start at most this many checks in this invocation")
    ap.add_argument("--retry-failed", action="store_true", help="run failed (status error) checks again")
    ap.add_argument("--concurrency", type=int, help="default config concurrency")
    a = ap.parse_args(argv)
    cfg = C.load_config(a.config)
    types = tuple(t for t in a.types.split(",") if t)
    bad = [t for t in types if t not in C.TYPES]
    if bad or not types:
        raise SystemExit(f"--types: unknown {bad}; choose from {', '.join(C.TYPES)}")
    base = a.archive or C.expand(cfg["archive"])
    src_root = base / a.run_id
    out_id = a.out_id or f"{a.run_id}-adhoc"
    out_root = base / out_id
    if out_root.resolve() == src_root.resolve() or src_root.resolve() in out_root.resolve().parents:
        raise SystemExit("the check's archive must be a new folder, not the source archive or inside it")
    archive = ER.Archive(out_root)
    if a.capture or a.spot_check:
        import adhoc_report as R
        return R.main_report(cfg, archive, a.runs_txt, spot_check=a.spot_check)
    src_plan, answers, skipped = source_answers(src_root, types)
    if src_plan["repo"] not in cfg["repos"]:
        raise SystemExit(f"the source's repo {src_plan['repo']!r} is not in the config")
    plan = build_plan(cfg, src_plan, src_root, out_id, types, answers, skipped)
    claude_bin = a.claude_bin or shutil.which(cfg["claude_bin"]) or cfg["claude_bin"]
    if a.dry_run:
        dry_run(cfg, plan, archive, src_root, src_plan, claude_bin, a.max_cost)
        return 0
    pf = archive.root / "plan.json"
    if pf.exists():
        old = json.loads(pf.read_text())
        for k in ("items", "commit", "model", "effort", "config_sha256", "brief_sha256", "schema_sha256",
                  "splitter_sha256", "types"):
            if old.get(k) != plan.get(k):
                raise SystemExit(f"{pf}: the saved plan's {k} differs from this one; resume needs the same "
                                 "source, scope, config, brief, schema and splitter (start a new --out-id instead)")
    else:
        archive.root.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
        archive.log("plan", answers=len(plan["items"]), units=sum(len(i["units"]) for i in plan["items"]))
    resume = (f"uv run python eval/adhoc/adhoc.py --run-id {a.run_id}"
              + (f" --out-id {a.out_id}" if a.out_id else "")
              + (f" --types {a.types}" if types != DEFAULT_TYPES else "")
              + (f" --config {a.config}" if a.config != C.CONFIG else "")
              + (f" --archive {a.archive}" if a.archive else "")
              + (f" --claude-bin {a.claude_bin}" if a.claude_bin else "")
              + (f" --max-cost {a.max_cost:g}" if a.max_cost != DEFAULT_MAX_COST else ""))
    token = ER.read_token(cfg["token_command"])
    t0 = time.monotonic()
    runner = AdhocRunner(cfg, plan, archive, claude_bin=claude_bin, token=token, max_cost=a.max_cost,
                         max_runs=a.max_runs, retry_failed=a.retry_failed,
                         concurrency=a.concurrency or cfg.get("concurrency", 1), resume_cmd=resume)
    rc = runner.run()
    ER.status(f"wall {time.monotonic() - t0:.0f} s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
