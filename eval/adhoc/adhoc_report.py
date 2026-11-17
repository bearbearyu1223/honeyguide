"""E1's capture (outputs/adhoc_check.txt, 74 columns) and Han's spot-check sheet, from the checks' archives.

Reads <archive>/<run-id>-adhoc/ (the answers arm), -adhoc-map/ (the control) and -adhoc-repeat/ (the repeat),
written by adhoc.py, and never writes to them, except --spot-check, which writes spot_check.md into the answers
archive (the same samples as the capture, with full GitHub links, which don't fit 74 columns).
Deterministic: every number comes from the saved checks, the pinned commit (the evidence pass) and outputs/runs.txt
(the map Checker numbers, parsed, never typed); the spot-check samples and the bootstrap are seeded (plan seed).
"""

from __future__ import annotations

import json
import random
import re
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "eval" / "score"))
import adhoc as A  # noqa: E402
import pairstats as PS  # noqa: E402

WIDTH = 74
SAMPLE = 20
MAP_SAMPLE = 10
TEXT_MAX, NOTE_MAX = 160, 200
TYPE_LABEL = {"flow": "flow", "whyhow": "why/how", "locate": "locate", "callers": "callers", "map": "map"}
CLAIMS = ("supported", "not_supported", "wrong")
RULE = "Compute, don't quote"


def wrap(text: str, indent: int = 2, sub: int | None = None) -> list[str]:
    sub = indent + 2 if sub is None else sub
    return textwrap.wrap(text, WIDTH, initial_indent=" " * indent, subsequent_indent=" " * sub,
                         break_on_hyphens=False) or [""]


def rule(title: str) -> list[str]:
    return ["", title, "-" * WIDTH]


