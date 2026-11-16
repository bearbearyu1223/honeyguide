"""Print the receipts of the real Honeyguide runs (run 1, run 2, repair, re-check, live demo).

    uv run python eval/runs/capture.py > outputs/runs.txt 2> outputs/runs.err

Reads the run archive (default ~/Documents/GitHub/honeyguide-targets/_runs,
or --archive DIR) and never writes to it. Prints seven labelled blocks: runs,
maps, checker, recheck, readability, demo, examples. Every number is read from the
archive; a value the archive does not hold prints as "not recorded".
Repos are printed by name, never by path. Standard library only (plus
honeyguide.readability for the readability block).
"""

import argparse
import json
import sys
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    from honeyguide.mapdoc import block_text, module_blocks, module_files
    from honeyguide.readability import check_readability, prose_pieces, words
except ImportError:   # run outside the uv environment
    sys.path.insert(0, str(HERE.parents[1] / "src"))
    from honeyguide.mapdoc import block_text, module_blocks, module_files
    from honeyguide.readability import check_readability, prose_pieces, words

WIDTH = 74
DEFAULT_ARCHIVE = Path.home() / "Documents" / "GitHub" / "honeyguide-targets" / "_runs"
NOT_RECORDED = "not recorded"
TOPICS = ("purpose", "users", "capabilities", "commands", "entry-points", "components", "start-here")
STATES = ("supported", "not_supported", "unchecked", "retired")
NARROWED_RULE = "the first claim in id order (both repos) with a 'rewrite' repair"
WRONGLY_PASSED = "c_20b0bb0d778f"
RECHECK_REWRITTEN = "c_b9a4c59e2e08"
PASSES = ("run 1", "run 2", "repair", "re-check")


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Pure helpers (tested in tests/test_eval_runs.py)

def repo_of_store(dirname):
    """'github.com__karpathy__nanochat__3a5e0bc50b12' -> 'nanochat'."""
    parts = dirname.split("__")
    return parts[2] if len(parts) >= 4 else dirname


def parse_time(text):
    return datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%SZ")


def minutes_between(start, end):
    """Minutes from start to end (ISO-Z strings), or None when either is missing."""
    if not start or not end:
        return None
    return (parse_time(end) - parse_time(start)).total_seconds() / 60


def claim_state(claim, stage):
    """A map claim's Checker state after repair round ``stage`` (0 = before repair).

    A repair recorded at round r means the claim was not supported after round r-1, so any repair at a round later
    than ``stage`` makes it ``not_supported`` then; otherwise its saved state holds.
    """
    if any(r.get("round", 0) > stage for r in claim.get("repairs") or []):
        return "not_supported"
    if claim.get("freshness") == "retired":
        return "retired"
    check = claim.get("check") or "unchecked"
    return check if check in STATES else "unchecked"


def stage_counts(claims, stage):
    c = Counter(claim_state(x, stage) for x in claims)
    return {s: c.get(s, 0) for s in STATES}


def anchor_lines(anchors):
    """Cited (path, line) pairs from saved anchors (dicts) or repair-history anchors ('path:start-end')."""
    out = set()
    for a in anchors or []:
        if isinstance(a, dict):
            path, start, end = a.get("path"), a.get("start"), a.get("end")
        else:
            path, _, span = str(a).rpartition(":")
            start, _, end = span.partition("-")
        try:
            start, end = int(start), int(end or start)
        except (TypeError, ValueError):
            continue
        out.update((path, n) for n in range(start, end + 1))
    return out


def repair_steps(claim):
    """(round, action, before_text, after_text, before_lines, after_lines) for each repair of a claim."""
    reps = sorted(claim.get("repairs") or [], key=lambda r: r.get("round", 0))
    steps = []
    for i, r in enumerate(reps):
        nxt = reps[i + 1] if i + 1 < len(reps) else None
        after_text = nxt["text"] if nxt else claim.get("text", "")
        after_anchors = nxt["anchors"] if nxt else claim.get("anchors")
        steps.append((r.get("round", 0), r.get("action"), r.get("text", ""), after_text,
                      len(anchor_lines(r.get("anchors"))), len(anchor_lines(after_anchors))))
    return steps


