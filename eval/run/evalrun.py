"""Run Honeyguide's four-way eval (T12): eval map builds, the outline, then every answering run of the plan.

    uv run python eval/run/evalrun.py --repo nanochat --size pilot --dry-run      # the plan + exact commands
    uv run python eval/run/evalrun.py --repo nanochat --size pilot --run-id pilot-nanochat [--max-cost 40]

Each run is an isolated `claude -p` (see runplan.py) in a throwaway root under config `scratch`. Everything kept
goes to the run archive, outside the repo: <archive>/<run-id>/
  plan.json                 the frozen plan (config snapshot, questions, every run in order)
  log.jsonl                 append-only events: start, done, restart after interruption, retry, stop
  runs/<id>/                prompt.txt, command.txt (token hidden), transcript.jsonl (stream-json), stderr.txt,
                            result.json (the result event), meta.json (status, answer, tokens, cost, model, wall)
  attempts/<id>/<n>/        earlier attempts of a run re-run with --retry-failed or after a usage-limit stop
  maps/seed<k>/             map.json (the Cartographer's output), validation.json, map.md (what map runs read)
  outline/                  outline.md (what outline runs read), outline.json (its size and the maps' sizes)

Resuming: run the same command with the same --run-id. Finished runs are skipped. A run that was interrupted
(started, no result) or stopped by the usage limit is run again, and the log says so. A failed run (status error)
is never re-run unless --retry-failed is given (which also re-runs a map build that returned no usable map); the
earlier attempt is kept. Capped runs and invalid answers are final (they count as wrong). The runner stops starting runs at --max-cost (list price, everything spent in this
run archive, so in-flight runs can overshoot by up to concurrency x the per-run cap), at --max-runs (runs started
by this invocation), or at the first usage-limit error, and prints the command that resumes.

The subscription token is read once from the keychain (config token_command), passed only into each child's
environment, never printed or written; a run whose output contains it is saved without that output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evalcfg as C  # noqa: E402

sys.path.insert(0, str(C.ROOT / "eval" / "questions"))
try:
    import honeyguide  # noqa: F401
except ImportError:   # run outside the uv environment
    sys.path.insert(0, str(C.ROOT / "src"))
import maprender as M  # noqa: E402
import outline_build as OB  # noqa: E402
import runplan as P  # noqa: E402
import runresult as RR  # noqa: E402
import workdirs as W  # noqa: E402
from repo import in_scope  # noqa: E402

PLACEHOLDER_TOKEN = "DRY-RUN-NO-TOKEN"


def status(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_token(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"could not read the token ({type(exc).__name__}); see config token_command") from None
    token = p.stdout.strip()
    if p.returncode != 0 or not token:
        raise SystemExit("no token from the keychain: run `claude setup-token` and save it with "
                         "`security add-generic-password -s honeyguide-oauth -a $USER -w` (config token_command)")
    return token


def scope_sources(clone: Path, commit: str, code_dirs: list[str]) -> dict[str, str]:
    """The key scope's .py files at commit (the outline's input), read with git show."""
    names = subprocess.run(["git", "-C", str(clone), "ls-tree", "-r", "--name-only", commit], check=True,
                           capture_output=True, text=True).stdout.splitlines()
    out = {}
    for p in sorted(names):
        if p.endswith(".py") and in_scope(p, tuple(code_dirs) or None):
            out[p] = subprocess.run(["git", "-C", str(clone), "show", f"{commit}:{p}"], check=True,
                                    capture_output=True, text=True).stdout
    return out


# ------------------------------------------------------------------------------------------------------------

class Archive:
    def __init__(self, root: Path):
        self.root = root

    def run_dir(self, item_id: str) -> Path:
        return self.root / "runs" / item_id

    def map_dir(self, seed: int) -> Path:
        return self.root / "maps" / f"seed{seed}"

    def log(self, event: str, **kw) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "log.jsonl").open("a") as f:
            f.write(json.dumps({"ts": now(), "event": event, **kw}, sort_keys=True) + "\n")

    def meta(self, item_id: str) -> dict | None:
        p = self.run_dir(item_id) / "meta.json"
        return json.loads(p.read_text()) if p.exists() else None

    def started(self, item_id: str) -> bool:
        return (self.run_dir(item_id) / "started").exists()

    def to_attempts(self, item_id: str) -> int:
        """Move runs/<id>/ to attempts/<id>/<n>/; returns n."""
        base = self.root / "attempts" / item_id
        n = len(list(base.glob("*"))) + 1 if base.exists() else 1
        base.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.run_dir(item_id)), str(base / str(n)))
        return n

    def spent(self) -> float:
        total = 0.0
        for p in list((self.root / "runs").glob("*/meta.json")) + list((self.root / "attempts").glob("*/*/meta.json")):
            total += float(json.loads(p.read_text()).get("usage", {}).get("cost_usd") or 0.0)
        return total


class Runner:
    def __init__(self, cfg: dict, plan: dict, archive: Archive, *, claude_bin: str, token: str, max_cost: float,
                 max_runs: int | None, retry_failed: bool, concurrency: int, resume_cmd: str):
        self.cfg, self.plan, self.archive = cfg, plan, archive
        self.repo = plan["repo"]
        rc = cfg["repos"][self.repo]
        self.clone = C.expand(rc["clone"])
        self.remove = list(rc.get("remove", []))
        self.code_dirs = list(rc.get("code_dirs", []))
        self.commit = plan["commit"]
        self.claude_bin = claude_bin
        self.token = token
        self.max_cost = max_cost
        self.max_runs = max_runs
        self.retry_failed = retry_failed
        self.concurrency = max(1, concurrency)
        self.resume_cmd = resume_cmd
        self.items = [P.Item(**d) for d in plan["items"]]
        self.questions = {q["id"]: q for q in plan["questions"]}
        self.seeds = plan["config"]["sizes"][plan["size"]]["map_seeds"]
        self.stop_reason = ""
        self.started_now = 0
        self.spent = archive.spent()
        self.parent_env = {k: os.environ[k] for k in ("LANG", "TERM") if k in os.environ}

    # -- which runs still need running ------------------------------------------------------------------
    def needs_run(self, item: P.Item) -> bool:
        meta = self.archive.meta(item.id)
        if meta is None:
            if self.archive.started(item.id):
                n = self.archive.to_attempts(item.id)
                self.archive.log("restart_after_interruption", id=item.id, attempt_kept=n)
                status(f"  {item.id}: interrupted earlier (no result); running it again (kept as attempt {n})")
            return True
        st = meta["status"]
        if st == "usage_limit":
            n = self.archive.to_attempts(item.id)
            self.archive.log("resume_after_usage_limit", id=item.id, attempt_kept=n)
            return True
        if self.retry_failed and (st == "error" or (item.kind == "map" and st == "invalid_answer")):
            n = self.archive.to_attempts(item.id)
            self.archive.log("retry_failed", id=item.id, attempt_kept=n, reason=meta.get("reason", ""))
            status(f"  {item.id}: failed earlier ({meta.get('reason', '')}); retrying (kept as attempt {n})")
            return True
        return False

    # -- one run ----------------------------------------------------------------------------------------
    def notes_for(self, item: P.Item) -> str | None:
        if item.condition == "map":
            return (self.archive.map_dir(item.map_seed) / "map.md").read_text()
        if item.condition == "outline":
            return (self.archive.root / "outline" / "outline.md").read_text()
        return None

    def execute(self, item: P.Item) -> dict:
        try:
            return self._execute(item)
        except Exception as exc:  # noqa: BLE001 - a runner-side failure is recorded as this run's error
            d = self.archive.run_dir(item.id)
            d.mkdir(parents=True, exist_ok=True)
            meta = {"id": item.id, "item": asdict(item), "status": "error",
                    "reason": f"runner: {type(exc).__name__}: {self._hide(str(exc))}", "usage": RR.usage_summary(None),
                    "ended": now()}
            (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
            return meta

    def _hide(self, s: str) -> str:
        return s.replace(self.token, "<token>") if self.token else s

    def _execute(self, item: P.Item) -> dict:
        d = self.archive.run_dir(item.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "started").write_text(now() + "\n")
        root = Path(tempfile.mkdtemp(prefix="hg-eval-", dir=str(C.expand(self.cfg["scratch"]))))
        try:
            cfg_dir, home, work = root / "cfg", root / "home", root / "work"
            for x in (cfg_dir, home, home / "tmp"):
                x.mkdir(parents=True)
            if item.kind == "answer" and item.condition == "no-access":
                wd = W.make_empty_workdir(work)
            else:
                wd = W.make_repo_workdir(self.clone, self.commit, self.remove, work)
            if item.kind == "map":
                prompt = P.map_prompt(work)
            else:
                q = self.questions[item.qid]
                prompt = P.answer_prompt({"url": self.plan["url"], "commit": self.commit}, self.repo, q["text"],
                                         self.notes_for(item))
            spec = P.run_spec(self.cfg, item, prompt=prompt, workdir=work, config_dir=cfg_dir, home_dir=home,
                              claude_bin=self.claude_bin)
            run = P.build_command(self.cfg, item, spec, P.child_env_source(self.token, self.parent_env))
            (d / "prompt.txt").write_text(prompt)
            shown = list(run.argv)
            shown[2] = f"<prompt.txt: {len(prompt)} chars>"
            (d / "command.txt").write_text("\n".join(P.isolate.describe(P.isolate.Run(
                argv=shown, env=run.env, cwd=run.cwd, redact=run.redact))) + f"\ncwd:  {run.cwd}\n")
            t0 = time.monotonic()
            timed_out = False
            try:
                p = subprocess.run(run.argv, env=run.env, cwd=run.cwd, capture_output=True, text=True,
                                   timeout=self.cfg["timeout_map_s" if item.kind == "map" else "timeout_answer_s"])
                out, err, code = p.stdout, p.stderr, p.returncode
            except subprocess.TimeoutExpired as exc:
                out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                code, timed_out = None, True
            wall = time.monotonic() - t0
            token_seen = bool(self.token) and (self.token in out or self.token in err)
            if token_seen:
                out, err = "", "[withheld: the token appeared in this run's output]\n"
            parsed = RR.parse_stream(out)
            result = parsed["result"]
            map_obj = answer = None
            if item.kind == "map":
                map_obj, how = M.extract_json(result or {})
                ok = map_obj is not None
            else:
                answer, how = RR.parse_answer(result)
                ok = answer is not None
            st, reason = RR.classify(code, result, err, ok, timed_out)
            if token_seen:
                st, reason = "error", "token in output (output withheld)"
            (d / "transcript.jsonl").write_text(out)
            (d / "stderr.txt").write_text(err)
            if result is not None:
                (d / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
            usage = RR.usage_summary(result)
            init = parsed["init"] or {}
            meta = {"id": item.id, "item": asdict(item), "status": st, "reason": reason, "exit": code,
                    "wall_s": round(wall, 1), "started": (d / "started").read_text().strip(), "ended": now(),
                    "model_requested": self.cfg["model"], "model_init": init.get("model"),
                    "models_used": usage["models"], "usage": usage, "tool_calls": parsed["tool_calls"],
                    "tool_names": parsed["tool_names"], "answer": answer, "answer_read_from": how,
                    "workdir": str(work), "workdir_files": wd["files"], "agent_files_removed": wd["removed"],
                    "prompt_chars": len(prompt), "leak_scan": P.isolate.leak_scan(out + err)}
            if item.kind == "map" and st == "ok":
                meta["map"] = self._save_map(item.map_seed, map_obj, how)
                if not meta["map"]["usable"]:
                    meta["status"], meta["reason"] = "invalid_answer", "map: " + meta["map"]["reason"]
            (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
            return meta
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _save_map(self, seed: int, obj: dict, how: str) -> dict:
        md = self.archive.map_dir(seed)
        md.mkdir(parents=True, exist_ok=True)
        (md / "map.json").write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        v = M.validate_map(self.clone, self.commit, obj)
        v["read_from"] = how
        if v["usable"]:
            resolved, _ = M.resolve_anchors(M.Repo.open(self.clone), self.commit, obj.get("claims"))
            text = M.render_map(obj, resolved)
            (md / "map.md").write_text(text)
            v["chars"], v["tokens_est"] = len(text), OB.est_tokens(text)
        (md / "validation.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
        status(f"  map seed {seed}: {v.get('claims', 0)} claims, anchors {v['anchors_resolved']}/"
               f"{v['anchors_total']} resolved, draft valid {v['draft_valid']}, "
               f"{v.get('tokens_est', 0)} tokens (est.)")
        return {k: v[k] for k in ("usable", "anchors_total", "anchors_resolved", "draft_valid")} | {
            "reason": v.get("reason", ""), "tokens_est": v.get("tokens_est", 0)}

    # -- the outline -------------------------------------------------------------------------------------
    def ensure_outline(self) -> str:
        """Build outline/outline.md once (size-matched to the mean of the maps' token estimates). '' when done,
        else why it can't be built yet."""
        od = self.archive.root / "outline"
        if (od / "outline.md").exists():
            return ""
        sizes = {}
        for s in range(1, self.seeds + 1):
            f = self.archive.map_dir(s) / "map.md"
            if not f.exists():
                return f"map seed {s} is not built"
            sizes[s] = OB.est_tokens(f.read_text())
        target = round(sum(sizes.values()) / len(sizes))
        o = OB.build_outline(self.repo, self.commit, scope_sources(self.clone, self.commit, self.code_dirs), target)
        od.mkdir(parents=True, exist_ok=True)
        (od / "outline.md").write_text(o.text)
        (od / "outline.json").write_text(json.dumps(
            {"target_tokens": target, "map_tokens_est": {str(k): v for k, v in sizes.items()},
             "tokens_est": o.tokens, "chars": len(o.text), "levels": o.levels, "left_out": o.left_out,
             "summary": o.summary()}, indent=1, sort_keys=True) + "\n")
        self.archive.log("outline_built", tokens=o.tokens, target=target)
        status(f"  {o.summary()}; maps {sizes}")
        return ""

    # -- the loop ----------------------------------------------------------------------------------------
    def _check_limits(self) -> bool:
        if self.spent >= self.max_cost:
            self.stop_reason = f"max cost reached (${self.spent:.2f} spent of ${self.max_cost:.2f}, list price)"
        elif self.max_runs is not None and self.started_now >= self.max_runs:
            self.stop_reason = f"max runs reached ({self.max_runs} started by this invocation)"
        return not self.stop_reason

    def _run_all(self, items: list[P.Item]) -> None:
        queue = list(items)
        total = len(self.items)
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            inflight = {}
            while queue or inflight:
                while queue and len(inflight) < self.concurrency and not self.stop_reason and self._check_limits():
                    it = queue.pop(0)
                    self.started_now += 1
                    self.archive.log("start", id=it.id)
                    inflight[ex.submit(self.execute, it)] = it
                if not inflight:
                    break
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for f in done:
                    it = inflight.pop(f)
                    meta = f.result()
                    self.spent += float(meta["usage"].get("cost_usd") or 0.0)
                    self.archive.log("done", id=it.id, status=meta["status"], reason=meta.get("reason", ""),
                                     cost_usd=meta["usage"].get("cost_usd", 0.0))
                    n_done = sum(1 for i in self.items if (self.archive.meta(i.id) or {}).get("status") in RR.FINAL)
                    status(f"  [{n_done}/{total}] {it.id}: {meta['status']}"
                           + (f" ({meta['reason']})" if meta.get("reason") else "")
                           + f", ${meta['usage'].get('cost_usd', 0.0):.3f}, {meta.get('wall_s', 0)} s;"
                           f" spent ${self.spent:.2f}")
                    if meta["status"] == "usage_limit" and not self.stop_reason:
                        self.stop_reason = f"usage limit hit at {it.id}"

    def run(self) -> int:
        todo = [i for i in self.items if self.needs_run(i)]
        status(f"{len(self.items)} runs in the plan, {len(todo)} to run, ${self.spent:.2f} already spent")
        self._run_all([i for i in todo if i.kind == "map"])
        blocked: list[str] = []
        answers = [i for i in todo if i.kind == "answer"]
        if not self.stop_reason:
            bad = {s for s in range(1, self.seeds + 1)
                   if (self.archive.meta(f"map-s{s}") or {}).get("status") != "ok"}
            why = "" if not bad else f"map seed(s) {sorted(bad)} not usable"
            if not why and any(i.condition == "outline" for i in answers):
                why = self.ensure_outline()
            keep = []
            for i in answers:
                if (i.condition == "map" and i.map_seed in bad) or (i.condition == "outline" and why):
                    blocked.append(i.id)
                else:
                    keep.append(i)
            if blocked:
                self.archive.log("blocked", runs=len(blocked), reason=why)
                status(f"  {len(blocked)} map/outline runs blocked: {why}")
            self._run_all(keep)
        return self.report(blocked)

    def report(self, blocked: list[str]) -> int:
        metas = {i.id: self.archive.meta(i.id) for i in self.items}
        by: dict[str, int] = {}
        for m in metas.values():
            st = (m or {}).get("status", "not run")
            by[st] = by.get(st, 0) + 1
        finished = sum(v for k, v in by.items() if k in RR.FINAL)
        print(f"run {self.plan['run_id']}: {finished} of {len(self.items)} runs finished; "
              + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + f"; spent ${self.spent:.2f} (list price)")
        if self.stop_reason:
            self.archive.log("stop", reason=self.stop_reason)
            print(f"stopped: {self.stop_reason}")
        if blocked:
            print(f"blocked: {len(blocked)} runs need a usable map (see maps/*/validation.json)")
        if by.get("error"):
            print(f"{by['error']} failed runs stay failed (they count as wrong); --retry-failed runs them again")
        if finished < len(self.items):
            print(f"resume with: {self.resume_cmd}")
            return 3
        return 0


# ------------------------------------------------------------------------------------------------------------

def dry_run(cfg: dict, plan: dict, archive: Archive, claude_bin: str) -> None:
    items = [P.Item(**d) for d in plan["items"]]
    qs = plan["questions"]
    n = plan["counts"]
    per_q = " + ".join(f"{cfg['passes'][c]} {c}" for c in C.CONDITIONS)
    per_q_n = sum(cfg["passes"][c] for c in C.CONDITIONS)
    types = {t: sum(1 for q in qs if q["type"] == t) for t in C.TYPES}
    subsets = {s: sum(1 for q in qs if q["subset"] == s) for s in ("before", "after", "none")}
    est = P.estimate(cfg, items)
    print("Honeyguide eval plan (dry run: nothing is run, no token is read)")
    print(f"run id     {plan['run_id']}   archive {archive.root}")
    print(f"repo       {plan['repo']} at {plan['commit'][:12]}   size {plan['size']}")
    print(f"model      {cfg['model']}, effort {cfg['effort']}; caps ${cfg['caps']['answer_usd']:g} per answer, "
          f"${cfg['caps']['map_usd']:g} per map build; stop at ${cfg['caps']['max_cost_usd']:g}")
    print(f"questions  {len(qs)}: " + ", ".join(f"{t} {k}" for t, k in types.items())
          + "; cutoff subsets " + ", ".join(f"{s} {k}" for s, k in subsets.items()))
    print("           " + " ".join(q["id"] for q in qs))
    print(f"runs       per question {per_q} = {per_q_n}; {len(qs)} x {per_q_n} = {n['answer runs']} answer runs"
          f" + {n['map builds']} map build(s) = {n['total']} runs")
    seeds = cfg["sizes"][plan["size"]]["map_seeds"]
    print(f"maps       {seeds} map seed(s); map pass k reads seed ((k-1) mod {seeds}) + 1: "
          + ", ".join(f"pass {k} -> seed {C.map_seed_for_pass(k, seeds)}" for k in range(1, cfg['passes']['map'] + 1)))
    print(f"ESTIMATE   ${est['usd'][0]:.0f}-${est['usd'][1]:.0f} list price; "
          f"{est['minutes_wall'][0] / 60:.1f}-{est['minutes_wall'][1] / 60:.1f} h wall at concurrency "
          f"{est['concurrency']} (config [estimate] ranges; not measured)")
    done = sum(1 for i in items if (archive.meta(i.id) or {}).get("status") in RR.FINAL)
    if (archive.root / "plan.json").exists():
        print(f"resume     the archive exists: {done} runs finished, they would be skipped")
    print("commands   token hidden; RUN_ROOT is each run's fresh scratch folder (removed after the run);")
    print("           prompts by size and hash; map/outline prompts are built after the map build")
    env_src = P.child_env_source(PLACEHOLDER_TOKEN, {k: os.environ[k] for k in ("LANG", "TERM") if k in os.environ})
    root = Path(str(C.expand(cfg["scratch"]))) / "hg-eval-RUN_ROOT"
    examples = {}
    for k, it in enumerate(items, 1):
        if it.kind == "map":
            prompt = P.map_prompt(root / "work")
        elif it.condition in ("map", "outline"):
            prompt = None
        else:
            prompt = P.answer_prompt({"url": plan["url"], "commit": plan["commit"]}, plan["repo"],
                                     next(q["text"] for q in qs if q["id"] == it.qid), None)
            examples.setdefault(it.condition, prompt)
        spec = P.run_spec(cfg, it, prompt=prompt or "", workdir=root / "work", config_dir=root / "cfg",
                          home_dir=root / "home", claude_bin=claude_bin)
        run = P.build_command(cfg, it, spec, env_src)
        if prompt is None:
            src = f"map seed {it.map_seed} text" if it.condition == "map" else "outline text"
            run.argv[2] = f"<prompt: brief + question {it.qid} + {src}>"
        else:
            run.argv[2] = f"<prompt: {len(prompt)} chars, sha256 {hashlib.sha256(prompt.encode()).hexdigest()[:12]}>"
        lines = P.isolate.describe(run)
        print(f"[{k}] {it.id}")
        print("  " + lines[0])
        if k == 1:
            print("  " + lines[1])
            print(f"  cwd:  {root / 'work'} (no-access: an empty dir; else git archive of the pin, "
                  f"agent files removed: {', '.join(cfg['repos'][plan['repo']].get('remove', [])) or 'none'})")
    for cond, prompt in examples.items():
        print(f"--- example prompt ({cond}) ---")
        print(prompt.rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Honeyguide's four-way eval (T12).")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--size", default="pilot")
    ap.add_argument("--run-id", help="the run archive folder (default <size>-<repo>)")
    ap.add_argument("--config", type=Path, default=C.CONFIG)
    ap.add_argument("--archive", type=Path, help="default: config archive")
    ap.add_argument("--claude-bin", help="default: config claude_bin on PATH")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and every command; run nothing")
    ap.add_argument("--max-cost", type=float, help="USD list price, default config caps.max_cost_usd")
    ap.add_argument("--max-runs", type=int, help="start at most this many runs in this invocation")
    ap.add_argument("--retry-failed", action="store_true", help="run failed (status error) runs again")
    ap.add_argument("--concurrency", type=int, help="default config concurrency")
    a = ap.parse_args(argv)
    cfg = C.load_config(a.config)
    if a.repo not in cfg["repos"]:
        raise SystemExit(f"unknown repo {a.repo!r}; config has {', '.join(cfg['repos'])}")
    if a.size not in cfg["sizes"]:
        raise SystemExit(f"unknown size {a.size!r}; config has {', '.join(cfg['sizes'])}")
    run_id = a.run_id or f"{a.size}-{a.repo}"
    archive = Archive((a.archive or C.expand(cfg["archive"])) / run_id)
    frozen, _, _ = C.load_questions(cfg, a.repo)
    questions = C.select_questions(cfg, a.repo, a.size)
    items = P.build_items(cfg, a.repo, a.size, questions)
    plan = P.plan_doc(cfg, a.repo, a.size, run_id, questions, items, frozen)
    claude_bin = a.claude_bin or shutil.which(cfg["claude_bin"]) or cfg["claude_bin"]
    if a.dry_run:
        dry_run(cfg, plan, archive, claude_bin)
        return 0
    pf = archive.root / "plan.json"
    if pf.exists():
        old = json.loads(pf.read_text())
        for k in ("config_sha256", "items", "questions", "commit", "manifest_sha256"):
            if old.get(k) != plan.get(k):
                raise SystemExit(f"{pf}: the saved plan's {k} differs from this one; resume needs the same config,"
                                 " questions and frozen sets (start a new --run-id instead)")
    else:
        archive.root.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
        archive.log("plan", runs=len(items), config_sha256=cfg["_sha256"])
    resume = (f"uv run python eval/run/evalrun.py --repo {a.repo} --size {a.size} --run-id {run_id}"
              + (f" --config {a.config}" if a.config != C.CONFIG else "")
              + (f" --archive {a.archive}" if a.archive else "")
              + (f" --claude-bin {a.claude_bin}" if a.claude_bin else ""))
    token = read_token(cfg["token_command"])
    runner = Runner(cfg, plan, archive, claude_bin=claude_bin, token=token,
                    max_cost=a.max_cost if a.max_cost is not None else cfg["caps"]["max_cost_usd"],
                    max_runs=a.max_runs, retry_failed=a.retry_failed,
                    concurrency=a.concurrency or cfg.get("concurrency", 1), resume_cmd=resume)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
