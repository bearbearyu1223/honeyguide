"""Score a Honeyguide eval run archive and print the capture the post quotes (outputs/eval_<repo>.txt).

    uv run python eval/score/evalscore.py --run-id pilot-nanochat > outputs/eval_nanochat.txt
    uv run python eval/score/evalscore.py --run-id pilot-nanochat --grading-sheet   # why/how blind sheet

Reads the run archive (see eval/run/evalrun.py) and never writes to it, except --grading-sheet, which writes
<archive>/<run-id>/grading/{sheet.md, sheet.json, blind_key.json, grades.json (a template, never overwritten)}.
The why/how grades are read back from grading/grades.json (or --grades FILE); its "grader" and "how" are printed.

Deterministic: every number comes from the saved runs, the frozen questions, Han's answers and grades; the
bootstrap is seeded. Re-scoring the same archive prints the same bytes. Rules: scoring.py (per type), the
module docstring of pairstats.py (analysis). Runs that errored, were capped or gave no valid answer count as wrong
(score 0) and are listed per cell; runs not run yet (pending, blocked, stopped by the usage limit) are left out.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "eval" / "run", ROOT / "eval" / "questions"):
    sys.path.insert(0, str(p))
try:
    import honeyguide  # noqa: F401
except ImportError:   # run outside the uv environment
    sys.path.insert(0, str(ROOT / "src"))
import evalcfg as C  # noqa: E402
import grading as G  # noqa: E402
import keys as K  # noqa: E402
import pairstats as S  # noqa: E402
import runresult as RR  # noqa: E402
import scoring as SC  # noqa: E402
from evalrun import scope_sources  # noqa: E402
from repo import REPOS, in_scope  # noqa: E402

WIDTH = 74
CONDS = C.CONDITIONS
PAIRS = (("map", "explore"), ("map", "outline"), ("explore", "no-access"))
FAILED = ("error", "capped", "invalid_answer")


# ------------------------------------------------------------------------------------------------------------
# Loading

def load_archive(root: Path) -> dict:
    plan = json.loads((root / "plan.json").read_text())
    metas = {}
    for p in sorted((root / "runs").glob("*/meta.json")):
        m = json.loads(p.read_text())
        metas[m["id"]] = m
    attempts = {}
    for p in sorted((root / "attempts").glob("*/*/meta.json")):
        attempts.setdefault(p.parent.parent.name, []).append(json.loads(p.read_text()))
    events = []
    if (root / "log.jsonl").exists():
        events = [json.loads(ln) for ln in (root / "log.jsonl").read_text().splitlines() if ln.strip()]
    maps = {}
    for p in sorted((root / "maps").glob("seed*/validation.json")):
        maps[int(p.parent.name[4:])] = json.loads(p.read_text())
    outline = None
    if (root / "outline" / "outline.json").exists():
        outline = json.loads((root / "outline" / "outline.json").read_text())
    return {"root": root, "plan": plan, "metas": metas, "attempts": attempts, "events": events, "maps": maps,
            "outline": outline}


def class_index(source: str, path: str) -> list[SC.Fn]:
    """Every class (qualname, line range): a class body can be a key caller (a field default), named by its
    class (the key's also_accept)."""
    import ast
    out: list[SC.Fn] = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                q = prefix + child.name
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                out.append(SC.Fn(path, q, start, child.end_lineno or child.lineno))
                visit(child, q + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, prefix + child.name + ".<locals>.")
    try:
        visit(ast.parse(source), "")
    except SyntaxError:
        return []
    return out


class RepoFacts:
    """The repo's functions, call graph and trace, at the pinned commit, for resolving and classifying items."""

    def __init__(self, cfg: dict, repo: str, commit: str, frozen: dict):
        rc = cfg["repos"][repo]
        clone = C.expand(rc["clone"])
        self.code_dirs = tuple(rc.get("code_dirs", [])) or None
        sources = scope_sources(clone, commit, list(rc.get("code_dirs", [])))
        self.funcs: dict[str, list[SC.Fn]] = {}
        for path, src in sources.items():
            try:
                fs = K.function_index(src, path)
            except SyntaxError:
                continue
            self.funcs[path] = [SC.Fn(f.file, f.qual, f.start, f.end) for f in fs] + class_index(src, path)
        roots = REPOS.get(repo, {}).get("package_roots", ("",))
        mods = []
        for path, src in sources.items():
            try:
                mods.append(K.module_info(src, path, roots))
            except SyntaxError:
                continue
        edges, _ = K.call_graph(K.Project(mods))
        self.adj: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for e in edges:
            self.adj.setdefault((e.caller_file, e.caller), set()).add((e.callee_file, e.callee))
        trace_path = C.expand(rc["trace"])
        self.events = json.loads(trace_path.read_text())["events"] if trace_path.exists() else []

    def in_scope(self, path: str) -> bool:
        return in_scope(path, self.code_dirs)

    def trace_pairs(self, phase: str) -> set[tuple[str, str]]:
        return {(e["file"], e["qual"]) for e in self.events if e.get("phase") == phase and e.get("kind") == "call"}

    def reachable(self, starts: list[tuple[str, str]]) -> set[tuple[str, str]]:
        seen = set(starts)
        todo = list(starts)
        while todo:
            for nxt in self.adj.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen


def human_answers(cfg: dict, repo: str) -> dict:
    d = C.expand(cfg.get("answers_dir", "eval/human/answers"))

    def read(name):
        p = d / f"{name}_{repo}.json"
        return json.loads(p.read_text()) if p.exists() else {}
    return {"disputes": read("disputes"), "hops": read("hops"), "whyhow": read("whyhow")}


def hop_marks(q: dict, hops_doc: dict) -> tuple[list[str | None], list[str]]:
    """Han's mark per frozen candidate hop, carried over only onto the same hop (index, file, function, line)."""
    saved = {h.get("index"): h for h in (hops_doc.get("questions", {}).get(q["id"], {}).get("hops", []))}
    marks, problems = [], []
    for i, h in enumerate(q["key"]["candidate_hops"]):
        s = saved.get(i)
        if s and (s.get("file"), s.get("qual"), s.get("line")) == (h["file"], h["qual"], h["lines"][0]):
            marks.append(s.get("mark"))
        else:
            marks.append(None)
            problems.append(f"{q['id']} hop {i}: no mark")
    return marks, problems


def dispute_decisions(q: dict, disputes_doc: dict) -> tuple[list[dict], list[str]]:
    saved = {d.get("index"): d for d in disputes_doc.get("questions", {}).get(q["id"], {}).get("disputes", [])}
    out, problems = [], []
    for i, d in enumerate(q.get("disputes_for_han", [])):
        s = saved.get(i)
        if s and (s.get("file"), s.get("caller"), s.get("lines")) == (d["file"], d["caller"], d["lines"]):
            out.append({"decision": s.get("decision")})
        else:
            out.append({"decision": None})
            problems.append(f"{q['id']} dispute {i}: undecided")
    return out, problems


# ------------------------------------------------------------------------------------------------------------
# Scoring

def leakage(q: dict, decisions: list[dict]) -> list[str]:
    """Key names that appear verbatim in the question (keys.leaks: whole identifiers, case-insensitive), by the
    generator's own rule (eval/questions/generate.py). locate and flow: the leaks frozen with the question (the
    key function, its class and file; every candidate hop's function name except the entry calls, which the
    question names on purpose). callers: recomputed with the generator's rule over the key callers plus the
    disputed sites Han decided are callers (their names and classes and files, minus the target, named on
    purpose)."""
    if q["type"] in ("locate", "flow"):
        return list(q.get("leaks", []))
    if q["type"] != "callers":
        return []
    pos, _ = SC.callers_key(q, decisions)
    quals = {qual for p in pos for qual in p["quals"]}
    named = set(q["target"]["qual"].replace(".<locals>.", ".").split("."))
    syms = sorted(({x.split(".")[-1] for x in quals} | {x.split(".")[0] for x in quals if "." in x})
                  - {"<module>"} - named)
    files = sorted({p["file"] for p in pos} - {q["target"]["file"]})
    return K.leaks(q["text"], syms, files)


def score_runs(arch: dict, frozen: dict, facts: RepoFacts, human: dict, grades: dict[str, float]) -> dict:
    """{run id: {"score": float or None, "detail": dict, "status": str}} for every finished answering run."""
    byid = {q["id"]: q for q in frozen["questions"]}
    out = {}
    cache: dict[str, tuple] = {}
    for rid, m in arch["metas"].items():
        it = m["item"]
        if it["kind"] != "answer" or m["status"] not in RR.FINAL:
            continue
        if m["status"] in FAILED:
            out[rid] = {"score": 0.0, "status": m["status"], "detail": {"reason": m.get("reason", "")}}
            continue
        ans, wd = m["answer"] or {"items": [], "text": ""}, m.get("workdir", "")
        if it["qtype"] == "whyhow":
            out[rid] = {"score": grades.get(rid), "status": "ok", "detail": {}}
            continue
        q = byid[it["qid"]]
        if q["type"] == "locate":
            d = SC.score_locate(ans, q["key"], facts.funcs, wd)
        elif q["type"] == "callers":
            dec, _ = dispute_decisions(q, human["disputes"])
            d = SC.score_callers(ans, q, dec, facts.funcs, facts.in_scope, wd)
        else:
            if q["id"] not in cache:
                marks, _ = hop_marks(q, human["hops"])
                hops = q["key"]["candidate_hops"]
                entries = []
                for e in q.get("entries", []):
                    f = next((h["file"] for h in hops if h["qual"] == e["qual"]), None)
                    if f:
                        entries.append((f, e["qual"]))
                cache[q["id"]] = (marks, facts.trace_pairs(q["trace_phase"]), facts.reachable(entries))
            marks, tp, reach = cache[q["id"]]
            d = SC.score_flow(ans, q["key"]["candidate_hops"], marks, facts.funcs, tp, reach, wd)
        out[rid] = {"score": d["score"], "status": "ok", "detail": d}
    return out


# ------------------------------------------------------------------------------------------------------------
# Printing

def rule(title: str) -> list[str]:
    return ["", title, "-" * WIDTH]


def wrap(text: str, indent: int = 2, sub: int = 4) -> list[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=" " * indent, subsequent_indent=" " * sub) or [""]


def f3(x: float | None) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def sgn(x: float) -> str:
    return "-" if math.isnan(x) else f"{x:+.3f}"


def money(x: float) -> str:
    return f"${x:,.2f}"


def build_label(meta: dict) -> str:
    """What a map run's usage and wall_s cover: "build", or "build + N fix round(s)" when fix rounds ran."""
    n = len(meta.get("fix_rounds") or [])
    return f"build + {n} fix round{'s' if n != 1 else ''}" if n else "build"


def grader_label(doc: dict | None) -> tuple[str, str]:
    """(who graded, how) from grades.json's "grader" and "how"; "not recorded" when the file names no grader."""
    doc = doc or {}
    return (str(doc.get("grader") or "").strip() or "not recorded", str(doc.get("how") or "").strip())


def capture(cfg: dict, arch: dict, frozen: dict, human: dict, facts: RepoFacts, grades: dict[str, float],
            grade_problems: list[str], grader: tuple[str, str] = ("not recorded", "")) -> str:
    plan, metas = arch["plan"], arch["metas"]
    seed = int(plan["config"].get("seed", 0))
    qs = plan["questions"]
    qtype = {q["id"]: q["type"] for q in qs}
    items = plan["items"]
    scores = score_runs(arch, frozen, facts, human, grades)
    L: list[str] = [f"Honeyguide eval: {plan['repo']} (run {plan['run_id']})", "=" * WIDTH]

    # --- header
    types = {t: sum(1 for q in qs if q["type"] == t) for t in C.TYPES}
    subs = {s: sum(1 for q in qs if q["subset"] == s) for s in ("before", "after", "none")}
    L += [f"  commit      {plan['commit'][:12]} ({frozen['url']})",
          f"  frozen set  MANIFEST.txt sha256 {plan['manifest_sha256'][:12]}; cutoff {frozen.get('cutoff', '')}",
          f"  size        {plan['size']}: {len(qs)} questions (locate {types['locate']}, callers "
          f"{types['callers']}, flow {types['flow']},",
          f"              why/how {types['whyhow']}); before cutoff {subs['before']}, after {subs['after']}, "
          f"untagged {subs['none']}",
          f"  model       requested {plan['config']['model']}, effort {plan['config']['effort']}"]
    used: dict[str, int] = {}
    for m in metas.values():
        key = "+".join(m.get("models_used") or []) or "(no result)"
        used[key] = used.get(key, 0) + 1
    L += wrap("used: " + ", ".join(f"{k} x{v}" for k, v in sorted(used.items())), 14, 14)
    by: dict[str, int] = {}
    for it in items:
        st = (metas.get(it["id"]) or {}).get("status", "not run")
        st = st if st in RR.FINAL else "not run"
        by[st] = by.get(st, 0) + 1
    retried = sum(1 for e in arch["events"] if e["event"] == "retry_failed")
    restarted = sum(1 for e in arch["events"] if e["event"] in ("restart_after_interruption",
                                                                 "resume_after_usage_limit"))
    fin = sum(v for k, v in by.items() if k in RR.FINAL)
    L += wrap(f"runs        {len(items)} planned ({plan['counts']['map builds']} map builds); finished {fin} ("
              + ", ".join(f"{k.replace('_', ' ')} {by.get(k, 0)}" for k in RR.FINAL)
              + f"); not run {by.get('not run', 0)}; re-run after a failure {retried}; re-run after an "
              f"interruption or usage limit {restarted}", 2, 14)

    # --- setup
    L += rule("setup: maps, outline, leakage")
    for s in sorted(arch["maps"]):
        v = arch["maps"][s]
        mm = metas.get(f"map-s{s}") or {}
        u = mm.get("usage") or RR.usage_summary(None)
        t = u["tokens"]
        L += [f"  map seed {s}  {v.get('claims', 0)} claims; anchors {v['anchors_resolved']}/{v['anchors_total']}"
              f" resolved",
              f"              draft valid {'yes' if v['draft_valid'] else 'no'}"
              f" ({len(v.get('draft_errors', []))} errors)",
              f"              {v.get('tokens_est', 0):,} tokens (est., chars/4) as given to map runs"]
        L += wrap(f"{build_label(mm)} {mm.get('wall_s', 0) / 60:.1f} min, {money(u['cost_usd'])} list; tokens in "
                  f"{t['input_tokens']:,}", 14, 14)
        L += [f"              cache read {t['cache_read_input_tokens']:,}, cache write "
              f"{t['cache_creation_input_tokens']:,}, out {t['output_tokens']:,}"]
        if mm.get("fix_rounds"):
            b = mm.get("build_usage") or RR.usage_summary(None)
            L.append(f"              build alone {mm.get('build_wall_s', 0) / 60:.1f} min, "
                     f"{money(b['cost_usd'])} list")
        ev = ", ".join(f"{k} {n}" for k, n in sorted(v.get("evidence", {}).items(), key=lambda kv: -kv[1]))
        if ev:
            L += wrap("evidence: " + ev, 14, 14)
        for p in v.get("unresolved", [])[:5]:
            L += wrap(f"unresolved: {p['claim']} {p['path']} ({p['status']})", 14, 16)
        if len(v.get("unresolved", [])) > 5:
            L.append(f"              ... {len(v['unresolved']) - 5} more unresolved (validation.json)")
    for it in items:
        if it["kind"] == "map" and it["map_seed"] not in arch["maps"]:
            st = (metas.get(it["id"]) or {}).get("status", "not run")
            L.append(f"  map seed {it['map_seed']}  not built ({st})")
    o = arch["outline"]
    if o:
        L += [f"  outline     {o['tokens_est']:,} tokens (est.) vs target {o['target_tokens']:,} (mean of the maps)"]
        L += wrap(o["summary"], 14, 14)
    else:
        L.append("  outline     not built")
    leak_rows = {}
    for q in frozen["questions"]:
        if q["id"] not in qtype:
            continue
        dec, _ = dispute_decisions(q, human["disputes"]) if q["type"] == "callers" else ([], [])
        hit = leakage(q, dec)
        leak_rows.setdefault(q["type"], []).append((q["id"], hit))
    parts = [f"{t} {sum(1 for _, h in leak_rows.get(t, []) if h)} of {len(leak_rows.get(t, []))}"
             for t in ("locate", "callers", "flow")]
    L += wrap("leakage (key names verbatim in the question): " + ", ".join(parts)
              + "; why/how not checked (rubric answers)", 2, 14)
    for t in ("locate", "callers", "flow"):
        for qid, h in leak_rows.get(t, []):
            if h:
                L += wrap(f"{qid}: {', '.join(h)}", 14, 16)

    # --- scores
    run_scores: dict[tuple[str, str], list[float]] = {}
    awaiting: set[str] = set()
    for it in items:
        if it["kind"] != "answer" or it["id"] not in scores:
            continue
        sc = scores[it["id"]]["score"]
        if sc is None:
            awaiting.add(it["qid"])
            continue
        run_scores.setdefault((it["qid"], it["condition"]), []).append(sc)
    run_scores = {k: v for k, v in run_scores.items() if k[0] not in awaiting}
    qmeans = S.question_scores(run_scores)
    L += rule("scores by condition (per run; score in [0, 1]; failed runs = 0)")
    L.append(f"  {'condition':<11}{'runs':>6}{'scored':>8}{'mean':>8}{'exact':>7}{'capped':>8}{'error':>7}"
             f"{'invalid':>9}")
    for c in CONDS:
        rs = [it for it in items if it["kind"] == "answer" and it["condition"] == c]
        sc = [scores[it["id"]]["score"] for it in rs if it["id"] in scores and it["qid"] not in awaiting
              and scores[it["id"]]["score"] is not None]
        st = [scores[it["id"]]["status"] for it in rs if it["id"] in scores]
        L.append(f"  {c:<11}{len(rs):>6}{len(sc):>8}{f3(S.mean(sc)):>8}{sum(1 for x in sc if x >= 1.0):>7}"
                 f"{st.count('capped'):>8}{st.count('error'):>7}{st.count('invalid_answer'):>9}")
    L += wrap("scores: locate 1/0 (first item, function level); callers F1; flow required hops in order (LCS / "
              f"required); why/how a blind grade by {grader[0]}. exact = runs scoring 1.", 2, 2)

    L += rule("by type (descriptive; mean per run)")
    L.append(f"  {'type':<9}{'questions':>10}" + "".join(f"{c:>12}" for c in CONDS))
    for t in C.TYPES:
        n_q = sum(1 for q in qs if q["type"] == t)
        cells = []
        for c in CONDS:
            xs = [x for (qid, cc), v in run_scores.items() if cc == c and qtype[qid] == t for x in v]
            cells.append(f"{f3(S.mean(xs)) if xs else '-':>12}")
        L.append(f"  {t:<9}{n_q:>10}" + "".join(cells))
    flow = [scores[i]["detail"] for i in scores if scores[i]["status"] == "ok" and qtype.get(
        next((it["qid"] for it in items if it["id"] == i), ""), "") == "flow"]
    if flow:
        L += wrap(f"flow items not in the key (all conditions): in the trace but pre-filtered "
                  f"{sum(d['trace'] for d in flow)}, other path {sum(d['other path'] for d in flow)}, invented "
                  f"{sum(d['invented'] for d in flow)}", 2, 4)
    cal = [scores[i]["detail"] for i in scores if scores[i]["status"] == "ok" and qtype.get(
        next((it["qid"] for it in items if it["id"] == i), ""), "") == "callers"]
    if cal:
        L += wrap(f"callers: answered sites Han decided are not callers {sum(d['fp_decided_not'] for d in cal)}; "
                  f"items outside the key scope ignored {sum(d['ignored_out_of_scope'] for d in cal)}", 2, 4)

    B = S.B_DEFAULT
    L += rule("paired differences by question")
    L += wrap(f"per question: mean over its passes; then the mean difference over questions with both conditions, "
              f"95% CI from {B} bootstrap resamples of questions (seed {seed})", 2, 2)
    for a, b in PAIRS:
        d = S.paired(qmeans, a, b)
        lo, hi = S.bootstrap_ci(d, B, seed)
        L.append(f"  {a + ' - ' + b:<22}{sgn(S.mean(d)):>8}  [{sgn(lo)}, {sgn(hi)}]  n={len(d)}")

    L += rule("learning vs remembering: mean score by cutoff subset")
    L.append(f"  {'subset':<9}{'questions':>10}" + "".join(f"{c:>12}" for c in CONDS))
    for sname in ("before", "after"):
        ids = [q["id"] for q in qs if q["subset"] == sname and q["id"] in qmeans]
        cells = "".join(f"{f3(S.mean([qmeans[i][c] for i in ids if c in qmeans[i]])) if ids else '-':>12}"
                        for c in CONDS)
        L.append(f"  {sname:<9}{sum(1 for q in qs if q['subset'] == sname):>10}{cells}")
    for a, b in (("map", "explore"), ("explore", "no-access")):
        for sname in ("before", "after"):
            d = S.paired(qmeans, a, b, [q["id"] for q in qs if q["subset"] == sname])
            lo, hi = S.bootstrap_ci(d, B, seed)
            L.append(f"  {a + ' - ' + b + ', ' + sname:<30}{sgn(S.mean(d)):>8}  [{sgn(lo)}, {sgn(hi)}]  n={len(d)}")
    L += wrap("why/how questions carry no cutoff tag and are in neither subset.", 2, 2)

    # --- cost
    prices = plan["config"]["prices"][plan["config"]["model"]]
    L += rule("tokens (thousands), time and cost per answering run (means)")
    L.append(f"  {'condition':<10}{'input':>7}{'cache rd':>9}{'cache wr':>9}{'output':>8}{'tools':>6}"
             f"{'min':>5}{'$ list':>8}{'$ nocache':>10}")
    per_cond = {}
    for c in CONDS:
        ms = [metas[it["id"]] for it in items if it["kind"] == "answer" and it["condition"] == c
              and (metas.get(it["id"]) or {}).get("status") in RR.FINAL]
        if not ms:
            L.append(f"  {c:<10}" + "-".rjust(7))
            continue
        tok = {k: S.mean([m["usage"]["tokens"][k] for m in ms]) for k in RR.TOKEN_FIELDS}
        cost = [m["usage"]["cost_usd"] for m in ms]
        nocache = [RR.notional_cost(m["usage"], prices)["without_cache"] for m in ms]
        per_cond[c] = {"runs": len(ms), "cost": sum(cost), "mean_cost": S.mean(cost), "mean_nocache": S.mean(nocache)}
        k = {f: tok[f] / 1000 for f in RR.TOKEN_FIELDS}
        L.append(f"  {c:<10}{k['input_tokens']:>7.1f}{k['cache_read_input_tokens']:>9.1f}"
                 f"{k['cache_creation_input_tokens']:>9.1f}{k['output_tokens']:>8.1f}"
                 f"{S.mean([m.get('tool_calls', 0) for m in ms]):>6.1f}"
                 f"{S.mean([m.get('wall_s', 0) for m in ms]) / 60:>5.1f}{S.mean(cost):>8.3f}{S.mean(nocache):>10.3f}")
    rebuilt = [(RR.notional_cost(m["usage"], prices)["rebuilt_with_cache"], m["usage"]["cost_usd"])
               for m in metas.values() if m["usage"]["cost_usd"]]
    if rebuilt:
        worst = max(abs(r - c) / c for r, c in rebuilt)
        L += wrap(f"price check: list cost rebuilt from tokens with the config prices is within "
                  f"{worst * 100:.1f}% of the CLI's total_cost_usd on every run ({len(rebuilt)} runs)", 2, 4)
    exact = {c: sum(1 for it in items if it["kind"] == "answer" and it["condition"] == c and it["qid"] not in awaiting
                    and it["id"] in scores and (scores[it["id"]]["score"] or 0) >= 1.0) for c in CONDS}
    L.append("  cost per exact answer (list, with cache):")
    cpc = {}
    for c in CONDS:
        if c in per_cond and exact[c]:
            cpc[c] = per_cond[c]["cost"] / exact[c]
            L.append(f"    {c:<11}{money(cpc[c]):>10}  ({exact[c]} exact of {per_cond[c]['runs']} runs)")
        else:
            L.append(f"    {c:<11}{'-':>10}  ({exact.get(c, 0)} exact)")
    builds = [metas[f"map-s{s}"]["usage"]["cost_usd"] for s in sorted(arch["maps"]) if f"map-s{s}" in metas]
    if builds and "map" in cpc:
        build = S.mean(builds)
        acc = exact["map"] / per_cond["map"]["runs"]
        L.append(f"  map build: {money(build)} list per map (mean of {len(builds)})")
        for other in ("explore", "outline"):
            if other in cpc:
                n = S.break_even(build, cpc["map"], cpc[other], acc)
                L += wrap(f"break-even vs {other}: " + ("never (map answers are not cheaper per exact answer)"
                                                        if n is None else f"{n:.0f} questions asked"), 4, 6)

    # --- failures
    L += rule("failed runs by cell (each counts as wrong)")
    any_failed = False
    for c in CONDS:
        for t in C.TYPES:
            bad = [(it["id"], scores[it["id"]]) for it in items if it["kind"] == "answer" and it["condition"] == c
                   and it["qtype"] == t and it["id"] in scores and scores[it["id"]]["status"] in FAILED]
            if bad:
                any_failed = True
                L.append(f"  {c} / {t}: {len(bad)}")
                for rid, s in bad:
                    L += wrap(f"{rid} {s['status']}" + (f" ({s['detail'].get('reason')})"
                                                        if s["detail"].get("reason") else ""), 4, 6)
    for it in items:
        if it["kind"] == "map" and (metas.get(it["id"]) or {}).get("status") in FAILED:
            any_failed = True
            m = metas[it["id"]]
            L += wrap(f"{it['id']} (map build) {m['status']} ({m.get('reason', '')})", 2, 4)
    if not any_failed:
        L.append("  none")

    # --- why/how and transcripts
    L += rule("why/how (graded blind)")
    L += wrap(f"grader: {grader[0]}" + (f"; {grader[1]}" if grader[1] else ""), 2, 4)
    wh = [it for it in items if it["kind"] == "answer" and it["qtype"] == "whyhow" and it["id"] in scores
          and scores[it["id"]]["status"] == "ok"]
    graded = sum(1 for it in wh if scores[it["id"]]["score"] is not None)
    L += wrap(f"graded {graded} of {len(wh)} finished answers; questions awaiting grades (left out of every score "
              f"above): {len(awaiting)}", 2, 4)
    for p in grade_problems:
        L += wrap("grades: " + p, 2, 4)
    hits: dict[str, int] = {}
    for m in metas.values():
        for k, n in (m.get("leak_scan") or {}).items():
            hits[k] = hits.get(k, 0) + n
    L += rule("transcripts")
    L += wrap("leak scan (isolate.py's strings, case-sensitive) over every saved transcript: "
              + (", ".join(f"{k} {v}" for k, v in sorted(hits.items())) if hits else "clean"), 2, 4)
    text = "\n".join(line.rstrip() for line in L) + "\n"
    too_wide = [ln for ln in text.splitlines() if len(ln) > WIDTH]
    if too_wide:
        raise AssertionError(f"capture line over {WIDTH} columns: {too_wide[0]!r}")
    return text


# ------------------------------------------------------------------------------------------------------------

def grading_files(arch: dict, human: dict) -> dict:
    policy, scale = G.policy_of(human["whyhow"])
    questions = [q for q in human["whyhow"].get("questions", [])
                 if q["id"] in {x["id"] for x in arch["plan"]["questions"]}]
    answers = [{"run_id": rid, "qid": m["item"]["qid"], "answer": m["answer"]} for rid, m in arch["metas"].items()
               if m["item"]["kind"] == "answer" and m["item"]["qtype"] == "whyhow" and m["status"] == "ok"]
    sheet, key = G.build_sheet(questions, answers, int(arch["plan"]["config"].get("seed", 0)), policy, scale)
    return {"sheet": sheet, "key": key, "scale": scale}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score a Honeyguide eval run archive; print the capture.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config", type=Path, default=C.CONFIG)
    ap.add_argument("--archive", type=Path, help="default: config archive")
    ap.add_argument("--grades", type=Path, help="default: <run>/grading/grades.json when it exists")
    ap.add_argument("--grading-sheet", action="store_true", help="write the why/how blind grading sheet")
    a = ap.parse_args(argv)
    cfg = C.load_config(a.config)
    root = (a.archive or C.expand(cfg["archive"])) / a.run_id
    arch = load_archive(root)
    repo = arch["plan"]["repo"]
    frozen = json.loads(C.expand(cfg["repos"][repo]["questions"]).read_text())
    human = human_answers(cfg, repo)
    g = grading_files(arch, human)
    gdir = root / "grading"
    if a.grading_sheet:
        gdir.mkdir(exist_ok=True)
        (gdir / "sheet.json").write_text(json.dumps(g["sheet"], indent=1, ensure_ascii=False) + "\n")
        (gdir / "sheet.md").write_text(G.sheet_markdown(g["sheet"]))
        (gdir / "blind_key.json").write_text(json.dumps(g["key"], indent=1, sort_keys=True) + "\n")
        if not (gdir / "grades.json").exists():
            (gdir / "grades.json").write_text(json.dumps(G.grades_template(g["key"]), indent=1) + "\n")
        print(f"grading sheet: {len(g['key'])} answers to grade; files in {gdir} "
              "(open sheet.md, not blind_key.json; fill grades.json)", file=sys.stderr)
        return 0
    grades, problems = {}, []
    grader = grader_label(None)
    gpath = a.grades or gdir / "grades.json"
    if gpath.exists():
        key = json.loads((gdir / "blind_key.json").read_text()) if (gdir / "blind_key.json").exists() else g["key"]
        gdoc = json.loads(gpath.read_text())
        grades, problems = G.read_grades(gdoc, key, g["scale"])
        grader = grader_label(gdoc)
    facts = RepoFacts(cfg, repo, arch["plan"]["commit"], frozen)
    sys.stdout.write(capture(cfg, arch, frozen, human, facts, grades, problems, grader=grader))
    return 0


if __name__ == "__main__":
    sys.exit(main())
