"""Print the receipts of the two refresh experiments (E2: nanochat across its July rewrite; E3: waku-agent, an
ordinary day).

    uv run python eval/refresh/capture.py > outputs/refresh.txt 2> outputs/refresh.err

Reads the refresh archive (default ~/Documents/GitHub/honeyguide-targets/_refresh, or --archive DIR), the runs
receipt (outputs/runs.txt, for E3's rebuild) and which Honeyguide commit each run started on: from
eval/refresh/run_commits.json, a record frozen once from the honeyguide-run worktree's HEAD reflog (git expires
reflog entries), else from that reflog live. Never writes to any of them, except

    uv run python eval/refresh/capture.py --freeze-run-commits

which writes eval/refresh/run_commits.json from the live reflog, with the time it was read, and refuses to
overwrite it.
Prints six labelled blocks: commits, plan, cost, refresh, current-but-false, build. Every number is read from
the archive, git or runs.txt; a value none of them holds prints as "not recorded". Nothing is read from an agent's
prose (its ``result`` text, activity statuses, retire reasons). Repos are printed by name, never by path.
Standard library only, plus honeyguide's own constants and eval/common/pylines.py.
"""

import argparse
import json
import subprocess
import sys
import textwrap
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from pylines import METHOD as PY_LINES_METHOD  # noqa: E402
from pylines import py_lines  # noqa: E402

try:
    from honeyguide.refresh import CLAIM_STATES
    from honeyguide.store import FRESHNESS
except ImportError:   # run outside the uv environment
    sys.path.insert(0, str(HERE.parents[1] / "src"))
    from honeyguide.refresh import CLAIM_STATES
    from honeyguide.store import FRESHNESS

WIDTH = 74
NOT_RECORDED = "not recorded"
GITHUB = Path.home() / "Documents" / "GitHub"
DEFAULT_ARCHIVE = GITHUB / "honeyguide-targets" / "_refresh"
DEFAULT_RUNS_TXT = HERE.parents[1] / "outputs" / "runs.txt"
DEFAULT_RUN_WORKTREE = GITHUB / "honeyguide-run"
DEFAULT_RUN_COMMITS = HERE / "run_commits.json"
REFLOG_ARGS = ("reflog", "--date=iso-strict", "--format=%H%x09%gd")
SHORT = 7
CURRENT_CLASSES = ("unchanged", "moved")   # the plan's "still current" classes

# What each experiment's archive holds. ``runs``: (label, subdir) in order (label: as the cost block prints it;
# short: as the commits block's run table prints it); ``refresh``: the subdirs that make up
# the refresh (the first one's start is the refresh's start); ``rebuild``: a subdir of this archive, or
# ("runs.txt", repo, passes) for a pipeline read from the runs receipt; ``rebuild_extra``: a pass of that pipeline
# with no counterpart in a one-run build (Explore, Checker, repair), so the ratio is also printed without it.
EXPERIMENTS = (
    {"name": "E2", "title": "nanochat across its July rewrite", "dir": "e2", "checkout": "nanochat",
     "runs": (("build", "build", "E2 build"), ("refresh", "refresh", "E2 refresh")), "refresh": ("refresh",),
     "rebuild": "build",
     "build_block": True},
    {"name": "E3", "title": "waku-agent, an ordinary day", "dir": "e3", "checkout": "waku-agent",
     "runs": (("refresh, attempt 1", "run", "E3 refresh, attempt 1"),
              ("refresh, attempt 2", "run2", "E3 refresh, attempt 2")), "refresh": ("run", "run2"),
     "rebuild": ("runs.txt", "waku-agent", ("run 2", "repair", "re-check")), "rebuild_extra": "re-check",
     "build_block": False},
)