def repair_summary(claims):
    """Per round: action counts, and for 'anchor' repairs how many cite more lines afterwards."""
    out = {}
    for claim in claims:
        for rnd, action, _, _, before, after in repair_steps(claim):
            row = out.setdefault(rnd, {"anchor": 0, "rewrite": 0, "retire": 0, "wider": 0})
            row[action] = row.get(action, 0) + 1
            if action == "anchor" and after > before:
                row["wider"] += 1
    return out


def new_repairs(before, after):
    """Repair entries in ``after``'s history that ``before``'s history does not hold (the later pass's)."""
    old = before.get("repairs") or []
    new = after.get("repairs") or []
    if new[:len(old)] == old:
        return new[len(old):]
    return [r for r in new if r not in old]


def rechecked_ids(before_claims, after_claims):
    """Ids of claims the later pass checked again: a checked_at later than every checked_at in ``before``,
    or a changed check, check_note, anchors or text."""
    before = {c["id"]: c for c in before_claims}
    latest = max((c.get("checked_at") or "" for c in before_claims), default="")
    out = []
    for c in after_claims:
        b = before.get(c["id"])
        if b is None:
            continue
        if (c.get("checked_at") or "") > latest or any(b.get(k) != c.get(k)
                                                        for k in ("check", "check_note", "anchors", "text")):
            out.append(c["id"])
    return out


def has_pass(entry):
    """True for a repair entry that records its own ``pass`` and per-pass ``round`` (saved since a707864)."""
    return bool(entry.get("pass")) and isinstance(entry.get("round"), int)


def pass_rounds(repairs):
    """One pass's repair entries numbered by the pass's own rounds. An entry that records its ``pass`` and
    ``round`` keeps them. A legacy entry (saved before passes existed) records only the claim's history count as
    its ``round``, so a claim already repaired in an earlier pass shows its first repair of this pass as round 2;
    those are renumbered by timestamp instead: the n-th distinct ``at`` among the legacy entries is round n."""
    stamps = sorted({r["at"] for r in repairs if r.get("at") and not has_pass(r)})
    return [dict(r) if has_pass(r) or not r.get("at") else dict(r, round=stamps.index(r["at"]) + 1)
            for r in repairs]


def pass_key(entry):
    """The repair pass an entry belongs to: its ``pass`` id, or None for every legacy entry (one legacy pass)."""
    return entry.get("pass") if has_pass(entry) else None


def last_pass(claims):
    """The pass key of the latest repair entry (by ``at``) across ``claims``; None when there are only legacy
    entries or none."""
    entries = [r for c in claims for r in c.get("repairs") or []]
    if not entries:
        return None
    return pass_key(max(entries, key=lambda r: r.get("at") or ""))


def one_pass(claims, key):
    """``claims`` with each repairs history cut to the entries of one pass (``key`` from pass_key), so rounds of
    different passes never mix."""
    return [dict(c, repairs=[r for r in c.get("repairs") or [] if pass_key(r) == key]) for c in claims]


def recheck_summary(before_claims, after_claims):
    """The re-check pass from two map snapshots: claims re-checked, their state before repair and after each
    round of this pass (from the repairs it added, renumbered by pass_rounds), and its actions per round."""
    before = {c["id"]: c for c in before_claims}
    ids = set(rechecked_ids(before_claims, after_claims))
    added = {c["id"]: new_repairs(before[c["id"]], c) for c in after_claims if c["id"] in ids}
    renumbered = iter(pass_rounds([r for reps in added.values() for r in reps]))
    pruned = [dict(c, repairs=[next(renumbered) for _ in added[c["id"]]])
              for c in after_claims if c["id"] in ids]
    rounds = {}
    for c in pruned:
        for r in c["repairs"]:
            row = rounds.setdefault(r.get("round", 0), {"anchor": 0, "rewrite": 0, "retire": 0})
            row[r.get("action")] = row.get(r.get("action"), 0) + 1
    return {"claims": len(after_claims), "rechecked": len(pruned),
            "stages": {k: stage_counts(pruned, k) for k in (0, 1, 2)}, "rounds": rounds}


