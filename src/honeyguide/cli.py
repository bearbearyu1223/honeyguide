"""``honeyguide``: status, refresh-plan (dry run), export, import. Results on stdout; errors on stderr."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .gitio import GitError, Repo
from .refresh import plan_refresh
from .repoid import identify
from .store import Store, StoreError, all_claims, export_bundle, import_bundle


def _open(args) -> tuple[Repo, dict, Store]:
    repo = Repo.open(args.repo)
    identity = identify(repo).to_dict()
    return repo, identity, Store(identity["id"])


def cmd_status(args) -> int:
    repo, identity, store = _open(args)
    head = repo.rev("HEAD")
    dirty = repo.dirty()
    if not store.exists():
        info = {"repo_id": identity["id"], "memory": str(store.dir), "saved": False, "head": head}
    else:
        map_layer, answers, notes = store.load("map"), store.load("answers"), store.load("notes")
        claims = [c for _, c in all_claims(map_layer, answers)]
        info = {
            "repo_id": identity["id"], "memory": str(store.dir), "saved": True,
            "map_commit": map_layer["commit"], "head": head, "dirty": dirty,
            "map_claims": len(map_layer["claims"]),
            "questions": len(answers["questions"]), "answers": len(answers["responses"]),
            "freshness": dict(Counter(c["freshness"] for c in claims)),
            "checks": dict(Counter(c["check"] for c in claims)),
            "notes": {"shared": sum(1 for n in notes["notes"] if n.get("share_with_agents")),
                      "private": sum(1 for n in notes["notes"] if not n.get("share_with_agents"))},
        }
    if args.json:
        print(json.dumps(info, indent=1))
        return 0
    print(f"repo id      {info['repo_id']}")
    print(f"memory       {info['memory']}")
    print(f"HEAD         {head[:12]}" + (f"  (uncommitted: {dirty['tracked']} tracked, "
                                         f"{dirty['untracked']} untracked)" if any(dirty.values()) else ""))
    if not info["saved"]:
        print("saved        nothing yet")
        return 0
    saved = info["map_commit"]
    print(f"map commit   {saved[:12] if saved else '-'}" +
          ("" if saved is None else ("  (up to date)" if saved == head else "  (behind HEAD: run refresh-plan)")))
    print(f"map claims   {info['map_claims']}")
    print(f"questions    {info['questions']}   answers {info['answers']}")
    print("freshness    " + "  ".join(f"{k} {v}" for k, v in sorted(info["freshness"].items())))
    print("checks       " + "  ".join(f"{k} {v}" for k, v in sorted(info["checks"].items())))
    print(f"notes        {info['notes']['shared']} shared with agents, {info['notes']['private']} private")
    return 0


def _loc(path: str, start, end) -> str:
    return f"{path}:{start}-{end}" if start is not None else f"{path}:?"


def cmd_refresh_plan(args) -> int:
    repo, _, store = _open(args)
    if not store.exists():
        print("nothing saved for this repo yet", file=sys.stderr)
        return 1
    map_layer, answers = store.load("map"), store.load("answers")
    plan = plan_refresh(repo, all_claims(map_layer, answers), target=args.to,
                        base=args.base or map_layer["commit"])
    if args.json:
        print(json.dumps({
            "base": plan.base, "target": plan.target, "warnings": plan.warnings, "counts": plan.counts(),
            "claims": [{"id": c.claim_id, "response": c.response_id, "state": c.state, "reason": c.reason,
                        "anchors": [{"from": _loc(a.old.path, a.old.start, a.old.end),
                                     "to": _loc(a.path, a.reloc.start, a.reloc.end), "state": a.state,
                                     "reason": a.reloc.reason} for a in c.anchors]} for c in plan.claims],
            "uncovered": [vars(u) for u in plan.uncovered], "unoutlined": plan.unoutlined,
        }, indent=1))
        return 0
    print(f"refresh plan {(plan.base or '-')[:12]} -> {plan.target[:12]} (dry run)")
    for warning in plan.warnings:
        print(f"warning: {warning}")
    print("claims       " + "  ".join(f"{k} {v}" for k, v in plan.counts().items()))
    for state in ("moved", "stale", "retired"):
        rows = [c for c in plan.claims if c.state == state]
        if rows:
            print(f"{state}:")
        for c in rows:
            for a in c.anchors:
                if a.state == "unchanged":
                    continue
                print(f"  {c.claim_id}  {_loc(a.old.path, a.old.start, a.old.end)} -> "
                      f"{_loc(a.path, a.reloc.start, a.reloc.end) if a.state != 'retired' else 'gone'}"
                      f"  {a.reloc.reason}")
    print(f"uncovered    {len(plan.uncovered)} new or changed unit(s) no claim cites")
    for u in plan.uncovered:
        print(f"  {u.path}:{u.start}-{u.end}  {u.qualname} ({u.kind}, {u.change})")
    if plan.unoutlined:
        print(f"changed files without an outline: {len(plan.unoutlined)}")
        for path in plan.unoutlined:
            print(f"  {path}")
    return 0


def cmd_export(args) -> int:
    _, _, store = _open(args)
    if not store.exists():
        print("nothing saved for this repo yet", file=sys.stderr)
        return 1
    text = json.dumps(export_bundle(store, args.include_private_notes), indent=1, ensure_ascii=False) + "\n"
    if args.output in (None, "-"):
        sys.stdout.write(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"exported to {args.output}")
    return 0


def cmd_import(args) -> int:
    _, identity, store = _open(args)
    bundle = json.loads(Path(args.file).read_text(encoding="utf-8"))
    store.init(identity)
    counts = import_bundle(store, bundle, force=args.force)
    print(f"imported: {counts['added']} added, {counts['kept_local']} already here (kept local)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honeyguide", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--repo", default=".", help="a path inside the checkout (default: .)")
        p.set_defaults(func=func)
        return p

    p = add("status", cmd_status, "repo id, saved commit vs HEAD, counts")
    p.add_argument("--json", action="store_true")
    p = add("refresh-plan", cmd_refresh_plan, "what refresh would do to each saved claim (changes nothing)")
    p.add_argument("--to", default="HEAD", help="target revision (default HEAD)")
    p.add_argument("--base", help="diff base for uncovered code (default: the map's commit)")
    p.add_argument("--json", action="store_true")
    p = add("export", cmd_export, "write all saved memory to one file")
    p.add_argument("-o", "--output", help="file to write (default: stdout)")
    p.add_argument("--include-private-notes", action="store_true",
                   help="also export notes not shared with agents (left out by default)")
    p = add("import", cmd_import, "merge an export into this repo's memory")
    p.add_argument("file")
    p.add_argument("--force", action="store_true", help="import an export made for another repo id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (GitError, StoreError, ValueError, KeyError) as exc:
        print(f"honeyguide: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