def trunc(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def share(k: int, n: int) -> str:
    return f"{k / n:.3f}" if n else "-"


# ------------------------------------------------------------------------------------------------------------
# Loading (one function: every section reads the same rows)

def _cost_file(d: Path) -> dict | None:
    for name in ("meta.json", A.ER.COST_SO_FAR):
        if (d / name).exists():
            return json.loads((d / name).read_text())
    return None


def load(archive) -> dict:
    """plan, metas, attempts (each attempt's meta.json, or its cost_so_far.json when it was killed before one),
    and one row per unit of a check that returned verdicts (ok, or partial: its missing units have verdict None):
    {unit, answer, qid, qtype, label, text, verdict, note, evidence}. Units of other checks count as not checked."""
    plan = json.loads((archive.root / "plan.json").read_text())
    metas = {i["id"]: archive.meta(i["id"]) for i in plan["items"]}
    attempts = []
    for d in sorted((archive.root / "attempts").glob("*/*")):
        x = _cost_file(d)
        if x:
            attempts.append(x)
    rows, not_checked = [], 0
    for it in plan["items"]:
        m = metas.get(it["id"])
        if not m or m.get("status") not in A.OK_LIKE:
            not_checked += len(it["units"])
            continue
        v = {r["unit"]: r for r in m["verdicts"]}
        for u in it["units"]:
            r = v.get(u["id"], {})
            rows.append({"unit": u["id"], "answer": it["id"], "qid": it["qid"], "qtype": it["qtype"],
                         "label": u.get("label", ""), "text": u["text"], "verdict": r.get("verdict"),
                         "note": r.get("note", ""), "evidence": r.get("evidence", [])})
    return {"plan": plan, "metas": metas, "attempts": attempts, "rows": rows, "not_checked": not_checked}


def tally(rows: list[dict]) -> dict:
    t = {v: sum(1 for r in rows if r["verdict"] == v) for v in A.VERDICTS}
    t["no verdict"] = sum(1 for r in rows if r["verdict"] is None)
    t["units"] = len(rows)
    t["claims"] = sum(t[v] for v in CLAIMS)
    t["bad"] = t["not_supported"] + t["wrong"]
    return t


def bounds(t: dict) -> tuple[str, str]:
    """The not-supported-plus-wrong share with the units without a verdict counted as not supported, and with
    them left out."""
    return share(t["bad"] + t["no verdict"], t["claims"] + t["no verdict"]), share(t["bad"], t["claims"])


# ------------------------------------------------------------------------------------------------------------
# The comparison's statistics (pure)

def clusters(rows: list[dict]) -> list[tuple[int, int]]:
    """(not supported + wrong, claims) per check (an answer or a batch), in id order."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["answer"], []).append(r)
    return [(tally(v)["bad"], tally(v)["claims"]) for _, v in sorted(by.items())]


def bootstrap_diff(a: list[tuple[int, int]], b: list[tuple[int, int]], n_boot: int = PS.B_DEFAULT,
                   seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile CI of share(a) - share(b), share = sum(bad) / sum(claims), resampling each arm's clusters with
    replacement (pairstats' seeding and percentile indices). A resample with no claims in an arm is skipped."""
    if not a or not b:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        ra = [a[rng.randrange(len(a))] for _ in a]
        rb = [b[rng.randrange(len(b))] for _ in b]
        na, nb = sum(n for _, n in ra), sum(n for _, n in rb)
        if na and nb:
            diffs.append(sum(k for k, _ in ra) / na - sum(k for k, _ in rb) / nb)
    if not diffs:
        return float("nan"), float("nan")
    diffs.sort()
    m = len(diffs)
    return diffs[int((1 - level) / 2 * m)], diffs[min(m - 1, int((1 + level) / 2 * m) - 1)]


def agreement(first: list[dict], second: list[dict]) -> dict:
    """Per-unit verdict agreement between two passes over the same units: {units (in both), both (a verdict in
    both), agree, confusion {(first, second): n}} with None for no verdict."""
    f = {r["unit"]: r["verdict"] for r in first}
    s = {r["unit"]: r["verdict"] for r in second}
    common = sorted(set(f) & set(s))
    conf: dict[tuple, int] = {}
    for u in common:
        conf[(f[u], s[u])] = conf.get((f[u], s[u]), 0) + 1
    both = [u for u in common if f[u] is not None and s[u] is not None]
    return {"units": len(common), "both": len(both), "agree": sum(1 for u in both if f[u] == s[u]),
            "confusion": conf}


# ------------------------------------------------------------------------------------------------------------
# outputs/runs.txt: the map Checker numbers (parsed)

ROW = re.compile(r"^  (\S+)\s{2,}(.+?)\s{2,}(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")


def sections(text: str) -> dict[str, list[str]]:
    """runs.txt's sections: a title at column 0 on the line above a rule of dashes -> the lines up to the next."""
    lines = text.splitlines()
    heads = [i for i in range(len(lines) - 1)
             if lines[i].strip() and not lines[i].startswith(" ") and re.fullmatch(r"-{10,}", lines[i + 1])]
    out = {}
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        out.setdefault(lines[i].strip(), lines[i + 2:end])
    return out


def _state_table(lines: list[str]) -> list[dict]:
    """The first 'repo stage supported not supp. unchecked retired' table in lines."""
    out: list[dict] = []
    in_table = False
    for ln in lines:
        if re.match(r"^\s+repo\s+stage\s+supported\s+not supp\.", ln):
            in_table = True
            continue
        if in_table:
            m = ROW.match(ln)
            if not m:
                break
            out.append({"repo": m.group(1), "stage": m.group(2).strip(), "supported": int(m.group(3)),
                        "not_supported": int(m.group(4))})
    return out


def parse_map_checker(text: str) -> list[dict]:
    """The first verdict table of runs.txt's 'checker' section: [{repo, stage, supported, not_supported}].
    [] when the section or its table isn't there in this form."""
    return _state_table(sections(text).get("checker", []))


def parse_recheck(text: str) -> dict:
    """runs.txt's 'recheck' section: {rule_new: the section says the rule was new, summary: [{repo, map_claims,
    rechecked, newly, still}], states: [{repo, stage, supported, not_supported}] (the re-checked claims only)}."""
    lines = sections(text).get("recheck", [])
    flat = " ".join(" ".join(lines).split())
    summary = []
    in_sum = False
    for ln in lines:
        if re.match(r"^\s+repo\s+map claims\s+re-checked\s+newly not supp\.\s+still not supp\.", ln):
            in_sum = True
            continue
        if in_sum:
            m = re.match(r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", ln)
            if not m:
                break
            summary.append({"repo": m.group(1), "map_claims": int(m.group(2)), "rechecked": int(m.group(3)),
                            "newly": int(m.group(4)), "still": int(m.group(5))})
    return {"rule_new": f'new "{RULE}" rule' in flat, "summary": summary, "states": _state_table(lines)}


def parse_map_states(text: str) -> list[dict]:
    """runs.txt's 'maps' section: [{repo, state, supported, not_supported}] per saved map ('run 1', 'run 2 after
    repair', 'run 2 after re-check')."""
    out: list[dict] = []
    cur: dict | None = None
    for ln in sections(text).get("maps", []):
        m = re.match(r"^  (\S+), (.+?)\s*$", ln)
        if m:
            cur = {"repo": m.group(1), "state": m.group(2)}
            continue
        m = re.match(r"^\s+Checker verdicts\s+supported (\d+), not supported (\d+)\s*$", ln)
        if m and cur is not None:
            out.append({**cur, "supported": int(m.group(1)), "not_supported": int(m.group(2))})
            cur = None
    return out


def parse_demo_answers(text: str) -> list[dict]:
    """The 'demo' section's live questions: [{q, repo, claims, supported, not_supported}] (Honeyguide's own
    answers, checked by its Checker against their cited lines)."""
    out: list[dict] = []
    cur: dict | None = None
    for ln in sections(text).get("demo", []):
        m = re.match(r"^  (q\d+)\s*$", ln)
        if m:
            cur = {"q": m.group(1)}
            out.append(cur)
            continue
        if cur is None:
            continue
        for key, pat in (("repo", r"^\s+repo\s+(\S+)\s*$"), ("claims", r"^\s+answer claims\s+(\d+)\s*$")):
            m = re.match(pat, ln)
            if m:
                cur[key] = int(m.group(1)) if key == "claims" else m.group(1)
        m = re.match(r"^\s+Checker\s+supported (\d+), not supported (\d+)\s*$", ln)
        if m:
            cur["supported"], cur["not_supported"] = int(m.group(1)), int(m.group(2))
    return [d for d in out if {"supported", "not_supported"} <= set(d)]


def map_rows(text: str) -> tuple[list[dict], list[dict], dict]:
    """The rows the capture prints from runs.txt, each with the rule that judged it: (map rows, re-checked rows,
    recheck). 'before' when the recheck section says the rule was new (the checker table predates it), else '?';
    the final map after the re-check is 'mixed'; the re-checked claims are 'with'."""
    rc = parse_recheck(text)
    before = "before" if rc["rule_new"] else "?"
    finals = {d["repo"]: d for d in parse_map_states(text) if d["state"] == "run 2 after re-check"}
    out: list[dict] = []
    repos = list(dict.fromkeys(r["repo"] for r in parse_map_checker(text)))
    for repo in repos:
        out += [{**r, "rule": before} for r in parse_map_checker(text) if r["repo"] == repo]
        if repo in finals and rc["summary"]:
            out.append({"repo": repo, "stage": "run 2 after re-check", "supported": finals[repo]["supported"],
                        "not_supported": finals[repo]["not_supported"], "rule": "mixed"})
    return out, [{**r, "rule": "with"} for r in rc["states"]], rc


# ------------------------------------------------------------------------------------------------------------
# The spot-check samples (one function: the capture and spot_check.md show the same units)

def sample(rows: list[dict], seed: int, n: int = SAMPLE) -> list[dict]:
    """n units with a verdict: each verdict's units shuffled (seeded), then taken round-robin across verdicts in
    VERDICTS order, so every verdict that occurs is represented."""
    rng = random.Random(seed)
    pools = []
    for v in A.VERDICTS:
        pool = sorted((r for r in rows if r["verdict"] == v), key=lambda r: r["unit"])
        rng.shuffle(pool)
        pools.append(pool)
    out: list[dict] = []
    while len(out) < n and any(pools):
        for pool in pools:
            if pool and len(out) < n:
                out.append(pool.pop(0))
    return out


def link(url: str, commit: str, ev: dict, short: bool = False) -> str:
    c = commit[:12] if short else commit
    tail = f"#L{ev['start']}" + (f"-L{ev['end']}" if ev["end"] != ev["start"] else "")
    return f"{url.rstrip('/')}/blob/{c}/{ev['path']}{tail}"


def _where(r: dict) -> str:
    return f"evidence label {r['label']}" if r.get("label") else \
        f"question {r['qid']} ({TYPE_LABEL.get(r['qtype'], r['qtype'])})"


def spot_check_md(data: dict, map_data: dict | None = None) -> str:
    plan = data["plan"]
    parts = [("ad-hoc answers", sample(data["rows"], plan["seed"]))]
    if map_data:
        parts.append(("map claims (the control)", sample(map_data["rows"], plan["seed"], MAP_SAMPLE)))
    out = [f"# E1 spot check: {plan['run_id']}", "",
           f"Seeded (seed {plan['seed']}), round-robin across verdicts. For each: do you agree with the verdict? "
           "Links are at the pinned commit.", ""]
    k = 0
    for title, s in parts:
        out += [f"## {title}: {len(s)} units", ""]
        for r in s:
            k += 1
            out += [f"### {k}. {r['verdict']}: `{r['unit']}`", "", f"{_where(r)[0].upper()}{_where(r)[1:]}.",
                    "", f"> {r['text']}", "", f"Note: {r['note'] or '(none)'}", ""]
            for e in r["evidence"]:
                out.append(f"- [{e['path']} {e['start']}-{e['end']}]({link(plan['url'], plan['commit'], e)})")
            if not r["evidence"]:
                out.append("- no evidence cited")
            out += ["", "Agree? ", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------------------

def _status_line(name: str, d: dict) -> str:
    by: dict[str, int] = {}
    for i in d["plan"]["items"]:
        st = (d["metas"].get(i["id"]) or {}).get("status", "not run")
        by[st] = by.get(st, 0) + 1
    return (f"{name} checked {by.get('ok', 0)} of {len(d['plan']['items'])}; "
            + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))


def _cost(d: dict) -> tuple[float, float, float, float]:
    ms = [m for m in d["metas"].values() if m]
    return (sum(float(m["usage"].get("cost_usd") or 0.0) for m in ms),
            sum(float(m.get("wall_s") or 0.0) for m in ms),
            sum(float((m.get("usage") or {}).get("cost_usd") or 0.0) for m in d["attempts"]),
            sum(float(m.get("wall_s") or 0.0) for m in d["attempts"]))


def _arm_row(name: str, t: dict) -> str:
    return (f"  {name:<16}{t['units']:>6}{t['claims']:>7}{t['supported']:>6}{t['not_supported']:>10}"
            f"{t['wrong']:>6}{t['no verdict']:>11}{share(t['bad'], t['claims']):>8}")


def _bad_list(rows: list[dict]) -> list[str]:
    L: list[str] = []
    bad = [r for r in rows if r["verdict"] in ("wrong", "not_supported")]
    for r in sorted(bad, key=lambda r: (r["verdict"] != "wrong", r["answer"], int(A.short_id(r["unit"])[1:]))):
        tag = "WRONG" if r["verdict"] == "wrong" else "not supp."
        lab = f" ({r['label']})" if r.get("label") else ""
        L += wrap(f"[{tag}] {r['unit']}{lab}: {trunc(r['text'], TEXT_MAX)}", 2, 6)
        L += wrap(f"note: {trunc(r['note'], NOTE_MAX) or '(none)'}", 6, 8)
    return L


def _evidence_lines(name: str, rows: list[dict], evidence: list[dict]) -> list[str]:
    ranges = sum(e["ranges"] for e in evidence)
    bad_ranges = [b for e in evidence for b in e["bad"]]
    whys: dict[str, int] = {}
    for b in bad_ranges:
        k = "lines out of range" if b["why"].startswith("lines out of range") else b["why"]
        whys[k] = whys.get(k, 0) + 1
    vb = [e for e in evidence if e["bad"]]
    vbv: dict[str, int] = {}
    for e in vb:
        vbv[e["verdict"]] = vbv.get(e["verdict"], 0) + 1
    no_ev = {v: sum(1 for r in rows if r["verdict"] == v and not r["evidence"]) for v in ("supported", "wrong")}
    L = [f"  {name}"]
    L += wrap(f"ranges cited {ranges}; ranges that don't exist at the commit {len(bad_ranges)}"
              + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(whys.items())) + ")" if whys else ""), 4, 6)
    L += wrap(f"verdicts citing at least one range that doesn't exist: {len(vb)}"
              + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(vbv.items())) + ")" if vbv else ""), 4, 6)
    L += wrap(f"verdicts that need evidence and cite none: supported {no_ev['supported']}, "
              f"wrong {no_ev['wrong']}", 4, 6)
    return L


