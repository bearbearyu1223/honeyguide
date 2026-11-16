"""Export the T5 and T6 human inputs as three self-contained JSON files (question text + annotations), for reading
and sharing. Read-only over the frozen sets and eval/human/answers/; writes eval/human/export/.

Every link points at GitHub at the pinned commit: each T5 relevant file, each T6a hop and each T6b in-key caller
and disputed call site (at its first line). T5 carries one grading policy for every question, at the top.

    uv run python eval/human/export.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chores as C  # noqa: E402

OUT = Path(__file__).resolve().parent / "export"


def shared(ans: dict, chore: str, key: str):
    """A document-level field every repo's answers file of one chore must agree on (None when none has it)."""
    values = {json.dumps(a.get(key), sort_keys=True) for (c, _), a in ans.items() if c == chore and a.get(key)}
    if len(values) > 1:
        raise SystemExit(f"{chore}_*.json disagree on {key}; make them agree before exporting")
    return json.loads(values.pop()) if values else None


def build(answers_dir: Path = C.ANSWERS, questions_dir: Path = C.QUESTIONS) -> dict[str, dict]:
    manifest = C.manifest_sha(questions_dir)
    repos = C.repo_names(questions_dir)
    frozen = {r: C.load_frozen(r, questions_dir) for r in repos}
    ans = {(c, r): C.read_json(C.answer_path(answers_dir, c, r)) or {} for c in ("whyhow", "hops", "disputes")
           for r in repos}
    refinement = (shared(ans, "whyhow", "refinement") or shared(ans, "hops", "refinement")
                  or shared(ans, "disputes", "refinement"))
    common = {"frozen_manifest_sha256": manifest, **({"refinement": refinement} if refinement else {})}

    t5 = {**common, "chore": "T5 why/how questions and rubrics",
          "grading_policy": shared(ans, "whyhow", "grading_policy") or C.GRADING_POLICY, "repos": {}}
    for r in repos:
        a, fz = ans[("whyhow", r)], frozen[r]
        qs = []
        for q in a.get("questions", []):
            q = dict(q)
            q["relevant_files"] = [{"path": p, "link": C.gh_link(fz["url"], fz["commit"], p)}
                                   for p in C.relevant_paths(q.get("relevant", ""))]
            qs.append(q)
        t5["repos"][r] = {"url": fz["url"], "commit": fz["commit"], "source": a.get("source", ""), "questions": qs}

    t6a = {**common, "chore": "T6a flow hops: required, optional or excluded for a complete answer",
           "marks": C.MARK_MEANINGS, "repos": {}}
    for r in repos:
        a = ans[("hops", r)].get("questions", {})
        qs = []
        for q in frozen[r]["flows"]:
            saved = {h["index"]: h for h in a.get(q["id"], {}).get("hops", [])}
            same = {h["index"]: s for h in q["hops"] if (s := saved.get(h["index"]))
                    and (s.get("file"), s.get("qual"), s.get("line")) == (h["file"], h["qual"], h["line"])}
            qs.append({"id": q["id"], "text": q["text"], "hops": [
                {"index": h["index"], "function": h["qual"], "file": h["file"], "line": h["line"],
                 "count": h["calls"], "link": h["link"], "mark": same.get(h["index"], {}).get("mark"),
                 "why": same.get(h["index"], {}).get("why", "")} for h in q["hops"]]})
        t6a["repos"][r] = {"url": frozen[r]["url"], "commit": frozen[r]["commit"],
                           "provenance": ans[("hops", r)].get("provenance", ""), "questions": qs}

    t6b = {**common, "chore": "T6b callers: in-key callers and the disputed call sites decided", "repos": {}}
    for r in repos:
        a = ans[("disputes", r)].get("questions", {})
        qs = []
        for q in frozen[r]["callers"]:
            saved = {d["index"]: d for d in a.get(q["id"], {}).get("disputes", [])}
            qs.append({"id": q["id"], "text": q["text"], "target": q["target"], "target_link": q["target_link"],
                       "in_key": q.get("in_key", []),
                       "disputes": [{"caller": d["caller"], "file": d["file"], "lines": d["lines"],
                                     "link": d["links"][0]["href"] if d["links"] else
                                     C.gh_link(frozen[r]["url"], frozen[r]["commit"], d["file"]),
                                     "kinds": d["kinds"], "decision": saved.get(d["index"], {}).get("decision"),
                                     "note": saved.get(d["index"], {}).get("note", "")} for d in q["disputes"]]})
        t6b["repos"][r] = {"url": frozen[r]["url"], "commit": frozen[r]["commit"], "questions": qs}

    return {"t5_whyhow.json": t5, "t6_flow_hops.json": t6a, "t6_callers.json": t6b}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, doc in build().items():
        (OUT / name).write_text(json.dumps(doc, indent=1, sort_keys=False, ensure_ascii=False) + "\n")
        print(OUT / name)


if __name__ == "__main__":
    main()