def map_stats(layer):
    doc = layer.get("document") or {}
    sections = [s for s in doc.get("sections") or [] if isinstance(s, dict)]
    overview = next((s for s in sections if s.get("kind") == "overview"), {"blocks": []})
    topics = []
    for b in overview.get("blocks") or []:
        t = b.get("topic")
        if t and t not in topics:
            topics.append(t)
    mods = module_blocks(doc)
    flows = doc.get("flows") or []
    claims = layer.get("claims") or []
    prose = " ".join(t for k, _, _, t in prose_pieces(doc) if k == "overview")
    return {
        "sections": [s.get("kind") for s in sections],
        "topics": topics,
        "modules": len(mods),
        "components": sum(1 for b in mods if len(module_files(b)) > 1),
        "flows": len(flows),
        "hops": sum(len(f.get("hops") or []) for f in flows),
        "claims": len(claims),
        "evidence": sorted(Counter(c.get("evidence") or "none" for c in claims).items(), key=lambda kv: (-kv[1], kv[0])),
        "overview_words": len(words(prose)),
    }


def overview_only(layer):
    doc = layer.get("document") or {}
    return {"sections": [s for s in doc.get("sections") or [] if isinstance(s, dict) and s.get("kind") == "overview"]}


def readability_counts(layer):
    errors, warnings = check_readability(overview_only(layer), strict=True)
    kinds = Counter()
    for w in warnings:
        parts = w.split(": ")
        kinds[parts[2] if len(parts) > 2 else "other"] += 1
    return len(errors), len(warnings), sorted(kinds.items())


# --------------------------------------------------------------------------
# Archive

def read_text(path):
    return path.read_text().strip() if path.is_file() else None


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def stores(root):
    """{repo: store dir} under root (the saved maps)."""
    if not root.is_dir():
        return {}
    return {repo_of_store(p.name): p for p in sorted(root.iterdir()) if (p / "map.json").is_file()}