def status(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Pure helpers (tested in tests/test_refresh_capture.py)

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


def days_between(a, b):
    """Days from datetime a to datetime b, or None when either is missing."""
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 86400


def ratio(num, den):
    return None if num is None or not den else num / den


def parse_reflog(text):
    """[(UTC datetime, full sha)] from ``git reflog --date=iso-strict --format=%H%x09%gd``, newest first."""
    out = []
    for line in (text or "").splitlines():
        if "\t" not in line:
            continue
        sha_, sel = line.split("\t", 1)
        if "@{" not in sel:
            continue
        stamp = sel[sel.index("@{") + 2:sel.rindex("}")]
        out.append((datetime.fromisoformat(stamp).astimezone(timezone.utc), sha_))
    return out


def head_at(entries, when):
    """(sha, since) for the reflog entry in force at ``when`` (an ISO-Z string): the latest one at or before it.
    ``entries`` are newest first, as git lists them (parse_reflog keeps that order), so the first entry at or
    before ``when`` is the HEAD move that came last; two moves in the same second are told apart by that order,
    not by their shas. None when ``when`` is missing or the reflog holds nothing that early."""
    if not when:
        return None
    t = parse_time(when).replace(tzinfo=timezone.utc)
    hit = next(((at, s) for at, s in entries if at <= t), None)
    if hit is None:
        return None
    at, s = hit
    return s, at


def iso_z(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def freeze_run_commits(runs, reflog, read_at):
    """The run-commit record: for each (label, start) run, the reflog entry in force at its start (head_at), with
    the time the reflog was read (``read_at``, a datetime). Written once to run_commits.json, so the table
    survives the reflog's expiry."""
    out = []
    for label, start in runs:
        at = head_at(reflog, start)
        out.append({"run": label, "start": start, "commit": at[0] if at else None,
                    "since": iso_z(at[1]) if at else None})
    return {"read_at": iso_z(read_at), "source": "git " + " ".join(REFLOG_ARGS) + " in the honeyguide-run worktree",
            "runs": out}


def run_heads(runs, reflog, record):
    """{label: ((sha, since) or None, source)} for (label, start) runs. The record's entry is used when its run
    and start match and it holds a commit (source 'record'); otherwise the live reflog (source 'reflog')."""
    rec = {(r.get("run"), r.get("start")): r for r in (record or {}).get("runs") or []}
    out = {}
    for label, start in runs:
        r = rec.get((label, start))
        if start and r and r.get("commit") and r.get("since"):
            out[label] = ((r["commit"], parse_time(r["since"]).replace(tzinfo=timezone.utc)), "record")
        else:
            out[label] = (head_at(reflog, start), "reflog")
    return out


def run_summary(result):
    """The numbers a claude -p JSON result holds (None for each one it does not)."""
    r = result or {}
    mu = r.get("modelUsage") or {}
    dur = r.get("duration_ms")

    def tok(key):
        return sum(m.get(key) or 0 for m in mu.values()) if mu else None
    return {
        "cost": r.get("total_cost_usd"),
        "session_min": None if dur is None else dur / 60000,
        "turns": r.get("num_turns"),
        "partial": bool(r.get("result_index")),
        "subtype": r.get("subtype"),
        "input": tok("inputTokens"), "cache_read": tok("cacheReadInputTokens"),
        "cache_write": tok("cacheCreationInputTokens"), "output": tok("outputTokens"),
        "models": [(name, m.get("costUSD")) for name, m in sorted(mu.items())],
        "denials": [d.get("tool_name") or "?" for d in r.get("permission_denials") or []],
        "subagents": dict(sorted(((r.get("subagent_stats") or {}).get("by_type") or {}).items())),
    }


def add(values):
    """Sum of values, or None when any is missing."""
    values = list(values)
    return None if any(v is None for v in values) or not values else sum(values)


def plan_classes(plan):
    """{claim id: plan state} from a refresh-plan --json output."""
    return {c["id"]: c["state"] for c in (plan or {}).get("claims") or []}


def plan_counts(plan):
    found = Counter(plan_classes(plan).values())
    return {s: found.get(s, 0) for s in CLAIM_STATES}


def uncovered_counts(plan):
    found = Counter(u.get("change") for u in (plan or {}).get("uncovered") or [])
    return {k: found.get(k, 0) for k in ("new", "changed")}


def freshness_counts(claims):
    found = Counter(c.get("freshness") for c in claims)
    return {f: found.get(f, 0) for f in FRESHNESS}


def retired_by_repair(claim):
    """True when the claim's retirement is a repair pass's ``retire`` action (same stamp)."""
    at = claim.get("retired_at")
    return bool(at) and any(r.get("action") == "retire" and r.get("at") == at for r in claim.get("repairs") or [])


def retired_before(claim, start):
    """True when the claim was already retired when the refresh started: retired, with a retired_at before
    ``start`` or none at all (refresh apply stamps none, so a claim an earlier refresh retired has none)."""
    return claim.get("freshness") == "retired" and (claim.get("retired_at") or "") < start


def new_claims(plan, claims, start):
    """The claims the refresh added: ids the plan does not list, less claims already retired before ``start``.
    The plan lists every claim saved before the refresh except the retired ones (plan_refresh skips them), so
    a claim a build's repair pass retired is missing from the plan without being new."""
    classes = plan_classes(plan)
    return [c for c in claims if c["id"] not in classes and not retired_before(c, start)]


def refresh_outcome(plan, claims, start):
    """What the refresh did, from the plan taken before it and the store saved after it.

    ``start`` is the refresh's start (ISO-Z). New claims: see new_claims. Retired by refresh apply: the plan
    classed it retired and it is retired now (apply_result stamps no retired_at). Retired later in the refresh:
    a retired_at at or after ``start``; split into the repair pass's ``retire`` and the re-map's (claims save /
    claims retire)."""
    classes = plan_classes(plan)
    by_id = {c["id"]: c for c in claims}
    new = new_claims(plan, claims, start)
    later = [c for c in claims if (c.get("retired_at") or "") >= start and c.get("freshness") == "retired"]
    remap = [c for c in later if not retired_by_repair(c)]
    by_class = Counter(classes.get(c["id"], "new") for c in remap)
    stale = [by_id[i] for i, s in classes.items() if s == "stale" and i in by_id]
    rechecked = [c for c in stale if (c.get("rechecked_at") or "") >= start]
    held = [c for c in rechecked if c.get("check") == "supported"]
    not_held = [c for c in rechecked if c.get("check") == "not_supported"]
    return {
        "after": freshness_counts(claims), "total": len(claims),
        "missing_from_store": sum(1 for i in classes if i not in by_id),
        "retired_before": sum(1 for c in claims if c["id"] not in classes and retired_before(c, start)),
        "retired_by_apply": sum(1 for i, s in classes.items()
                                if s == "retired" and (by_id.get(i) or {}).get("freshness") == "retired"),
        "retired_by_remap": len(remap), "retired_by_repair": len(later) - len(remap),
        "remap_by_class": {s: by_class.get(s, 0) for s in (*CLAIM_STATES, "new")},
        "new": len(new),
        "stale": len(stale), "stale_rechecked": len(rechecked), "stale_held": len(held),
        "stale_not_held": len(not_held),
        "stale_held_retired": sum(1 for c in held if c.get("freshness") == "retired"),
        "stale_not_held_retired": sum(1 for c in not_held if c.get("freshness") == "retired"),
        "stale_left_stale": sum(1 for c in stale if c.get("freshness") == "stale"),
    }


def repairs_in(claim, start, before=False):
    """The claim's repair entries at or after ``start`` (or, with ``before``, earlier)."""
    return [r for r in claim.get("repairs") or [] if ((r.get("at") or "") < start) == before]


def stage_verdicts(claims, start, stage):
    """New claims' Checker state after repair round ``stage`` of the refresh (0 = first check).

    A repair at round r (in the refresh) means the claim was not supported after round r-1; otherwise its saved
    check holds, read only when it was set during the refresh (checked_at at or after ``start``)."""
    out = Counter()
    for c in claims:
        if any((r.get("round") or 0) > stage for r in repairs_in(c, start)):
            out["not_supported"] += 1
        elif (c.get("checked_at") or "") >= start:
            out[c.get("check") or "unchecked"] += 1
        else:
            out[NOT_RECORDED] += 1
    return out


def rounds_summary(claims, start, before=False):
    """{round: {action: count}} for repair entries in (or, with ``before``, before) the refresh."""
    out = {}
    for c in claims:
        for r in repairs_in(c, start, before):
            row = out.setdefault(r.get("round") or 0, Counter())
            row[r.get("action") or "?"] += 1
    return out


def new_claim_verdicts(plan, claims, start):
    classes = plan_classes(plan)
    new = new_claims(plan, claims, start)
    old_repaired = sum(1 for c in claims if c["id"] in classes and repairs_in(c, start))
    passes = {r.get("pass") for c in claims for r in repairs_in(c, start)}
    return {"first": stage_verdicts(new, start, 0), "after": {k: stage_verdicts(new, start, k) for k in (1, 2)},
            "rounds": rounds_summary(claims, start), "old_repaired": old_repaired, "passes": len(passes)}


def current_but_false(plan, claims, start):
    """Claims the plan classed unchanged or moved (served as current) that the re-map retired in the refresh."""
    out = refresh_outcome(plan, claims, start)
    counts = plan_counts(plan)
    return {s: (out["remap_by_class"][s], counts[s]) for s in CLAIM_STATES}


def build_history(plan, claims, start):
    """The build's first check and repair rounds, from the repairs history saved before ``start``.

    A claim repaired in round r was not supported after round r-1. A claim the build never repaired kept its first
    verdict, readable only when nothing later overwrote it (checked_at before ``start``)."""
    classes = plan_classes(plan)
    built = [c for c in claims if c["id"] in classes]
    flagged = {r: sum(1 for c in built if any((e.get("round") or 0) == r for e in repairs_in(c, start, True)))
               for r in (1, 2)}
    unrepaired = [c for c in built if not repairs_in(c, start, True)]
    last = [c for c in built if any((e.get("round") or 0) == 2 for e in repairs_in(c, start, True))]

    def kept(cs):
        out = Counter()
        for c in cs:
            out[c.get("check") if (c.get("checked_at") or "") < start else NOT_RECORDED] += 1
        return out
    return {"claims": len(built), "flagged": flagged, "unrepaired": len(unrepaired),
            "unrepaired_verdicts": kept(unrepaired), "last_round": len(last), "last_verdicts": kept(last),
            "rounds": rounds_summary(built, start, before=True)}


def uncovered_mapped(plan, claims, ids=None):
    """Plan's uncovered units cited after the refresh by a current claim's anchor at the target (overlapping
    lines), optionally only claims in ``ids``. Returns {change kind: (cited, total)}."""
    target = (plan or {}).get("target")
    spans = [(a.get("path"), a.get("start"), a.get("end")) for c in claims
             if c.get("freshness") == "current" and (ids is None or c["id"] in ids)
             for a in c.get("anchors") or [] if a.get("commit") == target]
    out = {}
    for u in (plan or {}).get("uncovered") or []:
        hit = any(p == u["path"] and s is not None and s <= u["end"] and e >= u["start"] for p, s, e in spans)
        cited, total = out.get(u["change"], (0, 0))
        out[u["change"]] = (cited + hit, total + 1)
    return out


def parse_runs_block(text, repo):
    """{pass: {wall, turns, cost, exit}} for ``repo`` from runs.txt's 'runs' block (the first table, the
    house layout of eval/runs/capture.py: repo 12, pass 9, wall 14, turns 8, cost 13, exit 14)."""
    lines = (text or "").splitlines()
    try:
        i = lines.index("runs")
    except ValueError:
        return {}
    out = {}
    for line in lines[i + 2:]:
        if not line.strip():
            if out:
                break
            continue
        if line[2:14].strip() != repo:
            continue
        name = line[14:23].strip()
        wall, turns, cost, ex = (line[23:37].strip(), line[37:45].strip(), line[45:58].strip(),
                                 line[58:72].strip())
        out[name] = {"wall": None if wall in ("", NOT_RECORDED) else float(wall),
                     "turns": turns or None,
                     "cost": float(cost[1:]) if cost.startswith("$") else None,
                     "exit": ex or None}
    return out


# --------------------------------------------------------------------------
# Archive

def read_text(path):
    return path.read_text().strip() if path.is_file() else None


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def git(checkout, *args):
    """git's stdout in ``checkout`` (stripped), or None when it is missing or git fails."""
    if not (checkout / ".git").exists():
        return None
    try:
        p = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def commit_date(checkout, sha):
    out = git(checkout, "log", "-1", "--format=%cI", sha) if sha else None
    return datetime.fromisoformat(out).astimezone(timezone.utc) if out else None


def diff_stat(checkout, base, target, *paths):
    """(files, insertions, deletions) from git diff --numstat, or None."""
    if not base or not target:
        return None
    out = git(checkout, "diff", "--numstat", base, target, "--", *paths)
    if out is None:
        return None
    files = ins = dels = 0
    for line in out.splitlines():
        a, d, _ = line.split("\t", 2)
        files += 1
        ins += int(a) if a.isdigit() else 0
        dels += int(d) if d.isdigit() else 0
    return files, ins, dels


def store_dir(edir):
    home = edir / "home"
    found = sorted(p for p in home.iterdir() if (p / "map.json").is_file()) if home.is_dir() else []
    return found[0] if found else None


def load_experiment(archive, spec, runs_txt):
    edir = archive / spec["dir"]
    e = dict(spec)
    e["runs_data"] = []
    for label, sub, short in spec["runs"]:
        d = edir / sub
        e["runs_data"].append({"label": label, "sub": sub, "short": short, "start": read_text(d / "start"),
                               "end": read_text(d / "end"), "exit": read_text(d / "exit"),
                               "result": read_json(d / "result.json")})
    e["refresh_start"] = next((r["start"] for r in e["runs_data"] if r["sub"] == spec["refresh"][0]), None)
    e["plan"] = read_json(edir / "refresh_plan_before.json")
    sd = store_dir(edir)
    e["store_id"] = sd.name if sd else None
    e["repo"] = repo_of_store(sd.name) if sd else spec["checkout"]
    m = read_json(sd / "map.json") if sd else None
    e["map"] = m
    e["claims"] = (m or {}).get("claims") or []
    e["session"] = read_json(sd / "session.json") if sd else None
    co = edir / spec["checkout"]
    plan = e["plan"] or {}
    base, target = plan.get("base"), plan.get("target")
    e["git"] = {
        "base": base, "target": target,
        "base_date": commit_date(co, base), "target_date": commit_date(co, target),
        "count": git(co, "rev-list", "--count", f"{base}..{target}") if base and target else None,
        "py": diff_stat(co, base, target, "*.py"), "all": diff_stat(co, base, target),
        "py_base": py_lines(co, base), "py_target": py_lines(co, target),
    }
    rb = spec["rebuild"]
    if isinstance(rb, tuple):
        rows = parse_runs_block(runs_txt, rb[1])
        e["rebuild"] = {"source": "runs.txt", "rows": [(p, rows.get(p)) for p in rb[2]]}
    else:
        e["rebuild"] = {"source": rb}
    return e


# --------------------------------------------------------------------------
# Output

def rule(ch="-"):
    return ch * WIDTH


def header(name, what):
    return ["", name, rule(), *textwrap.wrap(what, WIDTH)]


def wrap(text, indent="  ", sub=None):
    return textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=sub or indent,
                         break_long_words=False, break_on_hyphens=False) or [indent]


def nr(v, fmt="{}"):
    return NOT_RECORDED if v is None else fmt.format(v)


def money(v):
    return nr(v, "${:.2f}")


def mins(v):
    return nr(v, "{:.1f}")


def tokens(v):
    return nr(v, "{:,}")


def table_row(label, cells, widths, indent="    ", first=22):
    """One table row; when a "not recorded" would not fit its column, the row as a wrapped list instead."""
    row = f"{indent}{label:<{first}}" + "".join(f"{v:>{w}}" for (_, v), w in zip(cells, widths, strict=True))
    if len(row) <= WIDTH and all(len(v) < w for (_, v), w in zip(cells, widths, strict=True)):
        return [row]
    return wrap(f"{label}: " + ", ".join(f"{k} {v}" for k, v in cells), indent, indent + "  ")


def sha(s):
    return s[:SHORT] if s else NOT_RECORDED


def when(d):
    return d.strftime("%Y-%m-%d %H:%M UTC") if d else NOT_RECORDED


def exp_title(e):
    return f"  {e['name']}  {e['repo']}: {e['title']}"


def all_runs(exps):
    """(short label, start) for every run of every experiment, in order."""
    return [(r["short"], r["start"]) for e in exps for r in e["runs_data"]]


def run_commits(exps, heads):
    """[(short label, start, (sha, since) or None)] for every run, from run_heads."""
    return [(short, start, heads[short][0]) for short, start in all_runs(exps)]


def heads_source(heads, record, record_name):
    """The sentence saying where the run-commit table was read from."""
    n = sum(1 for _, src in heads.values() if src == "record")
    read = (record or {}).get("read_at") or ""
    day = f"{read[:10]} {read[11:16]} UTC" if read else NOT_RECORDED
    if n and n == len(heads):
        return f"Read from {record_name}, frozen from that reflog at {day} (git expires reflog entries)."
    if n:
        return (f"{n} of {len(heads)} runs read from {record_name} (frozen from that reflog at {day}); the rest "
                "from the live reflog.")
    return "Read from the live reflog (no frozen record of these runs)."


def block_commits(exps, heads, source=""):
    lines = header("commits", "Base and target are the refresh plan's; dates are git committer dates; commits "
                              "in between from git rev-list --count base..target; files from git diff --numstat "
                              f"base target; Python lines: {PY_LINES_METHOD}; all in each experiment's checkout.")
    for e in exps:
        g = e["git"]
        lines.append(exp_title(e))
        lines.append(f"    base                {sha(g['base'])}  {when(g['base_date'])}")
        lines.append(f"    target              {sha(g['target'])}  {when(g['target_date'])}")
        lines.append(f"    days apart          {nr(days_between(g['base_date'], g['target_date']), '{:.1f}')}")
        lines.append(f"    commits in between  {nr(g['count'])}")
        for label, st in ((".py files changed", g["py"]), ("all files changed", g["all"])):
            v = NOT_RECORDED if st is None else f"{st[0]} (+{st[1]} / -{st[2]} lines)"
            lines.append(f"    {label:<20}{v}")
        for label, pl in ((".py lines at base", g["py_base"]), (".py lines at target", g["py_target"])):
            v = NOT_RECORDED if pl is None else f"{pl[1]:,} in {pl[0]} files"
            lines.append(f"    {label:<20}{v}")
    lines.append("")
    lines += wrap("Honeyguide code at each run's start: the commit the honeyguide-run worktree's HEAD was on "
                  "(its reflog, git reflog --date=iso-strict) at the time in the run's start file. The reflog "
                  "records HEAD moves, not uncommitted edits." + (f" {source}" if source else ""), "  ")
    lines.append(f"    {'run':<22}{'start (UTC)':<20}{'commit':<9}{'HEAD on it since'}")
    rows = run_commits(exps, heads)
    for short, start, at in rows:
        st = parse_time(start).strftime("%Y-%m-%d %H:%M:%S") if start else NOT_RECORDED
        lines.append(f"    {short:<22}{st:<20}" + (f"{sha(at[0]):<9}{at[1].strftime('%Y-%m-%d %H:%M:%S')}"
                                                     if at else NOT_RECORDED))
    shas = {at[0] for _, _, at in rows if at}
    if rows and len(shas) == 1 and all(at for _, _, at in rows):
        lines.append(f"    all {len(rows)} runs started on the same commit, {sha(next(iter(shas)))}")
    return lines


def block_plan(exps):
    lines = header("plan", "honeyguide refresh-plan --json, taken before each refresh: every saved claim's class "
                           "from its anchors (unanchored: no code anchors, left as it is) and the new or changed "
                           "Python units no live claim cites. 'applied' rows are the store's session refresh_log.")
    for e in exps:
        lines.append(exp_title(e))
        if e["plan"] is None:
            lines.append(f"    {NOT_RECORDED}")
            continue
        c, u = plan_counts(e["plan"]), uncovered_counts(e["plan"])
        lines.append(f"    plan                {sha(e['plan'].get('base'))} -> {sha(e['plan'].get('target'))}")
        lines.append(f"    claims              {sum(c.values())}")
        for s in CLAIM_STATES:
            lines.append(f"      {s:<18}{c[s]:>5}")
        lines.append(f"    uncovered units     {sum(u.values())} (new {u['new']}, changed {u['changed']})")
        lines.append(f"    changed files with no outline (not Python)  {len(e['plan'].get('unoutlined') or [])}")
        log = (e["session"] or {}).get("refresh_log")
        if log is None:
            lines.append(f"    applied             {NOT_RECORDED}")
        for entry in log or []:
            counts = ", ".join(f"{k} {v}" for k, v in (entry.get("counts") or {}).items())
            lines += wrap(f"applied {entry.get('at') or NOT_RECORDED}: {sha(entry.get('base'))} -> "
                          f"{sha(entry.get('target'))}; {counts}; uncovered {nr(entry.get('uncovered'))}",
                          "    ", "      ")
    return lines


def run_rows(e):
    """(label, summary, wall minutes, exit) for every run of ``e`` from its archive."""
    rows = []
    for r in e["runs_data"]:
        s = run_summary(r["result"])
        rows.append((r["label"], s, minutes_between(r["start"], r["end"]), r["exit"], r["result"] is not None))
    return rows


def block_cost(exps, heads=None):
    lines = header("cost", "Each run on its own line. $ = total_cost_usd from claude -p's JSON result (API list "
                           "price; subscription runs). wall = the launcher's end - start; session = duration_ms. "
                           "Tokens and models from modelUsage (the whole session, subagents included). "
                           "Ratios are refresh / rebuild on $ and wall minutes.")
    for e in exps:
        lines.append(exp_title(e))
        rows = run_rows(e)
        lines.append(f"    {'run':<22}{'$ list':>9}{'wall min':>10}{'session':>9}{'turns':>7}{'exit':>6}")
        for label, s, wall, ex, _ in rows:
            t = nr(s["turns"]) + ("*" if s["partial"] else "")
            lines += table_row(label, [("$ list", money(s["cost"])), ("wall min", mins(wall)),
                                       ("session", mins(s["session_min"])), ("turns", t), ("exit", nr(ex))],
                               (9, 10, 9, 7, 6))
        refresh = [(s, w) for (label, s, w, _, _), r in zip(rows, e["runs_data"], strict=True) if r["sub"] in e["refresh"]]
        if len(refresh) > 1:
            lines += table_row("refresh total", [("$ list", money(add(s["cost"] for s, _ in refresh))),
                                                 ("wall min", mins(add(w for _, w in refresh))),
                                                 ("session", mins(add(s["session_min"] for s, _ in refresh)))],
                               (9, 10, 9))
        lines.append("")
        lines.append(f"    {'tokens':<22}{'input':>9}{'cache read':>13}{'cache write':>13}{'output':>11}")
        for label, s, _, _, _ in rows:
            lines += table_row(label, [("input", tokens(s["input"])), ("cache read", tokens(s["cache_read"])),
                                       ("cache write", tokens(s["cache_write"])), ("output", tokens(s["output"]))],
                               (9, 13, 13, 11))
        lines.append("")
        for label, s, _, _, present in rows:
            models = ", ".join(f"{m} ({money(c)})" for m, c in s["models"]) or NOT_RECORDED
            lines += wrap(f"{label}: models {models}", "    ", "      ")
            subs = ", ".join(f"{k.split(':')[-1]} {v}" for k, v in s["subagents"].items()) or NOT_RECORDED
            lines += wrap(f"subagents {subs}; result {nr(s['subtype'])}; permission denials "
                          f"{len(s['denials']) if present else NOT_RECORDED}"
                          + (f" ({', '.join(f'{k} {v}' for k, v in sorted(Counter(s['denials']).items()))})"
                             if s["denials"] else ""), "      ")
        lines += denial_lines(e)
        lines.append("")
        lines += rebuild_lines(e, rows, heads)
    if any(s["partial"] for e in exps for _, s, _, _, _ in run_rows(e)):
        lines += wrap("* result_index > 0: turns and session minutes cover the last result segment only.", "  ")
    return lines


def denial_lines(e):
    """Files a run's denied Write/Edit calls aimed at, relative to the store (so no path is printed)."""
    out = []
    for r in e["runs_data"]:
        files = []
        for d in (r["result"] or {}).get("permission_denials") or []:
            fp = (d.get("tool_input") or {}).get("file_path")
            if fp and e["store_id"] and f"/{e['store_id']}/" in fp:
                files.append(fp.split(f"/{e['store_id']}/", 1)[1])
        if files:
            out += wrap(f"{r['label']}: denied writes into the store: "
                        + ", ".join(f"{f} x{n}" for f, n in sorted(Counter(files).items())), "    ", "      ")
    return out


def rebuild_lines(e, rows, heads=None):
    rb = e["rebuild"]
    refresh = [(s, w) for (_, s, w, _, _), r in zip(rows, e["runs_data"], strict=True) if r["sub"] in e["refresh"]]
    r_cost, r_wall = add(s["cost"] for s, _ in refresh), add(w for _, w in refresh)
    lines = []
    if rb["source"] == "runs.txt":
        lines += wrap("rebuild: the waku-agent full pipeline at its pin, from runs.txt's runs block (run 2 + "
                      "repair + re-check). It ran on older Honeyguide code (runs.txt does not record which "
                      "commit) and was a different invocation: three separate claude -p passes, not one.", "    ")
        lines.append(f"    {'rebuild pass':<22}{'$ list':>9}{'wall min':>10}{'turns':>7}")
        for name, row in rb["rows"]:
            row = row or {}
            lines += table_row(name, [("$ list", money(row.get("cost"))), ("wall min", mins(row.get("wall"))),
                                      ("turns", nr(row.get("turns")))], (9, 10, 7))
        b_cost = add((row or {}).get("cost") for _, row in rb["rows"])
        b_wall = add((row or {}).get("wall") for _, row in rb["rows"])
        lines += table_row("rebuild total", [("$ list", money(b_cost)), ("wall min", mins(b_wall))], (9, 10))
        extra = e.get("rebuild_extra")
        if extra:
            kept = [row for name, row in rb["rows"] if name != extra]
            x_cost = add((row or {}).get("cost") for row in kept)
            x_wall = add((row or {}).get("wall") for row in kept)
            lines += table_row(f"rebuild less {extra}", [("$ list", money(x_cost)), ("wall min", mins(x_wall))],
                               (9, 10))
        lines.append(f"    {'rebuild tokens':<22}{NOT_RECORDED} (runs.txt holds none)")
        lines.append("    (* in runs.txt: turns of the last result segment only)")
    else:
        at = {r["sub"]: (heads or {}).get(r["short"], (None, None))[0] for r in e["runs_data"]}
        mine = [at.get(sub) for sub in (rb["source"], *e["refresh"])]
        if all(mine) and len({m[0] for m in mine}) == 1:
            code = f"same Honeyguide commit as the refresh, {sha(mine[0][0])}, by the reflog"
        elif all(mine):
            code = "a different Honeyguide commit from the refresh, by the reflog"
        else:
            code = f"Honeyguide commit {NOT_RECORDED}"
        lines += wrap(f"rebuild: the {rb['source']} above ({code}; full Explore + Checker + repair at the base "
                      "commit).", "    ")
        s, w = next(((s, w) for (_, s, w, _, _), r in zip(rows, e["runs_data"], strict=True) if r["sub"] == rb["source"]),
                    (run_summary(None), None))
        b_cost, b_wall = s["cost"], w
    label = "refresh (both attempts)" if len(refresh) > 1 else "refresh"
    lines.append(f"    {label} / rebuild:  $ {nr(ratio(r_cost, b_cost), '{:.2f}')}, "
                 f"wall minutes {nr(ratio(r_wall, b_wall), '{:.2f}')}")
    if len(refresh) > 1:
        s, w = refresh[-1]
        lines.append(f"    last attempt only / rebuild:  $ {nr(ratio(s['cost'], b_cost), '{:.2f}')}, "
                     f"wall minutes {nr(ratio(w, b_wall), '{:.2f}')}")
    if rb["source"] == "runs.txt" and e.get("rebuild_extra"):
        extra = e["rebuild_extra"]
        lines += wrap(f"The {extra} pass has no counterpart in a one-run build (E2's: Explore, Checker, "
                      f"repair); the ratio without it:", "    ")
        who = "both attempts" if len(refresh) > 1 else "refresh"
        lines += wrap(f"{who} / rebuild less {extra}:  $ {nr(ratio(r_cost, x_cost), '{:.2f}')}, "
                      f"wall minutes {nr(ratio(r_wall, x_wall), '{:.2f}')}", "    ", "      ")
    return lines


def block_refresh(exps):
    lines = header("refresh", "What the refresh did, from the store saved after it and the plan taken before "
                              "it (never the agent's prose). Refresh start = the first refresh run's start. "
                              "New claims: ids the plan does not list, less any already retired before the "
                              "refresh (the plan skips retired claims). Retired by refresh apply: classed "
                              "retired by the plan. Retired by the re-map: a retired_at in the refresh, not a "
                              "repair's retire. Verdicts: each claim's saved check; a repair at round r in the "
                              "refresh means not supported after round r-1.")
    for e in exps:
        lines.append(exp_title(e))
        if e["plan"] is None or e["map"] is None or not e["refresh_start"]:
            lines.append(f"    {NOT_RECORDED}")
            continue
        start, plan, claims = e["refresh_start"], e["plan"], e["claims"]
        o = refresh_outcome(plan, claims, start)
        commit = e["map"].get("commit")
        same = " (= target)" if commit and commit == plan.get("target") else ""
        lines.append(f"    map commit after    {sha(commit)}{same}")
        lines.append(f"    claims after        {o['total']}: " + ", ".join(f"{k} {v}" for k, v in o["after"].items()))
        if o["missing_from_store"]:
            lines.append(f"    plan claims missing from the store  {o['missing_from_store']}")
        if o["retired_before"]:
            lines.append(f"    retired before the refresh (not in the plan)  {o['retired_before']}")
        lines.append(f"    retired in the refresh  {o['retired_by_apply'] + o['retired_by_remap'] + o['retired_by_repair']}")
        lines.append(f"      by refresh apply (plan: retired)    {o['retired_by_apply']:>4}")
        lines.append(f"      by the re-map                       {o['retired_by_remap']:>4}")
        lines.append(f"      by the repair pass (retire)         {o['retired_by_repair']:>4}")
        bc = o["remap_by_class"]
        lines += wrap("re-map retirements by plan class: " + ", ".join(f"{k} {bc[k]}" for k in bc), "      ",
                      "        ")
        lines.append(f"    new claims          {o['new']}")
        for label, ids in (("by a new claim", {c["id"] for c in new_claims(plan, claims, start)}),
                           ("by any current claim", None)):
            m = uncovered_mapped(plan, claims, ids)
            parts = ", ".join(f"{k} {m[k][0]} of {m[k][1]}" for k in ("new", "changed") if k in m)
            lines += wrap(f"uncovered units cited {label} (anchor at target, lines overlap): "
                          f"{sum(v[0] for v in m.values())} of {sum(v[1] for v in m.values())}"
                          + (f" ({parts})" if parts else ""), "    ", "      ")
        lines.append(f"    stale claims        {o['stale']}, re-checked in the refresh {o['stale_rechecked']}")
        lines.append(f"      {'Checker on re-check':<32}{'claims':>7}{'then re-map retired':>21}")
        lines.append(f"      {'still held (supported)':<32}{o['stale_held']:>7}{o['stale_held_retired']:>21}")
        lines.append(f"      {'no longer held (not supported)':<32}{o['stale_not_held']:>7}"
                     f"{o['stale_not_held_retired']:>21}")
        lines.append(f"      {'left stale after the refresh':<32}{o['stale_left_stale']:>7}")
        v = new_claim_verdicts(plan, claims, start)
        lines.append(f"    new claims, Checker {'supported':>12}{'not supp.':>11}{'other':>8}")
        for label, c in (("first check", v["first"]), ("after round 1", v["after"][1]),
                         ("after round 2", v["after"][2])):
            other = sum(n for k, n in c.items() if k not in ("supported", "not_supported"))
            lines.append(f"      {label:<18}{c['supported']:>12}{c['not_supported']:>11}{other:>8}")
        rounds = v["rounds"]
        lines.append(f"    repair in the refresh: {v['passes']} pass(es), {len(rounds)} round(s)")
        for rnd in sorted(rounds):
            lines.append(f"      round {rnd}: " + ", ".join(f"{k} {n}" for k, n in sorted(rounds[rnd].items())))
        lines.append(f"    older claims repaired in the refresh  {v['old_repaired']}")
    return lines


def block_current_but_false(exps):
    lines = header("current-but-false", "Claims the refresh plan classed unchanged or moved (their cited lines "
                                        "hash the same, so the refresh keeps them current) that the re-map then "
                                        "retired. Other classes for contrast. Replacement is not separate: the "
                                        "store keeps no link from a retired claim to a new one, and why it was "
                                        "retired is the agent's text, which this capture does not read.")
    for e in exps:
        lines.append(exp_title(e))
        if e["plan"] is None or e["map"] is None or not e["refresh_start"]:
            lines.append(f"    {NOT_RECORDED}")
            continue
        cbf = current_but_false(e["plan"], e["claims"], e["refresh_start"])
        lines.append(f"    {'plan class':<20}{'retired by re-map':>18}{'of':>6}")
        for s in CLAIM_STATES:
            lines.append(f"    {s:<20}{cbf[s][0]:>18}{cbf[s][1]:>6}")
        n = sum(cbf[s][0] for s in CURRENT_CLASSES)
        d = sum(cbf[s][1] for s in CURRENT_CLASSES)
        lines.append(f"    current but false   {n} of {d} (unchanged + moved)")
        lines.append(f"    replaced (linked to a new claim)  {NOT_RECORDED}")
    return lines


def block_build(exps):
    lines = header("build", "E2's build at the base commit: its first check and repair rounds, from the repairs "
                            "history saved before the refresh (a repair at round r = not supported after round "
                            "r-1). Verdicts the refresh re-checked were overwritten, so they print as not "
                            "recorded.")
    for e in exps:
        if not e.get("build_block"):
            continue
        lines.append(exp_title(e))
        if e["plan"] is None or e["map"] is None or not e["refresh_start"]:
            lines.append(f"    {NOT_RECORDED}")
            continue
        h = build_history(e["plan"], e["claims"], e["refresh_start"])
        lines.append(f"    claims built                        {h['claims']:>4}")
        lines.append(f"    not supported at first check        {h['flagged'][1]:>4}   (repaired in round 1)")
        lines.append(f"    not supported after round 1         {h['flagged'][2]:>4}   (repaired in round 2)")
        uv = h["unrepaired_verdicts"]
        lines.append(f"    never repaired                      {h['unrepaired']:>4}")
        lines.append(f"      first verdict kept: supported {uv.get('supported', 0)}, not supported "
                     f"{uv.get('not_supported', 0)}, {NOT_RECORDED} {uv.get(NOT_RECORDED, 0)}")
        lv = h["last_verdicts"]
        lines.append(f"    after round 2, the {h['last_round']} round-2 claims: supported "
                     f"{lv.get('supported', 0)}, not supported {lv.get('not_supported', 0)},")
        lines.append(f"      {NOT_RECORDED} {lv.get(NOT_RECORDED, 0)}")
        lines.append("    repair actions per round:")
        for rnd in sorted(h["rounds"]):
            lines.append(f"      round {rnd}: " + ", ".join(f"{k} {n}" for k, n in sorted(h["rounds"][rnd].items())))
        if not h["rounds"]:
            lines.append(f"      {NOT_RECORDED}")
    return lines


def record_name(path):
    """How the receipt names the run-commit record: its path in this repo, else its file name (never a full
    path)."""
    try:
        return str(path.resolve().relative_to(HERE.parents[1]))
    except ValueError:
        return path.name


def render(archive, runs_txt_path=DEFAULT_RUNS_TXT, run_worktree=DEFAULT_RUN_WORKTREE, run_commits_path=None):
    runs_txt = read_text(runs_txt_path) if runs_txt_path else None
    exps = [load_experiment(archive, spec, runs_txt) for spec in EXPERIMENTS]
    reflog = parse_reflog(git(run_worktree, *REFLOG_ARGS) if run_worktree else None)
    record = read_json(run_commits_path) if run_commits_path else None
    heads = run_heads(all_runs(exps), reflog, record)
    source = heads_source(heads, record, record_name(run_commits_path) if run_commits_path else "")
    status(f"experiments: {', '.join(e['name'] + ' ' + e['repo'] for e in exps)}; runs.txt "
           f"{'found' if runs_txt else 'missing'}; run commits: {source}")
    lines = ["Honeyguide refresh: receipts", rule("="),
             f"  archive   {archive.parent.name}/{archive.name} (read only)",
             "  " + "; ".join(f"{e['name']} {e['repo']}" for e in exps)]
    for block, args in ((block_commits, (exps, heads, source)), (block_plan, (exps,)),
                        (block_cost, (exps, heads)), (block_refresh, (exps,)), (block_current_but_false, (exps,)),
                        (block_build, (exps,))):
        status(f"block {block.__name__[6:]}")
        lines += block(*args)
    return "\n".join(line.rstrip() for line in lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    ap.add_argument("--runs-txt", type=Path, default=DEFAULT_RUNS_TXT)
    ap.add_argument("--run-worktree", type=Path, default=DEFAULT_RUN_WORKTREE)
    ap.add_argument("--run-commits", type=Path, default=DEFAULT_RUN_COMMITS,
                    help="the frozen run-commit record (preferred over the live reflog)")
    ap.add_argument("--freeze-run-commits", action="store_true",
                    help="write --run-commits from the live reflog, once, and exit")
    args = ap.parse_args(argv)
    if args.freeze_run_commits:
        return freeze(args)
    sys.stdout.write(render(args.archive, args.runs_txt, args.run_worktree, args.run_commits))
    return 0


def freeze(args):
    if args.run_commits.exists():
        status(f"{args.run_commits.name} exists; not overwriting it")
        return 1
    runs_txt = read_text(args.runs_txt) if args.runs_txt else None
    exps = [load_experiment(args.archive, spec, runs_txt) for spec in EXPERIMENTS]
    reflog = parse_reflog(git(args.run_worktree, *REFLOG_ARGS))
    if not reflog:
        status("no reflog in the run worktree; nothing written")
        return 1
    rec = freeze_run_commits(all_runs(exps), reflog, datetime.now(timezone.utc))
    missing = [r["run"] for r in rec["runs"] if not r["commit"]]
    if missing:
        status(f"the reflog holds no entry for {', '.join(missing)}; nothing written")
        return 1
    args.run_commits.write_text(json.dumps(rec, indent=2) + "\n")
    status(f"wrote {args.run_commits.name}: {len(rec['runs'])} runs, read {rec['read_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
