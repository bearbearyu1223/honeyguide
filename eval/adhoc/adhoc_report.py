"""E1's capture (outputs/adhoc_check.txt, 74 columns) and Han's spot-check sheet, from the check's archive.

Reads <archive>/<run-id>-adhoc/ (adhoc.py) and never writes to it, except --spot-check, which writes
spot_check.md there (the same sample as the capture, with full GitHub links, which don't fit 74 columns).
Deterministic: every number comes from the saved checks, the pinned commit (the evidence pass) and outputs/runs.txt
(the map Checker numbers, parsed, never typed); the spot-check sample is seeded (plan seed).
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
import adhoc as A  # noqa: E402

WIDTH = 74
SAMPLE = 20
TEXT_MAX, NOTE_MAX = 160, 200
TYPE_LABEL = {"flow": "flow", "whyhow": "why/how", "locate": "locate", "callers": "callers"}
CLAIMS = ("supported", "not_supported", "wrong")
FAILED = ("error", "capped", "invalid_answer")


def wrap(text: str, indent: int = 2, sub: int | None = None) -> list[str]:
    sub = indent + 2 if sub is None else sub
    return textwrap.wrap(text, WIDTH, initial_indent=" " * indent, subsequent_indent=" " * sub) or [""]


def rule(title: str) -> list[str]:
    return ["", title, "-" * WIDTH]


def trunc(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def share(k: int, n: int) -> str:
    return f"{k / n:.3f}" if n else "-"


# ------------------------------------------------------------------------------------------------------------
# Loading (one function: every section reads the same rows)

def load(archive) -> dict:
    """plan, metas, and one row per unit of a finished check: {unit, answer, qid, qtype, text, verdict, note,
    evidence}. Units of checks that did not finish ok are counted under 'not checked'."""
    plan = json.loads((archive.root / "plan.json").read_text())
    metas = {i["id"]: archive.meta(i["id"]) for i in plan["items"]}
    attempts = []
    for p in sorted((archive.root / "attempts").glob("*/*/meta.json")):
        attempts.append(json.loads(p.read_text()))
    rows, not_checked = [], 0
    for it in plan["items"]:
        m = metas.get(it["id"])
        if not m or m.get("status") != "ok":
            not_checked += len(it["units"])
            continue
        v = {r["unit"]: r for r in m["verdicts"]}
        for u in it["units"]:
            r = v.get(u["id"], {})
            rows.append({"unit": u["id"], "answer": it["id"], "qid": it["qid"], "qtype": it["qtype"],
                         "text": u["text"], "verdict": r.get("verdict"), "note": r.get("note", ""),
                         "evidence": r.get("evidence", [])})
    return {"plan": plan, "metas": metas, "attempts": attempts, "rows": rows, "not_checked": not_checked}


def tally(rows: list[dict]) -> dict:
    t = {v: sum(1 for r in rows if r["verdict"] == v) for v in A.VERDICTS}
    t["no verdict"] = sum(1 for r in rows if r["verdict"] is None)
    t["units"] = len(rows)
    t["claims"] = sum(t[v] for v in CLAIMS)
    return t


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


def parse_map_checker(text: str) -> list[dict]:
    """The first verdict table of runs.txt's 'checker' section: [{repo, stage, supported, not_supported}].
    [] when the section or its table isn't there in this form."""
    out: list[dict] = []
    in_table = False
    for ln in sections(text).get("checker", []):
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


# ------------------------------------------------------------------------------------------------------------
# The spot-check sample (one function: the capture and spot_check.md show the same units)

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


