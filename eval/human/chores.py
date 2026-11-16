"""Han's human eval chores (T5 why/how questions, T6a flow hops, T6b callers disputes): the frozen sets read, the
answers saved, and the summary that ``check.py`` prints and later steps read.

Standard library only. The frozen question sets (eval/questions/*.json, MANIFEST.txt) are read, never written.
Everything a sheet shows comes from the repo's JSON (the md sheets are generated from it; the tests check that
the two agree line by line).

Answers live in eval/human/answers/, one file per chore and repo:

- ``whyhow_<repo>.json``: T5, Han's own why/how questions with a rubric each (ids ``<prefix>-why-NN``, never
  reused; list order is the order Han set);
- ``hops_<repo>.json``: T6a, required / optional per candidate hop of every flow question;
- ``disputes_<repo>.json``: T6b, caller / not (and an optional note) per disputed call site.

Each file records the SHA-256 of eval/questions/MANIFEST.txt, so a later change of the keys is detected, and is
written as stable sorted JSON (sorted keys, one-space indent, trailing newline) through a temp file and a rename.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "eval" / "questions"
ANSWERS = Path(__file__).resolve().parent / "answers"
README = "README.md"          # at both pins (checked against the local clones in the tests when they exist)
SCHEMA = 1

REMINDER = ("Write these from the repo and your own curiosity. Don't look at Honeyguide's map of this repo while "
            "writing (the eval compares the map against exploring; questions shaped by the map would favour it).")
# T5 bounds: "about 10 per repo (allow 6-15)"; a rubric is 2-5 bullet points of what a good answer must say.
WHYHOW_MIN, WHYHOW_MAX, WHYHOW_TARGET = 6, 15, 10
RUBRIC_MIN, RUBRIC_MAX = 2, 5
MARKS = ("required", "optional")
DECISIONS = ("caller", "not")
# input limits (a local page, but a bad request should be refused, not saved)
MAX_TEXT, MAX_BULLET, MAX_NOTE, MAX_ITEMS, MAX_BULLETS = 4000, 600, 300, 40, 8


# --------------------------------------------------------------------------------------------------------------
# The frozen sets

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_sha(questions_dir: Path = QUESTIONS) -> str:
    """SHA-256 of MANIFEST.txt itself: one hash that changes whenever any frozen file (any key) changes."""
    return sha256_bytes((questions_dir / "MANIFEST.txt").read_bytes())


def verify_manifest(questions_dir: Path = QUESTIONS) -> list[str]:
    """Files whose SHA-256 differs from MANIFEST.txt (or that are missing); empty when the frozen sets are intact."""
    bad = []
    for line in (questions_dir / "MANIFEST.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, name = line.split(None, 1)
        path = questions_dir / name.strip()
        if not path.exists() or sha256_bytes(path.read_bytes()) != digest:
            bad.append(name.strip())
    return bad


def repo_names(questions_dir: Path = QUESTIONS) -> list[str]:
    """Repos with a frozen set: every <repo>.json that has a flow-hops sheet beside it."""
    return sorted(p.stem for p in questions_dir.glob("*.json")
                  if (questions_dir / f"{p.stem}_flow_hops_to_mark.md").exists())


def sheet_intro(md_path: Path) -> str:
    """The explanatory paragraph of a generated sheet (its third line), without the leading 'Commit abc1234. '
    and the md bold markers."""
    lines = md_path.read_text().splitlines()
    return re.sub(r"^Commit [0-9a-f]+\. ", "", lines[2]).replace("**", "") if len(lines) > 2 else ""


def hop_tags(h: dict) -> list[str]:
    """The tags the flow sheet prints after a hop, in the same order: xN, (fold), (cached), [thread(, wave)]."""
    tags = []
    if h["calls"] > 1:
        tags.append(f"x{h['calls']}")
    if h["folded"]:
        tags.append("(fold)")
    if h["cached"]:
        tags.append("(cached)")
    if h["thread"] != "main":
        tags.append(f"[{h['thread']}, {h['wave']}]" if h["wave"] else f"[{h['thread']}]")
    return tags


def hop_label(h: dict) -> str:
    """One hop as the md sheet writes it after the boxes: `qual` file:line tags."""
    extra = (" " + " ".join(hop_tags(h))) if hop_tags(h) else ""
    return f"`{h['qual']}` {h['file']}:{h['lines'][0]}{extra}"


def dispute_label(d: dict) -> str:
    at = ", ".join(str(n) for n in d["lines"])
    hint = "; only repo def named so" if d["only_repo_def_with_this_name"] else ""
    return f"`{d['caller']}` {d['file']} line {at} ({'/'.join(d['kinds'])}: `{d['name']}`{hint})"


def in_key_label(c: dict) -> str:
    alias = "".join(f" (also accepted: `{a}`, the class whose body holds the call)" for a in c["also_accept"])
    return f"in key ({c['source']}): `{c['qual']}` {c['file']}{alias}"


def gh_link(url: str, commit: str, path: str, line: int | None = None) -> str:
    return f"{url}/blob/{commit}/{path}" + (f"#L{line}" if line else "")


def load_frozen(name: str, questions_dir: Path = QUESTIONS) -> dict:
    """What the page and the summary need from one repo's frozen set."""
    data = json.loads((questions_dir / f"{name}.json").read_text())
    url, commit = data["url"].rstrip("/"), data["commit"]
    qs = data["questions"]
    prefix = qs[0]["id"].split("-")[0]
    flows = []
    for q in qs:
        if q["type"] != "flow":
            continue
        hops = []
        for i, h in enumerate(q["key"]["candidate_hops"]):
            hops.append({"index": i, "qual": h["qual"], "file": h["file"], "line": h["lines"][0],
                         "calls": h["calls"], "first_caller": h["first_caller"], "tags": hop_tags(h),
                         "label": hop_label(h), "link": gh_link(url, commit, h["file"], h["lines"][0])})
        flows.append({"id": q["id"], "phase": q["trace_phase"], "text": q["text"], "hops": hops})
    callers = []
    for q in qs:
        if q["type"] != "callers":
            continue
        t = q["target"]
        in_key = []
        for c in q["key"]["callers"]:
            lines = sorted(set(c["ast_lines"]) | set(c["trace_lines"]))
            in_key.append({"qual": c["qual"], "file": c["file"], "source": c["source"], "ast_via": c["ast_via"],
                           "also_accept": c["also_accept"], "lines": lines, "label": in_key_label(c),
                           "link": gh_link(url, commit, c["file"], lines[0] if lines else None)})
        disputes = []
        for i, d in enumerate(q["disputes_for_han"]):
            disputes.append({"index": i, "caller": d["caller"], "file": d["file"], "lines": d["lines"],
                             "kinds": d["kinds"], "name": d["name"],
                             "only_repo_def": d["only_repo_def_with_this_name"], "label": dispute_label(d),
                             "links": [{"line": n, "href": gh_link(url, commit, d["file"], n)} for n in d["lines"]]})
        callers.append({"id": q["id"], "text": q["text"], "target": t["qual"], "target_file": t["file"],
                        "target_line": t["lines"][0], "target_link": gh_link(url, commit, t["file"], t["lines"][0]),
                        "in_key": in_key, "disputes": disputes})
    return {
        "repo": name, "url": url, "commit": commit, "prefix": prefix,
        "tree": f"{url}/tree/{commit}", "readme": gh_link(url, commit, README),
        "flows": flows, "callers": callers, "dispute_kinds": data["dispute_kinds"],
        "flow_intro": sheet_intro(questions_dir / f"{name}_flow_hops_to_mark.md"),
        "disputes_intro": sheet_intro(questions_dir / f"{name}_callers_disputes.md"),
        "json_sha256": sha256_bytes((questions_dir / f"{name}.json").read_bytes()),
    }