def _spot(title: str, s: list[dict], plan: dict) -> list[str]:
    L = rule(title)
    L += wrap(f"links: {plan['url'].rstrip('/')}/blob/{plan['commit'][:12]}/<path>#L<start>-L<end>; "
              "full links in the answers archive's spot_check.md (--spot-check)", 2, 4)
    for k, r in enumerate(s, 1):
        L.append("")
        L += wrap(f"{k}. [{r['verdict']}] {r['unit']}" + (f" ({r['label']})" if r.get("label") else ""), 2, 6)
        L += wrap(r["text"], 6, 6)
        L += wrap(f"note: {r['note'] or '(none)'}", 6, 8)
        refs = [f"{e['path']}#L{e['start']}" + (f"-L{e['end']}" if e["end"] != e["start"] else "")
                for e in r["evidence"]]
        L += wrap("at: " + (", ".join(refs) if refs else "no evidence cited"), 6, 8)
    return L


def capture(data: dict, evidence: list[dict], runs_txt: str | None, map_data: dict | None = None,
            map_evidence: list[dict] | None = None, repeat: dict | None = None) -> str:
    plan, rows = data["plan"], data["rows"]
    for other in (map_data, repeat):
        if other and other["plan"]["commit"] != plan["commit"]:
            raise SystemExit(f"{other['plan']['run_id']} is at another commit than {plan['run_id']}")
    items = plan["items"]
    seed = plan["seed"]
    L: list[str] = [f"E1: ad-hoc answers checked: {plan['repo']} (run {plan['run_id']})", "=" * WIDTH]
    by_type = {t: sum(1 for i in items if i["qtype"] == t) for t in plan["types"]}
    qids = list(dict.fromkeys(i["qid"] for i in items))
    n_units = sum(len(i["units"]) for i in items)
    L += [f"  commit      {plan['commit'][:12]} ({plan['url']})"]
    L += wrap(f"source      {plan['source_run_id']}: the explore answers (an agent with Read, Grep and Glob, "
              "no map), as returned; nobody checked them", 2, 14)
    L += wrap(f"scope       {', '.join(TYPE_LABEL[t] for t in plan['types'])} questions: {len(items)} answers "
              f"to {len(qids)} questions ("
              + ", ".join(f"{TYPE_LABEL[t]} {k}" for t, k in by_type.items()) + ")"
              + (f"; skipped {len(plan['skipped'])}" if plan["skipped"] else ""), 2, 14)
    L += wrap(f"units       {n_units} (sentences and list items, split by script: eval/adhoc/adhoc_split.py)",
              2, 14)
    if map_data:
        mp = map_data["plan"]
        st = mp["strata"]
        L += wrap(f"control     map claims: {sum(len(i['units']) for i in mp['items'])} of the "
                  f"{mp['map_claims']} claims of {mp['source_run_id']}'s eval map (maps/seed1/map.json, built "
                  "at the same commit, never Checker-passed), a seeded sample (seed "
                  f"{mp['seed']}) stratified by evidence label ("
                  + ", ".join(f"{k} {v}" for k, v in sorted(st["sampled"].items())) + "); left out: "
                  + ", ".join(f"{lb} {st['in_map'].get(lb, 0)}" for lb in mp["exclude"])
                  + f"; anchors stripped; {len(mp['items'])} checks of about {mp['batch_size']} claims", 2, 14)
    else:
        L += wrap("control     map claims: not run yet (adhoc.py --source map)", 2, 14)
    L += wrap(f"checker     one isolated claude -p per check (an answer, or a batch of map claims), the same "
              f"brief, schema and parsing for both arms; Read/Grep/Glob on a fresh copy of the pin; requested "
              f"{plan['model']}, effort {plan['effort']}; cap ${plan['answer_cap_usd']:g} per check", 2, 14)
    arms = [("answers", data)] + ([("map", map_data)] if map_data else []) + ([("repeat", repeat)] if repeat else [])
    used: dict[str, int] = {}
    for _, d in arms:
        for m in d["metas"].values():
            if m:
                key = "+".join(m.get("models_used") or []) or "(no result)"
                used[key] = used.get(key, 0) + 1
    L += wrap("used: " + (", ".join(f"{k} x{v}" for k, v in sorted(used.items())) or "none yet"), 14, 14)
    L += wrap("checks      " + "; ".join(_status_line(n, d) for n, d in arms), 2, 14)
    costs = []
    for n, d in arms:
        c, w, ac, aw = _cost(d)
        costs.append(f"{n} ${c:.2f}, {w / 60:.1f} min" + (f" (earlier attempts ${ac:.2f}, {aw / 60:.1f} min)"
                                                          if d["attempts"] else ""))
    L += wrap("cost        " + "; ".join(costs) + " (list price; wall clock summed over checks)", 2, 14)
    gaps = []
    for n, d in arms:
        probs = [p for m in d["metas"].values() for p in (m or {}).get("problems") or []]
        dup = sum(1 for p in probs if ": repeated" in p)
        if probs or d["not_checked"]:
            gaps.append(f"{n}: {d['not_checked']} units in checks that returned no verdicts; {len(probs)} "
                        f"problem(s) in checks' output ({dup} repeated ids flagged)")
    if gaps:
        L += wrap("gaps        " + "; ".join(gaps), 2, 14)

    # --- the comparison
    L += rule("the comparison: ad-hoc answers against map claims (the control)")
    L += wrap("What this compares: sentences and list items from ad-hoc answers, and claims the Cartographer "
              "wrote for the eval map and that were never checked (the eval map was never Checker-passed), both "
              "judged by the same Checker: one brief, schema, isolation and parsing. The map claims' anchors were "
              "stripped, so for both arms the Checker finds the evidence itself.", 2, 2)
    L += ["", f"  {'arm':<16}{'units':>6}{'claims':>7}{'supp.':>6}{'not supp.':>10}{'wrong':>6}"
              f"{'no verdict':>11}{'ns+w':>8}", "  " + "-" * (WIDTH - 2)]
    ta = tally(rows)
    L.append(_arm_row("ad-hoc answers", ta))
    tm = tally(map_data["rows"]) if map_data else None
    if tm:
        L.append(_arm_row("map claims", tm))
    else:
        L.append(f"  {'map claims':<16}  not run yet")
    L += wrap("claims = units judged supported, not supported or wrong; ns+w = (not supported + wrong) / "
              "claims. not_a_claim and no verdict are left out of claims.", 2, 4)
    if tm:
        ca, cm = clusters(rows), clusters(map_data["rows"])
        diff = (ta["bad"] / ta["claims"] - tm["bad"] / tm["claims"]) if ta["claims"] and tm["claims"] else None
        lo, hi = bootstrap_diff(ca, cm, seed=0)
        if diff is not None:
            L += wrap(f"difference in ns+w, ad-hoc minus map: {diff:+.3f}, 95% CI [{lo:+.3f}, {hi:+.3f}] "
                      f"(bootstrap, {PS.B_DEFAULT} resamples of the checks as clusters: {len(ca)} answers, "
                      f"{len(cm)} batches; seed 0; units without a verdict left out)", 2, 4)
    for name, t in [("ad-hoc answers", ta)] + ([("map claims", tm)] if tm else []):
        hi_b, lo_b = bounds(t)
        L += wrap(f"bounds, {name}: {t['no verdict']} units without a verdict; ns+w with them counted as not "
                  f"supported {hi_b}, with them left out {lo_b}", 2, 4)

    # --- verdicts, answers arm
    L += rule("verdicts: ad-hoc answers (units of checks that returned verdicts)")
    L += ["  group           units  claims  supported  not supp.  wrong  not a claim",
          "  " + "-" * (WIDTH - 2)]

    def line(name: str, t: dict) -> str:
        return (f"  {name:<14} {t['units']:>6} {t['claims']:>7} {t['supported']:>10} {t['not_supported']:>10}"
                f" {t['wrong']:>6} {t['not_a_claim']:>12}")
    L.append(line("all", ta))
    for t in plan["types"]:
        L.append(line(TYPE_LABEL[t], tally([r for r in rows if r["qtype"] == t])))
    L += ["", "  shares of claims (units judged supported, not supported or wrong)"]
    L += [f"  {'group':<12}{'claims':>7}{'no verdict':>12}{'supported':>11}{'not supp.':>11}{'wrong':>7}"
          f"{'ns + wrong':>12}"]
    for name, sub in [("all", rows)] + [(TYPE_LABEL[t], [r for r in rows if r["qtype"] == t]) for t in plan["types"]]:
        t = tally(sub)
        L.append(f"  {name:<12}{t['claims']:>7}{t['no verdict']:>12}{share(t['supported'], t['claims']):>11}"
                 f"{share(t['not_supported'], t['claims']):>11}{share(t['wrong'], t['claims']):>7}"
                 f"{share(t['bad'], t['claims']):>12}")
    hi_b, lo_b = bounds(ta)
    L += wrap(f"no verdict: units the check left without one (never in claims). ns + wrong with them counted as "
              f"not supported {hi_b}, left out {lo_b}", 2, 4)
    lr = sum(1 for r in rows if r["verdict"] in ("not_supported", "wrong")
             and r["note"].strip().lower().startswith("line reference"))
    L += wrap(f"faulted only for a line reference (the note starts \"line reference:\"): {lr} of the {ta['bad']} "
              "units judged not supported or wrong", 2, 4)

    # --- per question
    L += rule("per question (both explore passes together)")
    L += ["  question   type      units  claims  supp.  not supp.  wrong  share supp.",
          "  " + "-" * (WIDTH - 2)]
    for q in qids:
        sub = [r for r in rows if r["qid"] == q]
        t = tally(sub)
        qt = next(i["qtype"] for i in items if i["qid"] == q)
        L.append(f"  {q:<10} {TYPE_LABEL[qt]:<8} {t['units']:>6} {t['claims']:>7} {t['supported']:>6} "
                 f"{t['not_supported']:>10} {t['wrong']:>6} {share(t['supported'], t['claims']):>12}")

    # --- verdicts, map arm
    if map_data:
        L += rule("verdicts: map claims, by evidence label")
        L += [f"  {'label':<17}{'units':>6}{'claims':>7}{'supp.':>6}{'not supp.':>10}{'wrong':>6}"
              f"{'not claim':>10}{'ns+w':>8}", "  " + "-" * (WIDTH - 2)]
        mrows = map_data["rows"]
        for lb in sorted({r["label"] for r in mrows}):
            t = tally([r for r in mrows if r["label"] == lb])
            L.append(f"  {lb:<17}{t['units']:>6}{t['claims']:>7}{t['supported']:>6}{t['not_supported']:>10}"
                     f"{t['wrong']:>6}{t['not_a_claim']:>10}{share(t['bad'], t['claims']):>8}")
        t = tally(mrows)
        L.append(f"  {'all':<17}{t['units']:>6}{t['claims']:>7}{t['supported']:>6}{t['not_supported']:>10}"
                 f"{t['wrong']:>6}{t['not_a_claim']:>10}{share(t['bad'], t['claims']):>8}")

    # --- not supported and wrong
    L += rule(f"the {ta['bad']} answer units judged wrong or not supported (truncated)")
    L += _bad_list(rows)
    if map_data:
        L += rule(f"the {tm['bad']} map claims judged wrong or not supported (truncated)")
        L += _bad_list(map_data["rows"])

    # --- evidence check
    L += rule("evidence check (every cited range against the pinned commit)")
    L += _evidence_lines("ad-hoc answers", rows, evidence)
    if map_data:
        L += _evidence_lines("map claims", map_data["rows"], map_evidence or [])

    # --- the repeat
    if repeat:
        rp = repeat["plan"]
        ids = {i["id"] for i in rp["items"]}
        first = [r for r in rows if r["answer"] in ids]
        ag = agreement(first, repeat["rows"])
        L += rule(f"repeat: the same check again on {len(ids)} answers (seed {rp['seed']})")
        L += wrap("answers: " + ", ".join(sorted(ids)), 2, 4)
        L += wrap(f"per-unit agreement: {ag['agree']} of the {ag['both']} units with a verdict in both passes "
                  f"({share(ag['agree'], ag['both'])}); {ag['units']} units in both", 2, 4)
        t1, t2 = tally(first), tally(repeat["rows"])
        L += wrap(f"ns+w on these answers: first pass {share(t1['bad'], t1['claims'])} ({t1['claims']} claims), "
                  f"repeat {share(t2['bad'], t2['claims'])} ({t2['claims']} claims)", 2, 4)
        cols = list(A.VERDICTS) + [None]
        names = {"supported": "supp.", "not_supported": "not supp.", "wrong": "wrong", "not_a_claim": "not claim",
                 None: "none"}
        corner = "first \\ repeat"
        L += ["", f"  {corner:<16}" + "".join(f"{names[c]:>11}" for c in cols)]
        for r in cols:
            L.append(f"  {names[r]:<16}" + "".join(f"{ag['confusion'].get((r, c), 0):>11}" for c in cols))

    # --- the map's Checker, for comparison
    L += rule("for comparison: the map Checker on Honeyguide's maps (outputs/runs.txt)")
    L += wrap("Not the main comparison (that is the control above): the map Checker judged each claim against "
              "the lines it cites, its not supported includes what is wrong here, and these maps went through "
              "repair. Each row says which Checker rule judged it.", 2, 2)
    mrs, rcs, rc = map_rows(runs_txt) if runs_txt is not None else ([], [], {})
    if not mrs:
        L += ["  see runs.txt (its checker table was not found in a form this parses)"]
    else:
        head = (f"  {'repo':<10} {'stage':<22} {'claims':>6} {'supp.':>6} {'not supp.':>9} {'share':>6}  rule")

        def mrow(m: dict) -> str:
            n = m["supported"] + m["not_supported"]
            return (f"  {m['repo']:<10} {trunc(m['stage'], 22):<22} {n:>6} {m['supported']:>6} "
                    f"{m['not_supported']:>9} {share(m['not_supported'], n):>6}  {m['rule']}")
        L += ["", head, "  " + "-" * (WIDTH - 2)] + [mrow(m) for m in mrs]
        if rcs:
            L += ["", "  the re-checked value claims only (runs.txt recheck):", head, "  " + "-" * (WIDTH - 2)]
            L += [mrow(m) for m in rcs]
        L += wrap("share = not supported / claims. rule: before = judged before the Checker's \"" + RULE
                  + "\" rule existed (runs.txt's recheck calls the rule new); with = judged under it"
                  + ("; mixed = the final map after the re-check: "
                     + ", ".join(f"{s['repo']} {s['rechecked']} of {s['map_claims']} claims judged under the rule"
                                 f", {s['map_claims'] - s['rechecked']} before it" for s in rc["summary"])
                     if rc.get("summary") else "") + ".", 2, 4)
        for s in rc.get("summary", []):
            L += wrap(f"{s['repo']}: of {s['rechecked']} value claims re-checked under the rule, {s['newly']} "
                      f"were newly not supported; {s['still']} still not supported after repair round 2", 2, 4)
    demo = parse_demo_answers(runs_txt) if runs_txt is not None else []
    for d in demo:
        n = d["supported"] + d["not_supported"]
        L += wrap(f"live answer {d['q']} ({d.get('repo', '?')}, Honeyguide's own answer): "
                  f"{n} claims, supported {d['supported']}, not supported {d['not_supported']} (share "
                  f"{share(d['not_supported'], n)}); judged against its cited lines, runs.txt does not record "
                  "under which rule", 2, 4)

    # --- spot checks
    s = sample(rows, seed)
    L += _spot(f"spot check for Han: {len(s)} units (seed {seed}, round-robin across verdicts)", s, plan)
    if map_data:
        ms = sample(map_data["rows"], seed, MAP_SAMPLE)
        L += _spot(f"spot check for Han, map claims: {len(ms)} units (seed {seed})", ms, plan)

    text = "\n".join(ln.rstrip() for ln in L) + "\n"
    too_wide = [ln for ln in text.splitlines() if len(ln) > WIDTH]
    if too_wide:
        raise AssertionError(f"capture line over {WIDTH} columns: {too_wide[0]!r}")
    return text


def main_report(cfg: dict, archive, runs_txt: Path, *, spot_check: bool = False, map_archive=None,
                repeat_archive=None) -> int:
    if not (archive.root / "plan.json").exists():
        raise SystemExit(f"{archive.root}: no plan.json (run the check first)")
    data = load(archive)
    map_data = load(map_archive) if map_archive and (map_archive.root / "plan.json").exists() else None
    repeat = load(repeat_archive) if repeat_archive and (repeat_archive.root / "plan.json").exists() else None
    if spot_check:
        p = archive.root / "spot_check.md"
        p.write_text(spot_check_md(data, map_data) + "\n")
        print(f"spot check: {p}", file=sys.stderr)
        return 0
    clone = A.C.expand(cfg["repos"][data["plan"]["repo"]]["clone"])
    lines_of = A.repo_lines(clone, data["plan"]["commit"])
    evidence = A.check_evidence(data["rows"], lines_of)
    map_ev = A.check_evidence(map_data["rows"], lines_of) if map_data else None
    text = runs_txt.read_text() if runs_txt.exists() else None
    sys.stdout.write(capture(data, evidence, text, map_data, map_ev, repeat))
    return 0
