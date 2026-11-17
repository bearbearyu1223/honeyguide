"""Per-question scoring for Honeyguide's eval: locate, callers, flow. Pure (dicts in, dicts out).

An answer is {items: [{file, symbol, line?}], text}. Each item is resolved to one function of the repo before it
is scored:
  file    the working-dir prefix (an absolute path) and a leading "./" are stripped; otherwise exact.
  symbol  backticks, "def "/"class " and a trailing "(...)" are dropped; "<module>" (or module, top-level,
          __main__) means top-level code. It resolves, among the functions defined in that file, to
          1. the function whose qualname equals it, else
          2. the functions whose qualname ends with "." + it, or that it ends with ("." + qualname: a module path
             in front); one match resolves; several match only when the item's line falls inside exactly one;
          3. none: then, if the item has a line, the innermost function containing that line.
          Ambiguous or unknown items resolve to nothing (they never match a key).
Scores, each in [0, 1]:
  locate   1 when the FIRST item resolves to the key function (or a function nested in it: also_accept, or a
           <locals> qualname under it) in the key file. Also reported: the file alone, and any item.
  callers  F1 of the answered caller set against the key: key callers (AST + trace) plus the disputed sites the annotator
           decided are callers; sites the annotator decided are not callers count as false positives when answered.
           Items outside the key's scope (tests, examples, docs; for waku-agent outside waku/) are ignored.
  flow     required hops (the annotator's marks) recalled in order: LCS of the answer's required hops (first mention,
           answer order) with the key's required hops (trace order), divided by the number required. Also
           reported: recall, optional hops named, excluded hops ignored, and every other item classified as
           "trace" (in the trace phase but pre-filtered), "other path" (statically reachable from the entry in
           the AST call graph, not in the trace) or "invented" (neither, or not a repo function).
"""

from __future__ import annotations

from dataclasses import dataclass

MODULE_ALIASES = {"<module>", "module", "<toplevel>", "toplevel", "top-level", "top level", "__main__",
                  "<main>", "main block", "module level", "module-level"}


@dataclass(frozen=True)
class Fn:
    file: str
    qual: str
    start: int
    end: int


def norm_file(path: str, workdir: str = "") -> str:
    p = path.strip().strip("`").strip()
    w = workdir.rstrip("/") + "/" if workdir else ""
    if w and p.startswith(w):
        p = p[len(w):]
    elif p.startswith("/") and "/work/" in p:     # a scratch working dir's absolute path (/.../hg-eval-*/work/)
        p = p.split("/work/", 1)[1]
    while p.startswith("./"):
        p = p[2:]
    return p


def norm_symbol(sym: str) -> str:
    s = sym.strip().strip("`").strip()
    for pre in ("async def ", "def ", "class "):
        if s.startswith(pre):
            s = s[len(pre):]
    if "(" in s:
        s = s[:s.index("(")]
    s = s.strip()
    if s.lower() in MODULE_ALIASES:
        return "<module>"
    return s


def resolve_item(item: dict, funcs: dict[str, list[Fn]], workdir: str = "") -> tuple[str, str | None]:
    """(file, qual or None) for one answer item; funcs: {file: [Fn]} of the repo."""
    f = norm_file(str(item.get("file", "")), workdir)
    s = norm_symbol(str(item.get("symbol", "")))
    line = item.get("line") if isinstance(item.get("line"), int) else None
    in_file = funcs.get(f, [])
    if s == "<module>":
        return f, "<module>"
    exact = [fn for fn in in_file if fn.qual == s]
    if exact:
        return f, exact[0].qual
    cands = [fn for fn in in_file if fn.qual.endswith("." + s) or s.endswith("." + fn.qual)]
    if len(cands) == 1:
        return f, cands[0].qual
    if len(cands) > 1:
        if line is not None:
            hit = [fn for fn in cands if fn.start <= line <= fn.end]
            if len(hit) == 1:
                return f, hit[0].qual
        return f, None
    if line is not None:
        hit = [fn for fn in in_file if fn.start <= line <= fn.end]
        if hit:
            return f, min(hit, key=lambda fn: fn.end - fn.start).qual
    return f, None


def _under(qual: str, key: str) -> bool:
    return qual == key or qual.startswith(key + ".<locals>.")