# --------------------------------------------------------------------------------------------------------------
# Answers on disk

def dumps(data) -> str:
    return json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_json(path: Path, data) -> None:
    """Atomic: a temp file in the same directory, then a rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(dumps(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def answer_path(answers_dir: Path, chore: str, repo: str) -> Path:
    return answers_dir / f"{chore}_{repo}.json"


def header(frozen: dict, chore: str, manifest: str) -> dict:
    return {"schema": SCHEMA, "chore": chore, "repo": frozen["repo"], "url": frozen["url"],
            "commit": frozen["commit"], "manifest_sha256": manifest,
            "questions_json_sha256": frozen["json_sha256"], "saved_at": now()}


def merge_hops(frozen: dict, saved: dict | None) -> dict:
    """{qid: [mark or None per hop]}. A saved mark carries over only onto the same hop (index, file, function,
    line): if the keys changed, a hop that moved or vanished comes back unmarked rather than taking another's mark."""
    marks = {}
    old = (saved or {}).get("questions", {})
    for q in frozen["flows"]:
        prev = {h.get("index"): h for h in old.get(q["id"], {}).get("hops", [])}
        row = []
        for h in q["hops"]:
            p = prev.get(h["index"])
            same = p and (p.get("file"), p.get("qual"), p.get("line")) == (h["file"], h["qual"], h["line"])
            row.append(p.get("mark") if same and p.get("mark") in MARKS else None)
        marks[q["id"]] = row
    return marks


