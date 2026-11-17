"""Run Honeyguide's four-way eval: eval map builds, the outline, then every answering run of the plan.

    uv run python eval/run/evalrun.py --repo nanochat --size pilot --dry-run      # the plan + exact commands
    uv run python eval/run/evalrun.py --repo nanochat --size pilot --run-id pilot-nanochat [--max-cost 40]

Each run is an isolated `claude -p` (see runplan.py) in a throwaway root under config `scratch`. Everything kept
goes to the run archive, outside the repo: <archive>/<run-id>/
  plan.json                 the frozen plan (config snapshot, questions, every run in order)
  log.jsonl                 append-only events: start, done, restart after interruption, retry, stop
  runs/<id>/                prompt.txt, command.txt (token hidden), transcript.jsonl (stream-json), stderr.txt,
                            result.json (the result event), meta.json (status, answer, tokens, cost, model, wall)
  runs/map-s<k>/            also map.json and validation.json (the build's own map and its check), cost_so_far.json
                            (what the build and the finished fix rounds billed, rewritten after each; read only
                            while the run has no meta.json), and
    fix/<n>/                one folder per fix round, the same files plus that round's map.json and validation.json
  attempts/<id>/<n>/        earlier attempts of a run re-run with --retry-failed or after a usage-limit stop
  maps/seed<k>/             the last round's map.json and validation.json; map.md (what map runs read) only when
                            the map passes the check
  outline/                  outline.md (what outline runs read), outline.json (its size and the maps' sizes)

The eval map: the Cartographer (eval mode, Read/Grep/Glob) returns the claims save input; maprender.validate_map
checks it. It is used only if it passes: no structure error and no draft error other than quotes that did not
resolve (not_found or ambiguous: counted, never fixed). A map that fails gets up to config map_fix_rounds fix rounds: each a new
isolated run (same isolation, model, effort, tools and map schema, a fresh repo copy) whose prompt holds the
blocking errors verbatim and the fix instructions, with the previous map as a file outside the working dir
(--add-dir). caps.map_usd covers the build and its fix rounds; each round's --max-budget-usd is what is left. The
map run's meta.json records fix_rounds (round, errors_in, errors_out, cost, wall_s) and its usage is the total;
log.jsonl gets a map_fix event per round. A map still failing after the rounds makes the map run invalid_answer,
and every map and outline run waits for a usable map (blocked).

Resuming: run the same command with the same --run-id. Finished runs are skipped. A run that was interrupted
(started, no result) or stopped by the usage limit is run again, and the log says so. A failed run (status error)
is never re-run unless --retry-failed is given (which also re-runs a map build that returned no usable map); the
earlier attempt is kept. A map run interrupted after its build or a fix round keeps what those billed (its
cost_so_far.json): `spent` counts it, in runs/ or attempts/, and a runner-side failure records it as the run's usage. Capped runs and invalid answers are final (they count as wrong). The runner stops starting runs at --max-cost (list price, everything spent in this
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
COST_SO_FAR = "cost_so_far.json"     # a map run's billed usage so far (build + finished fix rounds)


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
        """List price billed in this archive: each run folder (runs/<id>/, attempts/<id>/<n>/) counted once, from
        its meta.json, or, for a map run interrupted before it wrote one, from its cost_so_far.json."""
        total = 0.0
        for d in list((self.root / "runs").glob("*")) + list((self.root / "attempts").glob("*/*")):
            p = d / "meta.json" if (d / "meta.json").exists() else d / COST_SO_FAR
            if p.exists():
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
            so_far = json.loads((d / COST_SO_FAR).read_text()) if (d / COST_SO_FAR).exists() else {}
            meta = {"id": item.id, "item": asdict(item), "status": "error",
                    "reason": f"runner: {type(exc).__name__}: {self._hide(str(exc))}",
                    "usage": so_far.get("usage") or RR.usage_summary(None), "ended": now()}
            for k in ("build_usage", "build_wall_s", "fix_rounds", "wall_s"):
                if k in so_far:
                    meta[k] = so_far[k]
            (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
            return meta

    def _hide(self, s: str) -> str:
        return s.replace(self.token, "<token>") if self.token else s

    def _new_root(self) -> tuple[Path, Path, Path, Path]:
        """A throwaway run root under config scratch: (root, config dir, HOME, working dir path)."""
        root = Path(tempfile.mkdtemp(prefix="hg-eval-", dir=str(C.expand(self.cfg["scratch"]))))
        cfg_dir, home, work = root / "cfg", root / "home", root / "work"
        for x in (cfg_dir, home, home / "tmp"):
            x.mkdir(parents=True)
        return root, cfg_dir, home, work

    def _call(self, d: Path, run, prompt: str, timeout: int) -> dict:
        """Run one isolated `claude -p`; save prompt.txt, command.txt (token hidden), transcript.jsonl, stderr.txt
        and result.json in d. Output that contains the token is withheld."""
        (d / "prompt.txt").write_text(prompt)
        shown = list(run.argv)
        shown[2] = f"<prompt.txt: {len(prompt)} chars>"
        (d / "command.txt").write_text("\n".join(P.isolate.describe(P.isolate.Run(
            argv=shown, env=run.env, cwd=run.cwd, redact=run.redact))) + f"\ncwd:  {run.cwd}\n")
        t0 = time.monotonic()
        timed_out = False
        try:
            p = subprocess.run(run.argv, env=run.env, cwd=run.cwd, capture_output=True, text=True, timeout=timeout)
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
        (d / "transcript.jsonl").write_text(out)
        (d / "stderr.txt").write_text(err)
        if parsed["result"] is not None:
            (d / "result.json").write_text(json.dumps(parsed["result"], indent=1, sort_keys=True) + "\n")
        return {"out": out, "err": err, "code": code, "timed_out": timed_out, "wall": wall,
                "token_seen": token_seen, "parsed": parsed, "result": parsed["result"]}

    @staticmethod
    def _classify(c: dict, ok: bool) -> tuple[str, str]:
        st, reason = RR.classify(c["code"], c["result"], c["err"], ok, c["timed_out"])
        if c["token_seen"]:
            st, reason = "error", "token in output (output withheld)"
        return st, reason

    def _execute(self, item: P.Item) -> dict:
        d = self.archive.run_dir(item.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "started").write_text(now() + "\n")
        root, cfg_dir, home, work = self._new_root()
        try:
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
            c = self._call(d, run, prompt,
                           self.cfg["timeout_map_s" if item.kind == "map" else "timeout_answer_s"])
            result = c["result"]
            map_obj = answer = None
            if item.kind == "map":
                map_obj, how = M.extract_json(result or {})
                ok = map_obj is not None
            else:
                answer, how = RR.parse_answer(result)
                ok = answer is not None
            st, reason = self._classify(c, ok)
            usage = RR.usage_summary(result)
            init = c["parsed"]["init"] or {}
            meta = {"id": item.id, "item": asdict(item), "status": st, "reason": reason, "exit": c["code"],
                    "wall_s": round(c["wall"], 1), "started": (d / "started").read_text().strip(), "ended": now(),
                    "model_requested": self.cfg["model"], "model_init": init.get("model"),
                    "models_used": usage["models"], "usage": usage, "tool_calls": c["parsed"]["tool_calls"],
                    "tool_names": c["parsed"]["tool_names"], "answer": answer, "answer_read_from": how,
                    "workdir": str(work), "workdir_files": wd["files"], "agent_files_removed": wd["removed"],
                    "prompt_chars": len(prompt), "leak_scan": P.isolate.leak_scan(c["out"] + c["err"])}
            if item.kind == "map":
                self._cost_so_far(d, [usage], [meta["wall_s"]], [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
        if item.kind == "map" and st == "ok":
            self._finish_map(item, d, map_obj, how, meta)
            meta["ended"] = now()
        (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
        return meta

    # -- the eval map: check, fix rounds, save -----------------------------------------------------------
    def _check_map(self, obj: dict, how: str) -> dict:
        v = M.validate_map(self.clone, self.commit, obj)
        v["read_from"] = how
        return v

    @staticmethod
    def _cost_so_far(d: Path, usages: list[dict], walls: list[float], rows: list[dict]) -> None:
        """runs/map-s<k>/cost_so_far.json: the build's and the finished fix rounds' usage, so an interruption or a
        runner-side failure before meta.json keeps what was billed."""
        rec = {"usage": RR.sum_usage(usages), "build_usage": usages[0], "build_wall_s": walls[0],
               "wall_s": round(sum(walls), 1), "fix_rounds": rows, "updated": now()}
        (d / COST_SO_FAR).write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")

    @staticmethod
    def _write_round(d: Path, obj: dict, v: dict) -> None:
        """One round's map.json and validation.json, kept in that round's run folder."""
        (d / "map.json").write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        (d / "validation.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")

    def _finish_map(self, item: P.Item, d: Path, obj: dict, how: str, meta: dict) -> None:
        """The map build returned a map: check it; while it fails the check, run up to map_fix_rounds fix rounds
        (runs/<id>/fix/<n>/), each capped at what is left of caps.map_usd; save the last round's map to
        maps/seed<k>/ (map.md only when it passes). Updates meta: status, usage (build + fixes), fix_rounds."""
        cap, rounds = float(self.cfg["caps"]["map_usd"]), int(self.cfg.get("map_fix_rounds", 0))
        v = self._check_map(obj, how)
        self._write_round(d, obj, v)
        build_usage, build_wall = meta["usage"], meta["wall_s"]
        usages, walls, rows = [build_usage], [build_wall], []
        stop = ""
        n = 0
        while not v["usable"] and n < rounds:
            n += 1
            budget = P.fix_budget(cap, sum(u["cost_usd"] for u in usages))
            if budget <= 0:
                stop = f"no budget left for fix round {n} (caps.map_usd ${cap:g} spent)"
                n -= 1
                break
            errors_in = list(v["blocking_errors"])
            fd = d / "fix" / str(n)
            fd.mkdir(parents=True, exist_ok=True)
            status(f"  map seed {item.map_seed}: {len(errors_in)} validation error(s); fix round {n} of {rounds} "
                   f"(budget ${budget:g})")
            fm = self._fix_round(item, fd, obj, errors_in, n, rounds, budget)
            usages.append(fm["usage"])
            walls.append(fm["wall_s"])
            self._cost_so_far(d, usages, walls, rows)
            row = {"round": n, "errors_in": len(errors_in), "errors_out": None, "cost": fm["usage"]["cost_usd"],
                   "wall_s": fm["wall_s"], "status": fm["status"], "reason": fm["reason"]}
            if fm["status"] == "ok":
                obj, how = fm["map_obj"], fm["read_from"]
                v = self._check_map(obj, how)
                self._write_round(fd, obj, v)
                row["errors_out"] = len(v["blocking_errors"])
            rows.append(row)
            self._cost_so_far(d, usages, walls, rows)
            self.archive.log("map_fix", id=item.id, **row)
            if fm["status"] != "ok":
                stop = f"fix round {n}: {fm['status']}" + (f" ({fm['reason']})" if fm["reason"] else "")
                if fm["status"] == "usage_limit":
                    meta["status"], meta["reason"] = "usage_limit", f"usage limit in map fix round {n}"
                break
        meta["build_usage"], meta["build_wall_s"] = build_usage, build_wall
        meta["usage"] = RR.sum_usage(usages)
        meta["models_used"] = meta["usage"]["models"]
        meta["wall_s"] = round(sum(walls), 1)
        meta["fix_rounds"] = rows
        meta["totals"] = {"cost_usd": meta["usage"]["cost_usd"], "wall_s": meta["wall_s"], "fix_rounds": len(rows),
                          "map_cap_usd": cap}
        meta["map"] = self._save_map(item.map_seed, obj, v)
        meta["map"]["fix_rounds"] = len(rows)
        if meta["status"] == "usage_limit":
            return
        if not v["usable"]:
            why = stop or f"still failing after {len(rows)} fix round(s)"
            meta["status"], meta["reason"] = "invalid_answer", f"map: {v['reason']}; {why}"

    def _fix_round(self, item: P.Item, fd: Path, prev: dict, errors: list[str], n: int, rounds: int,
                   budget: float) -> dict:
        """One fix round, isolated like the build (fresh root and repo copy, same model, effort, tools and map
        schema); the previous map is root/prev/map.json, outside the working dir, reached with --add-dir."""
        (fd / "started").write_text(now() + "\n")
        root, cfg_dir, home, work = self._new_root()
        try:
            wd = W.make_repo_workdir(self.clone, self.commit, self.remove, work)
            (root / "prev").mkdir()
            prev_file = root / "prev" / "map.json"
            text = json.dumps(prev, indent=1, sort_keys=True) + "\n"
            prev_file.write_text(text)
            prompt = P.map_fix_prompt(work, prev_file, text.count("\n"), errors, n, rounds)
            spec = P.fix_run_spec(self.cfg, prompt=prompt, workdir=work, map_file=prev_file, budget=budget,
                                  config_dir=cfg_dir, home_dir=home, claude_bin=self.claude_bin)
            run = P.build_command(self.cfg, item, spec, P.child_env_source(self.token, self.parent_env), budget=budget)
            c = self._call(fd, run, prompt, self.cfg["timeout_map_s"])
        finally:
            shutil.rmtree(root, ignore_errors=True)
        obj, how = M.extract_json(c["result"] or {})
        st, reason = self._classify(c, obj is not None)
        usage = RR.usage_summary(c["result"])
        init = c["parsed"]["init"] or {}
        fm = {"id": item.id, "fix_round": n, "status": st, "reason": reason, "exit": c["code"],
              "wall_s": round(c["wall"], 1), "started": (fd / "started").read_text().strip(), "ended": now(),
              "budget_usd": budget, "errors_in": errors, "model_requested": self.cfg["model"],
              "model_init": init.get("model"), "models_used": usage["models"], "usage": usage,
              "tool_calls": c["parsed"]["tool_calls"], "tool_names": c["parsed"]["tool_names"],
              "map_read_from": how, "workdir_files": wd["files"], "agent_files_removed": wd["removed"],
              "prompt_chars": len(prompt), "previous_map_chars": len(text),
              "leak_scan": P.isolate.leak_scan(c["out"] + c["err"])}
        (fd / "meta.json").write_text(json.dumps(fm, indent=1, sort_keys=True) + "\n")
        return fm | {"map_obj": obj, "read_from": how}

    def _save_map(self, seed: int, obj: dict, v: dict) -> dict:
        """maps/seed<k>/: the final round's map.json and validation.json; map.md (what map runs read) only when the
        map passes the check."""
        md = self.archive.map_dir(seed)
        md.mkdir(parents=True, exist_ok=True)
        (md / "map.json").write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        v = dict(v)
        if v["usable"]:
            resolved, _ = M.resolve_anchors(M.Repo.open(self.clone), self.commit, obj.get("claims"))
            text = M.render_map(obj, resolved)
            (md / "map.md").write_text(text)
            v["chars"], v["tokens_est"] = len(text), OB.est_tokens(text)
        elif (md / "map.md").exists():
            (md / "map.md").unlink()     # an earlier attempt's text must not be read by map runs
        (md / "validation.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n")
        status(f"  map seed {seed}: {v.get('claims', 0)} claims, anchors {v['anchors_resolved']}/"
               f"{v['anchors_total']} resolved, draft valid {v['draft_valid']}, "
               f"{len(v.get('blocking_errors', []))} blocking error(s), {'usable' if v['usable'] else 'NOT usable'}, "
               f"{v.get('tokens_est', 0)} tokens (est.)")
        return {k: v[k] for k in ("usable", "anchors_total", "anchors_resolved", "draft_valid")} | {
            "reason": v.get("reason", ""), "tokens_est": v.get("tokens_est", 0),
            "blocking_errors": len(v.get("blocking_errors", []))}

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
        for s in range(1, self.seeds + 1):
            m = metas.get(f"map-s{s}") or {}
            if m.get("status") == "invalid_answer":
                print(f"map seed {s}: not usable after {len(m.get('fix_rounds', []))} fix round(s): "
                      f"{m.get('reason', '')} (maps/seed{s}/validation.json)")
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
    mb = est["map_build"]
    if n["map builds"]:
        print(f"map fix    up to {mb['fix_rounds']} fix round(s) per build when the map fails the check; build + "
              f"fixes capped at ${cfg['caps']['map_usd']:g} together; per map ${mb['usd'][0]:g}-${mb['usd'][1]:g}, "
              f"{mb['min'][0]:g}-{mb['min'][1]:g} min (build alone .. build + every fix round)")
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
        if it.kind == "map" and cfg.get("map_fix_rounds", 0):
            prev = root / "prev" / "map.json"
            fspec = P.fix_run_spec(cfg, prompt="", workdir=root / "work", map_file=prev,
                                   budget=cfg["caps"]["map_usd"], config_dir=root / "cfg", home_dir=root / "home",
                                   claude_bin=claude_bin)
            frun = P.build_command(cfg, it, fspec, env_src, budget=cfg["caps"]["map_usd"])
            frun.argv[2] = "<prompt: fix head + the blocking errors + Cartographer brief>"
            print(f"  fix round n (only if the map fails the check; --max-budget-usd is what is left of "
                  f"${cfg['caps']['map_usd']:g}; a fresh RUN_ROOT):")
            print("  " + P.isolate.describe(frun)[0])
    for cond, prompt in examples.items():
        print(f"--- example prompt ({cond}) ---")
        print(prompt.rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Honeyguide's four-way eval.")
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