def score_locate(answer: dict, key: dict, funcs: dict[str, list[Fn]], workdir: str = "") -> dict:
    items = answer.get("items") or []
    accept = [key["qual"], *key.get("also_accept", [])]

    def ok(item) -> tuple[bool, bool]:
        f, q = resolve_item(item, funcs, workdir)
        file_ok = f == key["file"]
        return file_ok, file_ok and q is not None and any(_under(q, a) for a in accept)

    first = ok(items[0]) if items else (False, False)
    any_func = any(ok(i)[1] for i in items)
    return {"score": 1.0 if first[1] else 0.0, "file_ok": first[0], "func_ok": first[1], "any_item_func_ok": any_func,
            "items": len(items)}


def callers_key(q: dict, decisions: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """(positives, negatives). positives: [{file, quals: {qual and also_accept}}], one per key caller (frozen key
    plus disputes decided 'caller'); negatives: (file, caller) pairs decided 'not'. decisions: one per
    q['disputes_for_han'] entry, in order ({decision}); a site left undecided is neither."""
    pos = [{"file": c["file"], "quals": {c["qual"], *c.get("also_accept", [])}} for c in q["key"]["callers"]]
    neg = []
    for d, dec in zip(q.get("disputes_for_han", []), decisions, strict=True):
        if dec.get("decision") == "caller":
            if not any(p["file"] == d["file"] and d["caller"] in p["quals"] for p in pos):
                pos.append({"file": d["file"], "quals": {d["caller"]}})
        elif dec.get("decision") == "not":
            neg.append((d["file"], d["caller"]))
    return pos, neg


def prf(tp: int, fp: int, n_key: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else (1.0 if n_key == 0 else 0.0)
    r = tp / n_key if n_key else (1.0 if fp == 0 else 0.0)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score_callers(answer: dict, q: dict, decisions: list[dict], funcs: dict[str, list[Fn]], in_scope,
                  workdir: str = "") -> dict:
    pos, neg = callers_key(q, decisions)
    answered: list[tuple[str, str | None]] = []
    ignored = 0
    for item in answer.get("items") or []:
        f, qual = resolve_item(item, funcs, workdir)
        if not in_scope(f):
            ignored += 1
            continue
        if (f, qual) not in answered or qual is None:
            answered.append((f, qual))
    matched: set[int] = set()
    fp = 0
    fp_not = 0
    for f, qual in answered:
        hit = next((i for i, p in enumerate(pos) if i not in matched and p["file"] == f and qual in p["quals"]), None)
        if hit is None:
            if qual is not None and any(p["file"] == f and qual in p["quals"] for p in pos):
                continue   # the same caller named twice (e.g. by an alias): counted once
            fp += 1
            fp_not += (f, qual) in neg
        else:
            matched.add(hit)
    p, r, f1 = prf(len(matched), fp, len(pos))
    return {"score": f1, "precision": p, "recall": r, "tp": len(matched), "fp": fp, "fp_decided_not": fp_not,
            "key": len(pos), "ignored_out_of_scope": ignored}


def lcs(a: list, b: list) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def score_flow(answer: dict, hops: list[dict], marks: list[str | None], funcs: dict[str, list[Fn]],
               trace_pairs: set[tuple[str, str]], reachable: set[tuple[str, str]], workdir: str = "") -> dict:
    """hops: the frozen candidate hops (key order); marks: the annotator's mark per hop (required / optional / excluded /
    None); trace_pairs: (file, qual) of every call in the question's trace phase; reachable: (file, qual)
    statically reachable from the entry calls."""
    index = {(h["file"], h["qual"]): i for i, h in enumerate(hops)}
    required = [i for i, m in enumerate(marks) if m == "required"]
    seq: list[int] = []
    optional: set[int] = set()
    cls = {"trace": 0, "other path": 0, "invented": 0}
    invented: list[str] = []
    for item in answer.get("items") or []:
        f, qual = resolve_item(item, funcs, workdir)
        i = index.get((f, qual)) if qual else None
        if i is not None:
            m = marks[i]
            if m == "required" and i not in seq:
                seq.append(i)
            elif m == "optional":
                optional.add(i)
            continue          # excluded (or unmarked) hops are ignored
        if qual is not None and (f, qual) in trace_pairs:
            cls["trace"] += 1
        elif qual is not None and (f, qual) in reachable:
            cls["other path"] += 1
        else:
            cls["invented"] += 1
            invented.append(f"{f}:{item.get('symbol', '')}")
    n = len(required)
    order = lcs(seq, required)
    return {"score": order / n if n else 1.0, "recall": len(seq) / n if n else 1.0, "in_order": order,
            "required": n, "recalled": len(seq), "optional_named": len(optional), **cls, "invented_items": invented}