def hops_doc(frozen: dict, marks: dict, manifest: str) -> dict:
    doc = header(frozen, "T6a flow hops", manifest)
    doc["questions"] = {
        q["id"]: {"hops": [{"index": h["index"], "file": h["file"], "qual": h["qual"], "line": h["line"],
                            "mark": marks[q["id"]][h["index"]]} for h in q["hops"]]}
        for q in frozen["flows"]}
    return doc


def merge_disputes(frozen: dict, saved: dict | None) -> dict:
    """{qid: [{"decision", "note"} per disputed site]}, carried over only onto the same site."""
    out = {}
    old = (saved or {}).get("questions", {})
    for q in frozen["callers"]:
        prev = {d.get("index"): d for d in old.get(q["id"], {}).get("disputes", [])}
        row = []
        for d in q["disputes"]:
            p = prev.get(d["index"])
            same = p and (p.get("file"), p.get("caller"), p.get("lines")) == (d["file"], d["caller"], d["lines"])
            row.append({"decision": p.get("decision") if same and p.get("decision") in DECISIONS else None,
                        "note": (p.get("note") or "") if same else ""})
        out[q["id"]] = row
    return out


def disputes_doc(frozen: dict, decisions: dict, manifest: str) -> dict:
    doc = header(frozen, "T6b callers disputes", manifest)
    doc["questions"] = {
        q["id"]: {"target": q["target"],
                  "disputes": [{"index": d["index"], "file": d["file"], "caller": d["caller"], "lines": d["lines"],
                                "kinds": d["kinds"], **decisions[q["id"]][d["index"]]} for d in q["disputes"]]}
        for q in frozen["callers"]}
    return doc


def blank_whyhow(frozen: dict) -> dict:
    return {"questions": [], "next_number": 1}


def clean_whyhow_item(item: dict, qid: str, repo: str) -> dict:
    """One T5 question as saved; raises ValueError on a malformed one (drafts with empty fields are fine)."""
    if not isinstance(item, dict):
        raise ValueError("a question must be an object")

    def text(key, limit):
        v = item.get(key, "")
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise ValueError(f"{key} must be text")
        if len(v) > limit:
            raise ValueError(f"{key} is longer than {limit} characters")
        return v

    must = item.get("rubric_must", [])
    if not isinstance(must, list) or len(must) > MAX_BULLETS or not all(isinstance(b, str) for b in must):
        raise ValueError(f"rubric_must must be a list of at most {MAX_BULLETS} strings")
    if any(len(b) > MAX_BULLET for b in must):
        raise ValueError(f"a rubric bullet is longer than {MAX_BULLET} characters")
    return {"id": qid, "repo": repo, "text": text("text", MAX_TEXT), "rubric_must": list(must),
            "rubric_partial": text("rubric_partial", MAX_TEXT), "rubric_wrong": text("rubric_wrong", MAX_TEXT),
            "relevant": text("relevant", MAX_TEXT)}


