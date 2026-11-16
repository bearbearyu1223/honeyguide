"""``honeyguide``: status, refresh-plan (dry run), export, import, and the agent contract's commands
(docs/design/agent-contract.md): JSON in on stdin, one JSON object out on stdout. Plus ``serve`` and ``watch``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import activity, claims, drafts, inbox, memory, repair
from .contract import ContractError
from .gitio import GitError, Repo
from .preview import preview
from .refresh import plan_refresh
from .repoid import identify
from .repoinfo import repo_info
from .store import Store, StoreError, all_claims, export_bundle, import_bundle, is_shared


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
            "notes": {"shared": sum(1 for n in notes["notes"] if is_shared(n)),
                      "private": sum(1 for n in notes["notes"] if not is_shared(n))},
            "memory_state": memory.memory_state(repo, store),
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
          ("" if saved is None else ("  (up to date)" if saved == head else
                                     "  (behind HEAD: run refresh-plan, then refresh apply)")))
    print(f"state        {info['memory_state']['headline']}")
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
        print(json.dumps(memory.plan_json(plan), indent=1))
        return 0
    print(f"refresh plan {(plan.base or '-')[:12]} -> {plan.target[:12]} (dry run; `refresh apply` saves it)")
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


# -- the agent contract: JSON in, JSON out ---------------------------------------------------

AGENT_COMMANDS = {
    # (group, name): (function(repo, store, data) -> dict, takes input)
    ("anchor", "resolve"): (lambda r, s, d: claims.resolve_call(r, d), True),
    ("claims", "save"): (lambda r, s, d: claims.save_claims(s, r, d), True),
    ("claims", "list"): (lambda r, s, d: memory.list_claims(s, d), True),
    ("claims", "retire"): (lambda r, s, d: memory.retire(s, d), True),
    ("claims", "repair"): (lambda r, s, d: repair.repair(r, s, d), True),
    ("verdict", "set"): (lambda r, s, d: claims.set_verdicts(s, d, r), True),
    ("refresh", "apply"): (lambda r, s, d: memory.refresh_apply(r, s, d), True),
    ("memory", "state"): (lambda r, s, d: memory.memory_state(r, s), False),
    ("inbox", None): (lambda r, s, d: inbox.inbox(s), False),
    ("question", "show"): (lambda r, s, d: inbox.show(s, d), True),
    ("question", "claim"): (lambda r, s, d: {"question": inbox.claim(s, d)}, True),
    ("question", "fail"): (lambda r, s, d: {"question": inbox.fail(s, d)}, True),
    ("question", "release"): (lambda r, s, d: {"question": inbox.release(s, d)}, True),
    ("question", "reopen"): (lambda r, s, d: {"question": inbox.reopen(s, d)}, True),
    ("answer", "record"): (lambda r, s, d: inbox.record_answer(s, r, d), True),
    ("activity", "start"): (lambda r, s, d: {"entry": activity.start(s, d)}, True),
    ("activity", "update"): (lambda r, s, d: {"entry": activity.update(s, d)}, True),
    ("activity", "finish"): (lambda r, s, d: {"entry": activity.finish(s, d)}, True),
    ("activity", "list"): (lambda r, s, d: activity.listing(s), False),
    ("preview", None): (lambda r, s, d: preview(r, s, d), True),
    ("refresh-log", "add"): (lambda r, s, d: {"entry": activity.add_refresh(s, d)}, True),
}


# Plain flags for the common inputs (T7.15), so an agent never pipes quoted JSON into a command: a pipe or a heredoc
# is a compound command, which the permission rule ``Bash(honeyguide:*)`` refuses. Anything larger goes in a file
# (``--input FILE``) written with the Write tool into ``honeyguide drafts dir``.
# (group, name): [(flag, input key, kind)]; kind: str, int, "list" (repeatable, comma-separated), "flag" (true when
# given), "file" (the file's text, stripped).
FLAGS: dict[tuple[str, str | None], list[tuple[str, str, object]]] = {
    ("anchor", "resolve"): [("--path", "path", str), ("--anchor", "anchor", str), ("--end-anchor", "end_anchor", str),
                            ("--extent", "extent", str), ("--commit", "commit", str)],
    ("claims", "list"): [("--scope", "scope", str), ("--check", "check", "list"), ("--freshness", "freshness", "list"),
                         ("--ids", "ids", "list"), ("--responses", "responses", "list"), ("--spans", "spans", "flag")],
    ("claims", "retire"): [("--id", "claims", "list"), ("--reason", "reason", str)],
    ("claims", "repair"): [("--response", "response", str)],
    ("verdict", "set"): [("--id", "claim", str), ("--verdict", "verdict", str), ("--note", "note", str),
                         ("--note-file", "note", "file")],
    ("refresh", "apply"): [("--note", "note", str), ("--to", "to", str), ("--base", "base", str)],
    ("question", "show"): [("--id", "id", str)],
    ("question", "claim"): [("--id", "id", str), ("--agent", "agent", str)],
    ("question", "fail"): [("--id", "id", str), ("--reason", "reason", str)],
    ("question", "release"): [("--id", "id", str)],
    ("question", "reopen"): [("--id", "id", str)],
    ("activity", "start"): [("--agent", "agent", str), ("--status", "status", str), ("--question", "question", str)],
    ("activity", "update"): [("--id", "id", str), ("--status", "status", str)],
    ("activity", "finish"): [("--id", "id", str), ("--state", "state", str), ("--status", "status", str)],
    ("preview", None): [("--claim", "claim", str), ("--anchor", "anchor", int), ("--path", "path", str),
                        ("--start", "start", int), ("--end", "end", int), ("--commit", "commit", str),
                        ("--context", "context", int)],
}


def _dest(flag: str) -> str:
    return "f_" + flag.lstrip("-").replace("-", "_")


def _flag_input(args) -> dict:
    """The input the plain flags give (empty when none was given)."""
    out: dict = {}
    for flag, key, kind in getattr(args, "flag_specs", []):
        value = getattr(args, _dest(flag), None)
        if value is None or value is False or value == []:
            continue
        if kind == "list":
            value = [v.strip() for item in value for v in item.split(",") if v.strip()]
        elif kind == "file":
            try:
                value = Path(value).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ContractError("bad_input", f"can't read {flag} {value}: {exc}") from None
        out[key] = value
    return out


def _read_input(args) -> object:
    """``--input FILE``, then any plain flags over it; with neither, stdin (nothing on a terminal: ``{}``)."""
    flags = _flag_input(args)
    if args.input:
        try:
            raw = Path(args.input).read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractError("bad_input", f"can't read the input: {exc}") from None
    elif flags or sys.stdin is None or sys.stdin.isatty():
        raw = ""
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise ContractError("bad_input", f"input is not JSON: {exc}") from None
    if flags:
        if not isinstance(data, dict):
            raise ContractError("bad_input", "flags go with an input object, not a list")
        data = {**data, **flags}
    return data


def _contract_error(exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc
    if isinstance(exc, GitError):
        return ContractError("git_error", str(exc))
    if isinstance(exc, StoreError):
        return ContractError("lock_timeout" if "holds the lock" in str(exc) else "store_error", str(exc))
    if isinstance(exc, OSError):
        return ContractError("store_error", str(exc))
    return ContractError("bad_input", str(exc))


def run_json(args, func) -> int:
    """Run one contract command; stdout gets exactly one JSON object either way."""
    try:
        data = _read_input(args) if args.takes_input else {}
        repo, identity, store = _open(args)
        store.init(identity)
        result = {"ok": True, **func(repo, store, data)}
        code = 0
    except (ContractError, GitError, StoreError, ValueError, KeyError, OSError) as exc:
        err = _contract_error(exc)
        result, code = err.to_dict(), 1
        print(f"honeyguide: {err.code}: {err.message}", file=sys.stderr)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return code


def cmd_map_validate(args) -> int:
    draft = args.stdin or bool(args.input)   # --input FILE is the same check as --stdin, read from a file

    def func(repo, store, data):
        if draft:
            return claims.validate_draft(repo, data, store, strict=args.strict)
        return claims.validate_map(repo, store.load("map"), strict=args.strict)
    args.takes_input = draft
    return run_json(args, func)


def _draft_summary(data: dict, files: list[str]) -> dict:
    from .readability import prose_pieces, words
    from .mapdoc import module_blocks
    doc = data["document"]
    overview = " ".join(t for k, _, _, t in prose_pieces(doc) if k == "overview")
    return {"files": files, "claims": len(data["claims"]),
            "blocks": sum(len(s.get("blocks") or []) for s in doc["sections"] if isinstance(s, dict)),
            "flows": len(doc["flows"]), "overview_words": len(words(overview)),
            "modules": len(module_blocks(doc))}


def cmd_drafts_dir(args) -> int:
    args.takes_input = False
    return run_json(args, lambda r, s, d: {"dir": str(drafts.agent_draft_dir(s, args.agent, args.name,
                                                                             fresh=args.fresh))})


def cmd_map_draft_dir(args) -> int:
    args.takes_input = False
    return run_json(args, lambda r, s, d: {"dir": str(drafts.map_draft_dir(s, fresh=args.fresh))})


def cmd_map_check(args) -> int:
    def func(repo, store, _):
        data, files = drafts.assemble(store, args.dir)
        return {**claims.validate_draft(repo, data, store, strict=True), **_draft_summary(data, files)}
    args.takes_input = False
    return run_json(args, func)


def cmd_map_ingest(args) -> int:
    def func(repo, store, _):
        data, files = drafts.assemble(store, args.dir)
        checked = claims.validate_draft(repo, data, store, strict=True)
        if not checked["valid"]:
            raise ContractError("validation_failed", f"{len(checked['errors'])} problem(s); nothing was saved "
                                "(run map check, fix every error, then ingest again)", checked["errors"])
        # T7.18: the repo card's facts, gathered at map time (git, and gh when signed in); refreshed on every ingest
        if isinstance(data.get("document"), dict):
            data["document"]["repo"] = repo_info(repo, claims.commit_of(repo, data.get("commit")))
        saved = claims.save_claims(store, repo, data)
        return {**saved, "readability": checked["readability"], **_draft_summary(data, files)}
    args.takes_input = False
    return run_json(args, func)


def cmd_repo_info(args) -> int:
    """``repo-info``: the repo card's facts as one JSON object; ``--save`` also stores them in the saved map's
    document (``document.repo``), which ``map ingest`` otherwise does at map time."""
    try:
        repo = Repo.open(args.repo)
        info = repo_info(repo, args.commit or "HEAD", gh=None if args.no_gh else "auto")
        if args.save:
            _, identity, store = _open(args)
            if not store.exists() or store.load("map").get("document") is None:
                raise ContractError("not_found", "no saved map to store the repo card in (map the repo first)")
            info = repo_info(repo, args.commit or store.load("map")["commit"] or "HEAD",
                             gh=None if args.no_gh else "auto")

            def put(layer: dict) -> None:
                layer["document"]["repo"] = info
            store.update("map", put)
        out, code = {"ok": True, **info}, 0
    except (ContractError, GitError, StoreError, OSError) as exc:
        err = _contract_error(exc)
        out, code = err.to_dict(), 1
        print(f"honeyguide: {err.code}: {err.message}", file=sys.stderr)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return code


def cmd_serve(args) -> int:
    from .server import serve
    repo, identity, store = _open(args)
    store.init(identity)
    try:
        return serve(repo, store, args.port)
    except OSError as exc:
        print(f"honeyguide: can't serve on 127.0.0.1:{args.port}: {exc}", file=sys.stderr)
        return 1


def cmd_watch(args) -> int:
    _, identity, store = _open(args)
    store.init(identity)
    return inbox.watch(store, interval=args.interval, follow=args.follow, timeout=args.timeout)


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

    groups: dict[str, argparse._SubParsersAction] = {}
    for (group, name), (func, takes_input) in AGENT_COMMANDS.items():
        if name is None:
            p = sub.add_parser(group, help="agent contract (JSON)")
        else:
            if group not in groups:
                g = sub.add_parser(group, help="agent contract (JSON)")
                groups[group] = g.add_subparsers(dest="action", required=True)
            p = groups[group].add_parser(name)
        p.add_argument("--repo", default=".", help="a path inside the checkout (default: .)")
        if takes_input:
            p.add_argument("--input", help="read the JSON input from this file (default: stdin)")
        specs = FLAGS.get((group, name), [])
        for flag, key, kind in specs:
            if kind == "list":
                p.add_argument(flag, dest=_dest(flag), action="append", metavar=key.upper(),
                               help=f"input {key} (repeat, or comma-separate)")
            elif kind == "flag":
                p.add_argument(flag, dest=_dest(flag), action="store_true", help=f"input {key}: true")
            elif kind == "file":
                p.add_argument(flag, dest=_dest(flag), metavar="FILE", help=f"input {key}: this file's text")
            else:
                p.add_argument(flag, dest=_dest(flag), type=kind, metavar=key.upper(), help=f"input {key}")
        if (group, name) == ("claims", "list"):
            p.add_argument("--json", action="store_true", help="accepted for symmetry: the output is always JSON")
        p.set_defaults(func=lambda a, f=func: run_json(a, f), takes_input=takes_input, input=None, flag_specs=specs)
    g = sub.add_parser("drafts", help="agent contract (JSON)")
    dsub = g.add_subparsers(dest="action", required=True)
    p = dsub.add_parser("dir", help="print (and create) the directory an agent writes its --input files in")
    p.add_argument("--repo", default=".")
    p.add_argument("--agent", required=True, help="the agent the files are for")
    p.add_argument("--name", help="a subdirectory, to keep parallel runs apart (e.g. the question id)")
    p.add_argument("--fresh", action="store_true", help="first remove the .json and .txt files left there")
    p.set_defaults(func=cmd_drafts_dir)
    g = sub.add_parser("map", help="agent contract (JSON)")
    msub = g.add_subparsers(dest="action", required=True)
    p = msub.add_parser("validate", help="check the saved map (or --stdin / --input: a claims-save input) against the rules")
    p.add_argument("--repo", default=".")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--input", help="read the claims-save input from this file (implies --stdin)")
    p.add_argument("--strict", action="store_true",
                   help="the draft rules: Overview topics, module titles and facts, coverage and the module count "
                        "required, readability errors are errors")
    p.set_defaults(func=cmd_map_validate)
    p = msub.add_parser("draft-dir", help="print (and create) the directory the Cartographer writes its draft map in")
    p.add_argument("--repo", default=".")
    p.add_argument("--fresh", action="store_true", help="first remove the .json drafts left there by an earlier run")
    p.set_defaults(func=cmd_map_draft_dir)
    p = msub.add_parser("check", help="validate the draft files in DIR (structure, claims, readability); saves nothing")
    p.add_argument("dir")
    p.add_argument("--repo", default=".")
    p.set_defaults(func=cmd_map_check)
    p = msub.add_parser("ingest", help="check the draft files in DIR and save them as the map (claims save)")
    p.add_argument("dir")
    p.add_argument("--repo", default=".")
    p.set_defaults(func=cmd_map_ingest)
    p = add("repo-info", cmd_repo_info, "the repo card's facts as JSON: link, languages, licence, contributors, dates, "
            "and GitHub counts when gh is signed in")
    p.add_argument("--commit", help="read git at this commit (default: HEAD; with --save, the map's commit)")
    p.add_argument("--save", action="store_true", help="also store them in the saved map (document.repo)")
    p.add_argument("--no-gh", action="store_true", help="never run gh (no GitHub counts)")
    p = add("serve", cmd_serve, "the local map page and its API on 127.0.0.1")
    p.add_argument("--port", type=int, default=8780)
    p = add("watch", cmd_watch, "print one line per new question (for the session's Monitor)")
    p.add_argument("--follow", action="store_true", help="keep watching; otherwise exit after the first batch")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--timeout", type=float, help="give up after this many seconds (exit 3)")
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
