"""Export the T5 and T6 human inputs as three self-contained JSON files (question text + annotations), for reading
and sharing. Read-only over the frozen sets and eval/human/answers/; writes eval/human/export/.

    uv run python eval/human/export.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chores as C  # noqa: E402

OUT = Path(__file__).resolve().parent / "export"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = C.manifest_sha()
    repos = C.repo_names()
    frozen = {r: C.load_frozen(r) for r in repos}
    ans = {(c, r): C.read_json(C.answer_path(C.ANSWERS, c, r)) or {} for c in ("whyhow", "hops", "disputes")
           for r in repos}
    common = {"frozen_manifest_sha256": manifest}

    t5 = {**common, "chore": "T5 why/how questions and rubrics", "repos": {}}
    for r in repos:
        a = ans[("whyhow", r)]
        t5["repos"][r] = {"commit": frozen[r]["commit"], "source": a.get("source", ""),
                          "questions": a.get("questions", [])}

    t6a = {**common, "chore": "T6a flow hops: required or optional for a complete answer", "repos": {}}
    for r in repos:
        a = ans[("hops", r)].get("questions", {})
        qs = []
        for q in frozen[r]["flows"]:
            saved = {h["index"]: h for h in a.get(q["id"], {}).get("hops", [])}
            qs.append({"id": q["id"], "text": q["text"], "hops": [
                {"index": h["index"], "function": h["qual"], "file": h["file"], "line": h["line"],
                 "count": h.get("count", 1), "mark": saved.get(h["index"], {}).get("mark"),
                 "why": saved.get(h["index"], {}).get("why", "")} for h in q["hops"]]})
        t6a["repos"][r] = {"commit": frozen[r]["commit"], "provenance": ans[("hops", r)].get("provenance", ""),
                           "questions": qs}

    t6b = {**common, "chore": "T6b callers: in-key callers and the disputed call sites decided", "repos": {}}
    for r in repos:
        a = ans[("disputes", r)].get("questions", {})
        qs = []
        for q in frozen[r]["callers"]:
            saved = {d["index"]: d for d in a.get(q["id"], {}).get("disputes", [])}
            qs.append({"id": q["id"], "text": q["text"], "target": q["target"],
                       "in_key": q.get("in_key", []),
                       "disputes": [{"caller": d["caller"], "file": d["file"], "lines": d["lines"],
                                     "kinds": d["kinds"], "decision": saved.get(d["index"], {}).get("decision"),
                                     "note": saved.get(d["index"], {}).get("note", "")} for d in q["disputes"]]})
        t6b["repos"][r] = {"commit": frozen[r]["commit"], "questions": qs}

    for name, doc in (("t5_whyhow.json", t5), ("t6_flow_hops.json", t6a), ("t6_callers.json", t6b)):
        (OUT / name).write_text(json.dumps(doc, indent=1, sort_keys=False, ensure_ascii=False) + "\n")
        print(OUT / name)


if __name__ == "__main__":
    main()