def apply_whyhow(state: dict, items: list, repo: str) -> dict:
    """Edit / reorder / delete: ``items`` is the whole list in Han's order; every id must already exist (new
    questions come from ``add_whyhow``, so two saves in flight can never mint the same id twice)."""
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError(f"questions must be a list of at most {MAX_ITEMS}")
    known = {q["id"] for q in state["questions"]}
    ids = [i.get("id") if isinstance(i, dict) else None for i in items]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question id")
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"unknown question id {unknown[0]!r} (add questions with /api/whyhow/add)")
    return {"questions": [clean_whyhow_item(i, i["id"], repo) for i in items], "next_number": state["next_number"]}


def add_whyhow(state: dict, prefix: str, repo: str) -> tuple[dict, dict]:
    if len(state["questions"]) >= MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} questions")
    n = state["next_number"]
    item = clean_whyhow_item({"rubric_must": ["", ""]}, f"{prefix}-why-{n:02d}", repo)
    return {"questions": state["questions"] + [item], "next_number": n + 1}, item


def whyhow_doc(frozen: dict, state: dict, manifest: str) -> dict:
    doc = header(frozen, "T5 why/how questions", manifest)
    doc.update(questions=state["questions"], next_number=state["next_number"],
               reminder=REMINDER, bounds={"questions": [WHYHOW_MIN, WHYHOW_MAX], "target": WHYHOW_TARGET,
                                          "rubric_bullets": [RUBRIC_MIN, RUBRIC_MAX]})
    return doc


def whyhow_problems(q: dict) -> list[str]:
    """What keeps one T5 question from being complete (empty when it is)."""
    out = []
    if not q["text"].strip():
        out.append("no question text")
    n = sum(1 for b in q["rubric_must"] if b.strip())
    if not RUBRIC_MIN <= n <= RUBRIC_MAX:
        out.append(f"rubric has {n} bullet{'s' if n != 1 else ''} (needs {RUBRIC_MIN}-{RUBRIC_MAX})")
    return out


# --------------------------------------------------------------------------------------------------------------
# The store the server holds: frozen sets, answers in memory, one lock, save after every change

