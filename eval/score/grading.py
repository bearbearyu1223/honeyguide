"""Blind grading of the why/how answers: a sheet with every finished answer shuffled per question and the
condition hidden, the annotator's rubric and grading policy beside it; the annotator's grades are read back later.

Pure apart from the caller's file writes. The blind key (blind id -> run id) is written to its own file so the sheet
can be read without it. Runs that failed (error, capped, invalid answer) are not on the sheet: they score 0 by rule.
Answers are shown as text plus their cited items, nothing else (no model id, no tokens, no tool calls, no cost).
"""

from __future__ import annotations

import json
import random
import string

DEFAULT_SCALE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
DEFAULT_POLICY = ("No grading_policy is recorded with the why/how questions. Default: correct = every rubric point "
                  "covered and nothing wrong; partial = some points covered; wrong = none, or a factual error about "
                  "the repo.")


def policy_of(whyhow_doc: dict) -> tuple[str, dict[str, float]]:
    """(policy text, grade scale) from the why/how answers file: its grading_policy (text, or an object with
    'text' and 'scale'), else the default."""
    gp = whyhow_doc.get("grading_policy")
    if isinstance(gp, str) and gp.strip():
        return gp.strip(), dict(DEFAULT_SCALE)
    if isinstance(gp, dict):
        scale = gp.get("scale") if isinstance(gp.get("scale"), dict) else DEFAULT_SCALE
        text = gp.get("text") or json.dumps({k: v for k, v in gp.items() if k != "scale"}, sort_keys=True)
        return str(text), {str(k): float(v) for k, v in scale.items()}
    return DEFAULT_POLICY, dict(DEFAULT_SCALE)


def blind_ids(n: int) -> list[str]:
    letters = string.ascii_uppercase
    return [letters[i] if i < 26 else f"{letters[i // 26 - 1]}{letters[i % 26]}" for i in range(n)]


def build_sheet(questions: list[dict], answers: list[dict], seed: int, policy: str, scale: dict) -> tuple[dict, dict]:
    """questions: the annotator's why/how questions; answers: [{run_id, qid, answer}] for finished runs (status ok).
    Returns (sheet, key)."""
    sheet = {"policy": policy, "scale": scale, "questions": []}
    key: dict[str, str] = {}
    for q in questions:
        rows = sorted((a for a in answers if a["qid"] == q["id"]), key=lambda a: a["run_id"])
        random.Random(f"{seed}:{q['id']}").shuffle(rows)
        shown = []
        for bid, a in zip(blind_ids(len(rows)), rows, strict=True):
            blind = f"{q['id']}-{bid}"
            key[blind] = a["run_id"]
            ans = a["answer"] or {}
            shown.append({"blind_id": blind, "text": ans.get("text", ""),
                          "cites": [f"{i.get('file')}:{i.get('symbol')}" + (f":{i['line']}" if "line" in i else "")
                                    for i in ans.get("items", [])]})
        sheet["questions"].append({"id": q["id"], "text": q["text"], "rubric_must": q.get("rubric_must", []),
                                   "rubric_partial": q.get("rubric_partial", ""),
                                   "rubric_wrong": q.get("rubric_wrong", ""), "answers": shown})
    return sheet, key


def sheet_markdown(sheet: dict) -> str:
    out = ["# Why/how answers: blind grading sheet", "",
           "The condition each answer came from is hidden; answers are shuffled per question.", "",
           "## Grading policy", "", sheet["policy"], "",
           "Grades: " + ", ".join(f"`{k}` = {v:g}" for k, v in sheet["scale"].items()),
           "", "Write each grade into grades.json under its blind id.", ""]
    for q in sheet["questions"]:
        out += [f"## {q['id']}: {q['text']}", "", "Rubric (must cover):"]
        out += [f"- {b}" for b in q["rubric_must"]]
        if q["rubric_partial"]:
            out += ["", f"Partial: {q['rubric_partial']}"]
        if q["rubric_wrong"]:
            out += ["", f"Wrong: {q['rubric_wrong']}"]
        for a in q["answers"]:
            out += ["", f"### {a['blind_id']}", "", a["text"] or "(empty)"]
            if a["cites"]:
                out += ["", "Cites: " + ", ".join(f"`{c}`" for c in a["cites"])]
        out.append("")
    return "\n".join(out)


def grades_template(key: dict) -> dict:
    return {"grader": "", "graded_at": "", "grades": {b: None for b in sorted(key)}}


def read_grades(grades: dict, key: dict, scale: dict) -> tuple[dict[str, float], list[str]]:
    """({run_id: score} for graded answers, problems). An ungraded answer is left out (not scored yet)."""
    scores: dict[str, float] = {}
    problems: list[str] = []
    for blind, g in sorted((grades.get("grades") or {}).items()):
        if blind not in key:
            problems.append(f"{blind}: not on the sheet")
            continue
        if g is None or g == "":
            continue
        if g not in scale:
            problems.append(f"{blind}: grade {g!r} is not one of {', '.join(scale)}")
            continue
        scores[key[blind]] = float(scale[g])
    return scores, problems