def load(archive):
    a = {"run1": stores(archive / "run1"), "final": stores(archive / "after-repair"),
         "recheck": stores(archive / "after-recheck")}
    a["repos"] = sorted(set(a["run1"]) | set(a["final"]) | set(a["recheck"]))
    a["passes"] = {}
    run1_start = read_text(archive / "run1" / "start")
    for repo in a["repos"]:
        a["passes"][(repo, "run 1")] = {"start": run1_start, "end": None, "exit": None,
                                        "result": read_json(archive / "run1" / f"{repo}-result.json")}
        for name, sub in (("run 2", "run2"), ("repair", "repair"), ("re-check", "recheck")):
            d = archive / sub / repo
            a["passes"][(repo, name)] = {"start": read_text(d / "start"), "end": read_text(d / "end"),
                                         "exit": read_text(d / "exit"), "result": read_json(d / "result.json")}
    a["demo"] = []
    live = archive / "demo" / "live"
    for q in sorted(live.iterdir()) if live.is_dir() else []:
        events = []
        for f in sorted(q.glob("answer-*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    events.append(e.get("e", e))
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        a["demo"].append({"name": q.name, "qid": read_text(q / "qid"), "result": result})
    a["answers"] = {repo: read_json(p / "answers.json") or {} for repo, p in a["final"].items()}
    return a


def layer(stores_, repo):
    p = stores_.get(repo)
    return read_json(p / "map.json") if p else None


# --------------------------------------------------------------------------
# Output

def rule(ch="-"):
    return ch * WIDTH


def header(name, what):
    return ["", name, rule(), *textwrap.wrap(what, WIDTH)]


def wrap(text, indent="  "):
    """Text verbatim, wrapped at WIDTH on spaces only; its own line breaks are kept."""
    out = []
    for line in text.split("\n"):
        out += textwrap.wrap(line, WIDTH, initial_indent=indent, subsequent_indent=indent,
                             break_long_words=False, break_on_hyphens=False) or [""]
    return out


def fmt_min(m):
    return NOT_RECORDED if m is None else f"{m:.1f}"


def block_runs(a):
    lines = header("runs", "Wall clock from the launcher's start/end files; turns and cost from claude -p's "
                           "JSON result (total_cost_usd: cost at API list price; these were subscription runs). "
                           "The total is all four passes.")
    lines.append(f"  {'repo':<12}{'pass':<9}{'wall min':>14}{'turns':>8}{'cost (list)':>13}{'exit':>14}")
    partial = False
    for repo in a["repos"]:
        total = 0.0
        for name in PASSES:
            p = a["passes"][(repo, name)]
            r = p["result"] or {}
            turns = r.get("num_turns")
            mark = ""
            if r.get("result_index"):
                mark, partial = "*", True
            t = NOT_RECORDED if turns is None else f"{turns}{mark}"
            cost = r.get("total_cost_usd")
            total += cost or 0.0
            c = NOT_RECORDED if cost is None else f"${cost:.2f}"
            lines.append(f"  {repo:<12}{name:<9}{fmt_min(minutes_between(p['start'], p['end'])):>14}{t:>8}{c:>13}"
                         f"{p['exit'] if p['exit'] is not None else NOT_RECORDED:>14}")
        lines.append(f"  {repo:<12}{'total':<9}{'':>14}{'':>8}{f'${total:.2f}':>13}")
    lines.append("")
    lines.append("  claude -p's own session duration (duration_ms), minutes:")
    for repo in a["repos"]:
        for name in PASSES:
            r = a["passes"][(repo, name)]["result"] or {}
            d = r.get("duration_ms")
            v = NOT_RECORDED if d is None else f"{d / 60000:.1f}" + ("*" if r.get("result_index") else "")
            lines.append(f"    {repo:<12}{name:<9}{v:>10}")
    if partial:
        lines += wrap("* result_index > 0: the session ended after background tasks, and the saved JSON is its "
                      "last result event only, so turns and duration_ms cover that last segment; cost "
                      "(total_cost_usd) is the whole session's.", "  ")
    return lines


def block_maps(a):
    lines = header("maps", "Run 1 (old Cartographer brief) against run 2 (Cartographer v2, start over), as saved "
                           "after the repair pass and after the re-check (the final state). Checker verdicts "
                           "are each claim's saved check.")
    for repo in a["repos"]:
        for name, store in (("run 1", a["run1"]), ("run 2 after repair", a["final"]),
                            ("run 2 after re-check", a["recheck"])):
            m = layer(store, repo)
            lines.append(f"  {repo}, {name}")
            if m is None:
                lines.append(f"    {NOT_RECORDED}")
                continue
            s = map_stats(m)
            lines.append(f"    sections            {len(s['sections'])} ({', '.join(s['sections'])})")
            lines += textwrap.wrap(f"{len(s['topics'])} of {len(TOPICS)}"
                                   + (f" ({', '.join(s['topics'])})" if s["topics"] else ""), WIDTH,
                                   initial_indent="    Overview topics     ", subsequent_indent=" " * 24)
            lines.append(f"    module blocks       {s['modules']} ({s['components']} with more than one file)")
            lines.append(f"    flows               {s['flows']} ({s['hops']} hops)")
            lines.append(f"    claims              {s['claims']}")
            v = Counter(claim_state(c, 99) for c in m.get("claims") or [])
            lines.append(f"    Checker verdicts    supported {v['supported']}, not supported {v['not_supported']}"
                         + "".join(f", {k} {v[k]}" for k in ("unchecked", "retired") if v[k]))
            ev = ", ".join(f"{k} {v}" for k, v in s["evidence"])
            lines += textwrap.wrap(ev, WIDTH, initial_indent="    evidence labels     ",
                                   subsequent_indent=" " * 24)
            lines.append(f"    Overview words      {s['overview_words']}")
    return lines


def block_checker(a):
    lines = header("checker", "Map claims by Checker verdict. Run 2's state before repair and after each round is "
                              "derived from each claim's repairs history in the repair pass (a repair at round r "
                              "means it was not supported after round r-1) and its current check.")
    lines.append(f"  {'repo':<12}{'stage':<22}{'supported':>10}{'not supp.':>10}{'unchecked':>10}{'retired':>8}")
    for repo in a["repos"]:
        rows = []
        r1 = layer(a["run1"], repo)
        if r1:
            rows.append(("run 1 (no repair)", {s: Counter(claim_state(c, 99) for c in r1["claims"]).get(s, 0)
                                               for s in STATES}))
        fin = layer(a["final"], repo)
        if fin:
            claims = one_pass(fin["claims"], last_pass(fin["claims"]))
            for stage, label in ((0, "run 2 before repair"), (1, "after repair round 1"),
                                 (2, "after repair round 2")):
                rows.append((label, stage_counts(claims, stage)))
        for label, c in rows:
            lines.append(f"  {repo:<12}{label:<22}{c['supported']:>10}{c['not_supported']:>10}{c['unchecked']:>10}"
                         f"{c['retired']:>8}")
    lines.append("")
    lines.append("  What repair did, per round (one row per repair action taken):")
    lines.append(f"  {'repo':<12}{'round':>5}{'anchors replaced':>18}{'cite more lines':>17}{'rewritten':>11}"
                 f"{'retired':>9}")
    for repo in a["repos"]:
        fin = layer(a["final"], repo)
        summary = repair_summary(one_pass(fin["claims"], last_pass(fin["claims"]))) if fin else {}
        for rnd in sorted(summary):
            s = summary[rnd]
            lines.append(f"  {repo:<12}{rnd:>5}{s['anchor']:>18}{s['wider']:>17}{s['rewrite']:>11}{s['retire']:>9}")
    lines += wrap("anchors replaced = the claim's text kept, its anchors replaced; cite more lines = of those, "
                  "the new anchors cover more source lines than the old; rewritten = the claim's text "
                  "changed to say only what the cited lines show.", "  ")
    return lines


def block_recheck(a):
    lines = header("recheck", "After the repair pass, a batch run re-checked every map claim that states a "
                              "value under the Checker's new \"Compute, don't quote\" rule, then ran the repair "
                              "pass (at most 2 rounds). Wall clock from the launcher's start/end files; turns "
                              "and cost from claude -p's JSON result (cost at API list price). Claims re-checked: "
                              "a checked_at later than every one in the map saved after repair, or a changed "
                              "check, note, anchors or text. States and repairs come from the repairs history "
                              "entries this pass added, numbered by this pass's rounds (the order of their "
                              "timestamps); a repair at round r means not supported after round r-1.")
    lines.append(f"  {'repo':<12}{'wall min':>9}{'turns':>7}{'cost (list)':>13}{'exit':>14}")
    for repo in a["repos"]:
        p = a["passes"][(repo, "re-check")]
        r = p["result"] or {}
        turns, cost = r.get("num_turns"), r.get("total_cost_usd")
        lines.append(f"  {repo:<12}{fmt_min(minutes_between(p['start'], p['end'])):>9}"
                     f"{NOT_RECORDED if turns is None else turns:>7}"
                     f"{NOT_RECORDED if cost is None else f'${cost:.2f}':>13}"
                     f"{p['exit'] if p['exit'] is not None else NOT_RECORDED:>14}")
    sums = {}
    for repo in a["repos"]:
        before, after = layer(a["final"], repo), layer(a["recheck"], repo)
        if before and after:
            sums[repo] = recheck_summary(before["claims"], after["claims"])
    lines.append("")
    lines.append(f"  {'repo':<12}{'map claims':>11}{'re-checked':>12}{'newly not supp.':>17}{'still not supp.':>17}")
    for repo in a["repos"]:
        s = sums.get(repo)
        if s is None:
            lines.append(f"  {repo:<12}{NOT_RECORDED:>11}")
            continue
        lines.append(f"  {repo:<12}{s['claims']:>11}{s['rechecked']:>12}{s['stages'][0]['not_supported']:>17}"
                     f"{s['stages'][2]['not_supported']:>17}")
    lines += wrap("newly not supported = re-checked claims the re-check found not supported (before repair); "
                  "still not supported = of those, not supported after repair round 2.", "  ")
    lines.append("")
    lines.append("  Re-checked claims by state:")
    lines.append(f"  {'repo':<12}{'stage':<22}{'supported':>10}{'not supp.':>10}{'unchecked':>10}{'retired':>8}")
    for repo in a["repos"]:
        s = sums.get(repo)
        for stage, label in ((0, "before repair"), (1, "after repair round 1"), (2, "after repair round 2")):
            if s is None:
                continue
            c = s["stages"][stage]
            lines.append(f"  {repo:<12}{label:<22}{c['supported']:>10}{c['not_supported']:>10}"
                         f"{c['unchecked']:>10}{c['retired']:>8}")
    lines.append("")
    lines.append("  What this pass's repair did, per round (one row per repair action):")
    lines.append(f"  {'repo':<12}{'round':>5}{'anchors replaced':>18}{'rewritten':>11}{'retired':>9}")
    for repo in a["repos"]:
        s = sums.get(repo) or {"rounds": {}}
        for rnd in sorted(s["rounds"]):
            r = s["rounds"][rnd]
            lines.append(f"  {repo:<12}{rnd:>5}{r['anchor']:>18}{r['rewrite']:>11}{r['retire']:>9}")
    return lines


def block_readability(a):
    lines = header("readability", "honeyguide.readability.check_readability(strict=True), the check behind "
                                  "`map validate --strict`, on the Overview section alone, for run 1, run 2 "
                                  "after repair, and run 2 after the re-check (the final maps).")
    lines.append(f"  {'repo':<12}{'map':<20}{'errors':>8}{'warnings':>10}  warnings by kind")
    for repo in a["repos"]:
        for name, store in (("run 1", a["run1"]), ("run 2 after repair", a["final"]),
                            ("run 2 after re-check", a["recheck"])):
            m = layer(store, repo)
            if m is None:
                lines.append(f"  {repo:<12}{name:<20}{NOT_RECORDED:>18}")
                continue
            e, w, kinds = readability_counts(m)
            k = ", ".join(f"{n} {c}" for n, c in kinds) or "none"
            lines += textwrap.wrap(k, WIDTH, initial_indent=f"  {repo:<12}{name:<20}{e:>8}{w:>10}  ",
                                   subsequent_indent=" " * 52)
    return lines


def find_question(a, qid):
    for repo in a["repos"]:
        ans = a["answers"].get(repo) or {}
        q = next((x for x in ans.get("questions") or [] if x.get("id") == qid), None)
        if q:
            r = next((x for x in ans.get("responses") or [] if x.get("id") == q.get("response")), None)
            return repo, q, r
    return None, None, None


def block_demo(a):
    lines = header("demo", "The two live questions, each answered by one claude -p session (stream-json "
                           "transcript; turns, duration_ms and cost from its final result event).")
    for d in a["demo"]:
        repo, q, resp = find_question(a, d["qid"])
        r = d["result"] or {}
        lines.append(f"  {d['name']}")
        lines.append(f"    question id       {d['qid'] or NOT_RECORDED}")
        lines.append(f"    repo              {repo or NOT_RECORDED}")
        if q:
            lines += textwrap.wrap(q.get("text", ""), WIDTH, initial_indent="    question          ",
                                   subsequent_indent=" " * 22)
        lines.append(f"    route (agent)     {(q or {}).get('agent') or NOT_RECORDED}")
        by_type = (r.get("subagent_stats") or {}).get("by_type") or {}
        subs = ", ".join(f"{k.split(':')[-1]} {v}" for k, v in sorted(by_type.items()))
        lines.append(f"    subagents run     {subs or NOT_RECORDED}")
        lines.append(f"    turns             {r.get('num_turns', NOT_RECORDED)}")
        dur = r.get("duration_ms")
        lines.append(f"    wall clock        {NOT_RECORDED if dur is None else f'{dur / 1000:.0f} s'} (claude -p)")
        if q and q.get("created_at") and q.get("answered_at"):
            secs = (parse_time(q["answered_at"]) - parse_time(q["created_at"])).total_seconds()
            lines.append(f"    posted->answered  {secs:.0f} s (answers.json timestamps)")
        cost = r.get("total_cost_usd")
        lines.append(f"    cost (list)       {NOT_RECORDED if cost is None else f'${cost:.2f}'}")
        claims = (resp or {}).get("claims") or []
        c = Counter(x.get("check") or "unchecked" for x in claims)
        lines.append(f"    answer claims     {len(claims)}")
        lines.append(f"    Checker           supported {c.get('supported', 0)}, "
                     f"not supported {c.get('not_supported', 0)}"
                     + "".join(f", {k} {v}" for k, v in sorted(c.items()) if k not in ("supported", "not_supported")))
    return lines


def first_narrowed(a):
    best = None
    for repo in a["repos"]:
        fin = layer(a["final"], repo)
        for claim in (fin or {}).get("claims") or []:
            for rnd, action, before, after, _, _ in repair_steps(claim):
                if action == "rewrite":
                    key = (claim["id"], rnd)
                    if best is None or key < best[0]:
                        best = (key, repo, rnd, before, after)
                    break
    return best


def block_examples(a):
    lines = header("examples", "Text printed verbatim from the saved maps (wrapped at 74 columns on spaces).")
    repo = "nanochat" if "nanochat" in a["repos"] else (a["repos"][0] if a["repos"] else None)
    r1 = layer(a["run1"], repo) if repo else None
    fin = layer(a["final"], repo) if repo else None
    lines.append(f"  (a) {repo}, run 1: the Overview's first block")
    ov = next((s for s in (r1 or {}).get("document", {}).get("sections", []) if s.get("kind") == "overview"), None)
    lines += wrap(block_text(ov["blocks"][0]), "      ") if ov and ov.get("blocks") else [f"      {NOT_RECORDED}"]
    lines.append("")
    lines.append(f"  (b) {repo}, run 2 after repair: the Purpose block(s)")
    ov = next((s for s in (fin or {}).get("document", {}).get("sections", []) if s.get("kind") == "overview"), None)
    purpose = [b for b in (ov or {}).get("blocks", []) if b.get("topic") == "purpose"]
    for i, b in enumerate(purpose):
        if i:
            lines.append("")
        lines += wrap(block_text(b), "      ")
    if not purpose:
        lines.append(f"      {NOT_RECORDED}")
    lines.append("")
    best = first_narrowed(a)
    lines += wrap(f"(c) a rewritten (narrowed) claim, picked as {NARROWED_RULE}", "  ")
    if best:
        (cid, _), crepo, rnd, before, after = best
        lines.append(f"      {cid} ({crepo}, repair round {rnd})")
        lines.append("      before:")
        lines += wrap(before, "        ")
        lines.append("      after:")
        lines += wrap(after, "        ")
    else:
        lines.append(f"      {NOT_RECORDED}")
    lines.append("")
    lines.append(f"  (d) {WRONGLY_PASSED}, the claim the Checker passed")
    claim = None
    for rp in a["repos"]:
        m = layer(a["final"], rp)
        claim = next((c for c in (m or {}).get("claims") or [] if c.get("id") == WRONGLY_PASSED), None)
        if claim:
            lines.append(f"      repo      {rp}")
            break
    if claim:
        lines.append("      text")
        lines += wrap(claim.get("text", ""), "        ")
        lines.append(f"      evidence  {claim.get('evidence')}")
        lines.append(f"      check     {claim.get('check')}"
                     + (f" (note: {claim['check_note']})" if claim.get("check_note") else " (no note)"))
        lines.append(f"      repairs   {len(claim.get('repairs') or [])}")
        for an in claim.get("anchors") or []:
            lines.append(f"      anchor    {an.get('path')}:{an.get('start')}-{an.get('end')}")
            lines += wrap(an.get("anchor", ""), "        ")
    else:
        lines.append(f"      {NOT_RECORDED}")
    lines.append("")
    lines.append(f"  (e) {WRONGLY_PASSED} after the re-check")
    lines += claim_after_recheck(a, WRONGLY_PASSED, with_before=False)
    rp, _, _ = find_claim(a, "recheck", RECHECK_REWRITTEN)
    if rp:
        lines.append("")
        lines.append(f"  (f) {RECHECK_REWRITTEN}, before and after the re-check")
        lines += claim_after_recheck(a, RECHECK_REWRITTEN, with_before=True)
    return lines


def find_claim(a, store, cid):
    for rp in a["repos"]:
        m = layer(a[store], rp)
        c = next((x for x in (m or {}).get("claims") or [] if x.get("id") == cid), None)
        if c:
            return rp, m, c
    return None, None, None


def claim_lines(claim, indent="      "):
    lines = [f"{indent}text"]
    lines += wrap(claim.get("text", ""), indent + "  ")
    lines.append(f"{indent}check     {claim.get('check')}")
    note = claim.get("check_note")
    lines.append(f"{indent}note      {'(empty)' if not note else ''}".rstrip())
    if note:
        lines += wrap(note, indent + "  ")
    for an in claim.get("anchors") or []:
        lines.append(f"{indent}anchor    {an.get('path')}:{an.get('start')}-{an.get('end')}")
        lines += wrap(an.get("anchor", ""), indent + "  ")
    return lines


def claim_after_recheck(a, cid, with_before):
    rp, _, after = find_claim(a, "recheck", cid)
    if not after:
        return [f"      {NOT_RECORDED}"]
    _, _, before = find_claim(a, "final", cid)
    lines = [f"      repo      {rp}"]
    if with_before:
        lines.append("      before (after repair):")
        lines += claim_lines(before, "        ") if before else [f"        {NOT_RECORDED}"]
        lines.append("      after (after re-check):")
        lines += claim_lines(after, "        ")
    else:
        lines += claim_lines(after)
    added = new_repairs(before or {}, after)
    lines.append(f"      re-check repairs  {len(added)}")
    for r in sorted(pass_rounds(added), key=lambda r: r.get("round", 0)):
        lines.append(f"      round {r.get('round')} {r.get('action')}, the Checker's note:")
        lines += wrap(r.get("check_note", ""), "        ")
    return lines


def render(archive):
    a = load(archive)
    status(f"repos: {', '.join(a['repos'])}; demo questions: {len(a['demo'])}")
    lines = ["Honeyguide runs: receipts", rule("="),
             f"  archive   {archive.parent.name}/{archive.name} (read only)",
             f"  repos     {', '.join(a['repos'])}"]
    for block in (block_runs, block_maps, block_checker, block_recheck, block_readability, block_demo,
                  block_examples):
        status(f"block {block.__name__[6:]}")
        lines += block(a)
    return "\n".join(line.rstrip() for line in lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = ap.parse_args(argv)
    sys.stdout.write(render(args.archive))


if __name__ == "__main__":
    main()