class Answers:
    def __init__(self, answers_dir: Path = ANSWERS, questions_dir: Path = QUESTIONS) -> None:
        self.dir = Path(answers_dir)
        self.questions_dir = Path(questions_dir)
        self.lock = threading.Lock()
        self.manifest = manifest_sha(self.questions_dir)
        self.frozen = {r: load_frozen(r, self.questions_dir) for r in repo_names(self.questions_dir)}
        self.stale = {}          # file name -> the manifest hash it was recorded against, when not the current one
        self.hops, self.disputes, self.whyhow = {}, {}, {}
        for r, fz in self.frozen.items():
            saved = {c: read_json(answer_path(self.dir, c, r)) for c in ("hops", "disputes", "whyhow")}
            for c, doc in saved.items():
                if doc and doc.get("manifest_sha256") != self.manifest:
                    self.stale[answer_path(self.dir, c, r).name] = doc.get("manifest_sha256")
            self.hops[r] = merge_hops(fz, saved["hops"])
            self.disputes[r] = merge_disputes(fz, saved["disputes"])
            w = saved["whyhow"]
            if w:
                self.whyhow[r] = {"questions": [clean_whyhow_item(q, q["id"], r) for q in w.get("questions", [])],
                                  "next_number": int(w.get("next_number", 1))}
            else:
                self.whyhow[r] = blank_whyhow(fz)

    def _repo(self, repo) -> dict:
        if repo not in self.frozen:
            raise ValueError(f"unknown repo {repo!r}")
        return self.frozen[repo]

    def set_hop(self, repo, qid, index, mark) -> None:
        fz = self._repo(repo)
        if mark is not None and mark not in MARKS:
            raise ValueError("mark must be required, optional or null")
        with self.lock:
            row = self.hops[repo].get(qid)
            if row is None or not isinstance(index, int) or not 0 <= index < len(row):
                raise ValueError("no such hop")
            row[index] = mark
            write_json(answer_path(self.dir, "hops", repo), hops_doc(fz, self.hops[repo], self.manifest))
            self.stale.pop(answer_path(self.dir, "hops", repo).name, None)

    def set_dispute(self, repo, qid, index, decision, note) -> None:
        fz = self._repo(repo)
        if decision is not None and decision not in DECISIONS:
            raise ValueError("decision must be caller, not or null")
        if not isinstance(note, str) or len(note) > MAX_NOTE or "\n" in note:
            raise ValueError(f"note must be one line of at most {MAX_NOTE} characters")
        with self.lock:
            row = self.disputes[repo].get(qid)
            if row is None or not isinstance(index, int) or not 0 <= index < len(row):
                raise ValueError("no such disputed site")
            row[index] = {"decision": decision, "note": note}
            write_json(answer_path(self.dir, "disputes", repo), disputes_doc(fz, self.disputes[repo], self.manifest))
            self.stale.pop(answer_path(self.dir, "disputes", repo).name, None)

    def save_whyhow(self, repo, items) -> list:
        fz = self._repo(repo)
        with self.lock:
            self.whyhow[repo] = apply_whyhow(self.whyhow[repo], items, repo)
            self._write_whyhow(fz)
            return self.whyhow[repo]["questions"]

    def add_whyhow(self, repo) -> dict:
        fz = self._repo(repo)
        with self.lock:
            self.whyhow[repo], item = add_whyhow(self.whyhow[repo], fz["prefix"], repo)
            self._write_whyhow(fz)
            return item

    def _write_whyhow(self, fz) -> None:
        repo = fz["repo"]
        write_json(answer_path(self.dir, "whyhow", repo), whyhow_doc(fz, self.whyhow[repo], self.manifest))
        self.stale.pop(answer_path(self.dir, "whyhow", repo).name, None)

    def state(self) -> dict:
        with self.lock:
            return {"manifest_sha256": self.manifest, "reminder": REMINDER, "stale": dict(self.stale),
                    "bounds": {"whyhow": [WHYHOW_MIN, WHYHOW_MAX], "target": WHYHOW_TARGET,
                               "rubric": [RUBRIC_MIN, RUBRIC_MAX]},
                    "repos": [{**fz, "marks": self.hops[r], "decisions": self.disputes[r],
                               "whyhow": self.whyhow[r]["questions"]} for r, fz in self.frozen.items()]}


# --------------------------------------------------------------------------------------------------------------
# The summary: the Done tab and check.py