def spot_check_md(data: dict) -> str:
    plan = data["plan"]
    s = sample(data["rows"], plan["seed"])
    out = [f"# E1 spot check: {plan['run_id']}", "",
           f"{len(s)} units, seeded (seed {plan['seed']}), round-robin across verdicts. For each: do you agree "
           "with the verdict? Links are at the pinned commit.", ""]
    for k, r in enumerate(s, 1):
        out += [f"## {k}. {r['verdict']}: `{r['unit']}`", "", f"Question {r['qid']} ({TYPE_LABEL[r['qtype']]}).",
                "", f"> {r['text']}", "", f"Note: {r['note'] or '(none)'}", ""]
        for e in r["evidence"]:
            out.append(f"- [{e['path']} {e['start']}-{e['end']}]({link(plan['url'], plan['commit'], e)})")
        if not r["evidence"]:
            out.append("- no evidence cited")
        out += ["", "Agree? ", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------------------

def capture(data: dict, evidence: list[dict], runs_txt: str | None) -> str:
    plan, metas, rows = data["plan"], data["metas"], data["rows"]
    items = plan["items"]
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
    L += wrap(f"checker     one isolated claude -p per answer, Read/Grep/Glob on a fresh copy of the pin; "
              f"requested {plan['model']}, effort {plan['effort']}; cap ${plan['answer_cap_usd']:g} per answer",
              2, 14)
    used: dict[str, int] = {}
    for m in metas.values():
        if m:
            key = "+".join(m.get("models_used") or []) or "(no result)"
            used[key] = used.get(key, 0) + 1
    L += wrap("used: " + (", ".join(f"{k} x{v}" for k, v in sorted(used.items())) or "none yet"), 14, 14)
    by: dict[str, int] = {}
    for i in items:
        st = (metas.get(i["id"]) or {}).get("status", "not run")
        by[st] = by.get(st, 0) + 1
    L += wrap(f"answers     checked {by.get('ok', 0)} of {len(items)}; "
              + ", ".join(f"{k} {v}" for k, v in sorted(by.items())), 2, 14)
    cost = sum(float(m["usage"].get("cost_usd") or 0.0) for m in metas.values() if m)
    wall = sum(float(m.get("wall_s") or 0.0) for m in metas.values() if m)
    acost = sum(float(m["usage"].get("cost_usd") or 0.0) for m in data["attempts"])
    awall = sum(float(m.get("wall_s") or 0.0) for m in data["attempts"])
    L += wrap(f"cost        ${cost:.2f} list, {wall / 60:.1f} min (sum of the checks' wall clock)"
              + (f"; earlier attempts ${acost:.2f}, {awall / 60:.1f} min" if data["attempts"] else ""), 2, 14)
    problems = sum(len((m or {}).get("problems") or []) for m in metas.values())
    if problems or data["not_checked"]:
        L += wrap(f"gaps        {data['not_checked']} units in checks that did not finish ok; {problems} "
                  "problem(s) in finished checks' output (missing or repeated ids, malformed entries)", 2, 14)

    # --- verdicts
    L += rule("verdicts (units of the finished checks)")
    L += ["  group           units  claims  supported  not supp.  wrong  not a claim",
          "  " + "-" * (WIDTH - 2)]

    def line(name: str, t: dict) -> str:
        return (f"  {name:<14} {t['units']:>6} {t['claims']:>7} {t['supported']:>10} {t['not_supported']:>10}"
                f" {t['wrong']:>6} {t['not_a_claim']:>12}")
    tall = tally(rows)
    L.append(line("all", tall))
    for t in plan["types"]:
        L.append(line(TYPE_LABEL[t], tally([r for r in rows if r["qtype"] == t])))
    if tall["no verdict"]:
        L += wrap(f"no verdict: {tall['no verdict']} units (the check left them out)", 2, 4)
    L += ["", "  shares of claims (units judged supported, not supported or wrong)"]
    L += ["  group           claims  supported  not supp.  wrong  not supp. + wrong"]
    for name, sub in [("all", rows)] + [(TYPE_LABEL[t], [r for r in rows if r["qtype"] == t]) for t in plan["types"]]:
        t = tally(sub)
        L.append(f"  {name:<14} {t['claims']:>7} {share(t['supported'], t['claims']):>10} "
                 f"{share(t['not_supported'], t['claims']):>10} {share(t['wrong'], t['claims']):>6} "
                 f"{share(t['not_supported'] + t['wrong'], t['claims']):>18}")
    lr = sum(1 for r in rows if r["verdict"] in ("not_supported", "wrong")
             and r["note"].strip().lower().startswith("line reference"))
    nbad = sum(1 for r in rows if r["verdict"] in ("not_supported", "wrong"))
    L += wrap(f"faulted only for a line reference (the note starts \"line reference:\"): {lr} of the {nbad} "
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

    # --- not supported and wrong
    bad = [r for r in rows if r["verdict"] in ("wrong", "not_supported")]
    L += rule(f"the {len(bad)} units judged wrong or not supported (text and note truncated)")
    for r in sorted(bad, key=lambda r: (r["verdict"] != "wrong", r["answer"], int(A.short_id(r["unit"])[1:]))):
        tag = "WRONG" if r["verdict"] == "wrong" else "not supp."
        L += wrap(f"[{tag}] {r['unit']}: {trunc(r['text'], TEXT_MAX)}", 2, 6)
        L += wrap(f"note: {trunc(r['note'], NOTE_MAX) or '(none)'}", 6, 8)

    # --- evidence check
    L += rule("evidence check (every cited range against the pinned commit)")
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
    L += wrap(f"ranges cited {ranges}; ranges that don't exist at the commit {len(bad_ranges)}"
              + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(whys.items())) + ")" if whys else ""), 2, 4)
    L += wrap(f"verdicts citing at least one range that doesn't exist: {len(vb)}"
              + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(vbv.items())) + ")" if vbv else ""), 2, 4)
    L += wrap(f"verdicts that need evidence and cite none: supported {no_ev['supported']}, "
              f"wrong {no_ev['wrong']}", 2, 4)

    # --- the map's Checker, for comparison
    L += rule("for comparison: the Checker on Honeyguide's maps (outputs/runs.txt)")
    mp = parse_map_checker(runs_txt) if runs_txt is not None else []
    if not mp:
        L += ["  see runs.txt (its checker table was not found in a form this parses)"]
    else:
        L += ["  repo        stage                  claims  supported  not supp.  share",
              "  " + "-" * (WIDTH - 2)]
        for m in mp:
            n = m["supported"] + m["not_supported"]
            L.append(f"  {m['repo']:<11} {trunc(m['stage'], 22):<22} {n:>6} {m['supported']:>10} "
                     f"{m['not_supported']:>10} {share(m['not_supported'], n):>6}")
        L += wrap("share = not supported / claims. First pass = 'run 1 (no repair)' and 'run 2 before repair'; "
                  "the later rows are after the repair pass.", 2, 4)
    demo = parse_demo_answers(runs_txt) if runs_txt is not None else []
    for d in demo:
        n = d["supported"] + d["not_supported"]
        L += wrap(f"live answer {d['q']} ({d.get('repo', '?')}, Honeyguide's own answer): "
                  f"{n} claims, supported {d['supported']}, not supported {d['not_supported']} (share "
                  f"{share(d['not_supported'], n)})", 2, 4)
    L += wrap("Not the same measurement: the map's Checker judged each claim against the lines the claim cites "
              "(quotes resolved by script, so a citation can't point at the wrong line), and its not supported "
              "includes what is wrong here. Here the Checker finds the evidence itself for each sentence or list "
              "item, which can bundle several facts, and cites the line numbers the answer typed.", 2, 2)

    # --- spot check
    s = sample(rows, plan["seed"])
    L += rule(f"spot check for Han: {len(s)} units (seed {plan['seed']}, round-robin across verdicts)")
    L += wrap(f"links: {plan['url'].rstrip('/')}/blob/{plan['commit'][:12]}/<path>#L<start>-L<end>; "
              "full links in the archive's spot_check.md (--spot-check)", 2, 4)
    for k, r in enumerate(s, 1):
        L.append("")
        L += wrap(f"{k}. [{r['verdict']}] {r['unit']}", 2, 6)
        L += wrap(r["text"], 6, 6)
        L += wrap(f"note: {r['note'] or '(none)'}", 6, 8)
        refs = [f"{e['path']}#L{e['start']}" + (f"-L{e['end']}" if e["end"] != e["start"] else "")
                for e in r["evidence"]]
        L += wrap("at: " + (", ".join(refs) if refs else "no evidence cited"), 6, 8)

    text = "\n".join(ln.rstrip() for ln in L) + "\n"
    too_wide = [ln for ln in text.splitlines() if len(ln) > WIDTH]
    if too_wide:
        raise AssertionError(f"capture line over {WIDTH} columns: {too_wide[0]!r}")
    return text


def main_report(cfg: dict, archive, runs_txt: Path, *, spot_check: bool = False) -> int:
    if not (archive.root / "plan.json").exists():
        raise SystemExit(f"{archive.root}: no plan.json (run the check first)")
    data = load(archive)
    if spot_check:
        p = archive.root / "spot_check.md"
        p.write_text(spot_check_md(data) + "\n")
        print(f"spot check: {p}", file=sys.stderr)
        return 0
    clone = A.C.expand(cfg["repos"][data["plan"]["repo"]]["clone"])
    evidence = A.check_evidence(data["rows"], A.repo_lines(clone, data["plan"]["commit"]))
    text = runs_txt.read_text() if runs_txt.exists() else None
    sys.stdout.write(capture(data, evidence, text))
    return 0