def summarize(answers_dir: Path = ANSWERS, questions_dir: Path = QUESTIONS) -> dict:
    """Per repo, what's complete and what's left, read from the files on disk (not from a running server)."""
    store = Answers(answers_dir, questions_dir)
    out = {"manifest_sha256": store.manifest, "frozen_mismatches": verify_manifest(questions_dir),
           "answers_dir": str(answers_dir), "repos": {}}
    for r, fz in store.frozen.items():
        files = {c: answer_path(store.dir, c, r) for c in ("whyhow", "hops", "disputes")}
        qs = store.whyhow[r]["questions"]
        wh_left = [{"id": q["id"], "problems": whyhow_problems(q)} for q in qs if whyhow_problems(q)]
        count_ok = WHYHOW_MIN <= len(qs) <= WHYHOW_MAX
        hop_qs = [{"id": q["id"], "marked": sum(m is not None for m in store.hops[r][q["id"]]),
                   "total": len(q["hops"])} for q in fz["flows"]]
        dis_qs = [{"id": q["id"], "target": q["target"],
                   "decided": sum(d["decision"] is not None for d in store.disputes[r][q["id"]]),
                   "total": len(q["disputes"]),
                   "open": [f"{d['caller']} ({d['file']})" for d, a in zip(q["disputes"], store.disputes[r][q["id"]], strict=True)
                            if a["decision"] is None]}
                  for q in fz["callers"] if q["disputes"]]
        hops = {"marked": sum(q["marked"] for q in hop_qs), "total": sum(q["total"] for q in hop_qs),
                "questions": hop_qs}
        disputes = {"decided": sum(q["decided"] for q in dis_qs), "total": sum(q["total"] for q in dis_qs),
                    "questions": dis_qs}
        stale = sorted(f.name for f in files.values() if f.name in store.stale)
        out["repos"][r] = {
            "commit": fz["commit"],
            "files": {c: {"path": str(p), "exists": p.exists()} for c, p in files.items()},
            "stale_files": stale,
            "whyhow": {"count": len(qs), "count_ok": count_ok, "complete": len(qs) - len(wh_left),
                       "left": wh_left, "done": count_ok and not wh_left},
            "hops": {**hops, "done": hops["marked"] == hops["total"]},
            "disputes": {**disputes, "done": disputes["decided"] == disputes["total"]},
        }
        out["repos"][r]["done"] = (not stale and out["repos"][r]["whyhow"]["done"]
                                   and out["repos"][r]["hops"]["done"] and out["repos"][r]["disputes"]["done"])
    out["done"] = not out["frozen_mismatches"] and all(v["done"] for v in out["repos"].values())
    return out


def summary_text(s: dict) -> str:
    """The summary as check.py prints it (the Done tab shows the same facts)."""
    lines = ["Human eval chores (T5 why/how, T6a flow hops, T6b callers disputes)",
             f"answers: {s['answers_dir']}",
             f"frozen sets: MANIFEST.txt sha256 {s['manifest_sha256']}",
             "  " + ("every file matches MANIFEST.txt" if not s["frozen_mismatches"]
                     else "CHANGED since MANIFEST.txt: " + ", ".join(s["frozen_mismatches"]))]
    for r, v in s["repos"].items():
        lines += ["", f"{r} (commit {v['commit'][:7]}): {'complete' if v['done'] else 'not complete'}"]
        w = v["whyhow"]
        lines.append(f"  T5 why/how       {w['count']} question{'' if w['count'] == 1 else 's'} (want {WHYHOW_MIN}-{WHYHOW_MAX}, about "
                     f"{WHYHOW_TARGET}); {w['complete']} with text and a {RUBRIC_MIN}-{RUBRIC_MAX} point rubric"
                     + ("  [done]" if w["done"] else ""))
        if not w["count_ok"]:
            lines.append(f"    left: {'add' if w['count'] < WHYHOW_MIN else 'remove'} questions to reach "
                         f"{WHYHOW_MIN}-{WHYHOW_MAX}")
        for q in w["left"]:
            lines.append(f"    left: {q['id']}: {'; '.join(q['problems'])}")
        h = v["hops"]
        lines.append(f"  T6a flow hops    {r} {h['marked']} of {h['total']} hops marked" + ("  [done]" if h["done"] else ""))
        for q in h["questions"]:
            if q["marked"] < q["total"]:
                lines.append(f"    left: {q['id']}: {q['total'] - q['marked']} of {q['total']} hops unmarked")
        d = v["disputes"]
        lines.append(f"  T6b disputes     {d['decided']} of {d['total']} disputed call sites decided"
                     + ("  [done]" if d["done"] else ""))
        for q in d["questions"]:
            if q["open"]:
                lines.append(f"    left: {q['id']} ({q['target']}): {', '.join(q['open'])}")
        for name in v["stale_files"]:
            lines.append(f"  STALE: {name} was recorded against another MANIFEST.txt; re-check it on the page")
        missing = [c for c, f in v["files"].items() if not f["exists"]]
        if missing:
            lines.append(f"  not saved yet: {', '.join(f'{c}_{r}.json' for c in missing)}")
    lines += ["", f"all complete: {'yes' if s['done'] else 'no'}"]
    return "\n".join(lines) + "\n"
